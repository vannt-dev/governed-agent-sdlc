+++
schema_version = 1
id = "TASK-20260920082002-ocr-integration-remediation"
kind = "task"
status = "completed"
task_level = "medium"
created_at = "2026-09-20T08:20:02Z"
updated_at = "2026-09-20T08:25:00Z"
parent = "PLAN-20260920082001-ocr-integration-remediation"
repositories = ["root"]
protected_areas = []

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-20T08:20:02Z"
evidence = "User instruction after the OCR integration status report: check và fix toàn bộ lại giúp mình; corrective implementation under the associated spec and plan."
+++

# Task: Correct OCR integration defects

Scope: src/agentkit review, policy, approval, run and evidence code; associated tests;
integration documentation and these workflow records. Verification results are recorded
below. Publishing and merging are not part of this task.

## Verification

- Canonicalized the review test fixture root to address the two CI path failures.
- Hardened OCR schema parsing, UTF-8 process output, bounded concurrent pipe reads,
  redaction of errors and JSON evidence, stored policy/approval checks, and report handling.
- With OCR_SMOKE_BIN set to the installed v1.12.7 executable:
  `python -m coverage run -m unittest discover -s tests`: 165 tests passed.
  `python -m coverage report`: 89%, above the 85% CI requirement.
- `python -m ruff check`, `python -m ruff format --check`, `python -m mypy`,
  `python tests/workflow_checks.py`, and `python -m agentkit validate`: passed.
- Real OCR delegation preview passed for an empty and a changed temporary repository.
  A full review reported a missing LLM endpoint; semantic LLM review remains unverified.
- These are local results on Windows. The remote platform matrix has not been rerun;
  the corrective changes have not been committed or pushed.
