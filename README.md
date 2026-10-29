<div align="center">

# Governed Agent SDLC

**Ship with agents. Keep humans in control.**

[![Validate](https://github.com/vannt-dev/governed-agent-sdlc/actions/workflows/validate.yml/badge.svg)](https://github.com/vannt-dev/governed-agent-sdlc/actions/workflows/validate.yml)
[![PyPI](https://img.shields.io/pypi/v/governed-agent-sdlc.svg)](https://pypi.org/project/governed-agent-sdlc/)
[![PyPI downloads](https://static.pepy.tech/badge/governed-agent-sdlc)](https://pepy.tech/projects/governed-agent-sdlc)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-0b7771)](https://www.python.org/)
[![MIT License](https://img.shields.io/badge/License-MIT-f06f4f.svg)](LICENSE)
[![Official vannt-dev build](https://vannt-dev.github.io/badges/official.svg)](https://vannt-dev.github.io/official.html)

[Project website](https://vannt-dev.github.io/governed-agent-sdlc/) · [Architecture](docs/architecture.md) · [Workflow](docs/workflow.md) · [CLI reference](docs/cli.md) · [Adoption guide](docs/adoption.md)

</div>

Governed Agent SDLC keeps one workflow policy for four AI coding agents: Claude Code, Codex,
OpenCode and Antigravity. The roles, artifact lifecycle, approval rules and protected areas live in
a tool-neutral core and one project manifest, and `agentkit generate` turns them into each agent's
own configuration; none of them keeps a parallel policy file. Stack profiles supply each stack's
commands and exclusions. [Maturity](#maturity) says which guards each agent enforces.

Human approvals can be checked against GitHub. With `[review].approval_mode = "github"` (or
`--approval-mode github` on an artifact transition), `agentkit artifact transition ... approved`
and `agentkit review approve` accept an approval only when its evidence is a pull request review
(or, for an artifact, an issue or pull request comment) in this repository, written by a human
owner, member or collaborator, as looked up through `gh`.
In the default local mode an approval is recorded as given and marked `unverified`.

The project is intentionally **human-in-the-loop**. It helps agents work predictably; it does not
grant an AI permission to approve, merge, release, or retrieve credentials.

> **Alpha status:** the core workflow, the Claude Code, Codex, OpenCode and Antigravity adapters,
> deterministic safety hooks, cross-platform validation, and PyPI Trusted Publishing are available.
> Interfaces may still evolve before 1.0.

## What is included

- Six tool-neutral roles: architect, planner, developer, reviewer, QA, and publisher.
- A structured artifact lifecycle with explicit approval evidence and supersession.
- A TOML project manifest for repository layout, profiles, commands, and protected areas.
- A dependency-free Python CLI: `init`, `generate`, `update-hooks`, `upgrade`, `validate`,
  `doctor`, and artifact commands.
- Claude Code agent generation and safety hooks.
- Native Codex project configuration and governed role generation.
- OpenCode subagents with a guard plugin, and Antigravity agents with a guard hook
  ([OpenCode adapter](adapters/opencode/README.md), [Antigravity adapter](adapters/antigravity/README.md)).
- Stack profiles for generic repositories, Python, .NET, Nuxt, Node.js and TypeScript, Java
  (Spring Boot on Maven), Flutter, Go, Rust, Kotlin (Gradle), and PHP (Composer).
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
python -m pip install --upgrade governed-agent-sdlc==0.8.0
agentkit --version
agentkit update-hooks
agentkit generate claude-code --force
agentkit doctor
```

Version 0.8.0 adds stack profiles for Go, Rust, Kotlin, and PHP for `agentkit init --profile`, and
GitHub-verified artifact approvals: with `[review].approval_mode = "github"` (or `artifact
transition ... approved --approval-mode github`) the evidence must be a review or comment on GitHub
by a human owner, member or collaborator, checked through `gh`. Approvals made in the default local
mode are now marked `verification = "unverified"`; approvals recorded earlier stay valid. Upgrading
the Python package does not overwrite project configuration, and that includes the guards under
`hooks/`, so run `update-hooks` to get the guards this version ships, and only then regenerate the
adapter (`generate codex --force` for Codex): regenerated settings can name a guard an older
project does not have, and a missing guard file fails every tool call it guards closed. See
[release notes](CHANGELOG.md) for the full changes.

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
not overwritten. A fresh project receives the stack profiles and a minimal `AGENTS.md` so
generated roles always have the instructions they reference.

`agentkit doctor` also compares the guards under `hooks/` and the files of each adapter in use with
what the installed version writes, and exits `1` when one is outdated or missing, so CI can catch a
project left behind by a package upgrade; a file that differs without a record only warns.
`agentkit upgrade` rewrites those files and keeps the ones edited by hand unless `--force` is
given; `--dry-run` shows what it would change. Generated files are recorded by hash in
`.agent/generated.json`; commit it with them. See the
[CLI reference](docs/cli.md#keeping-generated-files-current).

Name the stack when you initialize, and the manifest starts with its profile and its commands
instead of the generic one:

```bash
agentkit init my-service --profile java
agentkit init my-app --profile flutter --profile node   # several: the first to name a command wins
```

The profiles are `generic`, `python`, `dotnet`, `nuxt`, `node`, `java`, `flutter`, `go`, `rust`,
`kotlin` and `php`. The commands a profile gives are a starting point written into `[commands]` of
the manifest: a Gradle project replaces the Maven ones of `java`, and `flutter` names no build
because which artefact to build is the project's to say. `kotlin` runs `./gradlew check`, which
runs ktlint or detekt only when the build applies them, and `php` names `composer validate` and
PHPUnit; a project using PHPStan or PHP CS Fixer adds those commands. The `go` format check is a
POSIX shell line, because `gofmt -l` lists files without failing.

Create and move a governed artifact:

```bash
agentkit artifact new spec add-search
agentkit artifact transition docs/agent/specs/<file>.md awaiting_approval
agentkit artifact transition docs/agent/specs/<file>.md approved \
  --approved-by "github:maintainer" \
  --evidence "https://github.com/org/repo/issues/123#issuecomment-..."
```

An agent must never supply approval metadata for itself. The human supplies the actor and durable
evidence, and CI validates that the fields exist. By default (`[review].approval_mode = "local"`,
as for `review approve`) the approval is recorded as given and marked
`verification = "unverified"`. With `approval_mode = "github"`, or `--approval-mode github` on the
command, the CLI checks through `gh` that the review or comment URL is in this repository and was
written by a human collaborator, and records that login (`github:LOGIN`) as the approver; see
[artifact approval verification](docs/cli.md#artifact-approval-verification).

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
- Hooks also hold the workflow: a role is spawned only from artifacts that passed their gate, and a
  role that does not own a task file may change only its completion evidence.
- `docs/agent/` holds project artifacts, not hidden agent memory.

See [Architecture](docs/architecture.md), [Workflow](docs/workflow.md), and
[Adopting Governed Agent SDLC](docs/adoption.md).

## Maturity

The project is an alpha. Claude Code, Codex, OpenCode and Antigravity consume the same core
contracts rather than introducing parallel policy files. The credential and git guards hold on
all four; the role write scope and the role gate are enforced on Claude Code only, because only
its hook input says which role is acting.

See [CHANGELOG.md](CHANGELOG.md) for release history and upgrade notes.

## License

MIT. See [LICENSE](LICENSE).
