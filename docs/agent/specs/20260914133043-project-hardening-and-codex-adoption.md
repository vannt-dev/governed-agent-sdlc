+++
schema_version = 1
id = "SPEC-20260914133043-project-hardening-and-codex-adoption"
kind = "spec"
status = "approved"
task_level = "high_risk"
created_at = "2026-09-14T13:30:43.2978503Z"
updated_at = "2026-09-14T13:30:43.2978503Z"
repositories = ["root"]
protected_areas = ["release", "authorization"]

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-14T13:30:43.2978503Z"
evidence = "user instruction: 'triển khai tất cả luôn giúp mình' after reviewing the complete prioritized improvement list"
+++

# Specification: Project hardening and Codex adoption

## Goal

Raise the published alpha from a successful MVP release to a repeatable, auditable, and easier-to-adopt toolkit by completing packaging metadata, artifact-level CI, security automation, release governance, quality gates, browser-backed site checks, a native Codex adapter, and automation-oriented CLI capabilities.

## Confirmed facts

- Version `0.1.0` is published on PyPI through Trusted Publishing and contains the expected wheel and source archive.
- Runtime dependencies are intentionally empty and must remain empty.
- CI currently tests an editable installation on Python 3.11-3.13 across Linux, Windows, and macOS.
- External actions are pinned to immutable commit SHAs.
- The active `main-protection` ruleset requires Pull Requests and nine platform/version checks, but does not require an up-to-date branch or resolved conversations.
- Secret scanning and push protection are enabled; Dependabot alerts/security updates and CodeQL are not enabled.
- The README still describes package publication as future work and PyPI metadata has no project URLs.
- Codex reads layered `AGENTS.md` files from project root to working directory according to official OpenAI documentation.

## Product requirements

1. PyPI and repository documentation accurately describe installation, release state, supported Python versions, and project links.
2. CI validates the built wheel and sdist, not only an editable checkout, and proves packaged resources and CLI entry points work from a clean installation.
3. Developer-only quality tooling adds lint, formatting, type, and coverage gates without adding runtime dependencies.
4. Release builds use a pinned toolchain, validate metadata, preserve immutable action pins, and reject release tags not derived from `main`.
5. GitHub security automation includes Dependabot alerts/security updates and CodeQL analysis.
6. Release tags matching `v*` receive deletion/non-fast-forward protection and controlled creation.
7. The main ruleset requires current status checks and resolved review conversations; a one-review rule is deferred until a second human reviewer exists.
8. The site receives real browser smoke coverage for responsive layout, keyboard focus, internal navigation, and external-link validity.
9. A Codex adapter uses the existing tool-neutral core and native `AGENTS.md` discovery without weakening approval, credential, destructive-action, or human-merge rules.
10. CLI automation supports structured JSON output, dry-run/diff previews for generated changes, artifact listing/showing/graph inspection, and documented stable exit codes.
11. Manifest evolution has an explicit migration command and rejects unsafe or ambiguous migrations.

## Safety and compatibility constraints

- Preserve zero third-party runtime dependencies.
- Do not read or emit credentials, environment dumps, token stores, or local Codex user configuration.
- Do not overwrite existing project-owned `AGENTS.md`, `.codex/`, policy, or manifest files without an explicit force/preview flow.
- Repository settings changes must be minimal, auditable, and reversible.
- Do not require an impossible self-review for a single-maintainer repository.
- Do not merge, create a release tag, or publish `v0.1.1` until implementation, independent review, QA, CI, and a final human publish decision are complete.

## Scope

- Packaging and public documentation: `pyproject.toml`, `README.md`, `CHANGELOG.md`, and relevant docs/site copy.
- CLI and adapter implementation under `src/agentkit/`, `adapters/codex/`, generated resources, and tests.
- CI/release/security workflows under `.github/`, including artifact verification and CodeQL.
- Browser-backed site verification and accessibility/responsiveness assertions.
- GitHub repository security settings for Dependabot, the `main` ruleset, and a `v*` tag ruleset.
- Lifecycle artifacts under `docs/agent/`.

## Out of scope

- Adding runtime dependencies or an OpenAI API integration.
- Automatically trusting a repository in a user's personal Codex configuration.
- Requiring a GitHub approval from a nonexistent second maintainer.
- Automatic merge or release without the final human gate.

## Acceptance criteria

1. All existing behavior remains covered and the expanded suite passes on supported platforms.
2. Ruff, type checking, coverage, build metadata checks, compileall, and `agentkit validate` pass.
3. A clean environment installs the built wheel and exercises the CLI plus embedded scaffold resources.
4. Browser checks cover 320px and desktop viewports, focus visibility, and navigation.
5. `agentkit generate codex` is additive, idempotent, documented, and grounded in official Codex `AGENTS.md` behavior.
6. JSON output is machine-readable and normal human output remains backward compatible.
7. GitHub reports active Dependabot alerts/security updates, CodeQL analysis, tightened `main` rules, and an active release-tag ruleset.
8. The repository remains clean and validator reports zero errors and warnings.
9. Review and QA artifacts record exact commands, results, untested boundaries, and remaining risks.

## Evidence

- User-approved improvement list from the immediately preceding conversation.
- Official OpenAI Codex documentation for layered `AGENTS.md` discovery and project-scoped configuration.
- Current GitHub repository, ruleset, security feature, workflow, and PyPI metadata inspection on 2026-09-14.
