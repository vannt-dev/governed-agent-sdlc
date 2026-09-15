+++
schema_version = 1
id = "TASK-20260915001708-deterministic-browser-link-checks"
kind = "task"
status = "completed"
task_level = "medium"
created_at = "2026-09-15T00:17:08.441663+00:00"
updated_at = "2026-09-15T00:20:21.761242+00:00"
parent = "PLAN-20260914133044-project-hardening-and-codex-adoption"
repositories = ["root"]
protected_areas = []

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-15T00:17:08.5223896Z"
evidence = "approved browser-backed verification scope and instructed continuation through PR preparation"
+++

# Task: Deterministic browser link checks

## Goal

Remove GitHub runner rate-limit flakiness while preserving validation of every external link on the
site.

## Confirmed facts

- The same browser test passed on commit `527fc4d`, then failed twice on documentation-only commit
  `5205f69` because GitHub returned HTTP 429 for valid same-repository file URLs.
- All current HTTPS links target `https://github.com/vannt-dev/governed-agent-sdlc`; file links use
  `blob/main/<repository path>`.

## Assumptions

- Same-repository file targets are more reliably validated against the checked-out revision than
  through unauthenticated GitHub HTML requests from shared runners.

## Open questions

- None.

## Scope

- `tests/browser_checks.py`
- Lifecycle evidence for this remediation.

## Out of scope

- Site content or layout changes.

## Acceptance criteria

- Every HTTPS link must target the canonical repository URL.
- Every `blob/main` link must resolve to a real file inside the repository root.
- Browser layout, focus, and link checks pass locally and in hosted CI without network requests to
  GitHub HTML pages.

## Evidence

- Replaced unauthenticated GitHub HTML requests with deterministic validation of the canonical
  repository URL and checked-out `blob/main` file targets.
- Local Chromium browser suite: 3/3 passed without external network requests.
- Full unit suite: 75/75 passed.
- Ruff lint/format, strict mypy, `agentkit validate` (0 errors/warnings), and
  `git diff --check` passed.
