+++
schema_version = 1
id = "TASK-20260913153839-publish-hardening"
kind = "task"
status = "active"
task_level = "high_risk"
created_at = "2026-09-13T15:38:39.7190836Z"
updated_at = "2026-09-13T15:38:39.7190836Z"
parent = "PLAN-20260913150236-hardening-and-validation"
repositories = ["root"]
protected_areas = ["release"]

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-13T15:38:39.7190836Z"
evidence = "current Codex thread: user replied 'ok, triển khai luôn' after local completion and publish handoff"
+++

# Task: Publish repository hardening

## Goal

Create a task branch and initial commit, then push and open a pull request when repository remote
and GitHub authentication are available.

## Preconditions

- Specification, implementation plan, implementation tasks, independent review, and QA are
  completed.
- Human publish approval is recorded above.

## Write scope

Git task branch, commit, pull request, and this task's completion evidence.

## Constraints

- Never force-push or push directly to a protected branch.
- Never merge or release.
- Never retrieve or print credentials.

## Verification

`agentkit validate`, full unit suite, `git diff --check`, clean committed worktree, and PR URL.

## Completion evidence

Pending. No Git remote is configured and the active GitHub CLI authentication is invalid, so push
and pull-request creation cannot proceed until the human configures the external destination and
reauthenticates.

