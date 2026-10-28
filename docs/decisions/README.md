# Decision entries

One file per decision entry, from 2026-10-27 on. `docs/decisions.md` is closed: it stays as the record up to that date and is not edited.

- **Name:** `YYYY-MM-DD-<package-id>-<slug>.md`, lower case, digits and hyphens, ASCII. The date comes from `date +%F`; the package id is the one in the pull request title (for example `2026-10-27-cb-5-tasks-operations.md`); a measurement change uses `measurement-<kind>` after the date, as `python3 evals/eval_status.py measurement` suggests.
- **Content:** what an entry of `docs/decisions.md` looked like: a first line `## YYYY-MM-DD: <title> (<package>; ...)`, whose date is the date of the file name, then the entry's text (the decision, the alternatives rejected, why).
- **Never edited once merged.** A correction is a new file that names the file it corrects.
- **Checked by** `python3 scripts/validate.py` (`decision-files`): a name that does not match, or a first line that does not start with `## <the same date>: `, is an error. The `english-only` and `private-term` checks read this folder like any other.

Why: with one file per entry, two open pull requests never touch the same lines, so a merge no longer leaves every other pull request in conflict on the log.
