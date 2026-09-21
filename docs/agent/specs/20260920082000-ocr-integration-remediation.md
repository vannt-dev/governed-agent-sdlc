+++
schema_version = 1
id = "SPEC-20260920082000-ocr-integration-remediation"
kind = "spec"
status = "approved"
task_level = "medium"
created_at = "2026-09-20T08:20:00Z"
updated_at = "2026-09-20T08:20:00Z"
repositories = ["root"]
protected_areas = []

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-20T08:20:00Z"
evidence = "User instruction after the OCR integration status report: check và fix toàn bộ lại giúp mình. Authorizes checking and correcting the existing integration; does not authorize publishing or merging."
+++

# Specification: OCR integration remediation

Correct cross-platform CI failures and defects in the existing OCR integration.
Malformed reviewer output must become a provider error, sensitive reviewer text must
be redacted before storage, and incomplete evidence must never satisfy a review gate.
Preserve existing CLI compatibility and zero third-party runtime dependencies.

Acceptance: platform-independent artifact path tests; regression coverage for confirmed
provider/evidence defects; full unit, lint, format, type and project validation checks;
an isolated real OCR CLI smoke test where possible. Record any untested LLM behavior.
New UI products, mandatory artifact workflow changes, release and merge are outside
this corrective scope.
