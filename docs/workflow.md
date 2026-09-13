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

Artifacts in `approved`, `active`, `completed`, or `superseded` state retain their approval actor,
timestamp, and evidence. An archived artifact is not required to contain approval because drafts can
be archived without approval.
