+++
schema_version = 1
id = "PLAN-20260920082001-ocr-integration-remediation"
kind = "plan"
status = "approved"
task_level = "medium"
created_at = "2026-09-20T08:20:01Z"
updated_at = "2026-09-20T08:20:01Z"
parent = "SPEC-20260920082000-ocr-integration-remediation"
repositories = ["root"]
protected_areas = []

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-20T08:20:01Z"
evidence = "User instruction after the OCR integration status report: check và fix toàn bộ lại giúp mình. Implement corrective work and verify it locally."
+++

# Plan: OCR integration remediation

1. Canonicalize temporary project paths in artifact review tests.
2. Inspect provider parsing, execution and evidence handling; add regression tests for
   confirmed failures before correcting them.
3. Check stored decision and approval behavior against invalid evidence.
4. Run the complete unit suite, Ruff, mypy and agentkit validate; inspect the final diff.
5. Exercise a locally installed OCR binary on an isolated fixture and record results.
