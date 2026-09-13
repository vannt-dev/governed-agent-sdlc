+++
schema_version = 1
id = "SPEC-20260913164129-release-pipeline-and-v010"
kind = "spec"
status = "approved"
task_level = "high_risk"
created_at = "2026-09-13T16:41:29.568165+00:00"
updated_at = "2026-09-13T16:41:29.568165+00:00"
repositories = ["root"]
protected_areas = ["release"]

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-13T16:41:29.568165+00:00"
evidence = "user requested: 'ok, triển khai tất cả giúp mình' for release automation and v0.1.0 release"
+++

# Specification: Release pipeline automation and v0.1.0 release

## Goal

Establish an automated release pipeline (`.github/workflows/release.yml`), produce verified build artifacts (wheel and sdist), support GitHub Releases on tag pushes (`v*`), prepare PyPI publication readiness via OIDC Trusted Publishing, and publish the initial MVP release `v0.1.0`.

## Confirmed facts

- Package version in `pyproject.toml` is `0.1.0`.
- Build backend is `hatchling` with resource mappings for `core/`, `hooks/`, and `profiles/`.
- No git tags or GitHub releases exist yet.
- PyPI package name `governed-agent-sdlc` is available and not yet claimed.
- Release creation requires human authorization and is governed under protected area `release`.

## Assumptions

- Initial release tag is `v0.1.0`.
- GitHub Release creation and build asset attachment run on `v*` tag push or manual workflow dispatch.
- PyPI publishing is configured via official OIDC Trusted Publishing (`pypa/gh-action-pypi-publish`), proceeding gracefully if PyPI environment is configured.
- Release workflow uses immutable action pins and least-privilege permissions.

## Scope

- `.github/workflows/release.yml` with least privilege (`contents: write`, `id-token: write`).
- Pinned official action releases for checkout, setup-python, build, and release.
- Regression tests verifying release workflow pins and structure in `tests/test_release_workflow.py`.
- Source PR publication, review, QA, merge, tag `v0.1.0`, and GitHub Release creation.

## Out of scope

- Hardcoded PyPI API tokens (only modern OIDC / Trusted Publishing is supported).
- Changes to existing core agentkit logic.

## Acceptance criteria

1. Release workflow passes static syntax, action pin, and permission checks.
2. Build command produces valid wheel and sdist with all required resource folders.
3. Tests for release workflow pins pass.
4. All existing 45 unit tests and validator continue to pass with 0 errors/warnings.
5. Release PR merged to `main`.
6. Git tag `v0.1.0` created and GitHub Release `v0.1.0` published with release notes and distribution assets.
