+++
schema_version = 1
id = "QA-20260914004010-pypi-metadata25-remediation"
kind = "qa"
status = "completed"
task_level = "high_risk"
created_at = "2026-09-14T00:40:10.614864+00:00"
updated_at = "2026-09-14T00:40:47.293293+00:00"
parent = "REVIEW-20260914003905-pypi-metadata25-remediation"
repositories = ["root"]
protected_areas = ["release"]

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-14T00:40:47.293293+00:00"
evidence = "user response: 'ok' approving remediation QA and PR publication"
+++

# QA: PyPI Core Metadata 2.5 remediation

## Outcome

PASS candidate. The remediation is ready for CI validation through a Pull Request. Actual upload remains gated until the fix is merged and the user reauthorizes the retry.

## Evidence

- The official PyPA action is pinned to verified commit `dc37677b2e1c63e2034f94d8a5b11f265b73ba33` for v1.14.2.
- A regression assertion requires the exact publisher commit SHA.
- Full unit suite passes 53/53.
- `agentkit validate` reports 0 errors and 0 warnings.
- `compileall` and `git diff --check` pass.
- Metadata verification remains at its secure default (`true`).
- The earlier failed run did not upload either distribution to PyPI.

## Remaining external test

Successful OIDC publication of the Core Metadata 2.5 wheel and sdist can only be confirmed after merge and an explicitly approved retry.
