+++
schema_version = 1
id = "REVIEW-20260913160739-repository-presence-and-landing"
kind = "review"
status = "archived"
task_level = "high_risk"
created_at = "2026-09-13T16:07:39.3246145Z"
updated_at = "2026-09-13T16:17:58.683177+00:00"
parent = "TASK-20260913155701-pages-workflow"
repositories = ["root"]
protected_areas = ["authorization", "release"]
+++

# Independent review: Repository presence and landing page

## Outcome

Review does not pass. Four medium-severity findings remain in public security claims, narrow-screen
layout, keyboard focus contrast, and the code-of-conduct reporting path. The artifact remains
`draft`, so QA and publishing gates are intentionally not satisfied. The reviewer did not edit
implementation source, self-approve, publish, or change external repository settings.

## Scope reviewed

- Approved specification `SPEC-20260913155433-repository-presence-and-landing` and plan
  `PLAN-20260913155549-repository-presence-and-landing`.
- Completed implementation tasks `TASK-20260913155700-repository-content-and-site` and
  `TASK-20260913155701-pages-workflow`.
- Current uncommitted changes against `origin/main`, including landing HTML/CSS/SVG, README,
  CODEOWNERS, code of conduct, Pages workflow, tests, public links, action provenance, permissions,
  and lifecycle metadata.

## Findings

### Medium: Landing page overstates mechanically enforced role capability boundaries

`site/index.html:70` says agents receive only the capability required for their current role, and
`site/index.html:98` says role-scope escapes fail closed. In the shipped Claude adapter, reviewer
and QA agents still receive `Bash`, `Write`, and `Edit`; `.claude/settings.json:31-39` invokes the
role-scope guard only for `Write|Edit`, while `hooks/guard_role_scope.py:18-39` does not inspect
shell commands. A reviewer can therefore use its available Bash capability to modify source even
though direct Write/Edit calls are constrained. Instructions prohibit that behavior, but the
website presents it as a deterministic capability boundary. This conflicts with the
specification's accurate-public-claims requirement and could mislead adopters about the security
model.

Required remediation: narrow the site language to the mechanically enforced subset described in
`docs/architecture.md`, or separately scope Bash operations by role before claiming role-scope
escapes fail closed. Add a regression assertion for the final wording or enforcement behavior.

### Medium: Mobile header can overflow the viewport

`site/styles.css:38` keeps a two-rem gap between the brand and navigation. At the mobile breakpoint,
`site/styles.css:115-117` retains that gap while allowing the brand text to consume 150px plus a
36px icon and spacing, and keeps the full “View on GitHub” pill visible. Those minimum contents,
the inter-item gap, and 32px page padding exceed common 320px and 375px viewports. The flex row has
no wrapping, shrinking, or compact-label rule, so horizontal overflow is likely at the sizes where
the mobile media query is intended to apply. This misses the responsive acceptance criterion.

Required remediation: introduce a narrow-header layout that fits at 320px (for example, hide or
shorten the CTA, reduce the brand/gap, or wrap intentionally), then cover the viewport width in
browser QA or an equivalent rendered layout check.

### Medium: The global keyboard focus indicator lacks required contrast on light surfaces

`site/styles.css:105` uses coral (`#f06f4f`) for every `:focus-visible` outline. Its contrast is
2.61:1 against the primary paper background (`#f5f0e5`) and 2.91:1 against white
(`#fffdf7`), below the 3:1 contrast expected for visible focus indicators. Many links and buttons
appear on those light surfaces, so keyboard focus is not reliably perceivable even though a focus
rule exists. This misses the keyboard-accessibility acceptance criterion.

Required remediation: use a focus color with at least 3:1 adjacent contrast on every supported
surface, or apply surface-specific focus styles, and add a contrast regression check.

### Medium: Code-of-conduct reports are directed to a nonexistent private contact channel

`CODE_OF_CONDUCT.md:26-29` directs people to a contact channel on the owner's GitHub profile for
sensitive conduct reports. The public GitHub API currently reports no email, blog, or bio for
`vannt-dev`, so the referenced private channel does not exist. This leaves reporters without the
documented confidential enforcement path.

Required remediation: provide a concrete monitored private contact method, or use a documented
GitHub private-reporting mechanism that is actually enabled, and verify it before publication.

## Low-severity observations and coverage gaps

- `tests/test_site.py:42-78` checks landmark strings, local assets, anchors, a media-query marker,
  and workflow substrings, but it does not render at desktop/mobile widths, compute focus contrast,
  validate public security claims, parse YAML structurally, or exercise external links. These gaps
  allowed the findings above to pass all 43 tests.
- Browser visual inspection was not performed because the configured Browser skill reported no
  available backend. The implementation task records this limitation accurately; QA must not claim
  responsive or visual completion until a real rendering check runs.
- The README's project-site link and the site's `main` documentation links are expected to be
  unavailable or to reflect the old revision before merge and Pages enablement. They require
  post-deployment verification rather than being treated as currently live.

## Verified areas

- The Pages workflow uploads only `site/`, does not run on pull requests, uses the standard
  `contents: read`, `pages: write`, and `id-token: write` permissions, and has explicit deployment
  concurrency.
- Read-only `git ls-remote` queries against the four official action repositories confirmed that
  the exact 40-character pins correspond to checkout `v7.0.1`, configure-pages `v6.0.0`,
  upload-pages-artifact `v5.0.0`, and deploy-pages `v5.0.1`.
- The landing page has semantic landmarks, one H1, a skip link, resolved internal anchors, local
  runtime assets only, no script, reduced-motion handling, and accurate Python/MIT/CI/runtime-
  dependency facts apart from the role-boundary overstatement above.
- CODEOWNERS replaces all placeholders with `@vannt-dev` for policy, schema, hook, workflow, and
  site paths. README accurately labels the project MVP and does not imply PyPI availability.
- Artifact ancestry and approvals for the specification, plan, and completed implementation tasks
  validate successfully.

## Verification evidence

- `$env:PYTHONPATH='src'; uv run --no-project python -m unittest discover -s tests -v`: 43 tests
  passed.
- `$env:PYTHONPATH='src'; uv run --no-project python -m agentkit validate`: 0 errors, 0 warnings
  before adding this draft review artifact.
- `$env:PYTHONPATH='src'; uv run --no-project python -m compileall -q src hooks tests`: passed.
- `git diff --check`: passed with line-ending warnings only.
- Official action release pages and direct `git ls-remote` tag reads matched every pinned SHA.
- Read-only GitHub API checks confirmed `main` as the default branch, Pages disabled, empty current
  About metadata/topics, community health at 71%, and no public owner contact field.

## Gate decision

Independent review remains blocked by the four medium findings. Create a scoped remediation task,
resolve the issues, and obtain a new independent review before QA or publication.
