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
           `release`. An effect is never offered an approval: its card ends with the exact command, to be run on the
           page or in the terminal. A question is answered by replying to its card (when the policy permits `answer`
           and the platform keeps reply context). What the platform cannot draw as a button (no buttons, or more
           actions than it shows) becomes a typed line, "Send /approve 12". What the policy refuses is neither drawn nor
           offered as a line: the card says "Act on it on the page or in the terminal."

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

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


def build(project_name: str, item: dict, caps: dict, policy, notices: str = "text", page_url=None, operations=None,
          effect_command: str | None = None) -> dict:
    """The card of one open decision. Returns {"message": the neutral message without action ids (each action is
    {"op", "label"}), "content_sha256", "kind", "pending_id"}. `operations` is the table module (operations.py);
    `effect_command` is the exact command that approves an effect, spelled by the operations layer."""
    kind, pending_id = item["kind"], item["id"]
    words = list(item.get("actions") or [])
    allowed, refused = [], False
    for word in words:
        op = WORD_OPERATION.get(word)
        if op is None or (kind == "effect" and op == "approve"):
            continue
        if operations.permitted(op, CHANNEL, policy, kind):
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
    if kind == "effect":
        footer.append(EFFECT_LINE)
        if effect_command:
            footer.append(effect_command)
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
        else:
            body = _cut(body, room_for_body, CUT)
    text = header + "\n\n" + body + tail if body else header + tail
    message = {"text": text, "actions": [{"op": op, "label": LABELS[op]} for op in shown], "link": link, "document": document}
    return {"message": message, "content_sha256": content_sha256(item), "kind": kind, "pending_id": pending_id}


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
