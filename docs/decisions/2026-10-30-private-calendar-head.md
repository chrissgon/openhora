## 2026-10-30: PRIVATE-CALENDAR-HEAD: a calendar head with a time is a private write (data only; no model call, no provider call, no lab run, fingerprint unchanged)

**The rule.** `turn_gate.private_kind` reads a line that starts with a calendar head and holds a time as a private `"write"`. The heads are data (`runtime/registry/private_words.json`, `lead_with_time` of each language): English `book`, `schedule`; Portuguese `agendar`, `agende`, beside the `marca`, `marcar`, `marque` that S41-9 already held. They are exactly the calendar verbs and loose calendar verbs of each language table, which `new_request` already read as a write. The time reader is unchanged: any `natural_time.find` hit counts, a day alone included (OPEN-PCH-1, the supervisor by recommendation), as it does for "marca". No `.py` product file changed.

**Why.** The private detector was the one reader that did not read these heads as a calendar write: "Agende corte de cabelo amanhã às 14h" and "schedule a haircut tomorrow at 2pm" had verdict `None`, because `agende`, `agendar`, `book` and `schedule` are work starters, so the bare-reminder step stopped at them. The line was then stored as written, kept in the router's memory and, for a sender the interpreter does not read, routed to the planning agent instead of getting `IX_TYPE_WRITE`. The change only widens what is private (limits L51 and L61): no line becomes less private, and nothing opens a card, executes or approves. (validate: allow english-only -- the Portuguese line under test)

**Measured (0 model calls).** Over the 3,435 unique lines of the entry corpus and its `entry_ext` scenarios, the reply-guard lines, every `evals/interpreter` set and the three natural corpora: 11 lines change their `private_kind` verdict, all `None` to `"write"`, and 0 change their `new_request` verdict, so the reply-guard bars do not move. The entry replay is identical (the stored row of `guard.card_words.27` is already `IX_PRIVATE_LINE`). The 11 lines, each a calendar create:

1. `Agende corte de cabelo amanhã às 14h` (validate: allow english-only -- the Portuguese line under test)
2. `agende o fisioterapeuta sexta 9h`
3. `agendar consulta com a dra. Helena dia 22 às 16h`
4. `book an appointment with Dr. Helena on the 22nd at 4pm`
5. `book the dentist friday at 9am`
6. `schedule a meeting with Marta tomorrow at 2pm`
7. `book dinner with Tobias on friday at 7pm`
8. `schedule piano practice every day at 6pm`
9. `book lunch with Priya wednesday 8am on Outlook`
10. `book lunch with priya wednesday 8am on outlook`
11. `schedule Atlas project handoff for wednesday 8am`

**The cost, accepted.** Work requests that start with a head and a time are private writes too: "schedule a post for tomorrow at 9am", "schedule the newsletter for friday at 10am", "agende a publicação do post amanhã às 9h", "agendar o envio da campanha segunda 8h", "schedule a deploy for tonight at 11pm", "book club tomorrow at 7pm". A sender the interpreter does not read gets `IX_TYPE_WRITE` where the line went to the planning agent; for an `interpret` sender a model `route` becomes `clarify private-route`; in an outage the line gets `IX_OUTAGE`; the page and the terminal store the neutral word. A date-only English read where "schedule" is a noun ("schedule for tomorrow") also becomes private. The Portuguese "marca o post para sexta 10h" has had this cost since S41-9. Reads are not touched: "my schedule tomorrow", "what's on my calendar tomorrow at 2pm?", "scheduled posts for tomorrow at 9am?", "agendamento amanhã 14h". (validate: allow english-only -- the Portuguese line under test)

**Acceptance.** OPEN-PCH-2: the maintainer accepted the 11 newly private lines and the over-fire class on 2026-10-30. His words: "Aceito (Recomendado)". The two of the 11 that are lines of a `NO_NEW` corpus are listed as `ACCEPTED_NEW` in `runtime/tests/test_registry_data.py`, with a test that keeps each in its corpus and private; the 11 and the over-fire class are pinned in `runtime/tests/test_private_calendar_head.py`.

**Not done (OPEN-PCH-3).** GUARD-BARE-AGENDA does not join: pt-BR "agenda" is not added to `lead_with_time`. It would make 18 corpus lines change `private_kind` and 7 change `new_request`, turn reads such as "agenda de amanhã" into writes and change one golden row. "agenda X <day> <time>" is already private through the bare-reminder step. (validate: allow english-only -- the Portuguese line under test)

**Alternative rejected (OPEN-PCH-1).** A time that must be a clock or a relative time (a new key `lead_with_clock`, code in `turn_gate` and `registry_data`) would keep all 11 lines and drop "schedule for tomorrow" and "book a flight to Lisbon on friday", but "agende corte de cabelo amanhã" (a day, no clock) would stay unflagged, and it needs code; wider is the safe side. (validate: allow english-only -- the Portuguese line under test)

**Not verified.** Lines of es, fr, de and it that start with `book` or `schedule` (the steps are merged across languages; none in the corpora); the over-fire rate in real use (the corpora hold no work line that starts with a head and a time).
