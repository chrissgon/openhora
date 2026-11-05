# gitleaks as an optional second secret scanner

Read this when the user chose "bundled + gitleaks" in step 3 of the procedure, and when updating the pin.

## Why it is optional, and why it never replaces the bundled scanner

- The bundled `scripts/secret-scan/secret_scan.py` needs nothing from outside the repository, runs the same in the hook and in CI, and knows the project's planted fixtures: it labels a finding `real` or `planted?` from its folder and lets a planted value through with a reasoned line in `.secret-scan-allow`. It stays on in step 2, in the hook and in the checks workflow whatever the user chooses.
- gitleaks is an established scanner with a much larger rule set of provider formats. The cost of adding it is a downloaded binary that has to be pinned, verified and updated by hand. That is the user's choice, asked in step 3 with the bundled scanner alone as the recommendation.

## The pin

Read on 2026-10-15 from the latest stable release of the project's official GitHub releases page, `https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1` (published 2026-03-21), and from that release's checksums file, `https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_checksums.txt`. The release's asset digests shown by the host's API are the same values.

| Platform | Archive (`gitleaks_8.30.1_<platform>.tar.gz`) | sha256 |
|----------|----------------------------------------------|--------|
| linux-x64 | `linux_x64` | `551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb` |
| linux-arm64 | `linux_arm64` | `e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080` |
| darwin-x64 | `darwin_x64` | `dfe101a4db2255fc85120ac7f3d25e4342c3c20cf749f2c20a18081af1952709` |
| darwin-arm64 | `darwin_arm64` | `b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5` |

Where each value is used: `scripts/gitleaks_setup.py` holds all four (the person's machine); `assets/checks.yml` holds the version and the linux-x64 checksum (the CI runner); `assets/pre-commit` holds the version (it compares it with the `gitleaks.version` file the setup script writes). The tests in this skill's `scripts/tests/` fail when the three disagree with each other or with this table.

Commands used, from the README of that release: `gitleaks git` (the command that replaced `detect` in 8.19.0) with `--redact` (no secret value in any output), `--no-banner`, `--exit-code 1` (non-zero on a finding; also the default), `--config <file>`; the hook adds `--staged`. They were read from the release's README and source, not run when the pin was written: the first run of a project's CI is the first test of them.

## How to update the pin

1. Open the latest stable release on the official releases page and its checksums file. Take the version and the four checksums from the file, never from memory and never from a mirror.
2. Change the version and checksums in the three places above and in the table here, with the new access date, in one change.
3. Run the tests of `skills/ops-repo-baseline/scripts/tests/` (they check the agreement) and raise the skill's version with the `bump` command.
4. A project that already installed the baseline gets the new pin as a proposal for its existing files (Stop rule 4), not an overwrite.

## Why not the gitleaks Action

The project's GitHub Action asks for a license key when the repository belongs to an organisation account, and it is a moving dependency that runs code the project did not pin by checksum. A pinned archive with a checked sha256 needs neither. The workflow therefore downloads the release archive, checks it, and runs the binary; it adds no `uses:` line.

## The configuration

`assets/gitleaks.toml` extends gitleaks' default rules (`useDefault = true`) and adds one global allow-list for paths inside the folders the bundled scanner marks as planted fixtures (`PLANTED_DIRS` in `secret_scan.py`): the same names, so the two scanners agree about where a fixture can be. It allows no rule, no regex and no commit globally. The consequence to say to the user: a real secret committed under `tests/`, `fixtures/`, `evals/` or `examples/` is reported by the bundled scanner as `planted?` (and asked about), and is not reported by gitleaks, which is why the bundled scanner stays on.

## What the bundled scanner allows and gitleaks does not know

gitleaks reads neither `.secret-scan-allow` nor the bundled scanner's `kind`. A documented fake outside the planted folders, a line allowed in `.secret-scan-allow`, or a revoked key the user keeps in the history is a gitleaks finding until it is ignored there too, and the gitleaks step of the workflow and the hook fail on it.

1. Ask the user to run, once, `scripts/secret-scan/bin/gitleaks git --redact -v --no-banner --config scripts/secret-scan/gitleaks.toml .` after the setup script, and to paste the `Fingerprint:` lines. A fingerprint is `<commit>:<file>:<rule>:<line>` and holds no secret value. The hook's staged scan prints the three-part form `<file>:<rule>:<line>`, with no commit; that form is also valid in `.gitleaksignore` and covers every commit, and a finding that is not committed yet needs it. The skill does not run the setup script.
2. For each `.secret-scan-allow` line, and each finding the user confirms is planted or revoked, propose one line of `.gitleaksignore` (project root, one fingerprint per line). Write it only after the user agrees, as for `.secret-scan-allow`.
3. Until the lines exist, the gitleaks step of the workflow and the hook stay red. Say so in the report. Do not widen `gitleaks.toml` to silence them: its allow-list stays the planted folders.
4. A fingerprint holds a commit hash, so rewriting history changes it; the user regenerates the lines after a rewrite.
