+++
schema_version = 1
id = "REVIEW-20260914135631-project-hardening-and-codex-adoption"
kind = "review"
status = "completed"
task_level = "high_risk"
created_at = "2026-09-14T13:56:31.0000000Z"
updated_at = "2026-09-14T23:55:46.227935+00:00"
parent = "TASK-20260914134500-project-hardening-and-codex-adoption"
repositories = ["root"]
protected_areas = ["release", "authorization"]

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-14T23:55:45.980606+00:00"
evidence = "user instruction on 2026-09-15: 'ok, tiếp tục đi' after receiving the independent re-review conclusion"
+++

# Review request: Project hardening and Codex adoption

## State

Awaiting an independent reviewer. The implementation agent has recorded reproducible evidence but
has not approved its own changes.

## Required review focus

- Authorization and credential boundaries in generated Claude/Codex configuration and CLI paths.
- Release integrity: tag ancestry, pinned actions/tooling, attestations, and Trusted Publishing
  isolation.
- Backward compatibility for existing text CLI behavior, manifests, artifacts, and Claude output.
- Codex adapter correctness against official project configuration and layered `AGENTS.md` behavior.
- GitHub setting readback for Dependabot, CodeQL, main protection, and release-tag protection.
- Test completeness for JSON/dry-run/migration/artifact operations, packaging, and browser behavior.

## Candidate evidence

- Local unit tests after remediation: 74 passed; branch coverage: 86%.
- Ruff lint/format, strict mypy, compileall, `git diff --check`, and `agentkit validate`: passed.
- Workflow structure checks: 3 passed. Browser checks: 3 passed.
- Final `0.1.1` sdist/wheel: build and Twine validation passed; clean-wheel Codex/JSON/resource smoke
  test passed.
- CodeQL setup run `34852075380`: successful for Python and Actions; zero open CodeQL alerts.
- Dependabot alerts and automated security fixes: enabled; zero open Dependabot alerts.
- Rulesets read back as active: `main-protection` (`23188809`) and
  `release-tag-protection` (`23310501`).

## Untested boundary

The expanded hosted CI matrix has not run on this change because publishing the branch/PR follows
independent review. Merge, tag creation, GitHub Release, and PyPI publication remain prohibited
without the later explicit human decision.

## Initial independent findings

The independent reviewer reported no high findings, four medium findings, and two low findings:

1. Project Codex configuration could override stricter user approval/sandbox settings.
2. Codex restrictions were instructional only and lacked a technical hook guardrail.
3. Installed-wheel capability discovery omitted packaged adapters.
4. Malformed TOML escaped migration error handling and its documented exit/JSON contract.
5. Dependabot requested labels that did not exist.
6. Release reruns could attest rebuilt bytes while retaining different existing release assets.

## Remediation candidate

- Removed project-level approval/sandbox overrides. Codex now inherits the user's policy, while
  architect/planner/reviewer/QA/publisher subagents receive a stricter read-only role config.
- Added a project-local `PreToolUse` hook for credential access, environment dumps, force/direct
  protected pushes, and destructive git operations. The generated hook uses portable
  `uv run --no-project python`, resolves from Git root, and is documented as defense in depth.
- Added installed-resource adapter discovery and a clean-wheel manifest capability check.
- Converted malformed migration TOML to `ConfigError` and added text/JSON regression coverage.
- Removed nonexistent Dependabot labels.
- Made release creation fail if the GitHub Release already exists and required attestation
  verification on both downloaded assets before Trusted Publishing.
- Added direct hook deny/allow tests and an installed-wheel smoke test from a nested project path.

These remediations have not yet been accepted by the independent reviewer.

## Independent re-review — 2026-09-14

### Conclusion

No high, medium, or low findings remain in the remediation candidate. The six initial findings are
resolved in the reviewed working tree. The workspace user approved this review on 2026-09-15, and
the review lifecycle is complete.

### Evidence

- Inspected the complete remediation paths for Codex generation and hooks, CLI migration/error
  handling, installed-resource adapter discovery, Dependabot configuration, and release asset
  provenance.
- Compared generated Codex configuration with the current official OpenAI configuration reference
  and Hooks guide. Project `hooks.json`, `PreToolUse`, `commandWindows`, `agents.<name>.config_file`,
  `project_root_markers`, `features.hooks`, and `features.multi_agent` match the documented schema.
- `\.venv\Scripts\python.exe -m unittest discover -s tests -v`: 74 tests passed. The first
  sandboxed attempt could not create Windows temporary directories; the same command was rerun
  outside the filesystem sandbox and passed.
- `\.venv\Scripts\python.exe -m ruff check src hooks tests`: passed.
- `\.venv\Scripts\python.exe -m ruff format --check src hooks tests`: 23 files already formatted.
- `\.venv\Scripts\python.exe -m mypy`: passed for the configured strict scope (12 source files).
- `\.venv\Scripts\python.exe -m compileall -q src hooks tests`: passed.
- `\.venv\Scripts\python.exe -m agentkit validate`: 0 errors and 0 warnings.
- `git diff --check`: passed; Git emitted only line-ending conversion warnings on Windows.
- GitHub API readback: Dependabot security updates, secret scanning, and push protection enabled;
  zero open Dependabot and CodeQL alerts; CodeQL default setup configured for Python and Actions.
- GitHub API readback: `main-protection` (`23188809`) is active with strict current checks, resolved
  conversations, the nine OS/Python checks, `quality`, `package`, and `browser` contexts.
  `release-tag-protection` (`23310501`) is active for `refs/tags/v*` with creation, deletion, and
  non-fast-forward restrictions. The `dependencies` label referenced by Dependabot exists.

### Remaining boundaries

- Hosted Pull Request CI has not run because the reviewed branch has not been published.
- Project-local Codex hooks require the user's normal project/hook trust review before execution;
  this is intentional Codex behavior, and hooks remain defense in depth rather than a complete
  enforcement boundary.
- Merge, release tag creation, GitHub Release creation, and PyPI publication remain prohibited
  pending the later human gates.
