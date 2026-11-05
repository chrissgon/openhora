# Security policy

## Reporting a vulnerability

Report it privately through <the host's private reporting: on GitHub, the repository's **Security** tab, **Report a vulnerability**>. Do not open a public issue.

Include what is affected, how to reproduce it, and what an attacker gains. You will get an answer within <n, the number of days the user gave; never a default> days.

## What the repository already does

- Every push and pull request runs the project's checks and a secret scan of the working tree and the whole history (`.github/workflows/checks.yml`).
- A pre-commit hook runs the same secret scan before each commit (`.githooks/pre-commit`, enabled per clone with `git config core.hooksPath .githooks`).
- <Only when the user chose gitleaks: a second secret scanner, gitleaks, pinned to one version and checked against its published checksum, runs in the same two places.>
- Dependency alerts and version updates are on (`.github/dependabot.yml`).
