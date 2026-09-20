# CLI reference

## Commands

- `agentkit init [path] [--name NAME] [--adapter none|claude-code|codex] [--dry-run]`
- `agentkit validate [path] [--format text|json]`
- `agentkit doctor [path] [--format text|json]`
- `agentkit generate claude-code|codex [path] [--force] [--dry-run]`
- `agentkit migrate [path] [--to-version VERSION] [--dry-run]`
- `agentkit artifact new KIND SLUG [--path PATH]`
- `agentkit artifact transition FILE TARGET [--approved-by ACTOR] [--evidence EVIDENCE]`
- `agentkit artifact list [--path PATH] [--format text|json]`
- `agentkit artifact show FILE [--path PATH] [--format text|json]`
- `agentkit artifact graph [--path PATH] [--format text|json]`
- `agentkit review run [--provider mock|open-code-review] [--run-id ID] [--requirement FILE] [--spec FILE] [--plan FILE] [--from REF] [--to REF] [--commit REF] [--mock-findings FILE] [--output-dir DIR]`
- `agentkit review approve --run-id ID --policy POLICY --actor HUMAN --evidence URL [--attempt N] [--reject]`
- `agentkit review status --run-id ID [--attempt N]`
- `agentkit review preview [--from REF] [--to REF] [--commit REF]`
- `agentkit review evaluate FINDINGS [--output-dir DIR]`

## Governed review

A reviewer produces findings, and governance decides what they mean. `review run` calls the provider,
normalizes the findings, evaluates the `[[policies]]` from the manifest, and records the result under
`.agent/runs/<run-id>/review-attempt-N/`. Running again with the same `--run-id` records a new attempt;
existing attempts and approvals are never overwritten.

The requirement/specification/plan background is fixed for a run. A retry without context arguments
reuses it, and repeating the same context is allowed. Supplying different context returns exit `2`
before calling the reviewer; use a new `--run-id` for the changed requirement or plan.

- `open-code-review` runs the `ocr` CLI (`npm install -g @alibaba-group/open-code-review`). The
  executable comes from `OPEN_CODE_REVIEW_BIN` or `PATH`, never from the manifest. Pass
  `--requirement`, `--spec` or `--plan` to hand the reviewer a bounded `review-background.md`
  (`[review].include_*` switches each one off). The reviewer sees a filtered environment.
- A reviewer that cannot run (missing binary, timeout, malformed output) is a provider error, exit `3`,
  and is recorded as `provider-error.json`. It is never reported as a clean review.
- OCR's `skipped` result means no files were selected. The gate stays `skipped` with exit `6` in
  `review run` and `review status`; reports preserve that state instead of calling it a passed review.
- `review approve` records a human decision for a policy that required approval. AI actors are refused,
  evidence (ticket or PR URL) is required, and a decision cannot be recorded twice.
- `review status` recomputes the gate from the stored evidence, so it can be re-run after approving.
- `review preview` uses `ocr delegate preview` to list reviewable files without an LLM.
- `review run --artifact docs/agent/reviews/<file>.md` links a run to the review artifact it supports.
  The artifact id and path are recorded in `provider.json` and the event log; only review artifacts
  under `docs/agent` are accepted.
- Every run keeps an append-only `events.jsonl` (`review.started`, `review.completed`, `review.failed`,
  `policy.evaluated`, `policy.blocked`, `policy.approval_required`, `approval.granted`,
  `approval.rejected`) with sequential ids. It is derived from the evidence files, not a source of
  truth, so audit tools and viewers can follow a run in order.
- `review report --run-id ID [--html FILE]` summarizes attempts, findings by severity, decisions,
  approvals, gate status and events from the stored evidence. It only reads; the optional HTML page
  escapes all evidence text and refuses to overwrite an existing file.
- `agentkit validate` also checks `.agent/runs/`: attempt evidence against the finding schema
  (`core/schemas/review-finding.schema.json`, shared with Junto), approval records (human actor,
  evidence, valid decision) and the event log.

Manifest tables (all optional, validated strictly):

```toml
[review]
provider = "open-code-review"   # or "mock"
timeout_seconds = 180
include_requirement = true
include_spec = true
include_plan = true

[remediation]
enabled = true
max_attempts = 2                # after this many attempts require-remediation becomes block

[[policies]]                    # replaces the built-in defaults when present
id = "auth-block"
action = "block"                # continue | warn | block | require-human-approval | require-remediation
severity = "high"
category = "security"
file_pattern = "**/auth/**"
```

`review run` and `review status` exit codes: `0` passed (or approved), `1` blocked or rejected,
`2` configuration/filesystem error, `3` review provider error, `4` awaiting human approval,
`5` remediation required, `6` skipped (no completed review).

`--dry-run` reports paths without creating or overwriting them. Generation is additive unless
`--force` is supplied. Manifest migration refuses ambiguous projects and unsupported source or
target versions instead of guessing at a rewrite.

## Stable exit codes

- `0`: command completed and validation found no errors.
- `1`: validation completed with one or more project errors, or no command handler completed.
- `2`: invalid project configuration, artifact operation, filesystem operation, or unsupported
  migration prevented the command from completing.

JSON output writes one JSON document to stdout. Operational errors use the same shape on stderr:

```json
{"error": "description", "ok": false}
```

Human approval metadata must come from a human-controlled channel. The CLI checks that approval
fields are present; it does not grant an agent authority to fill them on its own.
