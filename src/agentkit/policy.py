from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Any, Literal

from agentkit.review import NormalizedFinding

PolicyAction = Literal[
    "continue",
    "warn",
    "block",
    "require-human-approval",
    "require-remediation",
]

ACTION_PRECEDENCE: list[PolicyAction] = [
    "block",
    "require-human-approval",
    "require-remediation",
    "warn",
    "continue",
]


@dataclass(frozen=True)
class PolicyRule:
    id: str
    action: PolicyAction
    severity: str | None = None
    category: str | None = None
    file_pattern: str | None = None
    reason: str | None = None

    def matches(self, finding: NormalizedFinding) -> bool:
        if self.severity and finding.severity != self.severity:
            return False
        if self.category and finding.category != self.category:
            return False
        if self.file_pattern:
            normalized_pattern = self.file_pattern.replace("\\", "/")
            normalized_file = finding.file.replace("\\", "/")
            if not fnmatch.fnmatch(normalized_file, normalized_pattern):
                return False
        return True


@dataclass(frozen=True)
class PolicyDecision:
    policy_id: str
    action: PolicyAction
    finding_ids: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "policyId": self.policy_id,
            "action": self.action,
            "findingIds": list(self.finding_ids),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class GovernanceDecision:
    action: PolicyAction
    decisions: tuple[PolicyDecision, ...]
    findings_count: dict[str, int]
    blocked: bool
    requires_approval: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.action,
            "blocked": self.blocked,
            "requiresApproval": self.requires_approval,
            "findingsCount": self.findings_count,
            "reasons": list(self.reasons),
            "policies": [d.to_dict() for d in self.decisions],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GovernanceDecision:
        """Rebuild a decision from stored `policy-result.json` evidence."""
        action = data.get("decision")
        if action not in ACTION_PRECEDENCE:
            raise ValueError(f"Unknown governance decision: {action!r}")
        decisions = tuple(
            PolicyDecision(
                policy_id=str(item["policyId"]),
                action=item["action"],
                finding_ids=tuple(str(x) for x in item.get("findingIds", [])),
                reason=str(item.get("reason", "")),
            )
            for item in data.get("policies", [])
        )
        return cls(
            action=action,
            decisions=decisions,
            findings_count=dict(data.get("findingsCount", {})),
            blocked=action == "block",
            requires_approval=action == "require-human-approval",
            reasons=tuple(str(r) for r in data.get("reasons", [])),
        )

    def policy_ids_for(self, action: PolicyAction) -> list[tuple[str, tuple[str, ...]]]:
        return [(d.policy_id, d.finding_ids) for d in self.decisions if d.action == action]


def default_policies() -> list[PolicyRule]:
    return [
        PolicyRule(
            id="critical-block",
            severity="critical",
            action="block",
            reason="Critical severity finding detected. Deployment/merge blocked.",
        ),
        PolicyRule(
            id="security-high-approval",
            severity="high",
            category="security",
            action="require-human-approval",
            reason="High severity security finding requires explicit human approval.",
        ),
        PolicyRule(
            id="high-warning",
            severity="high",
            action="warn",
            reason="High severity finding detected.",
        ),
        PolicyRule(
            id="medium-warning",
            severity="medium",
            action="warn",
            reason="Medium severity finding detected.",
        ),
        PolicyRule(
            id="low-continue",
            severity="low",
            action="continue",
            reason="Low severity finding allowed to proceed.",
        ),
    ]


VALID_ACTIONS = frozenset(ACTION_PRECEDENCE)
_POLICY_KEYS = {"id", "action", "severity", "category", "file_pattern", "reason"}


def load_policies(
    entries: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
) -> list[PolicyRule]:
    """Build rules from the manifest `[[policies]]` tables; use the defaults when unset."""
    if not entries:
        return default_policies()
    rules: list[PolicyRule] = []
    seen: set[str] = set()
    for index, item in enumerate(entries):
        unknown = set(item) - _POLICY_KEYS
        if unknown:
            raise ValueError(f"policies[{index}] has unknown fields: {', '.join(sorted(unknown))}")
        policy_id = item.get("id")
        if not isinstance(policy_id, str) or not policy_id.strip():
            raise ValueError(f"policies[{index}].id must be a non-empty string")
        if policy_id in seen:
            raise ValueError(f"Duplicate policy id: {policy_id}")
        seen.add(policy_id)
        if item.get("action") not in VALID_ACTIONS:
            raise ValueError(
                f"policies[{index}].action must be one of: {', '.join(ACTION_PRECEDENCE)}"
            )
        for key in ("severity", "category", "file_pattern", "reason"):
            if key in item and not isinstance(item[key], str):
                raise ValueError(f"policies[{index}].{key} must be a string")
        rules.append(
            PolicyRule(
                id=policy_id,
                action=item["action"],
                severity=item.get("severity"),
                category=item.get("category"),
                file_pattern=item.get("file_pattern"),
                reason=item.get("reason"),
            )
        )
    return rules


def provider_error_decision(kind: str, message: str) -> GovernanceDecision:
    """A reviewer that could not run must never look like a clean review, so this always blocks."""
    reason = f"Review provider failed ({kind}): {message}"
    return GovernanceDecision(
        action="block",
        decisions=(PolicyDecision("review-provider-error", "block", (), reason),),
        findings_count={"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0},
        blocked=True,
        requires_approval=False,
        reasons=(f"review-provider-error: {reason}",),
    )


class PolicyEngine:
    def __init__(self, rules: list[PolicyRule] | None = None) -> None:
        self.rules = tuple(rules if rules is not None else default_policies())

    def evaluate(
        self, findings: list[NormalizedFinding] | tuple[NormalizedFinding, ...]
    ) -> GovernanceDecision:
        counts = {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "info": 0,
        }
        for f in findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1

        if not findings:
            return GovernanceDecision(
                action="continue",
                decisions=(),
                findings_count=counts,
                blocked=False,
                requires_approval=False,
                reasons=("No findings detected.",),
            )

        decisions: list[PolicyDecision] = []

        for rule in self.rules:
            matching_ids = [f.id for f in findings if rule.matches(f)]
            if matching_ids:
                reason = (
                    rule.reason or f"Policy {rule.id} triggered by {len(matching_ids)} finding(s)."
                )
                decisions.append(
                    PolicyDecision(
                        policy_id=rule.id,
                        action=rule.action,
                        finding_ids=tuple(matching_ids),
                        reason=reason,
                    )
                )

        if not decisions:
            # Fallback when findings exist but no configured rules explicitly matched
            return GovernanceDecision(
                action="continue",
                decisions=(),
                findings_count=counts,
                blocked=False,
                requires_approval=False,
                reasons=("Findings detected but none matched active policy rules.",),
            )

        # Aggregate overall action by strict precedence
        action_rank = {action: index for index, action in enumerate(ACTION_PRECEDENCE)}
        sorted_decisions = sorted(decisions, key=lambda d: action_rank.get(d.action, 99))
        primary_action = sorted_decisions[0].action

        reasons = tuple(
            f"{d.policy_id}: {d.reason}" for d in sorted_decisions if d.action == primary_action
        )

        return GovernanceDecision(
            action=primary_action,
            decisions=tuple(decisions),
            findings_count=counts,
            blocked=(primary_action == "block"),
            requires_approval=(primary_action == "require-human-approval"),
            reasons=reasons,
        )
