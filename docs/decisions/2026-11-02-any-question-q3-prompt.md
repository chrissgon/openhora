## 2026-11-02: the interpreter's prompt asks for the kind question (ANY-QUESTION Q3; a draft measured on its head, merges only after the maintainer's decision; no model call by the package)

**What changed.** `runtime/interpreter_prompt.txt` gains three insertions and nothing else: a row `question` in the OUTPUT table (after `none`), rule 12 (after rule 11) and four worked examples (after `thanks, that is all`).
The file goes from 7,893 to 9,951 bytes; its sha256 goes from `3112db68e1493e4a93f00366b33ba6cf6ad02300702a81b038af49c19ee82b42` to `9e637e3244b7938224fccf9570ba8277cbd4d9060bf538f0e3a2e55fee575bfa`.
The kind `question` was already checked (`interpreter.check`) and answered by code (Q0 to Q2); only the prompt did not ask for it.

**Where the text departs from the design's draft, and why (D1 to D8).**

- D1: "Rules 4 and 9 come first: a line that answers an open item of the frame is that answer." A line on a frame is read as an answer today ("sim?" after "Posso?"); "never none" alone invites `question other` for it.
- D2: "A request worded as a question ("could you...?", "will you...?") is that request, read by the rules above." The regression sets hold requests worded as questions whose gold is not a question; without this, "can you ... ?" reads as `about can` and steals them (the stealing that bar rule 3 counts).
- D3: the question kinds are stated BEFORE "any other question that an op of the catalog answers is that op", so "was the e-mail sent?" is `done`, not `status` or `pending`.
- D4: `done` is whether something the person asked for was done (an e-mail sent, an event created or moved, a reminder or a task created, a card approved); `op` only when the line says what, as Q1 made `op` optional with `done`.
- D5: `can` is only whether the assistant can do what an op of the catalog does, with nothing to do in the line; an ability no op has is `other`, because `check` refuses `can` without `op` (`E_SHAPE`).
- D6: the `field` meanings are in words (when: the day, the time or the length; to: who receives it, copies included; from: the account it is sent from; other: any other part), as `ops_any_question.FIELD_KEYS` reads them.
- D7: four examples, none of the design's three (those were translations of lines of the Q-dev sets and would measure recall of an example): a request worded as a question (`remind`), a `done` question with an op (`event-change`), a `card` question about a copy (`field` to), a `can` question with an op (`file-trash`).
- D8: 2,054 characters added, about 543 tokens, against the design's 1,500 and 400; about US$ 0.89 for the full sitting on the daily route (US$ 0.97 to 1.13 with a screen). The tokens are an estimate (3.78 characters a token).

**The probe entry (OPEN-Q3-1, option (a), as the maintainer decided it).** The draft appends one entry to `runtime/interpreter_enable.json` (basis `maintainer-decision`, dated 2026-11-02) that pins the new `prompt_sha256` and copies every other pin of the entry before it (catalog, protocol, route, compose, revise, event card, the outage path).
It follows the precedent of four earlier drafts that changed a pinned hash (#630 CB-9, #679 MAIL-SUMMARY-FLIP, #680 CARD-MODEL-SEES, #674 mail-card-recipient): the executor writes the provisional entry in the draft, its reason says it is measured on the PR's head before merge and merges only after the maintainer's decision,
and one commit after the sitting writes his decision into the entry's `date` and `reason`. The reason holds the marker `RESULT-ANY-QUESTION-<date>`; the merge gate `test_interpreter_enable.py::test_the_newest_entry_names_the_result_file_it_was_decided_on_before_the_pull_request_merges` is red in CI while the marker stands, by design.

**The golden effect.** `runtime/tests/test_entry_replay.py` with the new prompt and NO new entry: 736 of the 1,235 scenarios differ (the interpreter is off at that head, so every line it read goes to the planning agent's path). With the probe entry: 35 passed, 16 skipped, no row changes.
The stand-in answers of the golden are recorded objects, not the model's answer to the new prompt, so the replay says only whether the interpreter is on.

**Pins.** Moves: `interpreter_prompt` in `scripts/tests/pinned_hashes.json` (now the new hash); new `interpreter_prompt_3112` (the hash of BL7-3, which every entry from BL7-3 to mail-card-recipient was decided on); the new entry's `prompt_sha256`.
Does not move: the six `prompt_sha256` values `3112db68` in the older entries (decided entries are never edited); the earlier decision files and measurement history; the recorded answers and evidence under `evals/interpreter/` (their headers name the prompt they were made at, and `--replay` refuses them);
the catalog, protocol, route, compose, revise and event card pins; the harness files (`harness_sha256` stays).

**What voids.** The figures of RESULT-MAIL-ASK-FLIP and RESULT-CARD-MODEL are of the old prompt. The recorded answers cannot measure the new one. Nothing is measured until the sitting.

**Not done by this package.** No model call, provider call, lab run or paid step; the screen and the sitting are the maintainer's, on his "pode". A re-wording after the screen is OPEN-Q3-2 (the maintainer's).

**After the sitting.** A paragraph is added here with the result file (`RESULT-ANY-QUESTION-<YYYY-MM-DD>`) and the maintainer's decision, in the same commit that fills the probe entry's `date` and `reason`.
