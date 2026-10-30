## 2026-10-29: `natural.candidate` and what only it read are deleted (CANDIDATE-OUT PR 2; no model call, no lab run, fingerprint unchanged)

PR 1 (#656) made the reminder question engine ask the code guard `turn_gate.new_request` instead of `natural.candidate`: after it, only the stand-ins of the tests read `candidate`. This change deletes it, with everything that only it read, and freezes the old reading in the test tree where the stand-ins still need it (OPEN-CO-1, recommendation: freeze).

**Deleted from the product.**
- `runtime/natural.py`: `candidate`, `_forget`, `_undo`, `_verb_noun`, the repeat scope of CB-9 (`_RepeatScope`, `_REPEAT`, `repeat_scope`, `repeat_goes_on`), `CANDIDATE_OPS`, `operation_of`, `LIST_WORDS_MAX`, `FORGET_WORDS_MAX`, `MANY_IDS_MAX`, the imports `contextlib` and `threading`, and the module text that described `candidate`. Kept: `BARE_WORDS_MAX` (`natural_writes_calendar`), `_anywhere` (`natural_writes`), `_head`, `_stop` (`messaging_inbound`), `_words`, `_tidy`. The lazy import of `recurrence` inside `repeat_goes_on` went with it.
- The four openers of the repeat scope: `ops_interpret.repeat_scope` (and the import of `ops_core` it alone used), `Bridge.repeat_scope`, and the `with` items at `ops_say.say`, `ops_say.natural_needs`, `messaging_turn._read` and `ops_natural_writes.natural_write` (the other managers on those lines stay; `natural_needs` and `_read` lose their `with`). `ops_say.interpreter_on` and its re-export in `ops.py` had one reader, `Bridge.repeat_scope`, and went with it.
- The ten table keys only those functions read, in both language tables, in `natural_time.LISTS`/`GROUPS` and in the schema text: `problem_words`, `calendar_noun_reads`, `remind_nouns`, `triggers.reminders`, `triggers.reminders_bare`, `triggers.undo`, `triggers.note`, `forget.verbs`, `forget.id_words`, `forget.id_marked`. Before each deletion the readers were grepped on the head (`git grep` over `runtime`, `scripts`, `evals`, `providers`, `interface`, `shared`, `skills`, `contracts`, `docs/architecture`): the product has none left for any of them; the only other readers were two places of `test_registry_data.py` (the fuzz of private lines read `triggers.note` and `remind_nouns` to build its heads and pool), which now read the frozen words of the stand-in, so the fuzz is byte for byte the same. `forget.nouns`, `forget.fillers`, `triggers.remind`, `remind_anywhere` and `calendar*` have live readers and stay.
- Comments that named `candidate` (`turn_gate`, `natural_writes_calendar`, the contract and the README) now say "the old `natural.candidate`" or point at the guard. `ops_card_revise.py`'s comment names `natural_writes.candidate`, another function, and is untouched.

**Frozen, test-owned (`runtime/tests/old_claim.py`).** `candidate`, `_forget`, `_undo`, `_verb_noun` are copied there byte for byte but for the names of the helpers that stayed in `natural.py`, with the ten keys as literals per language (`FROZEN_WORDS`) laid over the live tables by `_frozen_tables` whatever they hold. On the PR head, before the deletion commit, the copy equals the product function on the 1,848 unique lines of `evals/interpreter/dev-relabelled.jsonl`, `tier1-cover-v1.jsonl` and `runtime/tests/entry_corpus.jsonl` (2,606 raw): 579 lines are named by `candidate`, 0 differences for `candidate`, `_forget`, `_undo` and `_verb_noun`, sha256 `b0f902f8bc3d0c7e4c11c0344c6ff7248006fd571cbaf7279fc68dcc097adc26` over the sorted JSON of every (line, `candidate`, (`_forget`, `_undo`, `_verb_noun`)). A planted change of one frozen word (the English `undo`) makes the copy differ, so the comparison can fail. `closed_heads.py` reads `old_claim.candidate`; the `repeat_goes_on` branches of `closed_heads.make` and of `old_claim.claim` are deleted (`claim` is now `candidate`).

**How to recompute the hash.** The comparison needs both functions, so it runs on the freeze commit of this branch (`ecf1b912` at the time of writing: the commit titled "the stand-ins freeze the old candidate reading", the parent of the deletion), where the product `candidate` and the frozen copy both exist. Save the script below as `equal.py` at the repository root of that checkout and run `python3 equal.py`; it prints the counts and the hash (rerun there on 2026-10-30: 2606 raw, 1848 unique, 579 hits, 0 differences, the sha256 above). The serialisation is `json.dumps([line, candidate, [forget, undo, verb_noun]], sort_keys=True, ensure_ascii=False)` encoded as UTF-8, one update per unique line in order of first appearance in the three files (dev-relabelled `line`, tier1-cover-v1 `line`, entry corpus `text`).

```python
"""One run: the frozen copy in old_claim equals the product functions on the unique lines of the three sets. Prints the count and a sha256 of the (line, result) pairs."""
import hashlib, json, sys
sys.path.insert(0, "runtime"); sys.path.insert(0, "runtime/tests")
import natural, natural_time as nt, old_claim
lines = []
for path, key in (("evals/interpreter/dev-relabelled.jsonl", "line"), ("evals/interpreter/tier1-cover-v1.jsonl", "line"), ("runtime/tests/entry_corpus.jsonl", "text")):
    for row in open(path, encoding="utf-8"):
        row = json.loads(row)
        value = row.get(key)
        if isinstance(value, str):
            lines.append(value)
uniq = list(dict.fromkeys(lines))
print("raw", len(lines), "unique", len(uniq))
tables = natural._tables(None)
frozen = old_claim._frozen_tables(None)
h = hashlib.sha256()
diff = 0
hits = 0
for line in uniq:
    a = natural.candidate(line)
    b = old_claim.candidate(line)
    norm = nt.normalise(line)[0]
    pa = (natural._forget(norm, tables), natural._undo(norm, tables), natural._verb_noun(norm, tables))
    pb = (old_claim._forget(norm, frozen), old_claim._undo(norm, frozen), old_claim._verb_noun(norm, frozen))
    if a != b or pa != pb:
        diff += 1
        print("DIFF", repr(line), a, b, pa, pb)
    hits += a is not None
    h.update(json.dumps([line, a, pa], sort_keys=True, ensure_ascii=False).encode())
print("candidate hits", hits, "differences", diff, "sha256", h.hexdigest())
sys.exit(1 if diff else 0)
```

**Left for 44-B (OPEN-CO-5).** The dead `eventorother` branch and the op branches of `messaging_remind.natural`/`remind.natural`, which only pre-states and stand-ins reach, stay as they are. The docstring of `messaging_remind.natural` that named `natural.candidate` is fixed (one line).

**T9, computed twice.** Statically: `git grep` of every deleted name and key in the tests gave 14 files (`test_repeat_goes_on.py` deleted, `test_natural_reminders.py`, `test_natural_review3.py`, `test_natural_review4.py`, `test_natural_table.py`, `test_natural_corpus.py`, `test_natural_dialogues.py`, `test_natural_writes.py`, `test_recurrence.py`, `test_ops_natural_writes.py`, `test_registry_data.py`, `test_calendar_list_words.py`, `test_natural_time.py`, `test_request_not_answer.py`). By running, before any test edit, the 255 test files that read a changed module or the public surface of `ops` (125 by the names, 102 more by the modules, 28 that scan the source; three runs, never the whole suite): 262 tests failed in 15 files, the 13 above plus `test_turn_gate_refresh.py` (its inventory of thread-locals listed `natural.py` for the repeat scope) and `test_operations_table.py` (`interpreter_on` was in its list of public functions that are not operations; the list is `runtime/tests/expected/cb-9.json`). The run found two files the static list missed, and `test_request_not_answer.py` (a planted-fault helper) passes without an edit but was re-pointed anyway.
- **delete** (the subject left the product): `test_repeat_goes_on.py` (5 tests); `test_natural_writes.py` (2 tests on the scope; the part that still holds, "the operation fixed by the interpreter reads a repeating line", is kept as one edited test); `test_recurrence.py` (6 params), `test_ops_natural_writes.py` (2) — all of them tested a stand-in-only behaviour (`closed_heads.make` reading `repeat_goes_on`); `test_natural_review3.py` (32 params: forget by number, undo, a scheduling verb without the word reminder), `test_natural_review4.py` (21: the forms of a reminder number, a bare forget, a forget by the hour), and the 104 parameters of the candidate table in `test_natural_reminders.py`; four constants of `natural_cases_pt_br.py` that only the deleted tests read.
- **re-target**: `test_natural_reminders.py` (the table of 104 lines is the guard's oracle now: 86 lines agree with `turn_gate.new_request` and the 18 that differ are pinned one by one with the guard's verdict, with a vacuity case), `test_natural_corpus.py` (4) and `test_natural_dialogues.py` (5) and `test_registry_data.py` (3) to `old_claim.candidate`/`FROZEN_WORDS`, `test_request_not_answer.py` (the planted `old_rule` ends in the `private_kind` check the product's `recognises` has).
- **edit**: `test_calendar_list_words.py` (12: the column of `natural.candidate` dropped), `test_natural_table.py` (53: `operation_of` and the candidate half of a test), `test_natural_review3.py` (4) and `test_natural_review4.py` (1), `test_natural_time.py` (5: the stub table without the ten keys, plus a new test that the keys are gone and that the schema refuses a table with one of a group), `test_turn_gate_refresh.py` and `expected/cb-9.json` (the inventory), `test_turn_order.py` (a stub method). `test_import_breakers.py`: the budgets drop by two edges, one call each (after the rebase onto 44-B 3a, which had set 81 calls, 65 edges and 12 debt: the file's own AST count on the rebased head is 79, 63 and 11) (natural to recurrence, a debt edge; ops_natural_writes to ops_interpret, a cycle edge).
- **A finding.** The assertion `found["op"] not in ("event-create",)` of `test_natural_table.py` (the lines that ask for work) could not fail: `candidate` returns `calendar-event-create`, never `event-create`. It is dropped, not re-pointed; the test's first assertion (`natural.match(line) is None`) is the one that held.

CPU-s from `--durations=0 --durations-min=0` on the base (6ca4affa) and on the head, same 17 files, 4 workers, through `scripts/test_slots.py`: the deleted tests cost 0.02 s (`test_repeat_goes_on.py`) + 0.43 s (`test_recurrence.py`) + 0.22 s (`test_ops_natural_writes.py`) + less than 0.01 s for the rest, about 0.7 s. The whole set of 17 files costs 67.98 s on the base and 75.74 s on the head (`test_registry_data.py` 14.4 to 19.5 s and `test_natural_dialogues.py` 12.7 to 15.5 s differ between runs more than the change can: the load of the machine was not the same). **No suite-wide saving is claimed**: the 28 s of `test_request_not_answer.py` and `test_natural_dialogues.py` survive as edits, and the 830 to 1,275 CPU-s of BACKLOG-LIVE are not within this package's reach; M41-2 measures the whole suite after it.

**Checks.** The entry replay is identical (every row), `test_import_breakers.py`, `test_runtime_rules.py` and the 254 files above that remain pass on the head (9,148 passed, 20 skipped, one run after the last edit); `python3 scripts/validate.py` has 0 errors and the measurement fingerprint is unchanged; no model call, no lab run.
