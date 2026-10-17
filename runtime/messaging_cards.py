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

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import re
import hashlib

CHANNEL = "messaging"
WORD_OPERATION = {"approved": "approve", "accepted": "approve", "rejected": "reject", "released": "release"}
LABELS = {"approve": "Approve", "reject": "Reject", "release": "Release"}
ORDER = ("approve", "release", "reject")
CUT = "(continues on the page)"
WHOLE = "(the whole text follows as a document)"
PAGE_LINE = "Act on it on the page or in the terminal."
REPLY_LINE = "Reply to this message to answer."
EFFECT_LINE = "Approve it on the page or in the terminal:"
TOO_LONG_LINE = "Too long to approve here: approve it on the page or in the terminal."
APPROVES_LINE = "Approving applies exactly the text above (sha256 {sha})."
EFFECT_LABEL = "Approve this exact content"
MORE_LINE = "And {n} more waiting. Send /pending to list them."
PAGE_LABEL = "Open the page"


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


def header_of(project_name: str, item: dict) -> str:
    return f"{project_name} · {item['kind']} #{item['id']}"


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


def build(project_name: str, item: dict, caps: dict, policy, notices: str = "text", page_url=None, operations=None,
          effect_command: str | None = None, _no_effect_approval: bool = False) -> dict:
    """The card of one open decision. Returns {"message": the neutral message without action ids (each action is
    {"op", "label"}), "content_sha256", "kind", "pending_id", "whole", "approvable"} ("approvable": the card offers an approval, as a
    button or a typed line). `operations` is the table module (operations.py);
    `effect_command` is the exact command that approves an effect, spelled by the operations layer. `whole` is true when the
    message carries the decision's whole text (the body uncut, or the whole text as the attached document); with notices
    "count" it is false. `_no_effect_approval` is the second pass of an effect card whose first pass was not whole."""
    kind, pending_id = item["kind"], item["id"]
    words = list(item.get("actions") or [])
    allowed, refused = [], False
    effect_approval = (kind == "effect" and not _no_effect_approval and notices == "text" and item.get("effect_on_cards") is True
                       and operations.permitted("approve", CHANNEL, policy, effect_kind(item)))
    for word in words:
        op = WORD_OPERATION.get(word)
        if op is None or (kind == "effect" and op == "approve" and not effect_approval):
            continue
        if kind == "effect" and op == "approve":
            allowed.append(op)
        elif operations.permitted(op, CHANNEL, policy, kind):
            if op not in allowed:
                allowed.append(op)
        else:
            refused = True
    allowed.sort(key=ORDER.index)
    answerable = "answered" in words and kind == "question"
    reply = answerable and caps.get("reply_context") and operations.permitted("answer", CHANNEL, policy)
    if answerable and not reply:
        refused = True
    buttons_ok = bool(caps.get("buttons")) and caps.get("max_buttons", 0) > 0
    room = caps.get("max_buttons", 0) if buttons_ok else 0
    shown, lines = allowed[:room], [typed(op, pending_id) for op in allowed[room:]]
    footer = []
    if lines:
        footer += [f"Send {line}" for line in lines]
    if reply:
        footer.append(REPLY_LINE)
    if kind == "effect" and effect_approval:
        footer.append(APPROVES_LINE.format(sha=item.get("payload_sha256") or ""))
    elif kind == "effect":
        if _no_effect_approval:
            footer.append(TOO_LONG_LINE)
        footer.append(EFFECT_LINE)
        if effect_command:
            footer.append(code_span(effect_command))
    elif refused:
        footer.append(PAGE_LINE)
    link = None
    if page_url and (kind == "effect" or refused or notices == "count"):
        if caps.get("url_buttons"):
            link = {"label": PAGE_LABEL, "url": page_url}
        else:
            footer.append(page_url)
    header = header_of(project_name, item)
    full = decision_text(item)
    document = None
    whole = False
    if notices == "count":
        body = f"A {kind} waits for you."
    else:
        body = full
    tail = "\n\n" + "\n".join(footer) if footer else ""
    limit = int(caps.get("max_text") or 4096)
    room_for_body = limit - len(header) - 2 - len(tail)
    if notices != "count" and len(body) > room_for_body:
        if caps.get("documents"):
            body = _cut(body, room_for_body, WHOLE)
            document = {"name": f"{kind}-{pending_id}.txt", "text": full}
            whole = True      # the whole text follows as a document
        else:
            body = _cut(body, room_for_body, CUT)
    else:
        whole = notices != "count"
    if kind == "effect" and effect_approval and not whole:    # a cut card approves nothing: the same card again, with the command and the line
        return build(project_name, item, caps, policy, notices, page_url, operations, effect_command, _no_effect_approval=True)
    text = header + "\n\n" + body + tail if body else header + tail
    labels = dict(LABELS, approve=EFFECT_LABEL) if kind == "effect" else LABELS
    message = {"text": text, "actions": [{"op": op, "label": labels[op]} for op in shown], "link": link, "document": document}
    return {"message": message, "content_sha256": content_sha256(item), "kind": kind, "pending_id": pending_id, "whole": whole,
            "approvable": "approve" in allowed}


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
