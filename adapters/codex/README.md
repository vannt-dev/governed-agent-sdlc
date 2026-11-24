# Codex adapter

The Codex adapter uses Codex's native, layered `AGENTS.md` discovery and optional project-scoped
`.codex/config.toml` role declarations. Generate it with:

```bash
agentkit generate codex
```

Generation is additive by default. Use `--dry-run` to preview paths and `--force` only after
reviewing existing project-owned Codex configuration. The adapter does not modify user-level Codex
trust, authentication, provider, model, telemetry, approval, or sandbox settings. Non-developer
roles are read-only, and project-local hooks reinforce credential, destructive-git,
recursive-delete and [egress](../claude-code/README.md#what-guard_egresspy-refuses) restrictions,
reading a command line the way the
[Claude Code guard](../claude-code/README.md#how-guard_gitpy-reads-a-command) does. The egress
allowlist is read from the project's manifest. The output warning is Claude Code's only.
Hooks are useful guardrails, not a complete security boundary.

Official behavior references: <https://learn.chatgpt.com/docs/agent-configuration/agents-md> and
<https://learn.chatgpt.com/docs/hooks>.
