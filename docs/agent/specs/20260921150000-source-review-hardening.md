+++
schema_version = 1
id = "SPEC-20260921150000-source-review-hardening"
kind = "spec"
status = "approved"
task_level = "high_risk"
created_at = "2026-09-21T15:00:00Z"
updated_at = "2026-09-21T15:00:00Z"
repositories = ["root"]
protected_areas = ["authorization"]

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-21T15:00:00Z"
evidence = "User requested checking whether previous branches were merged and, if merged, creating new branches to continue implementation after the seven-defect source review. Scope here is the reported policy validation defect and its regression coverage. No merge or release authorization."
+++

# Reject invalid review policy filters

Reject severity and category values outside the shared normalized finding contract while loading project configuration. Typos, case mismatches, and empty filters must not silently disable a blocking rule. Preserve valid custom policy replacement semantics and existing explicit provider/enforcement settings.
