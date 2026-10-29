# Adopting Governed Agent SDLC

1. Run `agentkit init <project>`.
2. Edit `.agent/project.toml` (or an existing `agentkit.toml`) to describe real repository paths and
   profile capabilities. Every configured profile must have a corresponding stack profile, adapter,
   or repository integration.
3. Add repository-specific instructions without copying the core policies.
4. Generate the adapter used by your team:
   - Claude Code: `agentkit generate claude-code`
   - Codex: `agentkit generate codex`
   - OpenCode: `agentkit generate opencode`
   - Antigravity: `agentkit generate antigravity`
5. Run `agentkit doctor` on Windows, Linux, and macOS used by the team.
6. Add the reusable validation workflow to required GitHub checks. Pin its `uses:` line to a
   release tag or commit; the toolkit it runs is that same revision unless `toolkit-ref` names
   another one.
7. Configure a ruleset requiring pull requests, human review, and passing checks.
8. Add real owners to `CODEOWNERS` before enforcing it.

`init` preserves existing project-owned files. On a fresh project it installs core policy, hooks,
profiles, a manifest, and minimal `AGENTS.md` instructions before generating the selected adapter.

After upgrading the package in an existing project, run `agentkit doctor`: it reports the guards and
adapter files older than the installed version writes. `agentkit upgrade` rewrites them, guards
first, and keeps files edited by hand unless `--force` is given. Commit `.agent/generated.json`
with them, and add `agentkit doctor` to CI to catch a project left behind. Doing it by hand means
`agentkit update-hooks` and then `agentkit generate <adapter> --force`, in that order: the guards
are code the project copied at `init`, and regenerated settings may name a guard it does not have
yet.

Start with human-triggered roles. Add automatic routing only after two unrelated projects can use the
same core without modifying it.

Codex reads the root `AGENTS.md` and any more-specific files below it. The generated `.codex/`
configuration inherits the user's approval and sandbox policy, declares read-only non-developer
roles, and adds credential/git safety hooks. It intentionally does not change user-level trust,
authentication, provider, model, telemetry, approval, or sandbox settings. Hooks are defense in
depth, not a complete security boundary. Preview every generated path with
`agentkit generate codex --dry-run` before using `--force` in an existing setup.
