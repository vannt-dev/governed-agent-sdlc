# Changelog

All notable changes to Governed Agent SDLC are documented here. The project follows Semantic
Versioning while its public interfaces remain alpha.

## [0.6.0] - 2026-10-12

### Upgrade notes

- `agentkit artifact new plan`, `new review`, and `new qa` create different sections than before.
  Artifacts that already exist are not changed and stay valid.

### Added

- Templates for plans, reviews, and QA records under `core/templates/`, with the sections this
  project's own records settled on: a plan has `Outcome`, `Preconditions`, `Task graph`,
  `Ordering rationale`, `Verification`, and `Risks and required approvals`; a review has
  `Outcome`, `Scope reviewed`, `Findings`, `Missing tests`, `Verification evidence`, and
  `Residual risk`; a QA record has `Outcome`, `Environment and subject`,
  `Verification evidence`, `Unresolved defects`, and `Residual risks and untested areas`.

### Changed

- `agentkit artifact new plan`, `new review`, and `new qa` start from those templates instead of
  the generic sections. A project without its own copy of a template gets the packaged one.
  Artifacts that already exist are not changed.

## [0.5.0] - 2026-10-11

### Upgrade notes

- After upgrading the package, run `agentkit update-hooks` and then
  `agentkit generate claude-code --force` (or `generate codex --force`), in that order.
- `agentkit artifact new spec` and `agentkit artifact new task` create different sections than
  before. Artifacts that already exist are not changed and stay valid.

### Added

- `agentkit update-hooks [path] [--dry-run]` replaces a project's guard hooks with the ones the
  installed version ships. `init` never overwrites an existing `hooks/`, so this is how an
  existing project gets new and fixed guards. Files the package does not ship are left alone.
- `agentkit validate` and `agentkit doctor` warn when `.claude/settings.json` registers a guard
  file the project does not have.

### Changed

- `agentkit artifact new spec` and `agentkit artifact new task` start from the sections in
  `core/templates/` (the project's copy first, then the packaged one) instead of a second,
  generic list kept in the CLI. A new task now has `Write scope`, `Read-only impact scope`,
  `Dependencies`, `Verification`, and `Completion evidence`. Kinds with no template keep the
  generic sections.

### Fixed

- `agentkit init` run from a source checkout copied `__pycache__` folders into the new project's
  `hooks/`.

## [0.4.0] - 2026-10-11

### Upgrade notes

- `agentkit init` never overwrites an existing `hooks/` directory, so a project initialized with an
  earlier version keeps its old guards. Copy `hooks/*.py` from this version into the project before
  running `agentkit generate claude-code --force`: the regenerated settings name
  `hooks/guard_role_gate.py`, and a guard file that is missing fails every subagent spawn closed.
- The `developer` role is now restricted under `docs/agent/`: it may change only the completion
  evidence section of an existing task file. `reviewer` and `qa` gain the same right on task files
  outside their own directories. The main session is not affected.
- A command that only contains the word `env` is no longer refused. `env` and `printenv` are
  refused in command position, a secret file is refused when named as a shell word, and
  `echo`/`printf` are refused when they expand a variable next to a secret name.

### Added

- `hooks/guard_role_gate.py`: a role is spawned only from artifacts that passed their gate in
  `core/policies/workflow.toml`. It checks the artifacts the spawn prompt names and respects the
  manifest's `[workflow]` flags. Claude Code only; Codex has no equivalent tool hook.
- Task level `mechanical` for one uniform edit repeated across many files, with every level defined
  under `[task_levels]` in `core/policies/workflow.toml`.
- `agentkit validate` and `agentkit doctor` warn when an agent instruction file names a file that
  does not exist.
- The generated Claude Code settings also run the credential and git guards for the `PowerShell`
  tool, and the role-scope guard for `MultiEdit`.

### Fixed

- The credential guards (Claude Code and Codex) refused ordinary commands that mention a rule:
  `git commit -m "document env vars"`, `uv run --env-file x pytest`, `npx cross-env ...`,
  `echo "token refresh done"`, and heredocs whose text names `git credential`. Heredoc bodies are
  now treated as data, except for the command substitutions an unquoted heredoc still expands.
- `cat .env` was refused only because it contains the word `env`; secret files are now matched as
  files.

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

[0.6.0]: https://github.com/vannt-dev/governed-agent-sdlc/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/vannt-dev/governed-agent-sdlc/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/vannt-dev/governed-agent-sdlc/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/vannt-dev/governed-agent-sdlc/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/vannt-dev/governed-agent-sdlc/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/vannt-dev/governed-agent-sdlc/releases/tag/v0.1.0
