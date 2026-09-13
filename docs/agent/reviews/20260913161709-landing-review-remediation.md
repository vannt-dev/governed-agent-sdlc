+++
schema_version = 1
id = "REVIEW-20260913161709-landing-review-remediation"
kind = "review"
status = "completed"
task_level = "high_risk"
created_at = "2026-09-13T16:17:09.260704+00:00"
updated_at = "2026-09-13T16:19:05.714639+00:00"
supersedes = "REVIEW-20260913160739-repository-presence-and-landing"
parent = "TASK-20260913161019-landing-review-remediation"
repositories = ["root"]
protected_areas = ["authorization", "release"]

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-13T16:18:52.082419+00:00"
evidence = "user approved re-review in chat: 'ok, tiếp tục'"
+++

# Independent re-review: Repository presence and landing page remediation

## Outcome

The implementation passes independent technical re-review. All four medium-severity findings identified in `REVIEW-20260913160739-repository-presence-and-landing` have been verified as resolved in the working tree, and no new high- or medium-severity issues were detected.

The artifact is submitted as `awaiting_approval`. As per governance policy, the reviewer does not self-approve or authorize release gates; human approval is required to transition this review to `approved` and `completed` before QA and publishing proceed.

## Scope reviewed

- Superseded review `REVIEW-20260913160739-repository-presence-and-landing`.
- Completed remediation task `TASK-20260913161019-landing-review-remediation`.
- Working tree changes in `site/index.html`, `site/styles.css`, `CODE_OF_CONDUCT.md`, and `tests/test_site.py`.
- Automated test coverage and validation suite.

## Resolved findings

### 1. Accurate role capability and security boundary claims
- **Prior finding**: `site/index.html` overstated that agents receive only capabilities required for their role and that escapes fail closed, when reviewer/QA agents retain Bash access and hooks only check `Write|Edit`.
- **Resolution**: `site/index.html:70` and `site/index.html:98` were updated to state that policy keeps authority with humans, generated role guidance and hooks constrain supported tool actions, platform permissions form the boundary, and supported hooks deny known credential access, force pushes, protected-branch refspecs, and reviewer/QA source writes.
- **Verification**: `tests/test_site.py:test_public_copy_does_not_overstate_enforcement` passes.

### 2. Narrow mobile viewport overflow (320px–375px)
- **Prior finding**: Header brand text, 2rem gap, and CTA pill caused horizontal overflow on 320px–375px viewports.
- **Resolution**: `site/styles.css:126` introduces `@media (max-width: 380px) { .site-header .brand span { display: none; } }`, hiding the text label on narrow viewports while preserving the brand mark and CTA button within 320px width.
- **Verification**: `tests/test_site.py:test_responsive_and_accessibility_basics` validates the 380px rule and layout constraints.

### 3. Keyboard focus indicator contrast
- **Prior finding**: Single coral focus outline lacked WCAG 3:1 contrast against light background surfaces.
- **Resolution**: `site/styles.css:106` implements a dual-ring focus pattern (`outline: 3px solid var(--white); outline-offset: 2px; box-shadow: 0 0 0 6px var(--focus);`). This provides contrasting borders against both light backgrounds (`var(--focus)` has high contrast against `#f5f0e5` and `#fffdf7`) and dark surfaces (`var(--white)`).
- **Verification**: `tests/test_site.py:test_responsive_and_accessibility_basics` verifies the dual-ring focus rule.

### 4. Code of conduct private reporting channel
- **Prior finding**: `CODE_OF_CONDUCT.md` directed sensitive reports to a nonexistent private channel on GitHub profile `vannt-dev`.
- **Resolution**: `CODE_OF_CONDUCT.md:26-29` was updated to direct sensitive platform and conduct reports to `https://support.github.com/contact/report-abuse` and non-sensitive issues to repository issues.
- **Verification**: `tests/test_site.py:test_conduct_policy_has_real_private_reporting_link` passes.

## Verification evidence

- `python -m unittest discover -s tests -v`: 45 passed (45/45).
- `python -m agentkit validate`: 0 error(s), 0 warning(s).
- `python -m compileall -q src hooks tests`: clean, 0 errors.
- `git diff --check`: clean (CRLF warnings only).

## Gate decision

Independent technical review is clean. In accordance with SDLC policies and AGENTS.md, human approval of this review artifact is required to advance to QA and Publishing.
