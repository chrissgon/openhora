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
           document). Otherwise its card ends with the exact command, to be run on the page or in the terminal, and, when only the
           length stops it, the line "Too long to approve here". The result carries `whole`, which the bridge records in the
           ledger: an approval is taken only from a card that says it was whole. A question is answered by replying to its card (when
           the policy permits `answer` and the platform keeps reply context). What the platform cannot draw as a button (no buttons,
           or more actions than it shows) becomes a typed line, "Send /approve 12". What the policy refuses is neither drawn nor
           offered as a line: the card says "Act on it on the page or in the terminal."
  sender   (POL-2) the card is drawn for one sender, and what it offers is what THAT sender's profile permits: the owner's card of a plan has
           Approve and Reject, an employee's card of the same plan, whose profile lists neither, has no button; the result says whether the card
           offers its sender anything to act on or answer (`actionable`), which a profile with `notices: actionable` is sent a card for
  language (LR-1) the frames a card adds around the decision's text (the labels, the cut and whole notes, the "Send /approve 12" lines, "Act on it on the page or in the terminal.") and
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
import phrases  # noqa: E402  (the same folder: the sentences of a card, in the project's language)

CHANNEL = "messaging"
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


def code_span(command: str) -> str:
    """The command as a Markdown code span, which a messenger can offer as tap-to-copy. A command that holds a backtick
    is wrapped in a longer run of backticks with a space inside each end (CommonMark); the renderer strips that one
    space, so the visible command is the command byte for byte."""
    longest = max((len(r) for r in re.findall(r"`+", command)), default=0)
    if not longest and not (command.startswith(" ") or command.endswith(" ")):
        return f"`{command}`"
    fence = "`" * (longest + 1)
    return f"{fence} {command} {fence}"


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


def effect_card_text(item: dict, cfg=None, private: bool = True):
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
    shown = card if private else phrases.card_without_private(card)
    text = phrases.card_text(shown, cfg)
    return text + "\n" + phrases.text("CARD_HIDDEN_NOTE", cfg) if len(shown) < len(card) else text


def build(project_name: str, item: dict, caps: dict, policy, notices: str = "text", page_url=None, operations=None,
          effect_command: str | None = None, delivery: str | None = None, _blocked: str | None = None, sender: str | None = None, cfg=None) -> dict:
    """The card of one open decision. Returns {"message": the neutral message without action ids (each action is
    {"op", "label"}), "content_sha256", "kind", "pending_id", "whole", "approvable", "gated", "blocked"} ("approvable": the card offers an approval, as a
    button or a typed line; "gated": its approval needs the whole text; "blocked": "document" when its file did not arrive). `operations` is the table module (operations.py);
    `effect_command` is the exact command that approves an effect, spelled by the operations layer. `whole` is true when the
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
    cut_private = kind == "effect" and not private and effect_card_text(item, None, True) != effect_card_text(item, None, False)      # a line of the current text is left out
    if needs_whole and not blocked and notices == "text" and not cut_private:
        if kind == "effect":
            approval_ok = item.get("effect_on_cards") is True and operations.permitted("approve", CHANNEL, policy, effect_kind(item), sender)
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
    shown, lines = allowed[:room], [typed(op, pending_id) for op in allowed[room:]]
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
        if effect_command:
            footer.append(code_span(effect_command))
    elif refused:
        footer.append(t("PAGE_LINE"))
    link = None
    if page_url and (kind == "effect" or refused or notices == "count"):
        if caps.get("url_buttons"):
            link = {"label": t("PAGE_LABEL"), "url": page_url}
        else:
            footer.append(page_url)
    header = header_of(project_name, item, cfg)
    shown_body = effect_card_text(item, cfg, private) if kind == "effect" else None      # an effect that carries its card as lines (FND), said line by line in the language
    full = decision_text(dict(item, title=phrases.heading(item.get("title"), cfg),
                              body=shown_body if shown_body is not None else phrases.body(item.get("body"), cfg)))      # the heading and the body code wrote whole, said in the language; the hash is made of the stored ones
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
    if needs_whole and approval_ok and not whole:    # a cut card approves nothing: the same card again, with the command and the line
        return build(project_name, item, caps, policy, notices, page_url, operations, effect_command, delivery, _blocked="long", sender=sender, cfg=cfg)
    text = header + "\n\n" + body + tail if body else header + tail
    labels = {op: t("EFFECT_LABEL" if op == "approve" and kind == "effect" else "LABEL_" + op.upper()) for op in ORDER}
    message = {"text": text, "actions": [{"op": op, "label": labels[op]} for op in shown], "link": link, "document": document}
    if footer and caps.get("actions_need_reply"):
        message["footer"] = list(footer)      # the lines this function appended, handed over so that a provider never has to infer them (e-mail)
    return {"message": message, "content_sha256": content_sha256(item), "kind": kind, "pending_id": pending_id, "whole": whole,
            "approvable": "approve" in allowed, "gated": needs_whole, "actionable": bool(allowed) or bool(reply),
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

ATTACH_OPERATION = {"add": "attachment-add", "discard": "attachment-discard"}
ATTACH_LABELS = {"add": phrases.en("LABEL_ADD"), "discard": phrases.en("LABEL_DISCARD")}
ATTACH_ASK = phrases.en("ATTACH_ASK")
ATTACH_ASK_VERSION = phrases.en("ATTACH_ASK_VERSION")
ATTACH_COUNT = phrases.en("ATTACH_COUNT")


def attachment_card(project_name: str, row: dict, next_version: int, caps: dict, policy, notices: str = "text", operations=None, sender: str | None = None,
                    cfg=None) -> dict:
    """The card of one held file (kind `attachment`), drawn for the sender who sent it: a question with **Add** and **Discard**, each only when the sender's profile
    permits `attachment-add` / `attachment-discard`; a platform with no buttons gets the typed lines `Send /add 3` and `Send /discard 3`; what the policy refuses is
    neither drawn nor offered (the card says to act on the page or in the terminal). With notices "count" the card carries nothing of the project or of the file.
    `row` is the held file as `attachments` reads it (its name, kind and size are the sender's own words, already cleaned and cut). Returns {"message", "content_sha256"
    (the one of attachments.card_sha256), "kind": "attachment", "attachment_id", "actionable"}; the bridge records it in the ledger with the file's number in place of a
    decision's."""
    import attachments as att
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    words = [w for w in ("add", "discard") if operations.permitted(ATTACH_OPERATION[w], CHANNEL, policy, None, sender)]
    buttons_ok = bool(caps.get("buttons")) and caps.get("max_buttons", 0) > 0
    room = caps.get("max_buttons", 0) if buttons_ok else 0
    shown, typed_words = words[:room], words[room:]
    footer = [t("SEND_LINE", line=f"/{w} {row['id']}") for w in typed_words]
    if len(words) < 2:
        footer.append(t("PAGE_LINE"))
    header = t("HEADER_FILE", project=project_name, id=row["id"])
    if notices == "count":
        body = t("ATTACH_COUNT")
    else:
        body = t("ATTACH_ASK_VERSION" if row.get("label") == "refresh" else "ATTACH_ASK", platform=row.get("platform") or t("A_MESSAGING_APP"), name=row["name"],
                 size=att.size_text(row["bytes"], cfg), kind=row.get("kind") or t("FILE_WORD"), project=project_name, id=row["target"], n=next_version)
    tail = "\n\n" + "\n".join(footer) if footer else ""
    text = _cut(header + "\n\n" + body, int(caps.get("max_text") or 4096) - len(tail), t("CUT")) + tail
    message = {"text": text, "actions": [{"op": w, "label": t("LABEL_" + w.upper())} for w in shown], "link": None, "document": None}
    if footer and caps.get("actions_need_reply"):
        message["footer"] = list(footer)
    return {"message": message, "content_sha256": att.card_sha256(row["sha256"], row["target"], row["label"]), "kind": "attachment", "attachment_id": row["id"],
            "actionable": bool(words)}
