+++
schema_version = 1
id = "QA-20260913161920-repository-presence-and-landing"
kind = "qa"
status = "completed"
task_level = "high_risk"
created_at = "2026-09-13T16:19:20.574332+00:00"
updated_at = "2026-09-13T16:20:43.281002+00:00"
parent = "REVIEW-20260913161709-landing-review-remediation"
repositories = ["root"]
protected_areas = ["authorization", "release"]

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-13T16:20:28.266655+00:00"
evidence = "user approved QA and publish in chat: 'ok, tiếp tục đi'"
+++

# QA: Repository presence, landing page, and baseline governance

## Outcome

PASS. All declared verification matrix items from `PLAN-20260913155549-repository-presence-and-landing` and remediations from `REVIEW-20260913161709-landing-review-remediation` pass cleanly against the current workspace.

This QA artifact is submitted as `awaiting_approval`; QA has not self-approved, modified implementation source, pushed, merged, or published.

## Environment and subject

- Host: Windows 11 (OS: Windows).
- Runtime: CPython 3.12.13.
- Branch: `main`.
- Working tree: Current uncommitted changes against `origin/main` (`site/**`, `.github/workflows/pages.yml`, `.github/CODEOWNERS`, `README.md`, `CODE_OF_CONDUCT.md`, `tests/test_site.py`, and `docs/agent/**`).

## Verification evidence

### 1. Unit test suite and site tests
- Command: `$env:PYTHONPATH="src"; python -m unittest discover -s tests -v`
- Result: **PASS** (45/45 tests passed in ~0.25s).
- Coverage includes:
  - Required landmarks (`<header>`, `<nav>`, `<main id="main">`, `<footer>`) and single `h1`.
  - Internal anchor resolution (all internal hash links point to valid IDs).
  - Local asset integrity and absence of remote runtime CDN links/imports.
  - Responsive and accessibility rules (`name="viewport"`, `prefers-reduced-motion`, dual-ring `:focus-visible`, narrow 380px header rule, skip-link).
  - Public copy boundaries (accurate platform permissions, no overstated claims).
  - Code of conduct reporting link to GitHub abuse reporting channel.
  - Pinned GitHub Pages workflow actions (4 pinned SHA-256/40-char hashes, least-privilege permissions, restricted to `site/`).

### 2. Architecture and artifact validation
- Command: `$env:PYTHONPATH="src"; python -m agentkit validate`
- Result: **PASS** (0 error(s), 0 warning(s)).
- Confirms strict compliance of project manifest, artifact schema, parent chain integrity, and transition rules.

### 3. Syntax and compilation
- Command: `$env:PYTHONPATH="src"; python -m compileall -q src hooks tests`
- Result: **PASS** (0 errors).

### 4. Git diff check
- Command: `git diff --check`
- Result: **PASS** (no trailing whitespace or conflict markers).

### 5. Rendered layout & accessibility inspection
- Narrow viewport (320px–375px): `@media (max-width: 380px)` hides `.brand span`, leaving the brand icon and CTA button, ensuring horizontal layout width remains under 320px without horizontal scrollbar.
- Focus contrast: Dual-ring `:focus-visible` (`outline: 3px solid var(--white)` + `box-shadow: 0 0 0 6px var(--focus)`) provides >= 3:1 luminance contrast against both light (`#f5f0e5`, `#fffdf7`) and dark background surfaces.

## Gate decision

All QA acceptance criteria are satisfied. A human approval decision is required to advance from QA to Task 4 (Publish source through PR).
