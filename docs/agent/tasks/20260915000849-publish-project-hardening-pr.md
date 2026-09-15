+++
schema_version = 1
id = "TASK-20260915000849-publish-project-hardening-pr"
kind = "task"
status = "completed"
task_level = "high_risk"
created_at = "2026-09-15T00:08:49.979777+00:00"
updated_at = "2026-09-15T00:11:32.377389+00:00"
parent = "PLAN-20260914133044-project-hardening-and-codex-adoption"
repositories = ["root"]
protected_areas = ["release"]

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-15T00:08:50.0542830Z"
evidence = "user instruction on 2026-09-15: 'ok' after approving remediation and authorizing transition to PR preparation"
+++

# Task: Publish project hardening Pull Request

## Goal

Commit the reviewed and QA-approved project-hardening scope, push only the existing task branch,
open a Pull Request against `main`, and monitor required CI checks.

## Confirmed facts

- Specification and plan are approved.
- Implementation tasks, independent reviews, and QA are completed.
- The active branch is `task/project-hardening-and-codex-adoption`, not protected `main`.

## Assumptions

- The existing authenticated GitHub identity has permission to push the task branch and open a PR.

## Open questions

- None for PR creation. Merge, tag, GitHub Release, and PyPI publication require a later explicit
  human decision.

## Scope

- Create commits on `task/project-hardening-and-codex-adoption`.
- Push that task branch and open one Pull Request targeting `main`.
- Record and monitor required CI checks.

## Out of scope

- Merge, tag creation, GitHub Release creation, PyPI publication, or environment approval.

## Acceptance criteria

- Commit contains only the approved working-tree scope.
- Pull Request targets `main` from the task branch.
- Required checks are allowed to complete and their results are recorded.

## Evidence

- Implementation commit: `527fc4d` (`Harden project workflows and add Codex support`).
- Task branch pushed to `origin/task/project-hardening-and-codex-adoption` without force.
- Pull Request: <https://github.com/vannt-dev/governed-agent-sdlc/pull/9>, targeting `main`.
- Validation workflow run `34912055154`: all nine Linux/macOS/Windows Python 3.11-3.13 matrix
  jobs plus `quality`, `package`, and `browser` passed.
- CodeQL workflow run `34912053365`: Actions and Python analysis passed; the aggregate CodeQL
  check passed.
- PR remains unmerged. No tag, GitHub Release, PyPI publication, or environment approval was
  performed.
