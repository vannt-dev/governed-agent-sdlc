+++
schema_version = 1
id = "PLAN-20260913164154-release-pipeline-and-v010"
kind = "plan"
status = "approved"
task_level = "high_risk"
created_at = "2026-09-13T16:41:54.565034+00:00"
updated_at = "2026-09-13T16:41:54.565034+00:00"
parent = "SPEC-20260913164129-release-pipeline-and-v010"
repositories = ["root"]
protected_areas = ["release"]

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-13T16:41:54.565034+00:00"
evidence = "user requested: 'ok, triển khai tất cả giúp mình' for release automation and v0.1.0 release"
+++

# Implementation plan: Release pipeline automation and v0.1.0 release

## Outcome

Add an automated release workflow, verify distribution builds, publish the change via pull request, and release `v0.1.0` with assets and documentation on GitHub.

## Task graph

### Task 1 — Release workflow and regression tests
- Owner: developer
- Dependencies: approved plan
- Write scope: `.github/workflows/release.yml`, `tests/test_release_workflow.py`
- Work: add workflow with immutable pinned action SHAs, triggers on `v*` tags and `workflow_dispatch`, least-privilege permissions (`contents: write`, `id-token: write`), build wheel/sdist via `build`, create GitHub release via `softprops/action-gh-release`, and prepare PyPI publish step via `pypa/gh-action-pypi-publish`.
- Verification: action pin assertions, permission review, and unit tests.

### Task 2 — Build verification
- Owner: developer
- Dependencies: Task 1
- Write scope: task evidence
- Work: build wheel and sdist locally using `hatchling` / `build`, verify package contents, inspect embedded `core/`, `hooks/`, and `profiles/` resources.
- Verification: distribution inspection and test install smoke check.

### Task 3 — Independent review and QA
- Owner: reviewer, then QA
- Dependencies: Tasks 1 and 2
- Write scope: `docs/agent/reviews/**`, `docs/agent/qa/**`
- Work: review supply-chain security, permissions, action SHAs, OIDC configuration, and run test matrix.
- Verification: unit suite, agentkit validator, and compilation checks.

### Task 4 — Publish through PR
- Owner: publisher
- Dependencies: approved review and QA plus human publish approval
- Write scope: git branch, commits, pull request
- Work: open PR, wait for CI matrix checks, and merge to `main` upon human approval.

### Task 5 — Release v0.1.0
- Owner: publisher
- Dependencies: merged PR to `main`
- Write scope: git tag `v0.1.0`, GitHub Release
- Work: create tag `v0.1.0`, trigger release workflow, verify release publication and attached assets.

## Verification matrix

- `python -m unittest discover -s tests -v`
- `python -m agentkit validate`
- `python -m compileall -q src hooks tests`
- `git diff --check`
- Release workflow dry-run or dispatch verification
