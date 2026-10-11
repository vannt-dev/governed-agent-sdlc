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
| `hooks/guard_git.py` | Bash, PowerShell | force pushes, direct pushes to a protected branch, destructive git commands |
| `hooks/guard_role_scope.py` | Write, Edit, MultiEdit | a role writing outside its grant; in a task file a non-owner may change only the completion evidence |
| `hooks/guard_role_gate.py` | Agent, Task | spawning a role from an artifact that has not passed its gate in `core/policies/workflow.toml` |

Each guard's docstring records why it exists and what it deliberately leaves unchecked.

Claude Code plugin packaging may be added later for discovery and distribution. Security hooks stay
project-level because plugin-provided subagents do not enforce every project hook/permission field.
