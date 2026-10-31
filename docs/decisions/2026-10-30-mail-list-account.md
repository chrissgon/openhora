## 2026-10-30: A list of mail with two accounts asks which one, and the choice is the OK (mail-list-account; limit L65)

**The requests.** The maintainer asked, on 2026-10-30, that a list of e-mails ask which account before it reads, and that each list of two accounts be plain to read. His rule for the package: whatever
is a request of the person, the model reads it, so that it works in any situation; code rules only where the input is fully predictable. So a button and an exact closed word are code, and a free
answer is read by the model and then checked by code against the project's accounts.

**The decision.** A list of mail in a project with two or more mail sources of a known account, and no account, source, count or word filter in the call, asks "I understood: list your e-mails. Which
account? Gmail, Outlook or all." in place of "Shall I go ahead?". The choice is the OK: "Posso?" and then "qual conta?" would be two steps for one read. The options are the project's catalog
(`ops_items.account_choices`), at most eight and "All", never a model's; the plan's hash also binds them (`plan_confirm.plan_sha256(choices=...)`), a plain plan's hash is the digest it always was,
and nothing is read before an answer. `plan_confirm.take` takes a `plan_ok` with a `choice` for a question plan and refuses one without it, and refuses a `choice` on a plain plan, leaving the plan.

**How the person answers.**
- A button of the question (one for each account and "All"), or a whole line code reads as one option (`plan_confirm.choice_of`): a number, the name or a service word of an account with at most one
  small lead word ("o outlook"), a form of `runtime/list_pick.py` ("o segundo"), or a word that names every account (`command_words.ALL_ACCOUNTS`, six languages). Zero model calls.
- A yes word names no option: the question is asked again with its buttons, nothing is read. A no drops the plan.
- A line in question form ("gmail?", "todas?", "1?") is no answer: it asks something and decides nothing, as `card_words.question_form` says for a card word. It is not a closed choice; it reaches the
  model as any free line (one model call), with the options as a `choice` item of the frame. The same holds for a yes in question form ("sim?"): since PLAN-QUESTION-FORM (#676) the bridge
  does not take it as the OK of any plan, so it is no "yes" here either; the model reads it, nothing is read, and the question is asked again if the model cannot place it.
- Any other line reaches the interpreter with the options as a `choice` frame item beside the plan's item (no prompt, catalog or protocol change: the newest enable entry stays in force). A model's
  `option` never runs the plan: code checks it against the options and states a NEW plan that names the account ("... from Outlook. Shall I go ahead?"), whose OK is the person's own yes. A model's
  `clarify`, or its yes on the plan's item, asks the question again. A model's no drops the plan; `route` and `none` are as before.
- The question not being the last message: a typed word decides nothing (`PLAN_NOT_LAST_ACCOUNT`, the plan waits); a button names its message and runs. On e-mail only a reply counts.
- A bare approve or reject word ("aprovo", "rejeito") while the account question is last or waits brings no decision card back: `Bridge.word_again` already leaves a line to the plan that waits
  (`plan_waits`); this package pins it.

**No question when** the line or the model named an account or a source, fewer than two mail sources with a known account, the call has `count` or a `match`, or more than eight accounts. A sender who
holds `confirm-reads-off` is never asked (the supervisor's decision, OPEN-2) and gets the lists at once. No `service` slot is added to `items` (OPEN-3: the catalog hash would change and the interpreter
would need a new enable entry and a sitting). A person's own name for an account ("the one at work") has nothing to match and is asked again (OPEN-4).

**The display.** A reply that holds two or more mail sources is one message: a blank line before each source after the first, and each name in bold (Markdown by contract; Telegram, WhatsApp and Discord
render it, e-mail shows it as written). A one-account list is byte for byte what it was. Not separate messages: L64's "last message" rule reads the last send. A target that is only the plain name of
the account the line names ("e-mails via outlook") is the account, not a word filter (`ops_items.without_named_account`).

**The numbers (N1).** After a reply that listed exactly one mail source with rows, in a project with two or more, the sender's NEXT line within 600 s that writes a number and names no account means that
source, while its newest version is the version listed. `mail-read` binds `message=<source>#<n>` into the plan before "Posso?", so the hash binds it; a write ("arquiva o 3") gets the source in
`ops_natural_mail._messages`. After "All" the which-box question stays; on the second line the memory is gone. Memory only (`item_refs`): the project, the sender, a source id, a version, a clock and
a counter; no text, no number.

**Golden.** No row of the entry golden changes (no replay world has two mail sources), so there was nothing to re-record. The replay is blind to this package; the new test files are its proof.

**Cost.** A button or an exact closed word: 1 model call for the request and 0 for the answer. A free answer the model places: 1 + 1, about USD 0.0017 at the pooled median of M41-5 (about USD 0.00086 a
line). The new frame was not measured (OPEN-1, shipped without it): a wrong reading only states a plan that names the account and waits for the person's yes.

**Alternatives rejected.** Two steps ("Posso?" then "qual conta?"); a `service` slot on `items` (a catalog change); separate messages for each source (they would add risk to L64's last-message rule);
a number across the sources of "All" (numbers stay the snapshot's own).
