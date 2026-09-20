# Changelog

All notable changes to Governed Agent SDLC are documented here. The project follows Semantic
Versioning while its public interfaces remain alpha.

## [0.1.1] - Unreleased

### Added

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

[0.1.1]: https://github.com/vannt-dev/governed-agent-sdlc/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/vannt-dev/governed-agent-sdlc/releases/tag/v0.1.0
