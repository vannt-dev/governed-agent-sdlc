+++
schema_version = 1
id = "PLAN-20260914001432-pypi-trusted-publishing"
kind = "plan"
status = "approved"
task_level = "high_risk"
created_at = "2026-09-14T00:14:32.994723+00:00"
updated_at = "2026-09-14T00:14:32.994723+00:00"
parent = "SPEC-20260914001431-pypi-trusted-publishing"
repositories = ["root"]
protected_areas = ["release"]

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-14T00:14:32.994723+00:00"
evidence = "user instruction: 'ok, triển khai luôn' for the safe PyPI publication design"
+++

# Implementation plan: Safe PyPI Trusted Publishing

## Outcome

Make PyPI publication an explicit, environment-protected manual operation that uploads the exact artifacts already attached to a selected GitHub Release.

## Tasks

1. Add `release_tag` and retain the explicit `publish_to_pypi` dispatch control.
2. Restrict the build-and-release job to tag pushes or manual non-PyPI release runs.
3. Add a separate `publish-pypi` job with environment `pypi`, `id-token: write`, release-tag validation, and release asset download.
4. Update regression tests to prove the jobs are separated and least-privileged.
5. Run unit tests, `agentkit validate`, compileall, and `git diff --check`.
6. Record independent review and QA, then publish through a PR after human approval.

## Write scope

- `.github/workflows/release.yml`
- `tests/test_release_workflow.py`
- `docs/agent/**` lifecycle artifacts for this change

## Release procedure after merge

1. The user configures the PyPI pending publisher and GitHub `pypi` environment.
2. Dispatch `release.yml` from `main` with `release_tag=v0.1.0` and `publish_to_pypi=true`.
3. Approve the GitHub Environment deployment.
4. Verify the PyPI project, files, and installation smoke test.

