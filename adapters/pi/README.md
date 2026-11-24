# Pi adapter

Run `agentkit generate pi` in a configured project, or start one with
`agentkit init --adapter pi`. The [Pi coding agent](https://github.com/earendil-works/pi) reads
the repository's `AGENTS.md` by itself. The adapter adds what is specific to it under `.pi/` and
never touches user-level configuration (`~/.pi/agent`).

| Generated | What it is |
| --- | --- |
| `.pi/extensions/governed-guards.js` | An extension whose `tool_call` handler asks the project's guards before a tool runs. |

Generation is additive: an existing file is kept unless `--force` is given, and `--dry-run` only
lists the paths.

## Project trust

Pi loads extensions from a project's `.pi/extensions/` only after the project is trusted. In
interactive mode Pi asks the first time it starts in the folder; `pi --approve` trusts it for one
run. Until it is trusted the guards are not asked at all, and a non-interactive run (`pi -p`)
without `--approve` skips the extension without a word. Trust the project before you rely on the
guards.

## Guards

The extension translates Pi's tool call into the input the guards in `hooks/` read and runs them
with `uv run --no-project python`:

| Pi tool | Guards asked |
| --- | --- |
| `bash`, `powershell` | `hooks/guard_credentials.py`, `hooks/guard_git.py`, `hooks/guard_egress.py` |
| `read`, `ls`, `find`, `grep` | `hooks/guard_credentials.py` |

The guard sees the command or path as Pi will use it: a leading `@` is dropped, as Pi drops it,
and the folder the session runs in is passed on, so a recursive delete is judged from there. The
pattern `grep` searches for is text, not a path, and is not checked. `powershell` commands are
read as PowerShell.

A guard that objects blocks the call, and Pi shows the model the reason. So does a guard that is
missing or that fails: nothing that should have been checked is waved through.
`agentkit update-hooks` restores the guards.

Pi has no roles or subagents of its own, so the adapter generates none. The role write scope and
the role gate (`guard_role_scope.py`, `guard_role_gate.py`) are not wired here: they read which
role is acting from Claude Code's hook input. Writing files (`edit`, `write`) is not checked by a
guard. A role's limits on Pi are its instructions in `AGENTS.md` and `core/roles/`.

Hooks are useful guardrails, not a complete security boundary.

## What was checked

Behaviour references: Pi's `docs/extensions.md` (the `tool_call` event can block a call),
`docs/security.md` (project trust) and the tool definitions in
`packages/coding-agent/src/core/tools/`.

With Pi 1.6.0, in a project made by `agentkit init --adapter pi`: a run started with
`pi --approve` loaded the extension, and the guards blocked scripted tool calls
(`git push --force origin main`, `read @.env`, `rm -rf ..`) while `git status` ran. Without
`--approve` the same `read @.env` went through. The extension's `tool_call` handler is also run by Node in the test suite
against the real guards. The scripted calls came from a test model provider, so no model key
was needed.

Not checked: a session driven by a real model.
