# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""A notice as a platform-neutral card (runtime/messaging.py): a pending decision becomes {"text", "actions", "link",
"document"}, the message every messenger provider takes (providers/messenger/README.md), plus what the bridge needs to
bind a tap to it. Pure: it reads the decision, the capabilities the provider declared and the project's settings, and
calls nothing.

  header   `<project name> · <kind> #<id>`
  body     with notices "text": the decision's own text (title, then body), cut to fit with "(continues on the page)", or,
           when the platform takes documents, a short body and the whole text as a document; with notices "count":
           "A <kind> waits for you." and nothing of the project's text
  footer   (only for a platform that declares `actions_need_reply`) the lines the card ends with, as a list, beside `text`, which still
           ends with them: the e-mail provider moves them up under the first line and must never guess where they start
  actions  one for each resolution word of the decision whose operation the channel's policy permits
           (operations.permitted, decision M-8): approved and accepted are `approve`, rejected `reject`, released
           `release`. An effect is offered an approval only when ALL of these hold (POL-1; each one is code, none is a prompt):
           the accepted policy grants the messaging channel the effect's word (`approve-effect-<word>`), the notices carry
           text, the decision says the whole effect can be on a card (`effect_on_cards`: not an e-mail with an attachment, not a
           post with an image), and the card carried the whole text (the body uncut, or the whole text as the attached
           document). Otherwise its card says to approve it on the platform's page (no command and no hash: a phone has no terminal, limit L62) and, when only the
           length stops it, the line "Too long to approve here". The result carries `whole`, which the bridge records in the
           ledger: an approval is taken only from a card that says it was whole. A question is answered by replying to its card (when
           the policy permits `answer` and the platform keeps reply context). What the platform cannot draw as a button (no buttons,
           or more actions than it shows) becomes a typed line, "Send /approve 12". What the policy refuses is neither drawn nor
           offered as a line: the card says "Act on it on the platform's page."
  sender   (POL-2) the card is drawn for one sender, and what it offers is what THAT sender's profile permits: the owner's card of a plan has
           Approve and Reject, an employee's card of the same plan, whose profile lists neither, has no button; the result says whether the card
           offers its sender anything to act on or answer (`actionable`), which a profile with `notices: actionable` is sent a card for
  language (LR-1) the frames a card adds around the decision's text (the labels, the cut and whole notes, the "Send /approve 12" lines, "Act on it on the platform's page.") and
           the kind of the decision as a word are the phrase table's (runtime/phrases.py) in the language of the `cfg` handed to `build`; the decision's own text, the
           commands and the ids are never changed
  card     (FND) an effect of a write to the person's own accounts stores, beside its English body, `payload["card"]`: its lines as [key, {field: text}] of
           the phrase table's family CARD_. `build` says them line by line in the language when the card is well formed and its English lines are the stored body
           (`effect_card_text`); the hash on the card is the effect's own (`content_sha256`) in every language, and the fields are never translated

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import attachments  # noqa: E402  (the held file a card is drawn for)
import phrases  # noqa: E402  (the same folder: the sentences of a card, in the project's language)
import messaging_pending as pending_view  # noqa: E402  (what a question says in a list and on a card)

CHANNEL = "messaging"
LEDGER_LINE = re.compile(r"^(Ledger \(the publisher's record of the keys it published\)): /[^\n]+$", re.M)      # the platform's own frame line (publish_document): the publisher's ledger file by its path on this machine
APPROVE_FRAME = re.compile(r"^Approve exactly this: python3 runtime/cli\.py approve --project <project> [^\n]*$\n?", re.M)      # the platform's own how-to line of a stored body (command_line("approve", "<project>", ...))
WORD_OPERATION = {"approved": "approve", "accepted": "approve", "rejected": "reject", "released": "release"}
# The English frames of a card, kept under their old names; the phrase table (runtime/phrases.py) is their source and `build` says them in the language of
# the `cfg` it is given (the project's settings: anything that maps `language`), package LR-1.
LABELS = {"approve": phrases.en("LABEL_APPROVE"), "reject": phrases.en("LABEL_REJECT"), "release": phrases.en("LABEL_RELEASE")}
ORDER = ("approve", "release", "reject")
CUT = phrases.en("CUT")
WHOLE = phrases.en("WHOLE")
WHOLE_ABOVE = phrases.en("WHOLE_ABOVE")
DOCUMENT_NOTE = phrases.en("DOCUMENT_NOTE")
DOCUMENT_LINE = phrases.en("DOCUMENT_LINE")
PAGE_LINE = phrases.en("PAGE_LINE")
REPLY_LINE = phrases.en("REPLY_LINE")
EFFECT_LINE = phrases.en("EFFECT_LINE")
TOO_LONG_LINE = phrases.en("TOO_LONG_LINE")
APPROVES_LINE = phrases.en("APPROVES_LINE")
EFFECT_LABEL = phrases.en("EFFECT_LABEL")
MORE_LINE = phrases.en("MORE_LINE")
PAGE_LABEL = phrases.en("PAGE_LABEL")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def decision_text(item: dict) -> str:
    """The decision's own text: its title, then its body."""
    title, body = (item.get("title") or "").strip(), (item.get("body") or "").strip()
    return f"{title}\n\n{body}" if title and body else title or body


def router_asks(item: dict) -> bool:
    """Whether the decision is the question the router asked about a request (ops_requests._route_run writes it whole: the kind `question`, the title "The router asks"
    and the ending `question`). A card shows such a question as the question alone (phrases.asked_view); a task's question, whose title names its skill, is shown whole."""
    return phrases.is_router_question(item)      # the one test, shared with the conversation's reply (ops_say), so that the reply and the card stay in lockstep


def content_sha256(item: dict) -> str:
    """What a card is bound to: a plan's hash, an effect's payload hash, else the sha256 of the decision's text."""
    if item["kind"] == "plan":
        stated = (item.get("payload") or {}).get("plan_sha256")
        if isinstance(stated, str) and stated:
            return stated
    if item["kind"] == "effect" and item.get("payload_sha256"):
        return item["payload_sha256"]
    return sha256_text(decision_text(item))


def header_of(project_name: str, item: dict, cfg=None) -> str:
    return phrases.text("HEADER", cfg, project=project_name, kind=phrases.kind_word(item["kind"], cfg), id=item["id"])


def typed(op: str, pending_id: int) -> str:
    return f"/{op} {pending_id}"


def _cut(text: str, room: int, note: str) -> str:
    if len(text) <= room:
        return text
    keep = max(0, room - len(note) - 1)
    return text[:keep].rstrip() + "\n" + note


def effect_kind(item: dict) -> str:
    """The kind of `approve` the policy is asked about for an effect decision: `effect:<word>`, or `effect` when the word is not known."""
    word = item.get("effect_word")
    return "effect:" + word if isinstance(word, str) and word else "effect"


def gated(item: dict) -> bool:
    """Whether the approval of this decision needs a card that carried its whole text: an effect, and a plan that holds a step reaching the
    network (the destinations must have been shown). A plan that does not, and an acceptance, are approved as they always were."""
    return item["kind"] == "effect" or (item["kind"] == "plan" and item.get("plan_networked") is True)


def reads_private(policy, sender, operations) -> bool:
    """Whether the sender may be shown the current text of the person's own items on a card (the lines of phrases.CARD_PRIVATE): only a sender who holds the group
    `ask-mail` (the answer from mail and calendar). No sender, or a policy with no entry, is not."""
    try:
        groups = operations.effective_groups(CHANNEL, policy, sender)
    except Exception:      # a policy this function cannot read shows nothing private
        return False
    return bool(sender) and bool(groups) and phrases.CARD_PRIVATE_GROUP in groups


def private_groups(policy, sender, operations) -> frozenset:
    """The groups of phrases.PRIVATE_GROUPS the sender holds (the groups that show a private line: `ask-mail` for the e-mail and calendar lines, `tasks-read` for the title of a task
    the service holds now); none for no sender, no entry or a policy this function cannot read."""
    try:
        groups = operations.effective_groups(CHANNEL, policy, sender)
    except Exception:      # a policy this function cannot read shows nothing private
        return frozenset()
    return frozenset(g for g in phrases.PRIVATE_GROUPS if g in groups) if sender and groups else frozenset()


PHONE_DROPPED = ("CARD_MAIL_HASH", "CARD_FILE_HASH")      # the hash line of a card: a command's argument, which a phone does not type (the button binds to the hash the ledger recorded)
# What a phone does not show of a card (slice S16c): the internals the page and the terminal keep. A raw id of an event, the name of a snapshot and the time it was read, the version of an
# event or of a file, the id of a message, the path of a file on this machine and a file's hash are for the one who checks a card in the terminal; the card's hash and its effect document
# are untouched, and the lines that carry the person's data (account, calendar, title, the time now and the time after, reminder, where a removed event goes) stay.
# A line that names the TARGET of the card is never dropped (review of #544): the source of a file to replace (the person's own label of it) stays, and so does the message a reply answers
# (by its number in the person's list, its sender and its subject); what goes is an id, a version, a read time or a reference only code can use. A test builds two cards that differ only in
# their target for each kind of card and asserts that the phone texts differ.
PHONE_DROPPED += ("CARD_CAL_EVENT", "CARD_CAL_SNAPSHOT", "CARD_CAL_BASE", "CARD_MAIL_IN_REPLY", "CARD_BOX_SNAPSHOT")
PHONE_LINE = {"CARD_FILE_SAVE": "PHONE_FILE_SAVE",      # the save line without the file's short hash
              "CARD_CAL_CHANGE": "PHONE_CAL_CHANGE", "CARD_CAL_DROP_WHERE": "PHONE_CAL_DROP_WHERE", "CARD_CAL_DROP_NOTES": "PHONE_CAL_DROP_NOTES",
              "CARD_MAIL_REPLY_TO": "PHONE_MAIL_REPLY_TO", "CARD_MAIL_REPLY_TO_AT": "PHONE_MAIL_REPLY_TO_AT", "CARD_MAIL_ATTACHMENT": "PHONE_MAIL_ATTACHMENT", "CARD_BOX_READ_AT": "PHONE_BOX_READ_AT",
              "CARD_BOX_DRAFT_REPLY": "PHONE_BOX_DRAFT_REPLY", "CARD_FILE_CODE_REPLACE": "PHONE_FILE_CODE_REPLACE", "CARD_FILE_CODE_TRASH": "PHONE_FILE_CODE_TRASH",
              "CARD_FILE_PROJECT": "PHONE_FILE_PROJECT", "CARD_FILE_BASE": "PHONE_FILE_BASE"}
PHONE_DUPLICATE = {"CARD_CAL_NOW_WHEN": ("CARD_CAL_WHEN",), "CARD_CAL_NOW_TITLE": ("CARD_CAL_DROP_TITLE",)}      # a removal says the event twice (as it is now, and as what is removed): the phone says it once


REFERENCE = re.compile(r"([a-z0-9][a-z0-9-]{0,39})#([0-9]{1,4})")      # the shape of a message reference `<source id>#<n>` (runtime/item_refs.py ITEM_REF: a test holds the two equal; the layer diagram gives this module no edge to it)
PHONE_REF_LINES = ("PHONE_MAIL_REPLY_TO", "PHONE_MAIL_REPLY_TO_AT")      # the phone lines whose `ref` field is a message reference `<source id>#<n>`


def _named_ref(line: list, cfg) -> list:
    """BL5D: the phone line of a reply with its `ref` ("caixa-gmail#3") said by the plain name of the source ("3 do Gmail"), when `cfg["source_names"]` ({source id: name}, which the
    bridge hands to every card) knows the source and the whole field is a reference; any other line, field or source is returned as it is. A copy of the line's fields: the stored card, whose
    hash is the approval's (L55, L56), is never touched. Two cards that differ only in their target still read differently (S16c): the names of one project are unique."""
    names = cfg.get("source_names") if isinstance(cfg, dict) else None
    key, fields = line[0], line[1]
    if not names or key not in PHONE_REF_LINES or not isinstance(fields, dict) or not isinstance(fields.get("ref"), str):
        return line
    found = REFERENCE.fullmatch(fields["ref"])
    if not found or found.group(1) not in names:
        return line
    return [key, {**fields, "ref": phrases.text("SRC_ITEM_CARD", cfg, name=names[found.group(1)], n=int(found.group(2)))}]


def effect_card_text(item: dict, cfg=None, private: bool = True, owner: bool = False, approvable: bool = True):
    """The body of an `effect` decision said line by line in the project's language, or None. An effect of an account write (package FND) stores, beside
    its English body, its `card`: a list of [key, {field: text}] lines of the phrase table's family CARD_ (runtime/phrases.py card_valid). The lines are
    said in the language of `cfg` only when the card is well formed AND the English lines are exactly the stored body (so that the card says what the
    terminal and the page show of the same decision, and what the hash is the hash of); the values of the fields are the person's or a service's words and
    are never changed. Anything else (no card, a key outside the family, a field that is no text, a body that is not the lines) is None, and the card
    is built from the stored body as it always was."""
    payload = item.get("payload")
    card = payload.get("card") if isinstance(payload, dict) else None
    if not phrases.card_valid(card):
        return None
    if phrases.card_text(card).strip() != (item.get("body") or "").strip():
        return None
    groups = frozenset(phrases.PRIVATE_GROUPS) if private is True else frozenset() if private is False else private      # True and False are the whole and the none; a set of groups is the sender's own (CB-5)
    shown = card if groups >= frozenset(phrases.PRIVATE_GROUPS) else phrases.card_without_private(card, owner, groups)
    # `approvable` False is the phone (LIVE-2): the lines that are the platform's own how-to for a terminal go (the approve command, the hash line the command needs), and the
    # save line says no hash; every line of the person's data is as the card holds it. A reader offered no approval is not told how to approve either.
    present = {line[0] for line in shown}
    twice = {dup for key, dups in PHONE_DUPLICATE.items() if key in present for dup in dups}
    kept = shown if approvable else [[PHONE_LINE.get(line[0], line[0]), line[1]] for line in shown
                                     if not line[0].endswith("_APPROVE") and line[0] not in PHONE_DROPPED and line[0] not in twice]
    if not approvable:      # BL5D: the phone says the message a reply answers by the plain name of its source, from a copy of the line
        kept = [_named_ref(line, cfg) for line in kept]
    text = phrases.card_text(kept, cfg)
    return text + "\n" + phrases.text(phrases.hidden_note_key(card, shown), cfg) if len(shown) < len(card) else text


def build(project_name: str, item: dict, caps: dict, policy, notices: str = "text", page_url=None, operations=None,
          delivery: str | None = None, _blocked: str | None = None, sender: str | None = None, cfg=None, _typed: bool = False) -> dict:
    """The card of one open decision. Returns {"message": the neutral message without action ids (each action is
    {"op", "label"}), "content_sha256", "kind", "pending_id", "whole", "approvable", "offers", "gated", "blocked"} ("approvable": the card offers an approval, as a
    button, a typed line or, on a platform with no buttons, the word that approves; "offers": every act it offers, a list of operation names; "gated": its approval needs the whole text; "blocked": "document" when its file did not arrive). `operations` is the table module (operations.py).
    A card never carries a command or a path of this machine (limit L62): the page is named instead. `whole` is true when the
    message carries the decision's whole text: the body uncut, or the whole text as a document that was DELIVERED. The document of a
    card the approval of which needs it is sent first, as a message of its own (messaging_bridge.send_card), and `delivery` says what
    happened: "sent" (the provider confirmed the document: the card cites it and is whole) or "failed" (it did not arrive: the card is not
    whole, offers no approval and says so); None is a card not yet sent, whose document, if it has one, travels in the message.
    `_blocked` is the second pass of a card whose first pass was not whole.
    `sender` (POL-2) is the sender the card is for (`<platform>:<sender id>`, operations.sender_key): what a button offers is what THAT sender's profile
    permits, so a card drawn for a limited profile has fewer buttons than the same decision's card for the owner. "actionable" says whether the card
    offers its sender anything to act on or answer (the profile's `notices: actionable` sends a card only then).
    `cfg` maps `language` to the project's setting (the bridge hands over its settings): the frames the card adds around the decision's text are said in it
    (runtime/phrases.py); the decision's own text, the commands and the ids are not changed."""
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    kind, pending_id = item["kind"], item["id"]
    words = list(item.get("actions") or [])
    allowed, refused = [], False
    needs_whole = gated(item)
    blocked = _blocked or ("document" if delivery == "failed" else None)
    approval_ok = False
    private = reads_private(policy, sender, operations)
    groups = private_groups(policy, sender, operations)
    owner = bool(sender) and item.get("reader_sent_file") is True      # the sender who sent the held file a save card writes (W4a) sees its name there and approves it
    unreadable = kind == "effect" and not private and item.get("effect_word") in operations.ACCOUNT_APPROVAL_WORDS and not phrases.card_valid((item.get("payload") or {}).get("card"))
    shown_body = phrases.text("CARD_HIDDEN_NOTE_WHOLE", cfg) if unreadable else (effect_card_text(item, cfg, groups, owner, False) if kind == "effect" else None)      # an effect that carries its card as lines (FND), said line by line in the language; the line that tells how to approve is a command, which a phone is never given (limit L62)
    if shown_body is None and router_asks(item):
        shown_body = phrases.asked_view(item.get("body"), cfg)      # the router's question reaches a phone as the question and its framing, not as the template around it; the hash is made of the stored body
    shown_title = phrases.heading(item.get("title"), cfg)
    if kind == "question" and router_asks(item):
        shown_title = phrases.text("PEND_CARD_TITLE", cfg)      # a phone is not told "the router asks" (S14); the stored title is the card's hash
    elif kind == "question" and shown_body is None and pending_view.unclassified(item):
        shown_title, shown_body = phrases.text("PEND_NOT_UNDERSTOOD_TITLE", cfg), phrases.text("PHONE_NOT_UNDERSTOOD", cfg)      # a request the router could not read: one plain sentence, not the route and the flow (S14)
    full = decision_text(dict(item, title=shown_title,
                              body=shown_body if shown_body is not None else phrases.body(item.get("body"), cfg)))      # the heading and the body code wrote whole, said in the language; the hash is made of the stored ones
    if shown_body is None and kind == "effect":      # a stored body (no card): only the platform's two frame lines are touched, every other line is the person's data and is shown as it is
        full = APPROVE_FRAME.sub("", LEDGER_LINE.sub(lambda m: m.group(1) + ": " + phrases.text("PHONE_LEDGER_FILE", cfg), full)).rstrip("\n")
    cut_private = unreadable or (kind == "effect" and effect_card_text(item, None, True) != effect_card_text(item, None, groups, owner))      # a line of the current text is left out; so is a card of an account write that cannot be read as a card (fail closed)
    if needs_whole and not blocked and notices == "text" and not cut_private:
        if kind == "effect":
            approval_ok = item.get("effect_on_cards") is True and operations.permitted("approve", CHANNEL, policy, effect_kind(item), sender) \
                and (item.get("effect_sender_only") is not True or owner)      # the save of a held file is approved by the sender who sent it, and by no one else (Q9)
        else:
            approval_ok = (operations.permitted("approve", CHANNEL, policy, "plan", sender)
                           and operations.permitted("approve", CHANNEL, policy, "plan:networked", sender))
    for word in words:
        op = WORD_OPERATION.get(word)
        if op is None or (needs_whole and op == "approve" and not approval_ok):
            continue
        if needs_whole and op == "approve":
            allowed.append(op)
        elif operations.permitted(op, CHANNEL, policy, kind, sender):
            if op not in allowed:
                allowed.append(op)
        else:
            refused = True
    if kind == "plan" and needs_whole and not approval_ok and "approved" in words:
        refused = True
    allowed.sort(key=ORDER.index)
    answerable = "answered" in words and kind == "question"
    reply = answerable and caps.get("reply_context") and operations.permitted("answer", CHANNEL, policy, None, sender)
    if answerable and not reply:
        refused = True
    buttons_ok = bool(caps.get("buttons")) and caps.get("max_buttons", 0) > 0
    room = caps.get("max_buttons", 0) if buttons_ok else 0
    words_decide = not buttons_ok and not _typed and "approve" in allowed and "reject" in allowed      # a platform with no buttons: a WHOLE card says what a word does (package S2, limit L64), not a command to send; a card that is not whole (`_typed`, second pass) keeps the typed lines, as a word decides only a whole card
    shown, lines = allowed[:room], [typed(op, pending_id) for op in allowed[room:] if not (words_decide and op in ("approve", "reject"))]
    footer = []
    if lines:
        footer += [t("SEND_LINE", line=line) for line in lines]
    if reply:
        footer.append(t("REPLY_LINE"))
    if needs_whole and blocked:
        footer.append(t("DOCUMENT_LINE") if blocked == "document" else t("TOO_LONG_LINE"))
    if kind == "effect" and approval_ok:
        footer.append(t("APPROVES_LINE", sha=item.get("payload_sha256") or ""))
    elif kind == "effect":
        footer.append(t("EFFECT_LINE"))
    elif refused:
        footer.append(t("PAGE_LINE"))
    link = None
    if page_url and (kind == "effect" or refused or notices == "count"):
        if caps.get("url_buttons"):
            link = {"label": t("PAGE_LABEL"), "url": page_url}
        else:
            footer.append(page_url)
    if words_decide:
        footer.append(t("REPLY_WORDS_LINE"))      # the card ends with it
    header = header_of(project_name, item, cfg)
    document = None
    whole = False
    if notices == "count":
        body = t("WAITS_COUNT", kind=phrases.kind_word(kind, cfg))
    else:
        body = full
    tail = "\n\n" + "\n".join(footer) if footer else ""
    limit = int(caps.get("max_text") or 4096)
    room_for_body = limit - len(header) - 2 - len(tail)
    if notices != "count" and len(body) > room_for_body:
        if delivery == "failed" or not caps.get("documents"):
            body = _cut(body, room_for_body, t("CUT"))
        elif delivery == "sent":
            body = _cut(body, room_for_body, t("WHOLE_ABOVE"))
            whole = True      # the whole text went first, as a document the provider confirmed
        else:
            body = _cut(body, room_for_body, t("WHOLE"))
            document = {"name": f"{kind}-{pending_id}.txt", "text": full}
            whole = True      # the whole text follows as a document
    else:
        whole = notices != "count"
    if words_decide and not whole:      # a word decides only a whole card: this one keeps the typed approve and reject lines
        return build(project_name, item, caps, policy, notices, page_url, operations, delivery, _blocked=_blocked, sender=sender, cfg=cfg, _typed=True)
    if needs_whole and approval_ok and not whole:    # a cut card approves nothing: the same card again, with the command and the line
        return build(project_name, item, caps, policy, notices, page_url, operations, delivery, _blocked="long", sender=sender, cfg=cfg)
    text = header + "\n\n" + body + tail if body else header + tail
    labels = {op: t("EFFECT_LABEL" if op == "approve" and kind == "effect" else "LABEL_" + op.upper()) for op in ORDER}
    message = {"text": text, "actions": [{"op": op, "label": labels[op]} for op in shown], "link": link, "document": document}
    if footer and caps.get("actions_need_reply"):
        message["footer"] = list(footer)      # the lines this function appended, handed over so that a provider never has to infer them (e-mail)
    return {"message": message, "content_sha256": content_sha256(item), "kind": kind, "pending_id": pending_id, "whole": whole,
            "approvable": "approve" in allowed, "offers": list(allowed), "gated": needs_whole, "actionable": bool(allowed) or bool(reply),
            "blocked": "document" if (needs_whole and blocked == "document") else None}


def document_message(project_name: str, item: dict, document: dict, cfg=None) -> dict:
    """The message that carries a gated card's whole text, sent before the card: a line that names the decision, and the document."""
    return {"text": f"{header_of(project_name, item, cfg)}\n\n{phrases.text('DOCUMENT_NOTE', cfg)}", "actions": [], "link": None, "document": document}


def split(text: str, limit: int) -> list:
    """The text in pieces of at most `limit` characters, cut at a line end when one is near."""
    limit = max(1, int(limit))
    pieces = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        cut = cut if cut > limit // 2 else limit
        pieces.append(text[:cut].rstrip("\n"))
        text = text[cut:].lstrip("\n")
    if text or not pieces:
        pieces.append(text)
    return pieces


# --- the card of a file a sender sent (ATT-1) ----------------------------------------------------------------------------------------

ATTACH_OPERATION = {"add": "attachment-add", "discard": "attachment-discard", "save-google": "file-save", "save-microsoft": "file-save"}
SAVE_WORDS = ("save-google", "save-microsoft")      # the buttons that open the save card (package ATT-3), one for each account the project lists with folders
ATTACH_LABELS = {"add": phrases.en("LABEL_ADD"), "discard": phrases.en("LABEL_DISCARD"), "save-google": phrases.en("LABEL_SAVE_GOOGLE"),
                 "save-microsoft": phrases.en("LABEL_SAVE_MICROSOFT")}


def attachment_card(project_name: str, row: dict, next_version: int, caps: dict, policy, notices: str = "text", operations=None, sender: str | None = None,
                    cfg=None, accounts=(), extra=()) -> dict:
    """The one card of a file a sender sent (kind `attachment`), drawn for the sender who sent it: "I received <name> (<size>, <type>). What should I do?" with a button for
    each thing THAT sender's profile permits: **Save to Google Drive** / **Save to OneDrive** (one for each account in `accounts`, when the profile permits `file-save`),
    **Add to project** (only for a type that can become a source, when it permits `attachment-add`) and **Discard**. A platform with no buttons gets the typed lines
    (`Send /add 3`, `Send /discard 3`, or the words that save); what the policy refuses is neither drawn nor offered (the card says to act on the platform's page).
    With notices "count" the card carries nothing of the project or of the file. `row` is the held file as `attachments` reads it (its name, kind and size are the sender's own
    words, already cleaned and cut); `accounts` the accounts ("google", "microsoft") the project lists with folders; `extra` is lines (already said) added under the question: the note that
    the text sent with the file is read only as a request to save it, or that the service the text named is not set up. Returns {"message", "content_sha256" (the one of attachments.card_sha256), "kind": "attachment", "attachment_id",
    "actionable", "words"}; the bridge records it in the ledger with the file's number in place of a decision's."""
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    save_only = bool(row.get("save_only")) or attachments.is_save_only(row.get("kind"))
    wanted = [f"save-{a}" for a in accounts if f"save-{a}" in SAVE_WORDS] + ([] if save_only else ["add"]) + ["discard"]
    words = [w for w in wanted if operations.permitted(ATTACH_OPERATION[w], CHANNEL, policy, None, sender)]
    buttons_ok = bool(caps.get("buttons")) and caps.get("max_buttons", 0) > 0
    room = caps.get("max_buttons", 0) if buttons_ok else 0
    shown, typed_words = words[:room], words[room:]
    footer = [t("SEND_LINE", line=f"/{w} {row['id']}") if w in ("add", "discard") else t("ATTACH_TYPED_" + w.upper().replace("-", "_")) for w in typed_words]
    if not any(w in words for w in ("add", "discard")) or len(words) < len(wanted):
        footer.append(t("PAGE_LINE"))
    header = t("HEADER_FILE", project=project_name, id=row["id"])
    if notices == "count":
        body = t("ATTACH_COUNT")
    else:
        kind = attachments.IMAGE_WORDS.get(row.get("kind"), row.get("kind") or t("FILE_WORD")) if save_only else (row.get("kind") or t("FILE_WORD"))
        body = t("ATTACH_WHAT", name=row["name"], size=attachments.size_text(row["bytes"], cfg), kind=kind)
        if "add" in words:
            body += "\n" + (t("ATTACH_WHAT_VERSION", id=row["target"], n=next_version) if row.get("label") == "refresh" and next_version else t("ATTACH_WHAT_ADD", project=project_name, id=row["target"]))
        for line in extra:
            body += "\n" + line
    tail = "\n\n" + "\n".join(footer) if footer else ""
    text = _cut(header + "\n\n" + body, int(caps.get("max_text") or 4096) - len(tail), t("CUT")) + tail
    message = {"text": text, "actions": [{"op": w, "label": t("LABEL_" + w.upper().replace("-", "_"))} for w in shown], "link": None, "document": None}
    if footer and caps.get("actions_need_reply"):
        message["footer"] = list(footer)
    return {"message": message, "content_sha256": attachments.card_sha256(row["sha256"], row["target"], row["label"]), "kind": "attachment", "attachment_id": row["id"],
            "actionable": bool(words), "words": words}
