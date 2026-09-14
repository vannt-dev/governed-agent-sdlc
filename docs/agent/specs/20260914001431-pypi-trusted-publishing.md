+++
schema_version = 1
id = "SPEC-20260914001431-pypi-trusted-publishing"
kind = "spec"
status = "approved"
task_level = "high_risk"
created_at = "2026-09-14T00:14:31.994723+00:00"
updated_at = "2026-09-14T00:14:31.994723+00:00"
repositories = ["root"]
protected_areas = ["release"]

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-14T00:14:31.994723+00:00"
evidence = "user instruction: 'ok, triển khai luôn' in response to the proposed safe PyPI Trusted Publishing workflow"
+++

# Specification: Safe PyPI Trusted Publishing

## Goal

Publish the existing `v0.1.0` distribution to PyPI through GitHub OIDC Trusted Publishing without API tokens, without recreating or mutating the GitHub Release, and with a protected GitHub Environment approval gate.

## Confirmed facts

- Package name and version are `governed-agent-sdlc` and `0.1.0`.
- GitHub Release `v0.1.0` exists with wheel and source distribution assets.
- The current manual workflow path attempts GitHub Release creation before PyPI publication.
- PyPI Trusted Publishing requires `id-token: write` and an identity matching the configured owner, repository, workflow filename, and optional environment.

## Scope

- Refactor `.github/workflows/release.yml` into separate GitHub Release and PyPI publication jobs.
- Add a required manual `release_tag` input.
- Publish only assets downloaded from the selected existing GitHub Release.
- Bind the PyPI job to GitHub Environment `pypi` with least-privilege permissions.
- Extend regression tests for dispatch safety, environment binding, asset reuse, and action pinning.
- Produce governed review, QA, and publication evidence.

## Out of scope

- PyPI account creation or Trusted Publisher configuration on behalf of the user.
- Static PyPI credentials or API tokens.
- Retagging or rebuilding the published `v0.1.0` release.

## Acceptance criteria

1. Tag pushes continue to build and create GitHub Releases.
2. Manual PyPI publication does not execute the GitHub Release build/create job.
3. The PyPI job requires environment `pypi` and `id-token: write`.
4. PyPI uploads reuse the wheel and sdist from the requested GitHub Release.
5. Invalid or missing version tags are rejected before publication.
6. Unit tests, validator, compilation, and diff checks pass.

