+++
schema_version = 1
id = "REVIEW-20260913152024-hardening-and-validation"
kind = "review"
status = "archived"
task_level = "high_risk"
created_at = "2026-09-13T15:20:24.5042424Z"
updated_at = "2026-09-13T15:26:32.7731029Z"
parent = "TASK-20260913150502-docs-packaging"
repositories = ["root"]
protected_areas = ["authorization", "credentials"]
+++

# Independent review: Repository-wide hardening and validation

## Outcome

Review does not pass. Two high-severity security findings and one medium-severity validation
finding remain unresolved. The artifact remains `draft`, so QA's required `review.completed` gate
is intentionally not satisfied.

This result was superseded by `REVIEW-20260913152632-hardening-and-validation-remediation` after
remediation task `TASK-20260913152152-review-remediation` completed.

## Scope reviewed

- Approved specification `SPEC-20260913150033-hardening-and-validation`.
- Approved plan `PLAN-20260913150236-hardening-and-validation` and completed Tasks 1-5.
- Python CLI, manifest loading, artifact lifecycle and validation, generators, packaged resources,
  security hooks, schemas, tests, documentation, and GitHub workflows.
- Current uncommitted workspace; the repository has no baseline commit, so review was against the
  complete current files rather than a historical diff.

## Findings

### High: Protected-branch deletion refspecs bypass the Git guard

`hooks/guard_git.py:11-15` requires a non-empty source before the optional colon. Git deletion
refspecs have an empty source, so `git push origin :main` and
`git push origin :refs/heads/main` both return `None` from `evaluate` and would be allowed. These
commands directly modify/delete a protected branch, contrary to `core/policies/security.toml:11`
and specification acceptance criterion 8.

Required remediation: recognize empty-source deletion refspecs for every protected branch and add
deny tests for short and fully qualified destinations, paired with an allow test for deletion of a
non-protected feature branch if that operation is intended to remain allowed.

### High: Structurally malformed hook payloads fail open

`hooks/common.py:31-33` converts a missing or non-object `tool_input` to `{}`. Consequently both
`hooks/guard_credentials.py:30-46` and `hooks/guard_git.py:23-30` allow `{}` and
`{"tool_input": "bad"}`. The JSON is parseable but does not conform to the PreToolUse input shape,
so this contradicts the declared fail-closed behavior and specification acceptance criterion 8.
The existing test at `tests/test_guards.py:96-108` covers invalid JSON only and misses malformed
object shapes.

Required remediation: validate the hook event/tool name/tool-input object and required
tool-specific fields before evaluation, returning a denial for missing or invalid shapes. Add raw
process and direct evaluation tests for empty objects, scalar `tool_input`, missing Bash command,
and missing file/search inputs.

### Medium: Python validation is not schema-equivalent for booleans and approval objects

`src/agentkit/config.py:116-117` and `src/agentkit/validator.py:115-116` compare version values with
integer `1`; in Python, `True == 1`, so TOML `version = true` and `schema_version = true` are
accepted despite the schemas' integer constant. In addition, `src/agentkit/validator.py:141-155`
validates `approval` only for approval-history statuses. A draft artifact containing
`approval = "junk"`, or an approval table with unknown fields, produces no finding even though
`core/schemas/artifact.schema.json:30-39` requires an object and forbids additional properties.
This falls short of the spec's strict field-type and schema-equivalent validation requirements.

Required remediation: reject booleans explicitly for numeric schema versions; whenever `approval`
is present, validate its object type, allowed fields, field types, and timestamp, then separately
enforce its presence for approval-history states. Add regression tests for all cases.

## Missing tests

- Protected-branch deletion refspecs (`:main`, `:refs/heads/main`).
- Parseable but structurally invalid hook payloads and missing required tool fields.
- Boolean manifest/artifact schema versions.
- Invalid or additional approval metadata in statuses that do not require approval history.
- Full positive ancestry chain through completed review and QA (current tests exercise isolated
  parent failures but not the complete enabled workflow).

## Verification evidence

- `uv run --no-project python -m unittest discover -s tests -v` (outside the filesystem sandbox
  because Python's system temporary directory was otherwise denied): 33 tests passed.
- `$env:PYTHONPATH='src'; uv run --no-project python -m agentkit validate`: 0 errors, 0 warnings
  before this draft review artifact was added.
- `$env:PYTHONPATH='src'; uv run --no-project python -m compileall -q src hooks tests`: passed.
- `git diff --check`: passed; no tracked diff exists because all workspace files are untracked.
- Direct guard probes: both protected deletion commands and malformed hook objects returned `None`.
- Direct validator probes: malformed draft approval values and extra approval keys produced no
  findings.

## Residual risk

Regex-based shell inspection is not a complete shell parser, so fixes should cover documented and
common refspec spellings without claiming resistance to arbitrary shell obfuscation. QA should not
start until this review is remediated, re-reviewed, and transitioned through the governed lifecycle.
