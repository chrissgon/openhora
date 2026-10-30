## 2026-10-30: CARD-FALSE-REFUSAL: an open event card no longer answers "no permission" to a request the person did not make (0 model calls added; no prompt, no measurement, fingerprint unchanged)

**The rule.** On the card of an event that waits, when the interpreter's decision is `refuse_policy` (the model named an operation the sender may not ask, from another op or from a `clarify` with fewer than two allowed ops) and the line names no other object (`event_lookup.names_other_object`: mail, file, reminder, routine, task, folder, request, an address), `runtime/ops_event_revise.py` `revise` answers `EV_CHANGE_WHAT` and sends the old card again. Nothing is remembered and nothing is refused. When the line names another object, nothing changes: the decision is kept (`base.remember`), the line goes on and `PHONE_NOT_ALLOWED` is said, which is true of that request.

**Why.** The maintainer's report of 2026-10-30: `Mude o titulo para: Corte de Cabelo com Matheus` on an open event card was answered with the sentence that the sender has no permission for that. The model had read an operation (for example `todo-add`) that the person never asked for, so the refusal was false. (validate: allow english-only -- the line under test)

**What a person reads now**, for the reported line and one simulated answer each (0 real calls; simulated through the real bridge): `event-change` opens the revised card; `todo-add`, `mail-read` and `routine-create` give "I found the event, but not what to change. Tell me the new day and time, or the new name." with the old card sent again and nothing remembered; `route` and `none` pass on, the decision kept, as before.

**The cost, accepted.** A true request with no object word from a sender without its group ("comprar leite amanha" read as `todo-add`) hears "what to change?" instead of "no permission". A wrong question, never a false statement. `names_other_object` reads six languages and only picks the sentence. (validate: allow english-only -- the line under test)

**Out of scope.** The mail card and the sentence card: the mail call's prompt has no operation vocabulary, so it cannot give `refuse_policy`, and `RV_NOT_REVISABLE` calls no model. The title itself is read from the card only after the model sees the card (Part B, a separate pull request waiting on the maintainer's decision on the measurement).

**Measured.** 0 model calls, 0 lab runs. Tests: `runtime/tests/test_event_revise_flow.py` (the refusal asks what to change from an op and from a clarify; a line that names an object is still refused; a vacuity case that plants `names_other_object` returning true). Golden: 0 existing rows change; two rows in the package `runtime/tests/entry_ext/card-false-refusal.scenarios.jsonl` (`card-false-refusal.other-op.01`, `card-false-refusal.other-object.01`).

**Not verified.** Any real model's answer on the reported line; the phone end to end.
