## 2026-11-04: the notes of a mail summary stop flagging what code wrote and what the message holds (AF-4 `MAIL-ASK-NOTES`, SPEC-ACEITE-FIX-CODE; no model call, no lab run, fingerprint unchanged)

**The decision.** Two notes of a correct mail summary (row 4 of the acceptance run of 2026-11-04) are narrowed. Nothing is blocked either way; both are warnings.

- **The "Confira: ..." note (`MA_NUMBER_CHECK`).** `ops_mail_ask._after` now looks for the digit runs of the prose in the message's own words plus the `Received: <when>` line, which `_copy_text` writes into the model's copy. A prose that gives the time the message arrived is no longer flagged on its minutes. A number in neither place is still flagged. The quote check (`_verify`) is unchanged and still reads the message's own words only.
- **The "unknown source" note (`UNKNOWN_SOURCE`).** In `ask_reply.check`, with a `read_label` and one source, a `[x]` of the prose that the copy of that source holds (compared in lower case, with its brackets) is not an unknown source: no note, no flag. Without a `read_label`, and with several sources, the output is byte for byte as before.

**OPEN answers used.** OPEN-4: the recommendation. A `[x]` that is not in the copy keeps its note, since the note is a model-invention signal and dropping it would hide one. The case of an invented bracket is left until a run shows it.

**What does not change.** No approval check, card hash, phrase or phrase snapshot. `MA_NUMBER_CHECK` and `UNKNOWN_SOURCE` keep their words. The golden replay keeps its rows.
