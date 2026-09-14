+++
schema_version = 1
id = "TASK-20260913164700-publish-release-pipeline"
kind = "task"
status = "active"
task_level = "high_risk"
created_at = "2026-09-13T16:47:00.916453+00:00"
updated_at = "2026-09-13T16:47:00.916453+00:00"
parent = "PLAN-20260913164154-release-pipeline-and-v010"
repositories = ["root"]
protected_areas = ["release"]

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-13T16:47:00.916453+00:00"
evidence = "user requested: 'ok, triển khai tất cả giúp mình' for release automation and v0.1.0 release"
+++

# Task: Publish release pipeline through PR

## Goal

Create a feature branch, commit release workflow, tests, and lifecycle evidence, push branch, open Pull Request, wait for CI checks, and merge to `main`.

## Preconditions

- Approved spec, plan, tasks, review, and QA.
- User authorization to publish.

## Write scope

Git task branch, commits, pull request, and completion evidence.

## Verification

CI matrix passes 9/9 checks, clean merge to `main`.

## Completion evidence

Pending.
