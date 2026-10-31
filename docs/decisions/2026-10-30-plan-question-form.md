## 2026-10-30: PLAN-QUESTION-FORM: a line in question form is neither the OK nor the refusal of a plan (limit L65; 0 model calls, 0 lab runs, fingerprint unchanged)

**Decision (the maintainer, 2026-10-30).** After ACEITE-37 made `card_words.question_form` the rule for cards (a question glyph anywhere, or the leads "can you", "could you", "would you", "poderia", "consegue"), the same rule holds for the "Posso?" of a plan. "sim?" on a "Posso?" that is the last message no longer starts the confirmed call, and by the same rule "nao?" on it no longer takes the no-word path: both go on to the model as any free line. "sim", "sim!", "sim.", "nao", the Yes and No buttons and everything else stay as they were. Stopping a search with "nao?" (`research-run`) stays exactly as it was. The card paths are not touched.

**Readers of `natural.confirm_kind`, and the answer of each to a question form.**

| Reader | Answer to a question form |
|---|---|
| `messaging_turn.plan_confirm_applies` (the kind `plan-confirm`) | None: no OK and no refusal. Changed here, one new guard after the greeting guard. |
| `ops_turn._bare_plan_kind` (the row `plan-bare-word`, and the claim `_bare_plan_word`) | None for a yes as well as a no. Changed here. |
| `messaging_turn.research_run_applies` (the kind `research-run`) | Unchanged: "nao?" still stops a running search; with none running it goes on. |
| `natural_writes_mail`, `ops_natural_writes`, `interpreter` (`confirm_kind` of a draft answer, the plain no) | Unchanged: they read the word as before; this decision is about the plan of L65. |
| `interpreter_pipeline` (measurement only) | Unchanged. |

`natural.confirm_kind` itself is not changed.

**A fact that moved.** The brief expected `ops_turn._bare_plan_kind` to keep giving `PLAN_NOT_LAST` to "sim?" when the plan is not last. That row is also what a "sim?" meets when the bridge declined it on a plan that IS last (the row cannot tell the two apart), and it answered "To confirm, reply yes to the question ..." without the model. Left alone, "sim?" on a last plan would not have gone to the model. So the row reads the rule too: a "sim?" is never told `PLAN_NOT_LAST`, on a last plan or not; it goes on to the model, and the existing rule stands, that any other line ends a waiting plan. A plain "sim" on a plan that is not last still gets `PLAN_NOT_LAST` and keeps the plan. L65 says so in one sentence.

**Test that changed.** `test_messaging_plan_greeting.py` listed "tudo bem? sim" among the yes words of a last plan. It holds a question glyph, so by the rule it is a question form and no OK; it left that list and joined the new tests. The vacuity case of the greeting rule also switches the question rule off, since two rules now keep that line away.

**Golden.** Zero existing rows changed; 20 rows added in `runtime/tests/entry_ext/plan-question-form.*` (a last plan and a plan that is not last, with question forms, plain forms and a reply).

**Docs.** L65 (`contracts/runtime.md`, one sentence and the "In code" list), `runtime/README.md` and `docs/architecture/platform/messaging.md`. The generated copy of L65 in `docs/architecture/platform/runtime.md` follows from the batch keeper.
