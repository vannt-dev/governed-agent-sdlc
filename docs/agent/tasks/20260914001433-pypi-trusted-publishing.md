+++
schema_version = 1
id = "TASK-20260914001433-pypi-trusted-publishing"
kind = "task"
status = "completed"
task_level = "high_risk"
created_at = "2026-09-14T00:14:33.994723+00:00"
updated_at = "2026-09-14T00:21:16.112864+00:00"
parent = "PLAN-20260914001432-pypi-trusted-publishing"
repositories = ["root"]
protected_areas = ["release"]

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-14T00:14:33.994723+00:00"
evidence = "user instruction: 'ok, triển khai luôn' for PyPI Trusted Publishing implementation"
+++

# Task: Implement safe PyPI Trusted Publishing

## Goal

Separate PyPI publication from GitHub Release creation and enforce exact release-asset reuse through the protected `pypi` environment.

## Write scope

`.github/workflows/release.yml`, `tests/test_release_workflow.py`, and lifecycle artifacts for this task.

## Verification

- `python -m unittest discover -s tests -v`
- `python -m agentkit validate`
- `python -m compileall -q src hooks tests`
- `git diff --check`

## Completion evidence

- Separated GitHub Release creation and PyPI publication into mutually exclusive jobs for manual PyPI dispatches.
- Bound PyPI publication to environment `pypi` with `contents: read` and `id-token: write`.
- Added strict release-tag and exact wheel/sdist filename validation.
- Configured PyPI publication to download existing GitHub Release assets without rebuilding or mutating the release.
- Expanded the unit suite to 53 tests; all pass. Validator, compileall, and diff checks pass after implementation.
