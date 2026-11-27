## 2026-11-27: Two scratch paths are redacted from a merged entry, and the site test's licence line is marked (pt-1)

**Correction of `docs/decisions/2026-11-08-v3b-3-hf-tier-a.md`.** Entries are never edited once merged, and a correction is a new file. A redaction cannot be made by a new file alone: the text has to leave the old one. So that entry was edited in one place, and this file records the edit.

- **What changed there.** Two lines (the STOP C10 message and the first command of its steps) named a session's scratch folder by its full path, which carries the maintainer's local account name. The path is now written `<scratchpad>`. Nothing else in the entry changed; the path named a temporary folder that no longer exists and that no reader could open. The full text stays in the history.
- **Why.** Principle 8: the workbench holds nothing that identifies a person beyond the maintainer's name and handle where ownership needs them, and a scratch path needs neither. The local `private-term` check of `scripts/validate.py` found both lines.
- **The site test.** `site/tests/website.test.mjs` quotes the copyright line of `LICENSE` as the site shows it. That is the ownership exception of principle 8, so the line carries `validate: allow private-term -- <reason>`, as the check expects, instead of a change of the quoted text.

Rule for later entries: a command or a message copied into an entry writes a scratch folder as `<scratchpad>` (or a variable set to it), never as its full path.
