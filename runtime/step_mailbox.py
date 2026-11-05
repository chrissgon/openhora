#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The step kind `mailbox-change`: change the person's own mailbox, as an external effect the person approves (package W3). Archive messages, move them to a folder or label
the project names, mark them as read or unread, move them to the provider's trash, or save a draft (never sent). The kind prepares; it never writes. Two steps, as in a
send or a calendar change:

  prepare   checks the arguments, takes the account's address and the target folder from the project's `accounts` (a folder the project does not list is refused: limit
            L55), READS EACH MESSAGE FROM THE MAILBOX through the read-only mailbox service (its subject and sender as the service holds them now, its labels or its changeKey
            and folder: the base the change is checked against, limit L56), refuses a message that is gone or is already as asked, then asks the writer for a dry run of the
            requests (nothing is sent, no credential is read, no connection is opened), checks that what the writer would send is what the arguments say (the methods, the
            paths, nothing that sends), and writes the effect document (runtime/mailbox_document.py) through the effect-files service to
            <data_dir>/step-effects/<task id>/<cycle>/effect.json, 0600 in a 0700 folder.
  mailbox   the gate (runtime/steps.py, Gate): it has no executor. It opens an `effect` decision whose hash is the hash of the effect document and whose body is the card:
            the account, what is done, EVERY message by its current subject and sender, when they were read; the task waits. The person approves the hash in the terminal or on
            the page (a messaging app only when the project's policy grants it the word `mailbox`, and shows the subjects only to a sender who may read the mail), and then
            runtime/ops_step_effects.py calls the effect module (runtime/effect_mailbox.py), which reads the messages again, writes once, and sends nothing. A message moved
            meanwhile answers the decision, writes nothing and sends the task back to `prepare`.

Arguments (checked when the task is planned, so the plan's hash covers exactly what will be asked about):

  {"account": "google" | "microsoft", "action": "archive" | "move" | "mark" | "trash" | "draft"
   archive, trash:  "messages"
   move:            "messages", "folder" (a name of accounts.<a>.mail_folders)
   mark:            "messages", "state" ("read" | "unread")
   draft:           "to", "subject", "body" ["cc", "bcc"]   a new draft (lists of plain addresses; at most 20 in all)
                    or "reply" (one message) and "body"      a draft that answers a message of a snapshot}

`messages` is 1 to 20 entries, each {"ref" (`<source>#<n>`), "id", "snapshot_at"}: the reference the person named the message by, the id the snapshot's index
recorded and the time of that snapshot, and nothing else: not the sender, not the thread, not a subject (the preparation reads them from the mailbox, and a task's
arguments can be shown to a reader who may not see another person's mail). The `reply` of a draft adds what a reply needs: "thread_id", "message_id", "from_address" (the
sender the snapshot recorded, which must be the mailbox's now) and "reply_to_address". The operation (runtime/ops_mailbox.py) resolved the references with the caller's
own right to read the snapshot; the kind trusts none of it for the base: it reads the mailbox itself.

A reply goes to the `From` address of the message it answers, as the index recorded it and as the mailbox says now (they must be the same), and never to a `Reply-To`,
which the card shows and the draft does not use (limit L60); its subject is `Re:` and the subject of the message. A draft is saved, never sent.

Limit L30, in the structure of this file: it imports no module that calls a provider. What it needs of the accounts, of the mailbox and of the data folder it asks of
`ctx.services` (runtime/ops_step_seams.py), where `mailbox_read` has messages and folders read and a dry run and no way to write, and `effect_files` writes and reads the
effect document and does not execute it. The only code that writes is runtime/effect_mailbox.py `execute`, which this file cannot reach.

The kind is not `unattended`: a mailbox change starts when the person starts it and ends at the person's approval. It writes no file of the project (its footprint is empty).

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import mail_address  # noqa: E402
import mailbox_document  # noqa: E402
import send_document  # noqa: E402
import steps  # noqa: E402

KEYS = ("account", "action", "folder", "state", "messages", "to", "cc", "bcc", "subject", "body", "reply")
ENTRY_KEYS = ("ref", "id", "snapshot_at")      # what a change of messages keeps of a message: nothing the snapshot said of its sender or thread (the preparation reads those live)
REPLY_KEYS = ENTRY_KEYS + ("thread_id", "message_id", "from_address", "reply_to_address")      # a reply needs the sender the snapshot recorded, to compare it with the mailbox now
SERVICE_CODES = {"not_configured": "not_configured", "provider_failed": "provider_failed", "refused": "refused"}
GATE_STEP = "mailbox"


def _bad(field: str, hint: str = ""):
    return steps.StepFailure("bad_args", field, "", hint[:200])


def _entry(value, account: str, field: str) -> dict:
    """One entry of `messages` (the keys ENTRY_KEYS) or of the `reply` (REPLY_KEYS), checked: each a closed shape or null."""
    keys = REPLY_KEYS if field == "reply" else ENTRY_KEYS
    if not isinstance(value, dict) or set(value) != set(keys):
        raise _bad(field, "a message is named by " + ", ".join(keys))
    pattern = mailbox_document.GMAIL_ID if account == "google" else mailbox_document.GRAPH_ID
    if not isinstance(value["ref"], str) or not mailbox_document.REF.fullmatch(value["ref"]) or not isinstance(value["id"], str) or not pattern.fullmatch(value["id"]):
        raise _bad(field, "a message is named by a reference and an id of the account's service")
    for name, shape in (("thread_id", pattern), ("message_id", mailbox_document.INTERNET_ID)):
        if name in value and value[name] is not None and (not isinstance(value[name], str) or not shape.fullmatch(value[name])):
            raise _bad(field, f"{name} is in the form the service prints it, or null")
    for name in ("from_address", "reply_to_address"):
        if name in value and value[name] is not None:
            try:
                if mail_address.normalize_address(value[name]) != value[name]:
                    raise mail_address.AddressError("")
            except (mail_address.AddressError, TypeError):
                raise _bad(field, f"{name} is a plain address, or null") from None
    if not isinstance(value["snapshot_at"], str) or not mailbox_document.STAMP.fullmatch(value["snapshot_at"]):
        raise _bad(field, "snapshot_at is the time the snapshot was read, YYYY-MM-DDTHH:MM:SSZ")
    return dict(value)


def _addresses(value, field: str) -> list:
    if not isinstance(value, list) or not all(isinstance(a, str) for a in value):
        raise _bad(field, "a list of plain addresses")
    try:
        if [mail_address.normalize_address(a) for a in value] != value:
            raise mail_address.AddressError("an address is in its normal form")
    except mail_address.AddressError as e:
        raise _bad(field, e.reason) from None
    return list(value)


def _text(call, value, field: str):
    try:
        return call(value)
    except Exception as e:      # an EffectError of the document module: its reason names the rule, never the content
        raise _bad(field, str(getattr(e, "reason", ""))) from None


def check(args) -> dict:
    """The arguments of a mailbox-change, checked and normalised."""
    if not isinstance(args, dict) or set(args) - set(KEYS):
        raise _bad("args")
    account, action = args.get("account"), args.get("action")
    if account not in mailbox_document.ACCOUNTS:
        raise _bad("account", "give google or microsoft")
    if action not in mailbox_document.ACTIONS:
        raise _bad("action", "give archive, move, mark, trash or draft")
    out = {"account": account, "action": action}
    if action == "draft":
        for name in ("messages", "folder", "state"):
            if args.get(name) is not None:
                raise _bad(name, "a draft names no messages, folder or state of its own")
        if args.get("reply") is not None:
            for name in ("to", "cc", "bcc", "subject"):
                if args.get(name) is not None:
                    raise _bad(name, "a reply goes to the sender of the message it answers, with its subject: give only the body")
            out["reply"] = _entry(args["reply"], account, "reply")
        else:
            if args.get("to") is None or args.get("subject") is None:
                raise _bad("to" if args.get("to") is None else "subject", "a new draft needs to, subject and body")
            to, cc, bcc = (_addresses(args.get(name, []), name) for name in ("to", "cc", "bcc"))
            _text(lambda v: send_document.check_recipients("", to, cc, bcc), None, "to")
            out.update(to=to, cc=cc, bcc=bcc, subject=_text(send_document.check_subject, args["subject"], "subject"))
        if args.get("body") is None:
            raise _bad("body", "a draft needs a body")
        _text(send_document.check_body, args["body"], "body")
        for field, found in (("subject", mailbox_document.text_problem(out.get("subject", ""))), ("body", mailbox_document.text_problem(args["body"], lines=True))):
            if found:
                raise _bad(field, found)
        out["body"] = args["body"]
        return out
    for name in ("reply", "to", "cc", "bcc", "subject", "body"):
        if args.get(name) is not None:
            raise _bad(name, "only a draft has recipients, a subject, a body or a reply")
    found = args.get("messages")
    if not isinstance(found, list) or not 1 <= len(found) <= mailbox_document.MESSAGES_MAX:
        raise _bad("messages", f"name 1 to {mailbox_document.MESSAGES_MAX} messages")
    entries = [_entry(e, account, "messages") for e in found]
    if len({e["id"] for e in entries}) != len(entries) or len({e["ref"] for e in entries}) != len(entries):
        raise _bad("messages", "a message is named once")
    out["messages"] = entries
    if action == "move":
        if not isinstance(args.get("folder"), str) or not mailbox_document.NAME.fullmatch(args["folder"]):
            raise _bad("folder", "a folder is named as the project's accounts name it: lowercase letters, digits and hyphens")
        out["folder"] = args["folder"]
    elif args.get("folder") is not None:
        raise _bad("folder", "only a move names a folder")
    if action == "mark":
        if args.get("state") not in mailbox_document.STATES:
            raise _bad("state", "give read or unread")
        out["state"] = args["state"]
    elif args.get("state") is not None:
        raise _bad("state", "only a mark has a state")
    return out


def _service(ctx: steps.Context, name: str):
    found = ctx.services.get(name)
    if found is None:
        raise steps.StepFailure("not_configured", name)
    return found


def _asked(call, *args):
    """A service call whose failure is a closed code of the step."""
    try:
        return call(*args)
    except steps.StepFailure:
        raise
    except Exception as e:      # the services raise errors that carry a `code`; anything else is a provider failure
        code = SERVICE_CODES.get(getattr(e, "code", ""), "provider_failed")
        raise steps.StepFailure(code, "mailbox", "writer", str(getattr(e, "reason", ""))[:200] if code != "provider_failed" else "") from None


def _positions(numbers) -> str:
    return ", ".join(str(n) for n in numbers)


def _already(doc_pieces: dict, items: list, real_folder) -> list:
    """The positions of the messages that are already as the change would leave them (nothing would change)."""
    account, action = doc_pieces["account"], doc_pieces["action"]
    out = []
    for item in items:
        if account == "google":
            labels = item["labels"]
            same = ("INBOX" not in labels if action == "archive" else doc_pieces["folder_id"] in labels if action == "move"
                    else ("UNREAD" not in labels) == (doc_pieces["state"] == "read") if action == "mark" else "TRASH" in labels)
        else:
            same = item["is_read"] == (doc_pieces["state"] == "read") if action == "mark" else item["folder_id"] == real_folder
        if same:
            out.append(item["n"])
    return out


def _reply_of(account: str, entry: dict, live: dict, ref_subject: str) -> dict:
    """The message a draft answers, as the mailbox says it now, with the Reply-To the index recorded (shown on the card, never used)."""
    sender = entry["from_address"]
    if sender is None or not isinstance(live.get("from_address"), str) or live["from_address"].lower() != sender.lower():
        raise steps.StepFailure("sender_changed", "reply", "writer", "the sender of this message is not the one the snapshot recorded (or it has none): nothing is answered")
    thread = live.get("thread_id") or entry["thread_id"]
    message_id = live.get("message_id") or entry["message_id"]
    if account == "google" and (not thread or not message_id or not send_document.REFERENCE.fullmatch(message_id)):
        raise steps.StepFailure("not_replyable", "reply", "writer", "this message has no thread or Message-ID a reply can follow")
    reply_to = entry["reply_to_address"]
    return {"ref": entry["ref"], "id": entry["id"], "thread_id": thread if account == "google" else None, "message_id": message_id if account == "google" else None,
            "sender": sender, "reply_to": reply_to if reply_to and reply_to.lower() != sender.lower() else None, "subject": ref_subject,
            "date": mailbox_document.local_text(live.get("date")), "snapshot_at": entry["snapshot_at"]}


def _prepare(ctx: steps.Context, state: dict) -> dict:
    args = ctx.args
    reader, files = _service(ctx, "mailbox_read"), _service(ctx, "effect_files")
    account, action = args["account"], args["action"]
    if not reader.enabled(account):
        raise steps.StepFailure("not_configured", "account", "", "list the account in docs/workbench/runtime.json (the key accounts) and accept the file")
    pieces = dict(task_id=ctx.task_id, account=account, address=reader.address(account), action=action, zone=mailbox_document.zone_name(),
                  read_at=mailbox_document.utc_text(ctx.now()))
    google, real_folder = account == "google", None
    if action == "move":
        folder_id, why = reader.target(account, args["folder"])
        if why:
            raise steps.StepFailure("target_refused", "folder", "", why[:200])
        if not mailbox_document.destination_ok(account, folder_id):
            raise steps.StepFailure("target_refused", "folder", "", "that folder cannot be a place for a move (it is the inbox, the trash or another label that means something else)")
        pieces.update(folder=args["folder"], folder_id=folder_id, remove_inbox=google and reader.move_removes_inbox(account))
    elif not google and action in ("archive", "trash"):
        pieces.update(folder_id="archive" if action == "archive" else "deleteditems")
    if action == "mark":
        pieces.update(state=args["state"])
    if not google and pieces.get("folder_id"):      # the destination must exist, and its real id tells a message that is already there
        got = _asked(reader.folder_get, account, pieces["folder_id"])
        if not isinstance(got, dict) or got.get("found") is not True or not isinstance(got.get("id"), str):
            raise steps.StepFailure("folder_gone", "folder", "writer", "that folder is not in the mailbox (or the account has no such folder yet)")
        real_folder = got["id"]
        if action == "move":      # a mail_folders id that IS Deleted Items, Junk, Drafts... under another name is not a place for a move: the trash is mail-trash's
            for name in mailbox_document.FORBIDDEN_MOVE_FOLDERS:
                other = _asked(reader.folder_get, account, name)
                if isinstance(other, dict) and other.get("found") is True and other.get("id") == real_folder:
                    raise steps.StepFailure("target_refused", "folder", "", "that folder is one of the provider's own that a move never reaches (the trash, the junk folder, Drafts...): use mail-trash for the trash")
    try:
        if action == "draft":
            if args.get("reply") is not None:
                entry = args["reply"]
                live = _asked(reader.message_meta, account, [entry["id"]])[0]
                if live.get("found") is not True or live.get("is_draft") is True:
                    raise steps.StepFailure("message_gone", "reply", "writer", "that message is not in the mailbox any more")
                subject = mailbox_document.clean_line(live.get("subject"), send_document.SUBJECT_MAX)
                reply = _reply_of(account, entry, live, subject)
                draft = {"to": [reply["sender"]], "cc": [], "bcc": [], "subject": mailbox_document.reply_subject(subject), "body": args["body"], "reply": reply}
            else:
                draft = {"to": args["to"], "cc": args["cc"], "bcc": args["bcc"], "subject": args["subject"], "body": args["body"], "reply": None}
            pieces.update(draft=draft)
        else:
            entries = args["messages"]
            rows = _asked(reader.message_meta, account, [e["id"] for e in entries])
            items, gone = [], []
            for number, (entry, row) in enumerate(zip(entries, rows), 1):
                if row.get("found") is not True or row.get("is_draft") is True:
                    gone.append(number)
                    continue
                items.append(mailbox_document.message_item(account, number, entry["ref"], entry["snapshot_at"], row))
            if gone:
                raise steps.StepFailure("message_gone", "messages", "writer", f"the messages at positions {_positions(gone)} are not in the mailbox any more (or are drafts): "
                                        "refresh the source and name them again")
            same = _already(dict(account=account, action=action, folder_id=pieces.get("folder_id"), state=pieces.get("state")), items, real_folder)
            if same:
                raise steps.StepFailure("nothing_to_change", "messages", "", f"the messages at positions {_positions(same)} are already as asked: ask again without them")
            pieces.update(messages=items)
        draft_doc = mailbox_document.document(**pieces, dry_run_sha256="0" * 64)
    except steps.StepFailure:
        raise
    except Exception as e:      # an EffectError of the document: its reason names a limit, never the content
        raise steps.StepFailure("content_refused", "args", "", str(getattr(e, "reason", ""))[:200]) from None
    shown = _asked(reader.dry_run, draft_doc)
    would, digest = shown.get("would") if isinstance(shown, dict) else None, shown.get("would_sha256") if isinstance(shown, dict) else None
    if not isinstance(would, dict) or not isinstance(digest, str) or not mailbox_document.SHA256.fullmatch(digest) or not mailbox_document.requests_match(draft_doc, would):
        raise steps.StepFailure("preview_mismatch", "writer", "writer", "the writer would send something other than the arguments say: nothing is asked about it")
    doc = mailbox_document.document(**pieces, dry_run_sha256=digest)
    written = _asked(files.write, ctx.task_id, int(state.get("cycle", 0)), doc)
    return {"effect_sha256": written, "action": action, "account": account, "count": len(doc["messages"]) if doc["messages"] else 1}


def _open(ctx: steps.Context, state: dict) -> dict:
    """The effect decision of the gate: the effect document read back by the hash `prepare` recorded, its card, its hash."""
    recorded = state["steps"]["prepare"]["result"]["effect_sha256"]
    doc = _service(ctx, "effect_files").read(ctx.task_id, int(state.get("cycle", 0)), recorded)
    mailbox_document.check(doc)
    return {"title": mailbox_document.title(doc), "body": mailbox_document.body(doc, recorded), "payload_sha256": recorded,
            "payload": {"effect": mailbox_document.summary(doc), "card": mailbox_document.card_lines(doc, recorded)}}


KIND = steps.register(steps.Kind(
    name="mailbox-change",
    order=("prepare", GATE_STEP),
    executors={"prepare": _prepare},
    gates={GATE_STEP: steps.Gate(word=mailbox_document.WORD, open=_open, redo="prepare")},
    footprint=lambda args: (),
    check=check,
    unattended=False,
))


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
