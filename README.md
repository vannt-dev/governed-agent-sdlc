<div align="center">

# Governed Agent SDLC

**Ship with agents. Keep humans in control.**

[![Validate](https://github.com/vannt-dev/governed-agent-sdlc/actions/workflows/validate.yml/badge.svg)](https://github.com/vannt-dev/governed-agent-sdlc/actions/workflows/validate.yml)
[![PyPI](https://img.shields.io/pypi/v/governed-agent-sdlc.svg)](https://pypi.org/project/governed-agent-sdlc/)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-0b7771)](https://www.python.org/)
[![MIT License](https://img.shields.io/badge/License-MIT-f06f4f.svg)](LICENSE)

[Project website](https://vannt-dev.github.io/governed-agent-sdlc/) · [Architecture](docs/architecture.md) · [Workflow](docs/workflow.md) · [CLI reference](docs/cli.md) · [Adoption guide](docs/adoption.md)

</div>

Governed Agent SDLC is a cross-platform toolkit for AI coding agents. It separates a
tool-neutral workflow kernel from project profiles and vendor adapters, so the same approval,
security, artifact, review, and QA rules can be applied to different technology stacks.

The project is intentionally **human-in-the-loop**. It helps agents work predictably; it does not
grant an AI permission to approve, merge, release, or retrieve credentials.

> **Alpha status:** the core workflow, Claude Code and Codex adapters, deterministic safety hooks,
> cross-platform validation, and PyPI Trusted Publishing are available. Interfaces may still evolve
> before 1.0.

## What is included

- Six tool-neutral roles: architect, planner, developer, reviewer, QA, and publisher.
- A structured artifact lifecycle with explicit approval evidence and supersession.
- A TOML project manifest for repository layout, profiles, commands, and protected areas.
- A dependency-free Python CLI: `init`, `generate`, `validate`, `doctor`, and artifact commands.
- Claude Code agent generation and safety hooks.
- Native Codex project configuration and governed role generation.
- Stack profiles for generic repositories, Python, .NET, and Nuxt.
- Cross-platform tests and reusable GitHub Actions.

## Quick start

Requires Python 3.11 or newer. Install the published package:

```bash
python -m pip install governed-agent-sdlc
agentkit --version
agentkit doctor
```

Upgrade an existing installation to this release:

```bash
python -m pip install --upgrade governed-agent-sdlc==0.3.0
agentkit --version
agentkit doctor
```

Version 0.3.0 makes `review evaluate` apply the project's `[[policies]]` and treats findings with
a missing or unknown severity as `medium`. Give file findings canonical severities before
upgrading if you relied on unknown values passing as `info`. Initialization remains additive; upgrading the Python package does not overwrite
project configuration. See [release notes](CHANGELOG.md) for the full changes.

For local development:

```bash
python -m pip install -e .
agentkit doctor
agentkit validate
python -m unittest discover -s tests -v
```

Initialize another project:

```bash
agentkit init ../my-project --name my-project --adapter claude-code
cd ../my-project
agentkit doctor
```

Use `--format json` with `validate`, `doctor`, generation, migration, and artifact inspection
commands for automation. Preview additive initialization or adapter generation with `--dry-run`.

Initialization is additive: existing `AGENTS.md`, manifest, core policy, hook, and adapter files are
not overwritten. A fresh project receives the generic stack profiles and a minimal `AGENTS.md` so
generated roles always have the instructions they reference.

Create and move a governed artifact:

```bash
agentkit artifact new spec add-search
agentkit artifact transition docs/agent/specs/<file>.md awaiting_approval
agentkit artifact transition docs/agent/specs/<file>.md approved \
  --approved-by "github:maintainer" \
  --evidence "https://github.com/org/repo/issues/123#issuecomment-..."
```

An agent must never supply approval metadata for itself. The human supplies the actor and durable
evidence, and CI validates that the fields exist.

## Project manifest

`agentkit.toml` or `.agent/project.toml` is the source of truth:

```toml
version = 1
protected_areas = ["authentication", "database-schema", "billing"]

[project]
name = "commerce"
topology = "monorepo"

[[repositories]]
id = "backend"
path = "services/api"
profiles = ["dotnet"]

[[repositories]]
id = "frontend"
path = "apps/web"
profiles = ["nuxt"]

[workflow]
require_spec = true
require_plan = true
require_review = true
require_qa = true
```

Repository paths are resolved from the manifest and must remain inside the project root. No machine
or user-specific absolute path belongs in committed configuration.

Validation is strict and dependency-free. It rejects unsupported manifest versions and topology,
missing workflow flags, invalid field types, duplicate repository identities or paths, escaping
repository paths, and profile capabilities that are not provided by `profiles/`, `adapters/`, or
the repository's GitHub integration.

Artifact validation also checks kind-specific parent gates, approval history for approved/active/
completed/superseded states, repository and protected-area references, timestamps, supersession,
and metadata types. Artifact creation refuses filename collisions. Transitions made through the CLI
are restricted to Markdown files below the active project's `docs/agent/` directory.

## Design boundaries

- `core/` is vendor-neutral and is the only source of workflow meaning.
- `profiles/` contain stack-specific commands and exclusions.
- `adapters/` and generated tool files translate the core; they do not redefine it.
- `hooks/` enforce deterministic safety rules. Prompts explain behavior but are not security controls.
- Hook input is fail-closed: malformed input is denied, as are credential paths/environment dumps,
  force pushes, and direct protected-branch refspecs.
- `docs/agent/` holds project artifacts, not hidden agent memory.

See [Architecture](docs/architecture.md), [Workflow](docs/workflow.md), and
[Adopting Governed Agent SDLC](docs/adoption.md).

## Maturity

Version 0.1.1 is an alpha. Claude Code and Codex consume the same core contracts rather than
introducing parallel policy files.

See [CHANGELOG.md](CHANGELOG.md) for release history and upgrade notes.

## License

MIT. See [LICENSE](LICENSE).
