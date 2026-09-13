# Claude Code adapter

Run `agentkit generate claude-code` in a configured project. The generator creates project-level
subagents and command hooks under `.claude/` without introducing a second copy of core workflow
policy.

Generated role prompts point back to `core/roles/*.toml`. The adapter uses `uv run --no-project
python` for portable hook execution and contains no user-specific absolute paths.

Roles read `AGENTS.md` and whichever supported manifest location exists. Credential guards run for
Bash, Read, Glob, and Grep tool use; malformed hook input is denied instead of silently allowed.

Claude Code plugin packaging may be added later for discovery and distribution. Security hooks stay
project-level because plugin-provided subagents do not enforce every project hook/permission field.
