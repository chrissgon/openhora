## 2026-11-28: A first-time recipient on the card of an e-mail, and a default name in the recipient question (EM6, P5B-MAIL-ASK-TO-EMPTY)

**What.** Two small changes to the e-mail of the person's own account (chrissgon/openhora#891 and chrissgon/openhora#972).

1. **EM6.** The card of a new e-mail names the recipients the person has never written to or heard from: one line, `CARD_MAIL_FIRST_TIME`, after the Cc and Bcc lines and before the subject. A reply has none (it goes to a sender, who is known by construction).
2. **P5B-MAIL-ASK-TO-EMPTY.** The question `NW_MAIL_ASK_TO` keeps its forms; when the person named no one, the question is the whole sentence `NW_MAIL_ASK_TO_UNNAMED` ("What is the e-mail address of the recipient?"; pt-BR, the maintainer's own words, "quem vai receber") with no field, so that no translated text is stored in a field and the question reads whole in whatever language it is shown. No separate name question is asked. The maintainer's decision is W0-D6 in `docs/decisions/2026-11-28-w0-decisions-backlog-wave-0.md` (answer 16, revised).

**The record of correspondents.** An address is known when it is a sender or a Reply-To of the newest snapshot of any registered mail source, or a recipient of an e-mail this runtime sent: the `send-email` decisions that landed among the newest 500 approved effect decisions (one bounded query, `pending_effects_resolved`), read from their effect files and each checked against the hash the person approved. It is computed in memory for each card and stored nowhere, so no new file holds addresses. Comparison ignores case.

**The completeness rule.** A partial record would flag people the person does write to, so when the record cannot be complete there is no line: no registered mail source, a snapshot older than 26 hours, with no index or changed outside the runtime, or any error. One stale mail source therefore removes the line for every address, and a missing line is not proof that an address is known. The flag is advice and never stops a card.

**Limits.** The record knows only mail seen through the platform's own snapshots and sends. It does not know the person's whole mailbox history, mail written from other clients or the Sent folder, or a sent e-mail whose effect file retention removed, so the line can be shown for an address written to long ago. That is a false "first time", which costs a person one extra look, never a wrong send.

**Why it is safe.** The approved hash is the document's hash and does not change; the document gains no key; the card and the stored body are built from the same list in one place. The line adds and chooses no recipient (limit L60). It is a private line, shown only to a reader who may see the recipients. The outbox e-mail (a document with no `account`) has no card and no line.

**Wording awaiting the maintainer's approval (a proposal, not decided).** `CARD_MAIL_FIRST_TIME`: pt-BR "Primeira vez que você escreve para: {addresses}" (validate: allow english-only -- the proposed sentence under review), English "First time you write to: {addresses}". The pt-BR sentence has not been approved; it ships as the proposal, and a different wording is a new entry that names this file.

**Not done.** A flag on the card of a mailbox draft; a separate question for the recipient's name; a stored file of correspondents; any change to how a recipient is chosen.
