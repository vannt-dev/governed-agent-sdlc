# Adopting Governed Agent SDLC

1. Run `agentkit init <project>`.
2. Edit `.agent/project.toml` (or an existing `agentkit.toml`) to describe real repository paths and
   profile capabilities. Every configured profile must have a corresponding stack profile, adapter,
   or repository integration.
3. Add repository-specific instructions without copying the core policies.
4. Generate the Claude Code adapter with `agentkit generate claude-code`.
5. Run `agentkit doctor` on Windows, Linux, and macOS used by the team.
6. Add the reusable validation workflow to required GitHub checks.
7. Configure a ruleset requiring pull requests, human review, and passing checks.
8. Add real owners to `CODEOWNERS` before enforcing it.

`init` preserves existing project-owned files. On a fresh project it installs core policy, hooks,
profiles, a manifest, and minimal `AGENTS.md` instructions before generating the selected adapter.

Start with human-triggered roles. Add automatic routing only after two unrelated projects can use the
same core without modifying it.
