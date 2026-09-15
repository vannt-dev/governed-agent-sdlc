+++
schema_version = 1
id = "REVIEW-20260915002021-deterministic-browser-link-checks"
kind = "review"
status = "completed"
task_level = "medium"
created_at = "2026-09-15T00:20:21.886994+00:00"
updated_at = "2026-09-15T00:22:14.242990+00:00"
parent = "TASK-20260915001708-deterministic-browser-link-checks"
repositories = ["root"]
protected_areas = []

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-15T00:22:13.607075+00:00"
evidence = "user instruction on 2026-09-15: 'ok' after reviewing the deterministic browser link checks summary and passing checks"
+++

# Review request: deterministic browser link checks

## Goal

Independently verify the deterministic browser-link remediation before updating pull request #9.

## Confirmed facts

- Two hosted browser-check attempts failed when valid same-repository GitHub HTML URLs returned
  HTTP 429 responses.
- All seven HTTPS links in `site/index.html` target the canonical project repository; three target
  files under its `blob/main/` path.
- The browser check now validates the canonical repository URL directly and resolves repository-file
  links to real files inside the workspace instead of requesting GitHub HTML.
- Local verification passes: browser checks 3/3, unit tests 75/75, Ruff lint and format, strict mypy,
  `agentkit validate`, and `git diff --check`.

## Assumptions

- The current same-repository link policy is intentionally narrower than a general-purpose external
  URL availability checker.

## Open questions

- None. The workspace user approved the remediation review on 2026-09-15.

## Scope

- `tests/browser_checks.py`

## Out of scope

- Adding arbitrary third-party links to the site.
- Merging or releasing pull request #9.

## Acceptance criteria

- Browser checks make no unauthenticated GitHub HTML requests.
- Repository URLs must use the canonical repository and `blob/main/` form for file links.
- Every repository-file link resolves to an existing file without escaping the repository root.
- The browser suite passes locally.

## Evidence

- Hosted browser jobs `104201829081` and `104202331382` failed on different valid repository links
  with HTTP 429.
- `.venv\Scripts\python.exe tests\browser_checks.py`: 3/3 passed.
- `.venv\Scripts\python.exe -m unittest discover -s tests -v`: 75/75 passed.
- Ruff lint/format, strict mypy, `agentkit validate`, and `git diff --check`: passed.
