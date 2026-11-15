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

## D-002: The published-text check fails on personal information only; doc wording is a warning (2026-11-15)

**Decision.** `tests/test_wording.py` did two jobs with one result. It found personal information (usernames, mail
addresses, drive paths), and it found doc wording about a person (first person, or a role-style reference to the
maintainer) in prose files, comments, docstrings and golden-set notes. A wording finding failed the test run under the
heading "wording problems", although no personal information was present.

The two jobs are now separate in the result:

- A personal-information finding fails the check, as before. A failed check fails CI and stops the change.
- A wording finding is printed in the pytest warnings summary under "doc wording warnings (not blocking)", with the
  file and the line. The check passes, locally and in CI.

A pattern cannot tell the voice of the docs from a quoted customer or model message, so a wrong match now costs a line
of output and not a rewrite of correct text. The one-voice rule for published text is unchanged; only its enforcement
changed from a gate to a warning.

The first-person pattern also no longer matches the pronoun before a present-tense verb that ends in "ed" ("I need",
"I feed", "I speed", "I heed", "I seed", "I proceed", "I succeed", "I exceed"). The past-tense forms of these verbs
still match.

The repository has no commit hook and no check of commit messages, so no commit-message rule changed. The rules for
commit messages stay a manual check.
