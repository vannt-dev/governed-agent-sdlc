# Workflow

```text
raw requirement
  -> specification (draft -> awaiting_approval -> approved)
  -> plan and task graph
  -> implementation
  -> independent review
  -> QA evidence
  -> human publish approval
  -> pull request
```

Every artifact has a stable ID. Child artifacts reference their parent ID. Supersession is explicit:
the replacement names `supersedes`, while the old artifact transitions to `superseded`. Validation
rejects children of superseded or archived artifacts.

Statuses are changed through `agentkit artifact transition`, not by loosely editing prose. Approval
requires a human actor and durable evidence such as a GitHub issue or pull-request comment.

When the corresponding workflow flags are enabled, the validator enforces these parent gates:

- a plan references an approved, active, or completed specification;
- a task references an approved, active, or completed plan;
- a review references a completed task;
- QA references a completed review.

The Claude Code adapter applies the same gates earlier, when a role is spawned: `hooks/guard_role_gate.py`
reads `[gates]` in `core/policies/workflow.toml` and refuses to start a planner on a spec that is
still a draft, a developer on a task that is not active, and so on for review, QA, and publish. It
checks the artifacts the spawn prompt names by path, so name them.

## Task levels

`task_level` records how much scrutiny a change needs: `small`, `mechanical`, `medium`, or
`high_risk`. Each level is defined once, under `[task_levels]` in `core/policies/workflow.toml`.

The level follows what the change does, not where its files live. A rename that touches thirty
files, some of them under billing, changes no outcome and is `mechanical`. A one-line change to
who may see an invoice is `high_risk`.

## Evidence and ownership

A task file belongs to the planner. The developer, reviewer, and QA roles may fill in its
completion evidence section and nothing else; `hooks/guard_role_scope.py` refuses any other edit.
A role that finds the task wrong or incomplete records that in the evidence and stops at the
boundary of the written scope, and the planner changes the task.

Artifacts in `approved`, `active`, `completed`, or `superseded` state retain their approval actor,
timestamp, and evidence. An archived artifact is not required to contain approval because drafts can
be archived without approval.
