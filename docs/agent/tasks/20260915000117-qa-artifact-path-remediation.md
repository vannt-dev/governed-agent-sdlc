+++
schema_version = 1
id = "TASK-20260915000117-qa-artifact-path-remediation"
kind = "task"
status = "completed"
task_level = "medium"
created_at = "2026-09-15T00:01:17.608653+00:00"
updated_at = "2026-09-15T00:02:48.906162+00:00"
parent = "PLAN-20260914133044-project-hardening-and-codex-adoption"
repositories = ["root"]
protected_areas = []

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-15T00:01:17.7323633Z"
evidence = "approved project hardening plan and user instruction on 2026-09-15: 'ok, tiếp tục đi'"
+++

# Task: QA artifact path remediation

## Goal

Ensure `agentkit artifact new qa` writes the artifact to the documented `docs/agent/qa/`
directory and uses the conventional `QA` heading.

## Confirmed facts

- QA execution produced `docs/agent/qas/...`, while the approved plan and all existing QA
  artifacts use `docs/agent/qa/`.
- `create_artifact()` currently derives every directory as `f"{kind}s"` and every heading with
  `kind.title()`.

## Assumptions

- Existing artifact kinds retain their current plural directories.

## Open questions

- None.

## Scope

- `src/agentkit/artifacts.py`
- `tests/test_artifacts.py`
- This remediation task and the active QA evidence artifact.

## Out of scope

- Any other CLI or workflow behavior.

## Acceptance criteria

- A newly created QA artifact is placed directly under `docs/agent/qa/`.
- Its generated title begins with `# QA:`.
- Existing artifact-kind paths remain unchanged and the full unit suite passes.

## Evidence

- Added an explicit artifact-kind directory mapping so `qa` resolves to `docs/agent/qa/` while
  existing kinds retain their established directories.
- Added the conventional uppercase `QA` generated heading.
- Added `test_create_qa_uses_documented_directory_and_heading` regression coverage.
- Focused artifact suite: 7 tests passed. Full unit suite: 75 tests passed.
- Ruff lint/format, strict mypy, `agentkit validate` (0 errors/warnings), and
  `git diff --check` passed.
