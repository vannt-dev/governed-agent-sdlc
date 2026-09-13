+++
schema_version = 1
id = "PLAN-20260913155549-repository-presence-and-landing"
kind = "plan"
status = "approved"
task_level = "high_risk"
created_at = "2026-09-13T15:55:49.8677069Z"
updated_at = "2026-09-13T15:56:59.2408460Z"
parent = "SPEC-20260913155433-repository-presence-and-landing"
repositories = ["root"]
protected_areas = ["authorization", "release"]

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-13T15:56:59.2408460Z"
evidence = "current Codex thread: user replied 'triển khai' after implementation plan review"
+++

# Implementation plan: Repository presence, landing page, and baseline governance

## Outcome

Publish a polished dependency-free project website, complete repository metadata/community health,
and protect `main` with a recoverable least-privilege ruleset.

## Task graph

### Task 1 — Repository content and site design

- Owner: developer
- Dependencies: approved plan
- Write scope: `site/**`, `README.md`, `.github/CODEOWNERS`, `CODE_OF_CONDUCT.md`, site tests
- Work: build a semantic responsive landing page, update README, replace owner placeholders, and
  add community conduct guidance.
- Verification: HTML/CSS inspection, link checks, responsive browser inspection, accessibility
  smoke checks, existing unit suite, and validator.

### Task 2 — Pages workflow

- Owner: developer
- Dependencies: Task 1
- Write scope: `.github/workflows/pages.yml`, workflow-focused tests/documentation if needed
- Work: verify current official Pages action releases and immutable tag SHAs, then add a minimal
  deployment workflow for `site/` with explicit concurrency and least-privilege permissions.
- Verification: YAML inspection, pinned-SHA assertions, permission review, and GitHub Actions run.

### Task 3 — Independent review and QA

- Owner: reviewer, then QA
- Dependencies: Tasks 1 and 2 completed
- Write scope: `docs/agent/reviews/**`, then `docs/agent/qa/**`
- Work: independently review public claims, supply-chain pins, accessibility, security permissions,
  workflow behavior, and regression coverage; QA the page locally and through the deployed artifact.
- Acceptance: no unresolved high/medium findings and all declared checks pass.

### Task 4 — Publish source through PR

- Owner: publisher
- Dependencies: approved review and QA plus human publish approval
- Write scope: Git task branch, commits, pull request, artifact evidence
- Work: push a task branch, open a PR, wait for all required checks, and merge only after a separate
  explicit human merge decision.

### Task 5 — Configure GitHub surface and protection

- Owner: publisher
- Dependencies: source PR merged; human approval from this plan; capture current external state
- External scope: repository About metadata, topics, homepage, GitHub Pages configuration, rulesets
- Work:
  - set description, homepage, and focused topics;
  - configure Pages for the approved Actions workflow and verify the HTTPS site;
  - create a `main` ruleset requiring pull requests, blocking force pushes/deletions, and requiring
    the existing matrix checks, with owner bypass for recovery;
  - re-read settings after mutation and record rollback identifiers.
- Verification: repository API state, successful Pages deployment/live response, ruleset API state,
  and a final clean `main` check.

## Ordering rationale

- Public claims and page design precede deployment configuration.
- Official action verification precedes adding new workflow dependencies.
- Independent review and QA precede all source publication.
- GitHub Pages and ruleset settings are changed only after the corresponding workflow exists on
  `main`, avoiding a broken deployment or a ruleset that references absent checks.

## Rollback

- Revert the source PR to remove the site/workflow if deployment fails.
- Disable Pages through the repository API if published content is incorrect.
- Preserve the ruleset identifier and prior unprotected state; disable/delete only with explicit
  human direction if it blocks recovery.
- Restore prior About metadata from the captured audit values (all currently empty).

## Verification matrix

- `agentkit validate`
- `python -m unittest discover -s tests -v`
- HTML link and remote-resource checks
- Local browser inspection at desktop and mobile widths
- `git diff --check`
- GitHub PR CI on Windows, Ubuntu, macOS × Python 3.11–3.13
- Pages deployment job and live HTTPS response
- Repository metadata, Pages, community profile, and ruleset API reads

## Risks and approvals

- This plan changes authorization and publishes a public site, so it requires human approval before
  implementation.
- Major action upgrades require explicit human approval if official current releases differ from
  already-used action families.
- Merge remains a separate human decision even after review and QA pass.
