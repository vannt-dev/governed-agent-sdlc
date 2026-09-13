+++
schema_version = 1
id = "QA-20260913153405-hardening-and-validation"
kind = "qa"
status = "completed"
task_level = "high_risk"
created_at = "2026-09-13T15:34:05.8435648Z"
updated_at = "2026-09-13T15:36:30.955790+00:00"
parent = "REVIEW-20260913152632-hardening-and-validation-remediation"
repositories = ["root"]
protected_areas = ["authorization", "credentials"]

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-13T15:36:30.721174+00:00"
evidence = "current Codex thread: user replied 'ok, duyệt' to QA report"
+++

# QA: Repository-wide hardening and validation

## Outcome

PASS. The complete approved QA matrix passed against the current workspace and the final wheel.
This artifact remains `awaiting_approval`; QA has not self-approved, published, merged, pushed, or
modified implementation source.

## Environment and subject

- Host: Windows 11 (`Windows-11-10.0.26200-SP0`).
- Runtime: CPython 3.13.15 managed by `uv`.
- Branch: `main`.
- Revision: unavailable because the repository has no `HEAD` commit (`fatal: Needed a single
  revision`). All repository content is untracked, so QA tested the complete current files rather
  than a committed or tracked diff.
- Wheel: `governed_agent_sdlc-0.1.0-py3-none-any.whl`.
- Wheel SHA-256: `83CBBF7ECA19A613FC59784F98D9F4CDFAA6580E63E2BB7DC5AFE8F7E1BCC78D`.
- Isolated install location:
  `.temp/qa-20260913-1530/venv/Lib/site-packages/agentkit/__init__.py`.

## Verification evidence

### Schemas and compilation

Command:

```powershell
uv run --no-project python -c "import json, pathlib; files=['core/schemas/artifact.schema.json','core/schemas/project.schema.json']; [json.loads(pathlib.Path(f).read_text(encoding='utf-8')) for f in files]; print('parsed:', ', '.join(files))"
uv run --no-project python -m compileall -q src hooks tests
```

Result: PASS. Both JSON schema documents parsed successfully. `compileall` completed without an
error for `src`, `hooks`, and `tests`.

### Unit tests and project validation

Command:

```powershell
$env:PYTHONPATH='src'
uv run --no-project python -m unittest discover -s tests -v
uv run --no-project python -m agentkit validate
```

Result: PASS. All 38 tests passed in 0.200 seconds. Validation reported `0 error(s), 0 warning(s)`.

### Worktree checks

Command:

```powershell
git diff --check
git status --short
git branch --show-current
git rev-parse --verify HEAD
```

Result: `git diff --check` passed and the branch is `main`. `git status --short` reports all current
repository files as untracked. `git rev-parse --verify HEAD` fails because no initial commit exists.

### Wheel build and archive inspection

Command:

```powershell
$env:UV_CACHE_DIR='.temp/uv-qa-cache'
uv build --wheel --out-dir .temp/qa-20260913-1530/dist
```

Result: PASS. The build produced the wheel above. Archive inspection with Python `zipfile` found 33
entries and confirmed the packaged schemas, QA role, all three guards, and generic/Python profile
resources. No required resource was missing. The warning that the selected uv cache is below the
source directory did not affect the wheel; the archive listing contains no `.temp` or cache entry.

Required entries checked:

- `agentkit/resources/core/schemas/artifact.schema.json`
- `agentkit/resources/core/schemas/project.schema.json`
- `agentkit/resources/core/roles/qa.toml`
- `agentkit/resources/hooks/guard_credentials.py`
- `agentkit/resources/hooks/guard_git.py`
- `agentkit/resources/hooks/guard_role_scope.py`
- `agentkit/resources/profiles/generic/profile.toml`
- `agentkit/resources/profiles/python/profile.toml`

### Isolated installation and scaffold smoke test

Commands:

```powershell
uv venv .temp/qa-20260913-1530/venv --python 3.13
uv pip install --python .temp/qa-20260913-1530/venv/Scripts/python.exe --no-deps <built-wheel>
<isolated-agentkit> init .temp/qa-20260913-1530/fresh-scaffold --name "QA dual manifest" --adapter claude-code
<isolated-agentkit> doctor .temp/qa-20260913-1530/fresh-scaffold
<isolated-agentkit> validate .temp/qa-20260913-1530/fresh-scaffold
```

Result: PASS. Installation resolved only the local wheel and installed
`governed-agent-sdlc==0.1.0`. `init` created 12 scaffold items. Both `doctor` and `validate`
reported `0 error(s), 0 warning(s)`.

Manual assertions against generated files passed:

- `.agent/project.toml` exists and the root `agentkit.toml` is absent.
- Generated `AGENTS.md` and `.claude/agents/qa.md` mention both `agentkit.toml` and
  `.agent/project.toml`.
- `.claude/settings.json` contains the exact credential matcher `Bash|Read|Glob|Grep`, the Git
  matcher `Bash`, and the role-scope matcher `Write|Edit`.

### Complete positive workflow chain

A disposable fixture was created below the fresh scaffold with installed-package serialization:

```text
SPEC-QA-CHAIN (approved)
  -> PLAN-QA-CHAIN (approved)
  -> TASK-QA-CHAIN (completed)
  -> REVIEW-QA-CHAIN (completed)
  -> QA-QA-CHAIN (awaiting_approval)
```

Command:

```powershell
<isolated-agentkit> validate .temp/qa-20260913-1530/fresh-scaffold
```

Result: PASS, `0 error(s), 0 warning(s)`. This covers the prior low-severity gap where no single
positive fixture exercised every configured parent gate end to end. The fixture is disposable and
did not alter source or repository workflow artifacts.

## Transparent rerun notes

- Initial sandboxed `uv` calls could not access the user-level uv cache. The same checks were rerun
  with approved access to the managed runtime.
- The first unit-test invocation set `PYTHONPATH=src` after the test command, causing four test
  modules to fail import. The corrected command above then passed all 38 tests.
- An initial wheel-resource assertion used the incorrect expected path
  `agentkit/resources/profiles/generic.toml`. Archive listing showed the actual intended packaged
  layout at `agentkit/resources/profiles/generic/profile.toml`; the corrected assertion passed.
- A supplemental quoted-name assertion was invalid because native PowerShell argument processing
  removed the embedded quotes before the CLI received them. This was not counted as a product
  failure; the generated manifest parsed and validated successfully.

## Residual risks and untested areas

- QA covered Windows and Python 3.13 only. Python 3.11/3.12 and Linux/macOS CI jobs were not run in
  this local session.
- With no baseline commit, QA cannot bind the evidence to a commit SHA or detect omissions through
  a tracked diff.
- As documented by the completed independent review, present-but-empty `tool_input` objects remain
  accepted by credential and Git guards. Current Claude tool schemas do not execute an action from
  an empty object, but stricter structural validation remains a possible future hardening item.
- JSON schemas were syntax-parsed as required; no external JSON Schema conformance engine was added
  or invoked because the project intentionally has no runtime dependencies.

## Gate decision

The implementation meets the approved QA matrix with no observed release-blocking defect. Human
approval is required before this artifact can transition beyond `awaiting_approval`. Publishing,
merging, pushing, and release remain out of scope.
