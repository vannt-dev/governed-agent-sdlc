+++
schema_version = 1
id = "TASK-20260913164221-release-workflow-and-tests"
kind = "task"
status = "completed"
task_level = "medium"
created_at = "2026-09-13T16:42:21.096082+00:00"
updated_at = "2026-09-13T16:45:39.220446+00:00"
parent = "PLAN-20260913164154-release-pipeline-and-v010"
repositories = ["root"]
protected_areas = []

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-13T16:42:21.096082+00:00"
evidence = "approved release pipeline plan"
+++

# Task: Release workflow and regression tests

## Goal

Add `.github/workflows/release.yml` with pinned official actions, least-privilege permissions, build packaging steps, GitHub release creation, and regression tests in `tests/test_release_workflow.py`.

## Write scope

`.github/workflows/release.yml`, `tests/test_release_workflow.py`.

## Acceptance criteria

- Workflow triggers on `v*` tag push and `workflow_dispatch`.
- Actions are pinned to verified 40-character SHAs.
- Least-privilege permissions (`contents: write`, `id-token: write`).
- Python regression tests verify workflow structure and pinned actions.

## Verification

`unittest`, `agentkit validate`, and `git diff --check`.

## Completion evidence

Added `.github/workflows/release.yml` with pinned official action SHAs, least-privilege permissions, distribution build, GitHub release creation via GitHub CLI, and PyPI Trusted Publishing support. Added unit tests in `tests/test_release_workflow.py`. Full test suite passes 50/50, `agentkit validate` reports 0 errors/0 warnings, and `git diff --check` passes.
