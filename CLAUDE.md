# Claude Code Entry Point

Read `AGENTS.md` and `.agent/project.toml` or `agentkit.toml` first. Role definitions are generated
under `.claude/agents/`; their canonical policy remains in `core/roles/`.

Invoke specialized roles explicitly. Keep the main session focused on coordination and human gates.
Use command hooks for deterministic security decisions. Do not treat prompt compliance as a security
boundary.

Before completing a governed change, run:

```bash
agentkit validate
python -m unittest discover -s tests -v
```

