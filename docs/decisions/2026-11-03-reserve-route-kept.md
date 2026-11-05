## 2026-11-03: the outage route or-gpt-6-luna is re-measured at the current prompt and kept below rule 2, on the maintainer's decision (RESERVE-V3; no model call, no provider call, no lab run by this entry)

**The decision.** The outage route `or-gpt-6-luna` has been the fallback in force since the entry of 2026-10-28 (`docs/decisions/2026-10-28-luna-enable-fallback.md`). The entry of 2026-11-03 (ANY-QUESTION Q3) pinned a new interpreter prompt and its reason said that the outage path served that prompt unmeasured.
The route was then measured at the current prompt `9e637e32` and catalog `aed31af3` (head `e1527213`), beside the primary `or-deepseek-v4.1-flash`, on the same sets. The result file is `RESULT-RESERVE-V3-2026-11-03`; it lives outside the repository.

**What was measured.** The bar was:

- Rule 1 (hard, on Luna) was met: no effect without confirmation on any part; on the question set, no question opened a card and no greeting was answered as a question.
- Rule 2 was not met: `correct_direct` at most 10 points below the primary in pt-BR and in en. Luna was 12.7 points below in pt-BR and 11.9 points below in en.
- Rule 4 was met: every part stayed within the harness's error limit.
- The question set per language was printed, not judged.

The Luna figures: F `correct_direct` 0.708 against the primary's 0.817; on the question set, 0.840 against 0.940; Luna's parse failures 2.2%.

**What the maintainer decided (2026-11-03).** The maintainer keeps Luna as the fallback, below rule 2. A model that wrongly reads a line can still only open a card the person approves, and the mechanism of the outage path (the group `interpret-fallback`, the person's consent, the outage or the open breaker) is unchanged.

**What changes.** One new newest entry in `runtime/interpreter_enable.json`, dated 2026-11-03. It copies every key and value of the entry before it (prompt, catalog, protocol, route, languages, compose, revise and event card pins, and the outage path with its row hash `e029d4a7...`) and changes only `reason`, `status_line` and, inside the outage path, the text `measured`, which now names the 2026-11-03 events (`20261103T184754Z-5dad949d` for Luna and `20261103T184655Z-19a743ea` for the primary) and keeps the first measurement of 2026-10-28; its date is the same day as the entry before it, which `load` accepts.
The reason names `RESULT-RESERVE-V3-2026-11-03` and says "kept as the fallback below rule 2 by the maintainer's decision of 2026-11-03". The status line now says the outage path was re-measured on 2026-11-03 and kept below rule 2, in place of the 2026-10-28 wording. The entry before it is not edited.

**What does not change.** No pin, no route row, no prompt, no catalog; the golden replay (`runtime/tests/test_entry_replay.py`) keeps its rows. Turning the fallback off stays a new dated entry without `fallback`, or a change of the row's hash.
