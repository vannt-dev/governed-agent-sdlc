+++
schema_version = 1
id = "TASK-20260914003242-pypi-metadata25-remediation"
kind = "task"
status = "completed"
task_level = "high_risk"
created_at = "2026-09-14T00:32:42.343605+00:00"
updated_at = "2026-09-14T00:39:05.646693+00:00"
parent = "PLAN-20260914001432-pypi-trusted-publishing"
repositories = ["root"]
protected_areas = ["release"]

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-14T00:32:42.343605+00:00"
evidence = "user instruction: 'tiếp tục' approving the v0.1.0 PyPI publication; remediation is required after the approved run exposed publisher incompatibility with Core Metadata 2.5"
+++

# Task: Remediate PyPI Core Metadata 2.5 publication

## Goal

Upgrade the PyPA publisher action within major version 1 to the verified release that supports Core Metadata 2.5, without weakening metadata verification.

## Failure evidence

- Workflow run `34792945988` passed release-tag validation and exact asset download.
- `pypa/gh-action-pypi-publish` v1.12.4 rejected the wheel with `Invalid distribution metadata: '2.5' is not a valid metadata version`.
- No upload reached PyPI.

## Write scope

- `.github/workflows/release.yml`
- `tests/test_release_workflow.py`
- Remediation lifecycle artifacts

## Verification

- Pin `pypa/gh-action-pypi-publish` v1.14.2 to its verified commit SHA.
- Run the full unit suite, validator, compileall, and diff check.
- Publish through PR and retry only after human approval.

## Completion evidence

- Confirmed failed run `34792945988` reached the PyPI publisher after environment approval and exact asset download, then failed metadata verification because publisher v1.12.4 did not support Core Metadata 2.5.
- Verified official PyPA release v1.14.2 upgrades to Twine 7 for Core Metadata 2.5 support.
- Updated the immutable action pin to verified commit `dc37677b2e1c63e2034f94d8a5b11f265b73ba33` and added an exact regression assertion.
- Unit suite passes 53/53; validator, compileall, and diff checks pass.

