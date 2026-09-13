+++
schema_version = 1
id = "TASK-20260913150458-strict-configuration"
kind = "task"
status = "completed"
task_level = "high_risk"
created_at = "2026-09-13T15:04:57.4323631Z"
updated_at = "2026-09-13T15:15:32.273670+00:00"
parent = "PLAN-20260913150236-hardening-and-validation"
repositories = ["root"]
protected_areas = ["authorization", "credentials"]

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-13T15:04:57.4323631Z"
evidence = "approved implementation plan containing Task 1 in current Codex thread"
+++

# Task: Strict configuration and resource discovery

## Goal

Implement Task 1 from the approved plan.

## Write scope

`src/agentkit/config.py`, `src/agentkit/generator.py`, and focused tests.

## Dependencies

Approved parent plan.

## Acceptance criteria

Manifest contracts and resource discovery satisfy the approved specification.

## Verification

Focused tests, full unit suite, and `agentkit validate`.

## Completion evidence

Implemented strict manifest types, required workflow flags, topology/version checks, duplicate/path
checks, capability discovery, packaged profile resources, and explicit resource errors. Focused tests
and the full suite pass.

