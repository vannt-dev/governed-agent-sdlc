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
- `agentkit review run [--provider mock|open-code-review|cli] [--run-id ID] [--requirement FILE] [--spec FILE] [--plan FILE] [--from REF] [--to REF] [--commit REF] [--mock-findings FILE] [--output-dir DIR]`
- `agentkit review recover --run-id ID [--attempt N]`
- `agentkit review approve --run-id ID --policy POLICY --actor HUMAN --evidence URL [--attempt N] [--reject]`
- `agentkit review status --run-id ID [--attempt N]`
- `agentkit review preview [--from REF] [--to REF] [--commit REF]`
- `agentkit review evaluate FINDINGS [--output-dir DIR]`

## Governed review

A reviewer produces findings, and governance decides what they mean. `review run` calls the provider,
normalizes the findings, evaluates the `[[policies]]` from the manifest, and records the result under
`.agent/runs/<run-id>/review-attempt-N/`. Running again with the same `--run-id` records a new attempt;
existing attempts and approvals are never overwritten.

The requirement/specification/plan background is fixed for a run. A retry without context arguments
reuses it, and repeating the same context is allowed. Supplying different context returns exit `2`
before calling the reviewer; use a new `--run-id` for the changed requirement or plan.

- `open-code-review` runs the `ocr` CLI (`npm install -g @alibaba-group/open-code-review`). The
  executable comes from `OPEN_CODE_REVIEW_BIN` or `PATH`, never from the manifest. Pass
  `--requirement`, `--spec` or `--plan` to hand the reviewer a bounded `review-background.md`
  (`[review].include_*` switches each one off). The reviewer sees a filtered environment.
- A reviewer that cannot run (missing binary, timeout, malformed output) is a provider error, exit `3`,
  and is recorded as `provider-error.json`. It is never reported as a clean review.
- OCR's `skipped` result means no files were selected. The gate stays `skipped` with exit `6` in
  `review run` and `review status`; reports preserve that state instead of calling it a passed review.
- `review approve` records a human decision for a policy that required approval. AI actors are refused,
  evidence (ticket or PR URL) is required, and a decision cannot be recorded twice.
- `review status` recomputes the gate from the stored evidence, so it can be re-run after approving.
- Missing findings/provider evidence or inconsistent policy records return exit `2`; a report
  shows an unknown gate instead of reusing an earlier passing result.
- `review preview` uses `ocr delegate preview` to list reviewable files without an LLM.
- `review run --artifact docs/agent/reviews/<file>.md` links a run to the review artifact it supports.
  The artifact id and path are recorded in `provider.json` and the event log; only review artifacts
  under `docs/agent` are accepted.
- Every run keeps an append-only `events.jsonl` (`review.started`, `review.completed`, `review.failed`,
  `policy.evaluated`, `policy.blocked`, `policy.approval_required`, `approval.granted`,
  `approval.rejected`) with sequential ids. It is derived from the evidence files, not a source of
  truth, so audit tools and viewers can follow a run in order.
- `review report --run-id ID [--html FILE]` summarizes attempts, findings by severity, decisions,
  approvals, gate status and events from the stored evidence. It only reads; the optional HTML page
  escapes all evidence text and refuses to overwrite an existing file.
- `agentkit validate` also checks `.agent/runs/`: attempt evidence against the finding schema
  (`core/schemas/review-finding.schema.json`, shared with Junto), approval records (human actor,
  evidence, valid decision) and the event log.

Manifest tables (all optional, validated strictly):

```toml
[review]
provider = "open-code-review"   # or "mock", "cli"
timeout_seconds = 180
include_requirement = true
include_spec = true
include_plan = true
enforce_artifact_gate = false   # opt in: review artifacts require a fresh linked passing run
approval_mode = "local"        # or "github": verify a GitHub PR review before recording approval

[remediation]
enabled = true
max_attempts = 2                # after this many attempts require-remediation becomes block

[[policies]]                    # replaces the built-in defaults when present
id = "auth-block"
action = "block"                # continue | warn | block | require-human-approval | require-remediation
severity = "high"
category = "security"
file_pattern = "**/auth/**"
```

`review run` and `review status` exit codes: `0` passed (or approved), `1` blocked or rejected,
`2` configuration/filesystem error, `3` review provider error, `4` awaiting human approval,
`5` remediation required, `6` skipped (no completed review), `7` stale/unverified source evidence.

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

## Testing the installed OCR integration

Set `OCR_SMOKE_BIN` to an installed OCR executable, then run
`python -m unittest discover -s tests`. The optional smoke test creates a temporary Git repository
and checks `delegate preview` for clean and changed workspaces. It does not call an LLM or download
software. Without this variable, that test is skipped. A complete semantic review additionally
requires an OCR LLM endpoint or the host CLI backend below; a successful preview does not verify
semantic review.

## Host CLI review and evaluation

`--provider cli` uses installed OCR only for `delegate preview` and version-1 `delegate rule` JSON.
The host CLI reviews the selected Git diff, untracked files, rules and requirement background on stdin.
Set `AGENTKIT_REVIEW_COMMAND` in the calling environment to a trusted JSON argv array, for example:

```json
["codex", "exec", "--sandbox", "read-only", "--ephemeral", "--color", "never", "-"]
```

Claude or another CLI can be used through the same stdin/stdout contract. A Claude example is
`["claude", "--safe-mode", "--print", "--tools=", "--no-session-persistence", "--output-format", "text"]`.
On Windows, if only an npm `.cmd` shim is available, use `node` and the absolute path to the
installed CLI JavaScript entry point instead of the shim. No binary is selected by repository
configuration and nothing is downloaded at runtime. Authenticate the CLI through its normal login.
Choose a read-only/tool-disabled invocation: the harness does not sandbox arbitrary host commands.

The command must return a JSON object with OCR's `status` and `comments` shape; failures, incomplete
output and findings outside the selected files do not pass. Input is capped at 512 KiB, output at
8 MiB per stream, and execution at `[review].timeout_seconds`. These bound time and data, not billing;
CLI token usage is not available to the harness. Ref mode requires an existing commit and `--to`
requires `--from`.

Opt into the two-call live evaluation with `REVIEW_LIVE=1`, `OPEN_CODE_REVIEW_BIN` and
`AGENTKIT_REVIEW_COMMAND`, then run `python -m unittest discover -s tests -p test_cli_review.py -v`.
It checks a known division-by-zero defect and a clean control (zero high/critical false positives),
with 120 seconds per call. Normal CI uses deterministic tests and never calls a paid model.

## Freshness, recovery and approval trust

Each attempt captures source hashes and file modes, HEAD/index, resolved refs and background before review and
checks them again afterward. Status refuses stale inputs (`7`); legacy attempts without a snapshot
are explicitly unverified (`7`). Fingerprints exclude generated evidence, caches and environment
files, and contain hashes instead of source text. A changed manifest also invalidates the gate.

A process lock covers attempts, approvals and event numbering; concurrent writers are refused.
The OS releases the lock after a crash. `review recover` seals an interrupted attempt without
replacing partial evidence; rerunning review allocates the next attempt. A corrupt event log is
reported and requires inspection, never silently truncated.

With `enforce_artifact_gate = true`, CLI transition of a review artifact to `completed` requires
the latest attempt of a linked run to pass with current source. The default preserves the previous
manual artifact workflow.

Local approval mode records a claimed human identity and durable evidence; it does not authenticate
that identity. GitHub mode uses authenticated `gh api` to verify the precise review URL, human login,
collaborator association, submitted decision and commit against HEAD and the repository origin.
It requires a clean committed tree. Use `--actor github:LOGIN` and a URL ending in
`#pullrequestreview-ID`. Verification is recorded at approval time; it is not continuously polled
for later dismissal, and local evidence storage remains a trust boundary. See the
[GitHub review API](https://docs.github.com/en/rest/pulls/reviews#get-a-review-for-a-pull-request).
