+++
schema_version = 1
id = "REVIEW-20260914002029-pypi-trusted-publishing"
kind = "review"
status = "completed"
task_level = "high_risk"
created_at = "2026-09-14T00:20:29.394059+00:00"
updated_at = "2026-09-14T00:22:06.102416+00:00"
parent = "TASK-20260914001433-pypi-trusted-publishing"
repositories = ["root"]
protected_areas = ["release"]

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-14T00:22:06.102416+00:00"
evidence = "user response: 'ok' approving the PyPI Trusted Publishing review artifact"
+++

# Review: Safe PyPI Trusted Publishing

## Outcome

PASS candidate with no high- or medium-severity findings. Human approval is required because the implementation changes a protected release path and the implementing agent cannot approve its own review artifact.

## Scope reviewed

- `.github/workflows/release.yml`
- `tests/test_release_workflow.py`
- PyPI publication spec, plan, and task artifacts

## Findings

### Job isolation

The GitHub Release job and PyPI publication job have mutually exclusive conditions for a manual PyPI run. Publishing to PyPI cannot invoke release creation or replace GitHub Release assets.

### Artifact integrity

The PyPI job downloads exactly one expected wheel and one expected source archive from the selected existing GitHub Release. It validates a constrained version-tag format and exact filenames before invoking the publisher action.

### Credentials and permissions

No static PyPI credential is used. The PyPI job alone receives `id-token: write`, has read-only repository contents permission, and is bound to GitHub Environment `pypi`. The GitHub Release job no longer receives OIDC permission.

### Supply chain

All external actions remain pinned to immutable 40-character commit SHAs. The PyPI publisher uses `pypa/gh-action-pypi-publish` and duplicate versions fail rather than being silently skipped.

### Remaining human configuration

The repository owner must configure GitHub Environment `pypi` and a matching PyPI pending publisher before dispatch. The identity values must be owner `vannt-dev`, repository `governed-agent-sdlc`, workflow `release.yml`, and environment `pypi`.

## Verification evidence

- Unit suite: 53/53 passed.
- `agentkit validate`: 0 errors, 0 warnings.
- `compileall`: passed.
- `git diff --check`: passed.
