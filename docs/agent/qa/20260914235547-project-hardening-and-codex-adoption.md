+++
schema_version = 1
id = "QA-20260914235547-project-hardening-and-codex-adoption"
kind = "qa"
status = "completed"
task_level = "high_risk"
created_at = "2026-09-14T23:55:47.068635+00:00"
updated_at = "2026-09-15T00:08:32.068506+00:00"
parent = "REVIEW-20260914135631-project-hardening-and-codex-adoption"
repositories = ["root"]
protected_areas = ["release", "authorization"]

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-14T23:55:47.068635+00:00"
evidence = "user instruction on 2026-09-15: 'ok, tiếp tục đi' after approving independent review"
+++

# QA: Project hardening and Codex adoption

## Goal

Execute the approved verification matrix against the reviewed working tree and record exact results,
defects, untested boundaries, and remaining publication gates.

## Environment

- Windows 11, PowerShell, Python 3.13 from `.venv`.
- Repository branch: `task/project-hardening-and-codex-adoption`.
- Base revision: `6a3da11` (`origin/main` at the start of QA).

## Scenarios

- Unit and branch-coverage suite.
- Ruff lint and formatting, strict mypy, compileall, workflow structure checks.
- Browser-backed responsive, keyboard-focus, navigation, and external-link checks.
- Build and Twine metadata validation plus clean-wheel installation/resource/CLI smoke checks.
- `agentkit validate`, `git diff --check`, and GitHub security/ruleset readback.

## Findings

- Resolved medium: `agentkit artifact new qa` wrote to `docs/agent/qas/` and generated a `# Qa:`
  title. Remediation task `TASK-20260915000117-qa-artifact-path-remediation` added an explicit
  directory mapping, corrected the heading, added regression coverage, and passed independent
  human review.

## Evidence

- Final `\.venv\Scripts\python.exe -m coverage run -m unittest discover -s tests -v` followed by
  `\.venv\Scripts\python.exe -m coverage report`: 75 tests passed after remediation; 86% branch
  coverage, above the 85% gate.
- `\.venv\Scripts\python.exe -m ruff check src hooks tests`: passed.
- `\.venv\Scripts\python.exe -m ruff format --check src hooks tests`: 23 files already formatted.
- `\.venv\Scripts\python.exe -m mypy`: strict configured scope passed (12 source files).
- `\.venv\Scripts\python.exe tests\workflow_checks.py`: 3 tests passed.
- `\.venv\Scripts\python.exe -m compileall -q src hooks tests`: passed.
- `\.venv\Scripts\python.exe tests\browser_checks.py`: 3 Chromium tests passed, covering external
  links, keyboard focus, and horizontal overflow at 320, 375, and 1440 pixels. The in-app browser
  had no available instance, so the reproducible project Playwright suite was used as the browser
  evidence.
- `\.venv\Scripts\python.exe -m build`: built the `0.1.1` wheel and sdist successfully.
- `\.venv\Scripts\python.exe -m twine check` against both `0.1.1` distributions: passed.
- The final rebuilt `0.1.1` wheel installed into a clean Python 3.13 virtual environment. Packaged
  resources, `py.typed`, Codex adapter discovery, `doctor`, JSON dry-run generation, validation,
  and installed-wheel `artifact new qa` path/heading checks passed. Earlier harness-order and
  Windows quoting/PATH errors were discarded; only the final fail-fast run is recorded as passing.
- QA-discovered remediation verification: focused artifact suite 7/7 and full suite 75/75 passed;
  Ruff lint/format, strict mypy, validator, and diff check passed.
- GitHub API readback: Dependabot security updates, secret scanning, and push protection enabled;
  CodeQL default setup configured for Python and Actions; zero open Dependabot/CodeQL alerts; both
  required rulesets active with the expected checks and restrictions.
- `\.venv\Scripts\python.exe -m agentkit validate`: 0 errors and 0 warnings.
- `git diff --check`: passed with Windows line-ending conversion warnings only.

## Untested boundaries

- Hosted Pull Request CI cannot run until the branch is published.
- Merge, tag, GitHub Release, and PyPI publication remain outside this QA run.
