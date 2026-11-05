## 2026-11-02: A request whose tasks all ended cancelled by a rejected effect is cancelled (M41-3 P1 store-ends-rejected, finding 1 of SPEC-M41-3-FIXES; no model call, no provider call, no lab run, fingerprint unchanged)

**What happened.** In the phone test of 2026-11-02 every card the person turned down, and every card a revision replaced, left its request `planned` for ever. The card is an `effect` decision resolved `rejected`, its step task is `cancelled`, and `_refresh` in `providers/store/sqlite.py` completed a planned request only when all its tasks were `done`. In the project that was read, 19 requests were open in that shape (13 before the test, 19 after), and each revision leaked one more, so `/status` counted them.

**Decision.** `_refresh` gets a second rule beside the `done` rule: a planned request whose tasks are all `cancelled`, at least one of them by an `effect` decision resolved `rejected`, becomes `cancelled`. `cancelled` and not `done`, because nothing was done, and it is what the store already uses for a request the person turned down (plan, acceptance, question, `/cancel`). A cancelled task is final, so the request could never move again. It is not listed as `completed`, which keeps its meaning "done". A request whose only task was stopped by `task_stop` has no rejected effect and stays as it is (R18: a stop ends one running task and nothing else). Tests: `providers/store/tests/test_sqlite_reject_ends_request.py` and `runtime/tests/test_card_revise_ends_request.py`. Docs: the effect row of `contracts/runtime.md` and of `docs/architecture/platform/runtime.md`, and the docstrings of `_refresh` and `pending_resolve`.

**Maintainer's answers, 2026-11-02.**
- OPEN-1, heal the existing rows: **yes, heal**. Because `_refresh` runs in every resolving transaction, the rule also ends the leaked requests of a project at its next resolution, approval, cancel or task end. No migration, no schema bump, no command. The time of the change is "whenever the next resolution happens", not at deploy.
- OPEN-2, a request with a `done` task and a task cancelled by a rejected effect: **leave it as it is today** (`planned`). No such row exists; it is decided when a real case appears. A test pins it.

**Alternatives rejected.** Forward only, in the effect branch of `pending_resolve` (the person cancels the old ones one by one with `/cancel`, 19 commands here); a maintenance command or a migration.

**Limits.** No path here sends, writes or approves anything (L55): the rule only moves a request row that no task can move any more.

**Not verified.** No live run of the heal on the store of that project (it was only read). Whether the page or the board shows anything special for these requests today.
