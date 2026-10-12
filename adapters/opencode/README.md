# OpenCode adapter

Run `agentkit generate opencode` in a configured project, or start one with
`agentkit init --adapter opencode`. OpenCode reads the repository's `AGENTS.md` by itself; the
adapter adds what is specific to it under `.opencode/` and never touches user-level configuration.

| Generated | What it is |
| --- | --- |
| `.opencode/agents/<role>.md` | One subagent per governed role, named after the role. Its prompt points back to `AGENTS.md`, the manifest and `core/roles/<role>.toml`. |
| `.opencode/plugins/governed-guards.js` | A plugin whose `tool.execute.before` asks the project's guards before a tool runs. |

Generation is additive: an existing file is kept unless `--force` is given, and `--dry-run` only
lists the paths.

## Roles

Each agent is a `subagent` with a `permission` block. Only `developer` may edit files
(`edit: allow`); the five other roles have `edit: deny`. Every role is asked before a shell command
runs (`bash: ask`). Invoke a role by mentioning it, for example `@reviewer`.

## Guards

The plugin translates OpenCode's tool call into the input the guards in `hooks/` read and runs
them with `uv run --no-project python`:

| OpenCode tool | Guards asked |
| --- | --- |
| `bash` | `hooks/guard_credentials.py`, `hooks/guard_git.py` |
| `read`, `list`, `glob`, `grep` | `hooks/guard_credentials.py` |

A guard that objects refuses the call with its reason. So does a guard that is missing or that
fails: nothing that should have been checked is waved through. `agentkit update-hooks` restores
the guards.

The role write scope and the role gate (`guard_role_scope.py`, `guard_role_gate.py`) are not
wired here: they read which role is acting from Claude Code's hook input, which OpenCode's plugin
hook does not carry. On OpenCode a role's write limit is its `permission` block.

Hooks are useful guardrails, not a complete security boundary.

The plugin finds the project by its own place in it, so it works when OpenCode is started in a
subfolder or outside a git repository.

## What was checked

Behaviour references: <https://opencode.ai/docs/agents/> and <https://opencode.ai/docs/plugins/>.

With OpenCode 1.19.0: `opencode agent list` shows the six roles with these permissions, and the
resolved configuration lists the plugin. The plugin's `tool.execute.before` is run by Node in the
test suite against the real guards.

Not checked: a tool call refused inside a running OpenCode session. To try it, ask a session to
run `git push --force origin main`; the answer should carry `force push is forbidden`.
