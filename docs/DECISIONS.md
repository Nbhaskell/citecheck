# Decisions

## D-001: Settings of the public repository (2026-11-13)

**Decision.** The GitHub settings for this public repository are:

- Secret scanning with push protection: on.
- Dependabot alerts: on. Dependabot security update pull requests: off, because alerts are enough for a finished project.
- CodeQL default setup: on.
- Private vulnerability reporting: on. The reporting route is described in [`SECURITY.md`](../SECURITY.md).
- Ruleset "Protect main history" on the default branch: blocks force pushes and deletion. It does not require a pull request
  or a status check, because the project is finished and later small changes may go directly to `main`. CI still runs on every push to `main` and on every pull request.
- Projects tab: off.
- Merged branches are deleted automatically.
