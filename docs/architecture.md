# Architecture

Governed Agent SDLC has four layers:

```text
Project manifest + artifacts
            |
      tool-neutral core
            |
     vendor adapters/CLI
            |
 Claude Code / future tools / GitHub Actions
```

The core owns role authority, workflow transitions, approval policy, templates, and schemas.
Profiles add stack knowledge without changing governance. Adapters translate the core into a tool's
native format. Deterministic validators and hooks enforce the subset of policy that can be checked
mechanically.

Markdown remains readable to humans, while TOML frontmatter carries machine-checked identity,
status, parent relationships, repository scope, protected areas, and approval evidence.

The runtime intentionally has no third-party dependencies. Python code enforces the same supported
manifest and artifact contract documented by `core/schemas/`; packaged scaffold resources include
core policy, hooks, and stack profiles.

## Trust boundaries

- Humans own approval, merge, release, and meaningful scope expansion.
- Developers may write only task scope.
- Reviewers and QA do not repair source while assessing it.
- Publishers receive write capability only after review, QA, and human publish approval.
- Credentials remain in GitHub Apps, CI secret stores, or wrappers and never enter agent context.
- Security hooks fail closed on malformed input and cover shell, read, glob, and grep access paths.
