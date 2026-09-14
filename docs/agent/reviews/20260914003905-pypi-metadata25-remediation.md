+++
schema_version = 1
id = "REVIEW-20260914003905-pypi-metadata25-remediation"
kind = "review"
status = "completed"
task_level = "high_risk"
created_at = "2026-09-14T00:39:05.646693+00:00"
updated_at = "2026-09-14T00:40:10.614864+00:00"
parent = "TASK-20260914003242-pypi-metadata25-remediation"
repositories = ["root"]
protected_areas = ["release"]

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-14T00:40:10.614864+00:00"
evidence = "user response: 'ok' approving the Core Metadata 2.5 remediation review"
+++

# Review: PyPI Core Metadata 2.5 remediation

## Outcome

PASS candidate with no high- or medium-severity findings. Human approval is required before QA and publication because this changes a dependency in the protected release path.

## Root cause

Publisher action v1.12.4 rejected the already-built `v0.1.0` distributions at metadata verification with `Invalid distribution metadata: '2.5' is not a valid metadata version`.

## Remediation review

- PyPA `gh-action-pypi-publish` v1.14.2 explicitly includes Twine 7 support for Core Metadata 2.5.
- The selected commit `dc37677b2e1c63e2034f94d8a5b11f265b73ba33` is the verified commit resolved from the official `v1.14.2` tag.
- The upgrade remains within action major version v1 and retains immutable SHA pinning.
- Metadata verification remains enabled; no security check is bypassed.
- No distribution was uploaded during the failed run.

## Verification

- 53/53 unit tests passed.
- `agentkit validate`: 0 errors, 0 warnings.
- `compileall`: passed.
- `git diff --check`: passed.
