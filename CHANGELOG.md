# Changelog

All notable changes to Governed Agent SDLC are documented here. The project follows Semantic
Versioning while its public interfaces remain alpha.

## [0.3.0] - 2026-09-24

### Upgrade notes

- Findings files evaluated with `review evaluate` now use the project's `[[policies]]`; stricter project rules can change the exit code.
- A missing or unknown finding severity now normalizes to `medium` (warns under the default policies) instead of `info`.

### Fixed

- `review evaluate` now applies the project's configured `[[policies]]` instead of always using the defaults.
- File findings with a missing or unknown severity normalize to `medium`, like OCR findings, instead of non-blocking `info`.

## [0.2.0] - 2026-09-22

### Upgrade notes

- Invalid review severity/category filters now fail configuration loading. Use canonical values from the finding schema; correct misspellings before upgrading.
- Old review evidence without source fingerprints is unverified. Run a new review after upgrading; do not reuse historical passing verdicts.

### Added

- Source-bound review evidence, stale/legacy gate states, process locks and interrupted-attempt recovery.
- Opt-in artifact completion gates and GitHub PR review verification for human approvals.
- Host CLI review with validated OCR delegation rules, bounded stdin context, shared version-1 finding fixtures and opt-in semantic evaluations.

- Native Codex adapter generation based on project-scoped `AGENTS.md` discovery.
- Machine-readable CLI output, safe previews, artifact inspection, and manifest migration support.
- Artifact-level package verification, lint, type, coverage, and browser-backed site checks.
- Code scanning and stronger repository/release governance.
- Governed review: `agentkit review run|approve|status|preview` with an OpenCodeReview provider that
  uses the real `ocr` CLI, policy decisions from the manifest, human approval records, bounded
  remediation attempts, requirement-aware review background, and append-only per-attempt evidence
  under `.agent/runs/`.
- Manifest tables `[review]`, `[[policies]]` and `[remediation]`.
- Append-only per-run event log, `review report` (text, JSON and escaped static HTML), `--artifact`
  linking of a run to a review artifact, and `agentkit validate` checks for stored review evidence.
- `core/schemas/review-finding.schema.json`, the finding contract shared with Junto.

### Changed

- Bind freshness to working-tree file modes as well as content, keep selected Git paths literal, and record Git input timeouts as provider failures.
- Canonicalize review artifact test paths across Windows short names and macOS symlinks.
- Malformed OCR statuses produce typed provider errors; both output streams are bounded while running and decoded as UTF-8. Evidence redaction preserves escaped JSON strings.
- Status and reports refuse incomplete or inconsistent evidence, and invalid stored approval records cannot satisfy a human approval gate.
- Added an opt-in real OCR preview smoke test using `OCR_SMOKE_BIN`; it needs an installed binary but no LLM.
- Skipped OCR reviews now remain nonpassing in run, status, and report output (`run`/`status` exit `6`).
- Review retries reuse their original background when context arguments are omitted and reject changed context before invoking the provider; changed requirements or plans need a new run id.
- A review provider failure (missing binary, timeout, malformed output) is now a distinct provider
  error with exit code `3`, not a synthetic finding; review evidence is never overwritten and raw
  provider output is redacted before it is stored or printed.

- Completed PyPI project metadata and public installation guidance.
- Pinned the release build toolchain and hardened tag-to-main validation.

## [0.1.0] - 2026-09-14

### Added

- Initial governed workflow kernel, roles, policies, schemas, profiles, Claude Code adapter, CLI,
  deterministic safety hooks, cross-platform CI, GitHub Pages site, GitHub Release automation, and
  PyPI Trusted Publishing.

[0.3.0]: https://github.com/vannt-dev/governed-agent-sdlc/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/vannt-dev/governed-agent-sdlc/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/vannt-dev/governed-agent-sdlc/releases/tag/v0.1.0
