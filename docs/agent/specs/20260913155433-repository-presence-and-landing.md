+++
schema_version = 1
id = "SPEC-20260913155433-repository-presence-and-landing"
kind = "spec"
status = "approved"
task_level = "high_risk"
created_at = "2026-09-13T15:54:33.3296953Z"
updated_at = "2026-09-13T15:55:49.8677069Z"
repositories = ["root"]
protected_areas = ["authorization", "release"]

[approval]
approved_by = "workspace-user"
approved_at = "2026-09-13T15:55:49.8677069Z"
evidence = "current Codex thread: user replied 'ok tiếp tục' after specification review"
+++

# Specification: Repository presence, landing page, and baseline governance

## Goal

Make the public GitHub repository immediately understandable, discoverable, safely governed, and
presentable through a lightweight project landing page without introducing a frontend toolchain or
runtime dependency.

## Confirmed facts

- The repository is public at `https://github.com/vannt-dev/governed-agent-sdlc` and `main` is the
  default branch.
- Repository description, homepage, and topics are empty.
- GitHub Pages is not configured.
- `main` has no branch protection.
- `.github/CODEOWNERS` still contains `@your-github-username` placeholders.
- GitHub reports community profile health at 71%; README, license, contributing guide, security
  policy, issue forms, and pull-request template already exist, while a code of conduct is absent.
- The current cross-platform CI matrix passes on Windows, Ubuntu, and macOS with Python 3.11–3.13.
- The repository intentionally has no JavaScript/frontend runtime dependency.

## Assumptions

- The owner identity for CODEOWNERS is `@vannt-dev`.
- English remains the canonical public project language because all existing repository content is
  English.
- A static, responsive, accessible site is preferable to adopting a site generator at MVP stage.
- GitHub Pages should deploy only a dedicated `site/` directory, not expose workflow artifacts under
  `docs/agent/` as website content.
- The project is not yet being published to PyPI; claims and installation guidance must not imply
  that it is.

## Confirmed decisions

- Add a dependency-free landing page under `site/` using semantic HTML and CSS with no third-party
  scripts, trackers, remote fonts, or cookies.
- Add a pinned-SHA GitHub Pages deployment workflow using official GitHub actions and least-privilege
  permissions.
- Update repository About metadata with an accurate description, landing-page homepage URL, and
  focused topics.
- Replace CODEOWNERS placeholders with `@vannt-dev` and add a standard code of conduct.
- Add README badges/links only for capabilities that actually exist and avoid inflated maturity
  claims.
- Establish a repository ruleset for `main` requiring pull requests and the existing validation
  checks, while retaining an explicit owner bypass for repository recovery.

## Scope

- `site/index.html` and local CSS/assets required for a polished responsive landing page.
- `.github/workflows/pages.yml` with official actions pinned to verified immutable SHAs.
- README navigation, badges, positioning, quick-start clarity, and landing-page link.
- `.github/CODEOWNERS` and `CODE_OF_CONDUCT.md`.
- GitHub repository description, homepage, topics, Pages configuration, and a `main` ruleset.
- Tests/checks for HTML links, absence of remote resources, workflow syntax/permissions, existing
  Python suite, validator, and Pages deployment.
- Independent review, QA, PR publication, human merge approval, and post-merge Pages verification.

## Out of scope

- PyPI publication, semantic release, package signing, or a version bump.
- Analytics, cookies, forms, databases, authentication, or a JavaScript framework.
- Enabling Discussions, disabling Wiki, changing visibility, transferring ownership, or deleting
  branches.
- Automatic PR merge or release without a later explicit human decision.

## Acceptance criteria

1. Repository About displays an accurate concise description and focused topics.
2. The landing page clearly explains the problem, workflow, capabilities, trust boundaries, quick
   start, supported stacks, and links to source documentation.
3. The page is responsive, keyboard accessible, readable without JavaScript, and contains no broken
   internal links or remote runtime assets.
4. Pages deploys only `site/` through an official pinned-SHA workflow with minimal permissions.
5. README links to the live site and accurately reports CI, license, Python support, and MVP status.
6. CODEOWNERS contains real ownership and the repository has a code of conduct.
7. A `main` ruleset requires pull requests and the validation workflow without blocking Dependabot
   or emergency owner recovery.
8. Existing 38 tests and `agentkit validate` remain green; Pages deployment succeeds and the live
   HTTPS URL returns the expected page.
9. Independent review and QA report no unresolved high/medium findings before merge.

## Risks and required approvals

- GitHub Pages publication and repository metadata are externally visible changes.
- A malformed ruleset can block maintainers or automation; current settings must be captured before
  mutation and an owner bypass retained.
- Workflow actions are supply-chain dependencies; versions and tag SHAs require official-source
  verification before use.
- This specification requires human approval before planning because it changes authorization and
  publishing behavior. Merge remains a separate later human approval.
