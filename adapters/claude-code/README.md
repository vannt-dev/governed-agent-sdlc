# Claude Code adapter

Run `agentkit generate claude-code` in a configured project. The generator creates project-level
subagents and command hooks under `.claude/` without introducing a second copy of core workflow
policy.

Generated role prompts point back to `core/roles/*.toml`. The adapter uses `uv run --no-project
python` for portable hook execution and contains no user-specific absolute paths.

Roles read `AGENTS.md` and whichever supported manifest location exists. Malformed hook input is
denied instead of silently allowed. The generated `.claude/settings.json` registers four guards:

| Guard | Tools | Refuses |
| --- | --- | --- |
| `hooks/guard_credentials.py` | Bash, PowerShell, Read, Glob, Grep | reading credential files, credential stores, environment dumps |
| `hooks/guard_git.py` | Bash, PowerShell | force pushes, direct pushes to a protected branch, destructive git commands, recursive deletes outside a named path in the workspace |
| `hooks/guard_role_scope.py` | Write, Edit, MultiEdit | a role writing outside its grant; in a task file a non-owner may change only the completion evidence |
| `hooks/guard_role_gate.py` | Agent, Task | spawning a role from an artifact that has not passed its gate in `core/policies/workflow.toml` |

Each guard's docstring records why it exists and what it deliberately leaves unchecked.

### How `guard_git.py` reads a command

The guard judges the commands a line runs, not the text in it (`hooks/command_line.py`):

- The line is cut at `;`, `&&`, `||`, `|`, `&` and line ends that stand outside quotes, and each
  command is checked on its own. `echo "a; rm -rf /"` passes; `echo a; rm -rf /` is refused.
- The body of `$( )`, of backquotes and of `( )` is checked, and so is the text given to
  `bash -c`, `sh -c`, `eval`, `powershell -Command` and `cmd /c`.
- `NAME=value` prefixes, redirections and `sudo`, `command`, `exec`, `env`, `xargs`, `nohup`,
  `nice`, `time`, `timeout` are looked through to the command behind them.
- Heredoc bodies and, in PowerShell, here-strings are data.
- A line that cannot be read (a quote or bracket left open) is refused when it names `git` or a
  delete command.

A recursive delete (`rm -r`, `rm -rf`, `rm -R`, `rm --recursive`, `rd /s`, `del /s`,
`Remove-Item -Recurse`) passes only when every target is a named path inside the workspace:

| Passes | Refused |
| --- | --- |
| `rm -rf build`, `rm -rf build/*`, `cd app && rm -rf dist` | `/`, `~`, `$HOME`, `.`, `..`, a bare `*` |
| `rd /s /q build`, `Remove-Item -Recurse -Force build` | a path outside the workspace, such as `../x` or `/tmp/x` |
| `rm -f notes.txt` (not recursive) | anything in a `.git` folder |
| | a target the text does not tell: `"$DIR"`, `$(...)`, arguments from `xargs` |

`cd` is followed along the line, so `cd /tmp && rm -rf build` is refused. Paths are compared as
text; a symbolic link is not followed. Variables are not expanded and script files are not opened,
so the guard is a guardrail, not a sandbox.

Claude Code plugin packaging may be added later for discovery and distribution. Security hooks stay
project-level because plugin-provided subagents do not enforce every project hook/permission field.
