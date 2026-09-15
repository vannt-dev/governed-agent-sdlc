+++
schema_version = 1
id = "PLAN-20260914133044-project-hardening-and-codex-adoption"
kind = "plan"
status = "approved"
task_level = "high_risk"
created_at = "2026-09-14T13:30:44.0000000Z"
updated_at = "2026-09-14T13:30:44.0000000Z"
parent = "SPEC-20260914133043-project-hardening-and-codex-adoption"
repositories = ["root"]
protected_areas = ["release", "authorization"]

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-14T13:30:44.0000000Z"
evidence = "user instruction: 'triển khai tất cả luôn giúp mình' after reviewing the complete prioritized improvement list"
+++

# Implementation plan: Project hardening and Codex adoption

## Outcome

Deliver all approved improvements as reviewable tasks while keeping repository-setting changes and the eventual `v0.1.1` publication behind explicit evidence and final gates.

## Task graph

### Task 1 — Packaging, documentation, and quality foundation

- Update package URLs, SPDX license metadata, installation guidance, maturity copy, changelog, and versioned release documentation.
- Add pinned development/build tooling without changing runtime dependencies.
- Add Ruff, type, coverage, build, metadata, and installed-wheel checks.
- Verification: unit suite, lint, type check, coverage, build, metadata check, wheel install smoke test.

### Task 2 — CI and release hardening

- Expand CI with quality and artifact jobs while retaining the cross-platform matrix.
- Pin the release build toolchain and verify metadata before creating GitHub assets.
- Require a release tag commit to be reachable from `origin/main` and retain exact-asset PyPI publication.
- Replace brittle workflow string assertions with structured or behavior-focused checks where practical.
- Verification: workflow regression tests and local build/install simulation.

### Task 3 — Codex adapter and CLI automation

- Add a native Codex adapter based on official `AGENTS.md` discovery.
- Extend generation and initialization choices additively and idempotently.
- Add JSON output, previews for mutating generation, artifact list/show/graph commands, stable exit-code documentation, and safe manifest migration.
- Verification: CLI subprocess/integration tests, path-boundary tests, idempotency tests, and packaged-resource tests.

### Task 4 — Browser-backed site verification

- Add a deterministic local static-server/browser check for mobile/desktop layout, focus visibility, navigation, and external links.
- Keep browser tooling development-only and isolate it from runtime/package dependencies.
- Verification: browser suite plus existing static site tests.

### Task 5 — GitHub security and governance settings

- Enable Dependabot alerts and security updates.
- Enable CodeQL default setup or land an immutable-pinned advanced workflow if default setup cannot be configured safely.
- Tighten the existing `main` ruleset for current checks and resolved conversations without requiring unavailable reviewers.
- Create an active tag ruleset for `v*` that prevents deletion and non-fast-forward updates and restricts creation appropriately.
- Verification: read back repository security configuration and rulesets through GitHub APIs.

### Task 6 — Independent review and QA

- Perform an implementation review focused on authorization, release integrity, adapter correctness, backward compatibility, and external settings.
- Remediate high/medium findings within approved scope, then run full QA across all local and remote checks.
- Record untested boundaries and exact evidence in `docs/agent/reviews/` and `docs/agent/qa/`.

### Task 7 — Publish through PR and prepare v0.1.1

- Create a task branch, commit the approved scope, open a Pull Request, and wait for all required checks.
- Do not merge, tag, or publish until the final human decision after review and QA.
- After authorization, merge, tag `v0.1.1`, verify GitHub Release assets, approve the `pypi` environment, publish through Trusted Publishing, and verify PyPI hashes/provenance.

## Verification matrix

- `python -m agentkit validate`
- `python -m unittest discover -s tests -v`
- Ruff format and lint checks
- Static type check
- Coverage report and threshold
- `python -m compileall -q src hooks tests`
- Build plus metadata validation
- Clean wheel installation and CLI/scaffold smoke test
- Browser-backed site checks
- `git diff --check`
- GitHub ruleset/security readback
- Pull Request CI matrix

## Human gates

- The current user instruction approves this specification, plan, implementation scope, dependency additions limited to development/build tooling, and the described reversible GitHub security settings.
- A separate final decision is required before merge, tag creation, GitHub Release publication, or PyPI publication.
