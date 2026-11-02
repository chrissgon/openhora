## 2026-11-02: the interpreter's harness reads the outcome question (ANY-QUESTION Q0; no model call, no lab run, lab fingerprint unchanged)

**What the package does.** The harness that measures the interpreter learns the outcome `question`, the sixth kind of the interpreter's protocol that package Q1 adds to the checker. Nothing here asks a model for it: the kind is inert until a later prompt asks for it, and this package makes a recorded answer of that kind scorable, mappable, writable as evidence and valid in a corpus.

**The gold and the observed word.** A gold `question` is `{"outcome": "question", "about": A}` plus, by `about`: `card` takes a required `field` (`title`, `when`, `place`, `to`, `from`, `subject`, `approve`, `other`) and no `op`; `done` takes no `field` and an optional `op` of the served catalog (`ops` or `refused`); `can` takes no `field` and a required `op` (the same); `other` takes neither. The observed word is `question`, its detail `{"about", "field", "op"}` (None for a key the decision does not carry). A question matches a gold `question` when the three are equal (None equal to absent).

**No new rule and no new category.** A question that matches is `correct` (rule 8). A question that does not match, and a question on a gold of another outcome, fall to rule 9 and are `missed`; a gold `question` met by a card is `wrong_card` (rule 2), by a read `wrong_read` (rule 5), by a route `wrong_route` (rule 6) and by a clarify `clarify` (rule 7), exactly as those rules already say. A question that takes the place of another gold (stealing) is a counter, not a category: `question_on_other_golds`, `{gold outcome: items}`, one item counted once, shown in the summary and in the text report and read by bar rule 3 of DESIGN-ANY-QUESTION OPEN-7. The severity list and the nine rule texts are unchanged (a test holds both as literals).

**The five examples** appended to `taxonomy.json` (after the 32 that existed; the first nine are pinned): a question card/when observed as the same, `correct`; a gold done/remind met by done with op `event-create`, `missed`; an op gold `reminders` met by a question done/remind, `missed`; a gold can/event-change met by a card, `wrong_card`; a gold `none` met by a question other, `missed`.

**Files.** `evals/interpreter/taxonomy.json` (observed word, its meaning, the matching sentence, the metric, the five examples), `runtime/interpreter_score.py` (`OUTCOME_OF`, `matches`, `summary`), `runtime/interpreter_pipeline.py` (`OUTCOMES`, `observe`), `runtime/interpreter_measure.py` (`text_report`), `evals/evidence_lines.py` (`IX_OBSERVED`, `IX_GOLDS`), `scripts/interpreter_corpus_format.py` (`OUTCOMES`, the check of a question gold), `runtime/tests/test_interpreter_echo.py` (the echo answers a question gold), `evals/interpreter/README.md`, the test `runtime/tests/test_interpreter_question_scoring.py`.

**The new hashes.**

| | before (156eac52) | after |
|---|---|---|
| `taxonomy.json` bytes | b4efce8315a8727d509d5abf4c31e041a8873b2fa0a494d1853fcdea62ec4ce5 (11643 bytes) | f5c12ff3a78f90747bc1b87f266fdbe0ea7b0dafab84059044d3c264e7a21cf9 (13128 bytes) |
| `taxonomy_sha256` (canonical) | 72d02a19aea3a586d64b48ea2236cd5b8cec2ab27ff1dcb349947bf9c4c06fbb | 8cdae32992fb2427ef608c5965c6945f70fc51e71845d2ea2dac59ce1f6b6724 |
| `harness_sha256` | a94effb6df234ee3240f775f34a95f1facaed047d6e8412d07e017758e58f1b0 | b422fae90fe977d82df85bbb362d6b226f9c8902d84e66ee18837a712563910c |

Computed with `python3 -c "import sys,json,hashlib; sys.path.insert(0,'runtime'); import interpreter_evidence as e; print(hashlib.sha256(open('evals/interpreter/taxonomy.json','rb').read()).hexdigest(), e.sha_obj(json.load(open('evals/interpreter/taxonomy.json'))), e.harness_sha256())"`.

**Is it a measurement change, and does it need an epochs line?** Verified in the code:
- It is a change of what the INTERPRETER measurement reads: `taxonomy.json` and the four `runtime/interpreter_*.py` modules are `HARNESS_FILES` (`runtime/interpreter_evidence.py:41`), so `harness_sha256` and `taxonomy_sha256` of every later event change. The current set of a route is filtered by `taxonomy_sha256` (`evals/interpreter_status.py` `_hash_fields`), so it empties every current set. Today none is current: at the pin every row of `interpreter_status.py status` is `needs a run` by `catalog_sha256` (30 rows); with the taxonomy edited the same 30 rows stay `needs a run` and the cause reads `taxonomy_sha256, catalog_sha256`; the held-out lists (`blite-blind-v2-split.json`) are unchanged (`heldout_report` does not filter by taxonomy).
- It is NOT a measurement change of the skill lab: `FINGERPRINT_FILES` (`evals/eval_status.py`) hold none of these files, so no `eval_status.py measurement` command and no gate-file change.
- **No `epochs.json` line:** `evals/interpreter/epochs.json` holds catalog epochs only (`catalog_sha256`, `date`, `state`, `served`); the catalog does not change.
- A decision file: yes, this one, as the freeze of IX-1 recorded the taxonomy's hashes (`docs/decisions.md` is closed since 2026-10-27).

**Status output after the change.** `python3 evals/interpreter_status.py status` lists 30 rows, all `needs a run`: the six languages of the five routes. The causes read `taxonomy_sha256, catalog_sha256` for or-deepseek-v4.1-flash and or-gpt-6-luna, `prompt_sha256, taxonomy_sha256, catalog_sha256` for the reference route, and `no test run of this route` for the two routes never run; the held-out set rows are unchanged; `go: no`. Every current set was already empty before this change (it was `needs a run` by `catalog_sha256`).

**Limits.** No path here sends, writes, approves, rejects, ends or opens anything (L55): the package changes a scorer, a mapping, a validator and a data file, and makes no model, provider or lab call.

**Not verified.** No run of the harness over a model's answer of the kind (none exists; the set that would exercise it is package Q2).
