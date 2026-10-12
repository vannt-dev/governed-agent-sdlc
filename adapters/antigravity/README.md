# Antigravity adapter

Run `agentkit generate antigravity` in a configured project, or start one with
`agentkit init --adapter antigravity`. Antigravity (the `agy` CLI, the successor of Gemini CLI)
reads the repository's `AGENTS.md` by itself; the adapter adds what is specific to it under
`.agents/` and never touches user-level configuration in `~/.gemini/`.

| Generated | What it is |
| --- | --- |
| `.agents/agents/<role>/agent.md` | One agent per governed role, in a folder named after it. Its instructions point back to `AGENTS.md`, the manifest and `core/roles/<role>.toml`. |
| `.agents/hooks.json` | A `PreToolUse` hook named `governed-agent-sdlc` for the tools that run a command or reach a file. |
| `.agents/hooks/governed_guard.py` | What the hook runs: it asks the project's guards and answers Antigravity. |

Generation is additive: an existing file is kept unless `--force` is given, and `--dry-run` only
lists the paths.

## Roles

Start a session as a role with `agy --agent reviewer`, or choose one in the `/agents` panel. An
Antigravity agent file documents a `name` and a `description` and no permission keys, so a role's
limits are its instructions there; the guards below hold for every role.

## Guards

The hook is asked before `run_command`, `view_file`, `find_by_name` and `grep_search`. It
translates the call into the input the guards in `hooks/` read:

| Antigravity tool | Guards asked |
| --- | --- |
| `run_command` (its `CommandLine`) | `hooks/guard_credentials.py`, `hooks/guard_git.py` |
| the file tools (their paths and file patterns) | `hooks/guard_credentials.py` |

For the file tools the hook goes by what an argument looks like, not by its name: an argument
that is a path, every entry of a list (file patterns), and for `find_by_name` every text it is
given. The text a search looks for is not a target.

A guard that objects is answered to Antigravity as `{"decision": "deny", "reason": ...}`, which
the agent sees as `tool call denied by pre-tool hook: <reason>`. No objection means no answer,
and Antigravity's own permission flow goes on. Input that is not a tool call, a guard that is
missing and a guard that fails are all denied. `agentkit update-hooks` restores the guards.

Antigravity allows the hook 30 seconds. The script gives the guards 20 in all and answers with
a refusal when they take longer, so a slow guard is never a silent pass.

The hook's command is `uv run --no-project python hooks/governed_guard.py`: Antigravity starts a
hook in the folder of its `hooks.json`, so the path is relative to `.agents/`. The script finds
the project by its own place in it.

The role write scope and the role gate (`guard_role_scope.py`, `guard_role_gate.py`) are not
wired here: they read which role is acting from Claude Code's hook input, which Antigravity's
hook input does not carry.

Hooks are useful guardrails, not a complete security boundary.

## What was checked

Behaviour references: <https://www.antigravity.google/docs/cli/commands/agents>,
<https://www.antigravity.google/docs/hooks?tab=cli> and
<https://www.antigravity.google/docs/rules?tab=cli>.

Run in sessions of the Antigravity CLI 1.2.9 on Windows, with the generated files unchanged:
`cat .env`, viewing `.env` and `git push --force origin main` were each denied with the guard's
reason, a file the guards have no objection to was read, and `agy --agent reviewer` started with
the reviewer's instructions.

Not checked: `find_by_name` and `grep_search` inside a session (the documentation names the
tools but not their arguments, which is why the hook goes by an argument's shape), the
Antigravity IDE, and a session started with permissions auto-approved.
