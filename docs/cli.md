# CLI reference

## Commands

- `agentkit init [path] [--name NAME] [--adapter none|claude-code|codex] [--dry-run]`
- `agentkit validate [path] [--format text|json]`
- `agentkit doctor [path] [--format text|json]`
- `agentkit generate claude-code|codex [path] [--force] [--dry-run]`
- `agentkit migrate [path] [--to-version VERSION] [--dry-run]`
- `agentkit artifact new KIND SLUG [--path PATH]`
- `agentkit artifact transition FILE TARGET [--approved-by ACTOR] [--evidence EVIDENCE]`
- `agentkit artifact list [--path PATH] [--format text|json]`
- `agentkit artifact show FILE [--path PATH] [--format text|json]`
- `agentkit artifact graph [--path PATH] [--format text|json]`

`--dry-run` reports paths without creating or overwriting them. Generation is additive unless
`--force` is supplied. Manifest migration refuses ambiguous projects and unsupported source or
target versions instead of guessing at a rewrite.

## Stable exit codes

- `0`: command completed and validation found no errors.
- `1`: validation completed with one or more project errors, or no command handler completed.
- `2`: invalid project configuration, artifact operation, filesystem operation, or unsupported
  migration prevented the command from completing.

JSON output writes one JSON document to stdout. Operational errors use the same shape on stderr:

```json
{"error": "description", "ok": false}
```

Human approval metadata must come from a human-controlled channel. The CLI checks that approval
fields are present; it does not grant an agent authority to fill them on its own.
