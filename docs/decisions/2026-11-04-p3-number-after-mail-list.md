## 2026-11-04: A bare number counts as a message number on the first line after a mail list, never without a list (P3 of SPEC-ACEITE-FIX-READING, OPEN-4; no prompt change, no catalog change, no model call, no provider call, no lab run, fingerprint unchanged)

**What happened.** In the acceptance run of 2026-11-04 (row 5) the person saw a list of e-mails and wrote "arquiva o 3". The interpreter read `mail-archive` with message 3, but `mail_number_seed` took the model's number only when `natural_writes_mail.free_numbers` found it as a message number: `#n`, or right after a mail noun. "o 3" has an article and no noun, so the numbers differed and the phone said IX_CANNOT_WRITE. Code ignored that a mail list was on the screen.

**The maintainer's answer to OPEN-4 (2026-11-04).** The recommendation was taken: the article form ("o 3", "the 3") and a bare number count only on the first line after a mail list; never without a list on screen.

**What changed.**

- `item_refs.remember_listed` takes `mail_shown`; `ops_items.remember_listed` passes it when the reply listed mail with rows (one source or several, so two boxes count too). It is kept apart from the single-source record of N1 (`_LISTED`), which keeps its rules. `item_refs.mail_list_on_screen(ctx, channel, sender)` is true on the first line after such a reply, inside `LISTED_S` (600 s), on a messaging app.
- `natural_writes_mail.free_numbers` takes `after_list=False`. When True, a number after `o`, `a`, `os`, `as` or `the`, or the second word of the line (right after the verb), also counts. Every other refusal is unchanged: ranges, times, clocks, units, currency, the texts of spans, a number with neither an article nor a place after the verb ("arquiva o 5, recebi 3 dias atrás" gives [5], never [3, 5]).
- `ops_natural_mail.mail_number_seed` takes optional `ctx`, `channel`, `sender` and passes `after_list`; without `ctx` it is the old rule. `ops_interpret._carry_out` passes them at its one call. With two mail boxes holding the number, the family asks the existing "De qual caixa?".

**Alternatives rejected.** A thread-local flag set by `begin_turn` (hidden state, fragile if a turn moves threads); the article form with no list (a number in a line with no list on screen means nothing, principle 13: the stricter rule stays); a longer window than the one `listed_source` uses.

**What does not change.** The measured mirror `interpreter_pipeline._numbers_step` keeps the default, so the harness hash does not move; no prompt, no catalog, no pinned text; the entry in force in `runtime/interpreter_enable.json` stays. The golden replay keeps its rows (no scenario holds a mail list followed by a bare number).
