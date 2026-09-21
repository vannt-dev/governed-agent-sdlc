+++
schema_version = 1
id = "SPEC-20260920090000-ocr-integration-completion"
kind = "spec"
status = "approved"
task_level = "high_risk"
created_at = "2026-09-20T09:00:00Z"
updated_at = "2026-09-20T09:00:00Z"
repositories = ["root"]
protected_areas = ["authorization"]

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-20T09:00:00Z"
evidence = "User accepted the full prioritized upgrade list and requested implementation of all items, plus durable handoff notes; then requested flexibility for Claude, Codex and other backends. Feature-branch commit/push is in that list; merge and release remain unauthorized."
+++

# OCR integration completion

Implement freshness, shared findings, artifact gates, run locking/recovery, verified GitHub approvals, selectable review backends, delegation rules, behavioral evals, reports, and feature-branch CI delivery. Preserve zero runtime dependencies. Local approval mode remains compatible; strict artifact/GitHub gates are explicit opt-ins. Do not merge or release.
