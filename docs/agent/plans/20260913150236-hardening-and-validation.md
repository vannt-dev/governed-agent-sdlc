+++
schema_version = 1
id = "PLAN-20260913150236-hardening-and-validation"
kind = "plan"
status = "completed"
task_level = "high_risk"
created_at = "2026-09-13T15:02:36.3226224Z"
updated_at = "2026-09-13T15:36:31.192200+00:00"
parent = "SPEC-20260913150033-hardening-and-validation"
repositories = ["root"]
protected_areas = ["authorization", "credentials"]

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-13T15:04:57.4323631Z"
evidence = "current Codex thread: user replied 'tiếp tục giúp mình' after implementation plan review"
+++

# Implementation plan: Repository-wide hardening and validation

## Outcome

Deliver the approved hardening specification as a sequence of bounded tasks, with independent
review and QA artifacts before any publication activity.

## Preconditions

- Specification `SPEC-20260913150033-hardening-and-validation` is approved by the workspace user.
- This plan must receive separate human approval before any task becomes active or source is edited.
- No push, merge, release, or dependency-major-upgrade is authorized.

## Task graph

### Task 1 — Strict configuration and resource discovery

- Owner: developer
- Dependencies: approved plan
- Write scope: `src/agentkit/config.py`, `src/agentkit/generator.py`, config/generator test files
- Read-only scope: `agentkit.toml`, `core/schemas/project.schema.json`, `profiles/**`, packaging config
- Work:
  - Enforce manifest version, project topology, required sections, field types, repository entries,
    protected areas, command values, workflow flags, and known profiles without runtime dependencies.
  - Preserve support for both manifest locations and define deterministic precedence.
  - Correct missing-resource error handling and packaged/check-out resource discovery.
- Verification: focused config/generator tests and manifest validation.

### Task 2 — Artifact lifecycle and workflow gates

- Owner: developer
- Dependencies: Task 1
- Write scope: `src/agentkit/artifacts.py`, `src/agentkit/validator.py`, artifact/validator tests
- Read-only scope: `core/policies/**`, `core/schemas/artifact.schema.json`, templates and workflow docs
- Work:
  - Validate artifact metadata types, schema version, timestamps, task level, repository/protected-area
    references, relationship kinds, and state-dependent approval evidence.
  - Enforce enabled spec/plan/review/QA gates with kind-correct ancestry.
  - Prevent create collisions and reject inconsistent supersession relationships.
- Verification: positive and negative lifecycle/gate tests.

### Task 3 — CLI project containment and scaffold consistency

- Owner: developer
- Dependencies: Tasks 1 and 2
- Write scope: `src/agentkit/cli.py`, `src/agentkit/generator.py`, scaffold assets, CLI/generator tests
- Read-only scope: README, adapter documentation, project instructions
- Work:
  - Resolve transition operations through the active project and require targets below
    `docs/agent/`.
  - Generate instructions that support either manifest location.
  - Add a non-overwriting `AGENTS.md` scaffold for newly initialized projects.
  - Safely encode project names written to TOML.
- Verification: temporary-project CLI and scaffold smoke tests.

### Task 4 — Security hook hardening

- Owner: developer
- Dependencies: approved plan; may execute after Task 1 independently of Tasks 2–3
- Write scope: `hooks/**`, `.claude/settings.json`, hook tests, generator hook configuration
- Read-only scope: `core/policies/security.toml`, Claude adapter documentation
- Work:
  - Make malformed/unreadable hook input fail closed.
  - Cover secret-path access through read, grep, and glob tool shapes.
  - Reject protected-branch push refspec variants, force refspecs, and common option ordering while
    retaining normal feature-branch pushes.
  - Add paired allow/deny tests for every new rule to control false positives.
- Verification: complete guard suite plus representative raw hook-process tests.

### Task 5 — Documentation and packaging alignment

- Owner: developer
- Dependencies: Tasks 1–4
- Write scope: `README.md`, `docs/**`, `adapters/**`, `pyproject.toml` only if packaging evidence
  demonstrates a required correction, documentation tests if introduced
- Read-only scope: all implemented behavior and CI workflows
- Work:
  - Update user-facing validation, artifact, scaffold, and security behavior.
  - Ensure wheel contents support documented scaffold behavior.
  - Keep examples and commands cross-platform and free of machine-specific paths.
- Verification: build wheel, inspect archive contents, install into an isolated environment, run CLI
  init/doctor/validate smoke flow.

### Task 6 — Independent review

- Owner: reviewer
- Dependencies: Tasks 1–5 completed
- Write scope: `docs/agent/reviews/**`
- Read-only scope: full implementation diff, approved spec/plan/tasks, tests
- Work: review correctness, compatibility, security bypasses, validation contract, and missing tests.
- Acceptance: no unresolved high/medium findings; lower findings are documented for human decision.

### Task 7 — QA

- Owner: QA
- Dependencies: Task 6 completed with acceptable result
- Write scope: `docs/agent/qa/**`
- Read-only scope: source, test matrix, build artifacts and exact revision/worktree state
- Work: execute validator, full tests, package build/install, CLI smoke scenarios, and record outputs.
- Acceptance: all declared checks pass or unresolved failures are reported without claiming success.

## Ordering rationale

- Configuration contracts come first because validator, generator, CLI, and test fixtures depend on
  a trustworthy project model.
- Artifact semantics precede CLI containment so the CLI can delegate to one validated lifecycle
  implementation.
- Hook hardening is isolated because it changes protected authorization/credential behavior and
  needs focused regression tests.
- Documentation follows code so it records verified behavior rather than intended behavior.
- Review and QA remain independent gates after implementation.

## Acceptance criteria

- Every criterion in the approved specification is mapped to at least one task and test.
- Implementation remains within the declared paths; scope expansion requires a superseding plan.
- All source changes have focused regression coverage.
- Review and QA artifacts contain reproducible evidence and do not self-approve publication.

## Verification matrix

- `agentkit validate`
- `python -m unittest discover -s tests -v`
- Source and test compilation on the available Python runtime
- Wheel build and archive-content inspection
- Isolated wheel installation followed by `agentkit init`, `doctor`, and `validate`
- Manual inspection of generated Claude settings and agents
- `git diff --check` and final worktree scope review

## Risks and approvals

- Human approval of this plan is required before implementation.
- Tasks 3 and 4 affect authorization and credential protections; behavior changes must fail closed
  and be independently reviewed.
- Publishing remains explicitly out of scope and requires a later human decision.
