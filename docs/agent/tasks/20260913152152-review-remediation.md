+++
schema_version = 1
id = "TASK-20260913152152-review-remediation"
kind = "task"
status = "completed"
task_level = "high_risk"
created_at = "2026-09-13T15:21:52.4339623Z"
updated_at = "2026-09-13T15:25:09.652299+00:00"
parent = "PLAN-20260913150236-hardening-and-validation"
repositories = ["root"]
protected_areas = ["authorization", "credentials"]

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-13T15:21:52.4339623Z"
evidence = "approved hardening plan and explicit instruction to continue through independent review remediation"
+++

# Task: Independent review remediation

## Goal

Resolve every high and medium finding in review `20260913152024-hardening-and-validation`.

## Write scope

`hooks/common.py`, `hooks/guard_credentials.py`, `hooks/guard_git.py`,
`hooks/guard_role_scope.py`, `src/agentkit/config.py`, `src/agentkit/validator.py`, and focused tests.

## Acceptance criteria

- Protected deletion refspecs are denied.
- Missing or non-object `tool_input` is denied by every guard.
- Boolean schema versions are rejected.
- Any supplied approval table is strictly validated, including unexpected fields.

## Verification

Focused regression tests, full unit suite, `agentkit validate`, and independent re-review.

## Completion evidence

Fixed protected deletion refspec handling, structural hook payload validation, strict integer schema
versions, and strict optional approval tables. Added five regression scenarios; focused tests and the
full 38-test suite pass, `agentkit validate` reports 0 errors/0 warnings, and `git diff --check`
passes.

