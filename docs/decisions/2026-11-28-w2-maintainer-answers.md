## 2026-11-28: The maintainer's answers to the open choices of wave 2 (w2-answers; EM6, AT2, I2, L66)

**Status.** Answered by the maintainer in chat on 2026-11-28, one question at a time, before the batch of wave 2 merged into `main`. This entry records the answers. Earlier entries are never edited: where an answer replaces a choice, it names the entry and the package that does the work. The maintainer's words are translated from Portuguese.

## EM6: the first-time line on a card

**Approved as proposed.** A card for an e-mail from the person's own account to an address the account has never written to carries `CARD_MAIL_FIRST_TIME`: "First time you write to: {addresses}" (Portuguese: "Primeira vez que voce escreve para: {addresses}", accented in the phrase table).

## AT2: files by e-mail (`docs/decisions/2026-11-28-at2-files-by-email.md`)

- **D1, one mebibyte in all: kept for now.** Raising the read bound alone would let any sender whose domain passes DMARC make the provider read a large message before any check. The maintainer asked that the larger limit be a high-priority backlog item: AT4, chrissgon/openhora#1025 (read the structure, check the sender, then fetch the one file part).
- **D2, a message over 1 MiB dropped with no answer: replaced.** The maintainer: "It must tell me; otherwise I will think the e-mail went through when it did not." Package AT2b of wave 2 sends the senders who hear the count a fixed too-large sentence (`docs/decisions/2026-11-28-at2b-too-large-notice.md`).
- **D3, no file on a forward: replaced, later.** After the forward rule was explained (a forwarded message is never a request, so its body is not read), the maintainer chose that the files of a forwarded e-mail be offered with the usual save card. Not in wave 2: AT5, chrissgon/openhora#1026. Until it lands, AT2's behaviour stands.

## I2: imported skills in the runtime (`docs/decisions/2026-11-28-i2-imported-skill-runtime.md`)

- **Assumption 1, a local test of the current content only: approved.** An edit after the test needs a new test before the skill runs again.
- **Assumption 2, no web for an imported skill: approved for now.** The maintainer then asked that the person be able to allow the web for one imported skill, with the risk of a leak stated plainly because the skill is not official, "only in the backlog as a future possibility, with no urgency": I7, chrissgon/openhora#1027.
- **Assumption 3, the planning agent owns every imported task: replaced.** The maintainer: "When a skill is imported, we must be able to associate it with an area", built now, in wave 2: package I2b (`docs/decisions/2026-11-28-i2b-imported-skill-area.md`).

## L66: the two citations of a limit never written

**Approved.** The batch of wave 2 pointed both citations of `L66` in `contracts/runtime.md` (reserved for FWD-REF, cut on 2026-10-27, never written) at L48, which already covers a held file. The number L66 stays unused and is never reused.

## What is still the maintainer's

The steps of T47 that only the maintainer runs before the merge (cancel the old jobs, `--check` the Google accounts, `scripts/rename_move.py` per project, reschedule, `keyring del` of the old entries), and the merge of the batch into `main`.
