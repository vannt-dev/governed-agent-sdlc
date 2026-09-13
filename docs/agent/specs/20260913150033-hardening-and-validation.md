+++
schema_version = 1
id = "SPEC-20260913150033-hardening-and-validation"
kind = "spec"
status = "completed"
task_level = "high_risk"
created_at = "2026-09-13T15:00:33.6709428Z"
updated_at = "2026-09-13T15:36:31.430647+00:00"
repositories = ["root"]
protected_areas = ["authorization", "credentials"]

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-13T15:02:36.3226224Z"
evidence = "current Codex thread: user replied 'tiếp tục giúp mình' after specification review"
+++

# Specification: Repository-wide hardening and validation

## Goal

Make the toolkit enforce the workflow, artifact, manifest, adapter, and security contracts it
documents, while preserving its dependency-free runtime and cross-platform Python 3.11+ support.

## Context

The repository-wide audit found that the current test suite passes, but several documented
contracts are not mechanically enforced. The repository is also new, has no commits, and all files
are currently untracked, so there is no historical baseline or reviewable implementation diff.

## Confirmed facts

- `agentkit.toml` requires specification, plan, review, and QA stages.
- `core/policies/workflow.toml` defines ordered gates from approved specification through QA and
  human publish approval.
- `core/policies/security.toml` declares fail-closed behavior and forbids direct protected-branch
  pushes and credential access.
- `agentkit validate` currently reports zero findings and all 13 existing unit tests pass.
- Manifest loading does not enforce manifest version, topology, required workflow keys, field types,
  profile existence, or the supplied JSON schema contract.
- Artifact validation does not enforce the declared workflow gates and only requires approval
  evidence while status is exactly `approved`.
- Artifact filenames and IDs have second-level resolution, allowing same-kind/same-slug creation in
  the same second to overwrite an existing artifact.
- Artifact transition accepts paths outside the configured project's artifact directory.
- `package_root()` contains an unreachable missing-resource exception.
- Generated Claude agent instructions assume `.agent/project.toml`; configured projects may instead
  use `agentkit.toml`.
- A newly initialized project does not receive `AGENTS.md`, although generated agents require it.
- Malformed hook input is converted to an empty object and allowed, contrary to fail-closed policy.
- The Git guard does not reliably reject refspec forms such as `HEAD:main` or
  `refs/heads/main`, and credential protection is not consistently applied to all read/search tools.
- The current tests do not cover generator/scaffold behavior, CLI path containment, strict config
  validation, workflow gates, malformed hook input, or common Git refspec bypasses.

## Assumptions

- The Python runtime must remain dependency-free; JSON schema files are canonical documentation,
  while equivalent validation may be implemented directly in Python.
- Backward compatibility is required for both supported manifest locations.
- Existing valid manifests and artifacts must continue to validate without migration.
- Archived artifacts may legitimately lack approval evidence when archived directly from draft or
  awaiting approval.
- `active`, `completed`, and `superseded` artifacts must retain approval evidence because their
  valid transition histories require prior approval.

## Open questions

- None required for implementation after human approval of this specification. Exact internal
  decomposition belongs in the implementation plan.

## Confirmed decisions

- Keep Python 3.11 as the minimum supported version.
- Do not add runtime dependencies.
- Treat malformed hook input as denied.
- Validate configured profiles against packaged or checkout profile definitions.
- Constrain artifact transitions to Markdown artifacts below `docs/agent/` in the active project.
- Refuse artifact creation collisions instead of overwriting existing files.
- Generate adapter instructions that explicitly support either manifest location.
- Scaffold an `AGENTS.md` when one does not already exist, without overwriting project-owned
  instructions.

## Scope

- Strengthen `src/agentkit/config.py` with strict manifest shape and semantic validation.
- Strengthen `src/agentkit/validator.py` with schema-equivalent artifact checks, approval history
  requirements, relationship rules, and configured workflow gates.
- Harden artifact creation and transition path safety in `src/agentkit/artifacts.py` and CLI wiring.
- Fix resource discovery and make generated/scaffolded adapter guidance consistent.
- Harden credential, Git, role-scope, and malformed-input hook behavior.
- Add focused positive and negative unit tests for every changed contract and guard path.
- Update README and architecture/workflow/adoption documentation where observable behavior changes.
- Run project validation, full unit tests, package build/install smoke checks, and CLI smoke checks.

## Out of scope

- Adding Codex or other new vendor adapters.
- Publishing, merging, releasing, or pushing changes.
- Adding third-party runtime dependencies.
- Changing the six-role authority model beyond enforcing its existing contracts.
- Designing organization-specific protected branch names or credential systems.

## Acceptance criteria

1. Invalid manifest versions, topology, missing required sections/keys, invalid field types,
   duplicate or escaping repository paths, and unknown profiles produce actionable validation errors.
2. Workflow validation enforces enabled spec, plan, implementation, review, and QA ancestry/gates
   with kind-appropriate parent relationships and rejects inactive or missing parents.
3. Approval evidence is required for every artifact status whose valid history proves it was
   approved, while draft-origin archived artifacts remain valid.
4. Creating the same artifact twice cannot overwrite an existing file or reuse an ID.
5. CLI transitions reject files outside the active project's `docs/agent/` tree.
6. Resource discovery raises an intentional, actionable error when packaged resources are absent.
7. Generated agents work with either supported manifest location, and fresh scaffolds contain the
   instructions those agents are told to read.
8. Hooks deny malformed input, common direct/forced protected-branch refspec variants, credential
   store/environment access, and secret-path reads/searches while retaining explicit allow tests.
9. Documentation matches implemented behavior and contains no machine-specific paths.
10. `agentkit validate`, the complete unit suite, package build/install smoke test, and CLI smoke
    test pass on the available environment; CI remains configured for Windows, Linux, macOS and
    Python 3.11-3.13.

## Risks and required approvals

- This changes authorization and credential enforcement, both protected areas in `agentkit.toml`.
- Stricter validation may reject previously accepted but contract-invalid manifests or artifacts.
- Hook regex/parser changes can cause false positives and must include paired allow/deny tests.
- Human approval is required before planning and implementation. The approving human must provide
  `approved_by` and durable `evidence`; the implementing agent must not invent either value.
