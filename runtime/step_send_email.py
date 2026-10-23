#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The step kind `send-email`: send an e-mail from the project's outbox, as an external effect the person approves (package EMAIL-SEND).
The kind prepares; it never sends. Two steps, as in a write-back:

  prepare   checks the recipients, the subject and the body, reads each attachment (a regular file under docs/ of the project, never of
            the sources folder, no link on the way), takes the sender from the project's `outbox`, asks the provider for a dry run through
            the read-only outbox service (nothing is sent, no credential is read, no connection is opened), checks that what the provider
            would send is what the arguments say (the envelope, the subject, the body, each attachment), and writes the effect document
            (runtime/send_document.py) through the effect-files service to <data_dir>/step-effects/<task id>/<cycle>/effect.json, 0600 in a
            0700 folder.
  send      the gate (runtime/steps.py, Gate): it has no executor. It opens an `effect` decision whose hash is the hash of the effect
            document and whose body shows the sender, every recipient (the Bcc too), the subject, the text whole and each attachment by
            name, size and hash; the task waits. The person approves the hash in the terminal or on the page (any other channel is
            refused, unless the project's policy grants it, and an e-mail with an attachment is never whole on a messaging card), and then
            runtime/ops_step_effects.py calls the effect module (runtime/effect_send.py), which checks each attachment is still the file
            the task read, and sends once. An attachment changed meanwhile answers the decision, sends nothing and sends the task back to
            `prepare`.

Arguments (checked when the task is planned, so the plan's hash covers exactly what will be asked about):

  {"to": "a@x.example, b@y.example", "subject": "<one line>", "body": "<text>"
   [, "cc": "...", "bcc": "...", "attach": ["docs/<path>.pdf", ...], "in_reply_to": "<id@host>"]}

`to`, `cc` and `bcc` are comma-separated plain addresses (no display name; the word `none` is no one); at most 20 recipients in all; the
subject is one line of at most 200 characters; the body at most 100 KB; at most 10 attachments, of the extensions pdf, docx, xlsx, pptx, odt,
txt, csv, md, png, jpg, 18 MB together. The sender is never an argument: it is the `from` of the project's `outbox`.

Limit L30, in the structure of this file: it imports no module that calls a provider. What it needs of the outbox and of the data folder it
asks of `ctx.services` (runtime/ops_step_seams.py), where `outbox` has a dry run and no way to send, and `effect_files` writes and reads the
effect document and does not execute it. The only code that sends is runtime/effect_send.py `execute`, which this file cannot reach.

The kind is not `unattended`: a send starts when the person starts it and ends at the person's approval. It writes no file of the project
(its footprint is empty).

From the person's own account (package W2, SPEC-SECRETARY-WRITES 3.2). With `account` (`google` or `microsoft`) the sender is that account, never the outbox: its
address is `accounts.<account>.address` of the project, the mailer is the account's (`gmail`, `outlook`: an implementation of the same class, named explicitly),
and the dry run asks that mailer. A reply is `{"account": ..., "reply": "<source id>#<n>", "body": "..."}`: the recipient is the SENDER of the message answered, as
the index of the snapshot recorded it (runtime/item_refs.py, through the read-only seam `account_mail`), never an address of the message's text and never its
`Reply-To`, which the card shows and does not use (limit L60); the subject is `Re: ` and the subject the index kept; In-Reply-To, References and, for Gmail, the
conversation come from the index. A reply has no To, Cc, Bcc, subject or attachment of its own, and there is no reply to all. The card is made of fixed lines of the
phrase table (`payload["card"]`), the person's text behind a mark on every line, and its title is fixed text.

  {"account": "google" | "microsoft", "to": "...", "subject": "<one line>", "body": "<text>" [, "cc": "...", "bcc": "...", "attach": [...]]}      a new e-mail
  {"account": "google" | "microsoft", "reply": "<source id>#<n>", "body": "<text>"}                                                             a reply

A Bcc is not sent from a Google account in this version (the Gmail API reads the recipients from the message's headers, and whether it removes a Bcc header before
delivery is not verified): it is refused here and again by the mailer. Who may use a reference into a snapshot is bound into the task: the operation
(runtime/ops_mail_send.py) writes `channel` (terminal, page or messaging) and, for messaging, `sender` into the arguments of a reply as the caller gave them, the check
below is strict about them, and the preparation resolves the reference with them (a messaging sender needs the group `ask-mail`), never as the operations' own call.
The operation also writes `reply_pin`, the service id and the Message-ID of the message it resolved; a preparation whose reference now names another message (a
refreshed snapshot renumbers its items) is refused. `steps.plan_task` refuses these arguments and `account` and `reply` in a plan or a flow: only the outbox's
e-mail is a plan's task.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import mail_refs  # noqa: E402
import phrases  # noqa: E402
import send_document  # noqa: E402
import steps  # noqa: E402

KEYS = ("to", "cc", "bcc", "subject", "body", "attach", "in_reply_to", "account", "reply", "reply_pin", "channel", "sender")
CHANNELS = ("terminal", "page", "messaging")      # who asked, for the right to read a snapshot (runtime/item_refs.py): written by the operation, never by a person
SENDER = re.compile(r"[a-z][a-z0-9-]{0,31}:[A-Za-z0-9_.@+=-]{1,128}")
REPLY_FORBIDS = ("to", "cc", "bcc", "subject", "in_reply_to", "attach")      # a reply has none of these of its own
SERVICE_CODES = {"not_configured": "not_configured", "provider_failed": "provider_failed", "refused": "refused"}
GATE_STEP = "send"
REFUSED_NEXT = ("the provider would not build this e-mail exactly as written (an address, a subject it could not encode exactly, a text it could "
                "not read back the same): shorten or simplify the subject, check the addresses, and start the task again")
REFUSED_NEXT_OWN = ("the mailer would not take this e-mail as written (an address, the subject, an attachment over the size it takes, or a text it could not read back "
                    "the same): check them, and start the task again")      # the mailer's own sentence can quote an address, a subject or a file name; this one never does


def _text(args: dict, field: str) -> str:
    value = args.get(field)
    if not isinstance(value, str):
        raise steps.StepFailure("bad_args", field)
    return value


def _checked(call, *a, field: str, hint: str = ""):
    """A check of the document module whose refusal is a bad argument: the sentence names the rule, never the content."""
    try:
        return call(*a)
    except Exception as e:      # an EffectError of the document, with its `reason`
        raise steps.StepFailure("bad_args", field, "", (hint or str(getattr(e, "reason", "")))[:200]) from None


def _own_text(field: str, text) -> None:
    """A text of an e-mail from the person's own account that its card could not show, or that could pass for the frame of the card, is a bad argument."""
    problem = send_document.text_problem(text, multiline=field == "body")
    if problem:
        raise steps.StepFailure("bad_args", field, "", problem[:200])


def _check_reply(args: dict) -> dict:
    """The arguments of a reply from the person's own account: the account, the reference of the message answered and the text."""
    for name in REPLY_FORBIDS:
        if name in args:
            raise steps.StepFailure("bad_args", name, "", phrases.en("ACCT_MAIL_REPLY_FIELDS")[:200])
    reference = args["reply"]
    if not isinstance(reference, str) or not send_document.SNAPSHOT_REF.fullmatch(reference):
        raise steps.StepFailure("bad_args", "reply", "", "name the message as <source id>#<number>, for example inbox#3")
    body = send_document.lines_as_lf(_text(args, "body")) if "body" in args else None
    _checked(send_document.check_body, body, field="body")
    _own_text("body", body)
    out = {"account": args["account"], "reply": reference, "body": body}
    if args.get("channel") not in CHANNELS:      # who asks is never left to a default: a missing channel would read as full rights on a snapshot
        raise steps.StepFailure("bad_args", "channel", "", "say who asks: terminal, page or messaging")
    out["channel"] = args["channel"]
    if args.get("sender") is not None:
        if not isinstance(args["sender"], str) or not SENDER.fullmatch(args["sender"]) or args["channel"] != "messaging":
            raise steps.StepFailure("bad_args", "sender", "", "a sender is <platform>:<id> and goes with the channel messaging")
        out["sender"] = args["sender"]
    elif args["channel"] == "messaging":
        raise steps.StepFailure("bad_args", "sender", "", "a messaging reply names the sender who asks")
    pin = args.get("reply_pin")
    if pin is not None:      # written by the operation: the message the reference named when it was resolved
        if not isinstance(pin, dict) or set(pin) != {"id", "message_id"} or not isinstance(pin["id"], str) or send_document.PROVIDER_ID.fullmatch(pin["id"]) is None \
                or not isinstance(pin["message_id"], str) or send_document.REFERENCE.fullmatch(pin["message_id"]) is None:
            raise steps.StepFailure("bad_args", "reply_pin", "", "the message a reply answers is pinned by its id and its Message-ID")
        out["reply_pin"] = {"id": pin["id"], "message_id": pin["message_id"]}
    return out


def check(args) -> dict:
    """The arguments of a send-email, checked and normalised (the addresses in their normal form, joined by ', ')."""
    if not isinstance(args, dict) or set(args) - set(KEYS):
        raise steps.StepFailure("bad_args", "args")
    for name in ("reply_pin", "channel", "sender"):
        if name in args and args.get("reply") is None:
            raise steps.StepFailure("bad_args", name, "", "only a reply is pinned to a message and bound to who asked")
    if "account" not in args and "reply" in args:
        raise steps.StepFailure("bad_args", "reply", "", "a reply is sent from one of your own accounts: give account (google or microsoft)")
    if "account" in args:
        if args["account"] not in send_document.ACCOUNTS:
            raise steps.StepFailure("bad_args", "account", "", "give google or microsoft")
        if args.get("reply") is not None:
            return _check_reply(args)
        if args.get("in_reply_to") is not None:
            raise steps.StepFailure("bad_args", "in_reply_to", "", "an answer to a message is a reply: give reply as <source id>#<number>")
    out = _check_outbox(args)
    if "account" in args:
        if args["account"] == "google" and out.get("bcc"):
            raise steps.StepFailure("bad_args", "bcc", "", phrases.en("ACCT_MAIL_BCC_GMAIL")[:200])
        _own_text("subject", out["subject"])
        _own_text("body", out["body"])
        out["account"] = args["account"]
    return out


def _check_outbox(args: dict) -> dict:
    """The arguments of a new e-mail, whoever sends it."""
    lists = {name: _checked(send_document.addresses, _text(args, name) if name in args else "", name, field=name) for name in ("to", "cc", "bcc")}
    if "to" not in args:
        raise steps.StepFailure("bad_args", "to", "", "give at least one address")
    _checked(send_document.check_recipients, "", lists["to"], lists["cc"], lists["bcc"], field="to")
    subject = _checked(send_document.check_subject, _text(args, "subject") if "subject" in args else None, field="subject")
    body = send_document.lines_as_lf(_text(args, "body")) if "body" in args else None
    _checked(send_document.check_body, body, field="body")
    out = {"to": ", ".join(lists["to"]), "subject": subject, "body": body}
    for name in ("cc", "bcc"):
        if lists[name]:
            out[name] = ", ".join(lists[name])
    if args.get("in_reply_to") is not None:
        out["in_reply_to"] = _checked(send_document.check_reference, args["in_reply_to"], field="in_reply_to")
    attach = args.get("attach")
    if attach is not None:
        if not isinstance(attach, list) or len(attach) > send_document.ATTACH_MAX:
            raise steps.StepFailure("bad_args", "attach", "", f"give at most {send_document.ATTACH_MAX} files of docs/")
        names = set()
        for rel in attach:
            if not isinstance(rel, str) or not steps.REL_PATH.fullmatch(rel) or not send_document.DOCS_PATH.fullmatch(rel) \
                    or ".." in rel.split("/") or rel.endswith(".comments.md"):
                raise steps.StepFailure("bad_args", "attach", "", "give files under docs/")
            name = _checked(send_document.attachment_name, rel.rsplit("/", 1)[-1], field="attach")
            if name.lower() in names:
                raise steps.StepFailure("bad_args", "attach", "", "two attachments have the same file name")
            names.add(name.lower())
        if attach:
            out["attach"] = list(attach)
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
        raise steps.StepFailure(code, "outbox", "mailer", REFUSED_NEXT if code == "refused" else "") from None


def _attachments(ctx: steps.Context) -> list:
    """[{path, name, bytes, sha256, data}] of the files the arguments name, read with steps.read_file (no link anywhere on the way, never the
    sources folder, a regular file); the total is held under the cap as it grows. StepFailure: attachment_missing, attachment_too_large,
    protected_path, path_unsafe."""
    found, left = [], send_document.ATTACH_TOTAL_MAX
    for rel in ctx.args.get("attach", []):
        try:
            data = steps.read_file(ctx, rel, left)
        except steps.StepFailure as e:
            code = {"missing": "attachment_missing", "too_large": "attachment_too_large"}.get(e.code, e.code)
            raise steps.StepFailure(code, "attach", "", "write the file first, then start this task" if code == "attachment_missing" else
                                    "send fewer or smaller files: the attachments are at most 18 MB together"
                                    if code == "attachment_too_large" else "") from None
        left -= len(data)
        found.append({"path": rel, "name": rel.rsplit("/", 1)[-1], "bytes": len(data), "sha256": send_document.sha(data), "data": data})
    return found


def _same(doc: dict, shown: dict) -> bool:
    """Whether what the provider's dry run says it would send is what the document says: the sender and every recipient of the envelope, the
    headers, the text and each attachment. The provider builds its own preview from the same flags; a difference is a refusal."""
    headers, envelope = shown.get("headers") or {}, shown.get("envelope") or {}
    return (envelope.get("from") == doc["from"] and envelope.get("to") == send_document.recipients(doc)
            and headers.get("To") == ", ".join(doc["to"]) and (headers.get("Cc") or "") == ", ".join(doc["cc"])
            and headers.get("Subject") == doc["subject"] and headers.get("Message-ID") == doc["message_id"]
            and headers.get("In-Reply-To") == doc["in_reply_to"] and "Bcc" not in headers and shown.get("body") == doc["body"]
            and (headers.get("References") or None) == (" ".join(doc.get("references") or []) or None) and shown.get("thread_id") == doc.get("thread_id")
            and shown.get("reply_id") == (doc["reply"]["provider_id"] if doc.get("account") == "microsoft" and doc.get("reply") else None)
            and shown.get("body_sha256") == doc["body_sha256"] and shown.get("idempotency_key") == doc["idempotency_key"]
            and [(a.get("name"), a.get("bytes"), a.get("sha256")) for a in shown.get("attachments") or []]
            == [(a["name"], a["bytes"], a["sha256"]) for a in doc["attachments"]])


def _asked_own(call, *args, words: bool = False):
    """A call of the account service whose failure is a closed code of the step. `words`: the call is the reading of the message a reply answers, whose refusal carries
    a sentence written by code from the phrase table (it names the reference, never a text). Any other refusal (the mailer's dry run, the write of the document)
    has the step's fixed sentence: a mailer's own sentence can quote an address, a subject or a file name, and the task's note and failure are read by every channel.
    The mailer's exact sentence is not lost: it is the failure's `detail`, returned to the one who started the step and stored nowhere."""
    try:
        return call(*args)
    except steps.StepFailure:
        raise
    except Exception as e:
        code = SERVICE_CODES.get(getattr(e, "code", ""), "provider_failed")
        reason = " ".join(str(getattr(e, "reason", "") or "").split())[:200] if code == "refused" else ""
        reason = reason[len("error: "):] if reason.startswith("error: ") else reason      # the mailer's own sentence, without its prefix
        if words:
            raise steps.StepFailure(code, "account", "mailer", reason or (REFUSED_NEXT_OWN if code == "refused" else "")) from None
        raise steps.StepFailure(code, "account", "mailer", REFUSED_NEXT_OWN if code == "refused" else "", detail=reason) from None


def _prepare_own(ctx: steps.Context, state: dict) -> dict:
    """The preparation of an e-mail from the person's own account: the account and its address from the project's `accounts`, the message answered (a reply) from the
    index of the snapshot, a dry run by the account's mailer, and the effect document."""
    args = ctx.args
    mail, files = _service(ctx, "account_mail"), _service(ctx, "effect_files")
    account = args["account"]
    if not mail.enabled(account):
        raise steps.StepFailure("not_configured", "account", "", phrases.en("ACCT_NOT_CONFIGURED").format(account=account)[:200])
    reply, read = None, []
    if args.get("reply"):
        facts = _asked_own(mail.reply_facts, args["reply"], account, args.get("channel"), args.get("sender"), words=True)
        moved = mail_refs.pin_problem(args.get("reply_pin"), facts)      # the reference may name another message than the one the operation resolved
        if moved:
            raise steps.StepFailure("reply_moved", "reply", "mailer", moved[:200])
        reply = {k: facts[k] for k in send_document.REPLY_KEYS}
        recipients = dict(to=[facts["address"]], cc=[], bcc=[], subject=mail_refs.reply_subject(facts["subject"]), in_reply_to=facts["message_id"],
                          references=[facts["message_id"]], thread_id=facts["thread_id"])
    else:
        read = _attachments(ctx)
        recipients = dict(to=send_document.addresses(args["to"], "to"), cc=send_document.addresses(args.get("cc", ""), "cc"),
                          bcc=send_document.addresses(args.get("bcc", ""), "bcc"), subject=args["subject"], in_reply_to=None, references=[], thread_id=None)
    pieces = dict(task_id=ctx.task_id, provider=mail.implementation(account), from_addr=mail.address(account), body=args["body"], account=account, reply=reply,
                  attachments=[{k: a[k] for k in ("path", "name", "bytes", "sha256")} for a in read], **recipients)
    try:
        draft = send_document.document(**pieces, dry_run_sha256="0" * 64)
    except Exception as e:      # an EffectError of the document: its reason names a limit, never the content
        raise steps.StepFailure("content_refused", "body", "", str(getattr(e, "reason", ""))[:200]) from None
    shown = _asked_own(mail.dry_run, draft, [a["data"] for a in read])
    would, digest = shown.get("would") if isinstance(shown, dict) else None, shown.get("would_sha256") if isinstance(shown, dict) else None
    if not isinstance(would, dict) or not isinstance(digest, str) or not send_document.SHA256.fullmatch(digest) or not _same(draft, would):
        raise steps.StepFailure("preview_mismatch", "account", "mailer", "the mailer would send something other than the arguments say: nothing is asked about it")
    doc = send_document.document(**pieces, dry_run_sha256=digest)
    written = _asked_own(files.write, ctx.task_id, int(state.get("cycle", 0)), doc)
    return {"effect_sha256": written, "recipients": len(send_document.recipients(doc)), "attachments": len(read), "bytes": len(doc["body"].encode("utf-8"))}


def _prepare(ctx: steps.Context, state: dict) -> dict:
    args = ctx.args
    if args.get("account"):
        return _prepare_own(ctx, state)
    outbox, files = _service(ctx, "outbox"), _service(ctx, "effect_files")
    if not outbox.enabled():
        raise steps.StepFailure("not_configured", "outbox", "", "configure an outbox in docs/workbench/runtime.json")
    provider = _asked(outbox.provider)
    read = _attachments(ctx)
    pieces = dict(task_id=ctx.task_id, provider=provider, from_addr=outbox.sender(), to=send_document.addresses(args["to"], "to"),
                  cc=send_document.addresses(args.get("cc", ""), "cc"), bcc=send_document.addresses(args.get("bcc", ""), "bcc"),
                  subject=args["subject"], body=args["body"], in_reply_to=args.get("in_reply_to"),
                  attachments=[{k: a[k] for k in ("path", "name", "bytes", "sha256")} for a in read])
    try:
        draft = send_document.document(**pieces, dry_run_sha256="0" * 64)
    except Exception as e:      # an EffectError of the document: its reason names a limit, never the content
        raise steps.StepFailure("content_refused", "body", "", str(getattr(e, "reason", ""))[:200]) from None
    shown = _asked(outbox.dry_run, draft, [a["data"] for a in read])
    would, digest = shown.get("would") if isinstance(shown, dict) else None, shown.get("would_sha256") if isinstance(shown, dict) else None
    if not isinstance(would, dict) or not isinstance(digest, str) or not send_document.SHA256.fullmatch(digest) or not _same(draft, would):
        raise steps.StepFailure("preview_mismatch", "outbox", "mailer", "the provider would send something other than the arguments say: "
                                "nothing is asked about it")
    doc = send_document.document(**pieces, dry_run_sha256=digest)
    written = _asked(files.write, ctx.task_id, int(state.get("cycle", 0)), doc)
    return {"effect_sha256": written, "recipients": len(send_document.recipients(doc)), "attachments": len(read),
            "bytes": len(doc["body"].encode("utf-8"))}


def _open(ctx: steps.Context, state: dict) -> dict:
    """The effect decision of the gate: the effect document read back by the hash `prepare` recorded, its preview, its hash."""
    recorded = state["steps"]["prepare"]["result"]["effect_sha256"]
    doc = _service(ctx, "effect_files").read(ctx.task_id, int(state.get("cycle", 0)), recorded)
    send_document.check(doc)
    payload = {"effect": send_document.summary(doc)}
    if send_document.is_own(doc):      # the card, line by line: the phrase table says it in the project's language, the hash stays the effect's
        payload["card"] = send_document.card_lines(doc, recorded)
    return {"title": send_document.title(doc)[:200], "body": send_document.body(doc, recorded), "payload_sha256": recorded, "payload": payload}


KIND = steps.register(steps.Kind(
    name="send-email",
    order=("prepare", GATE_STEP),
    executors={"prepare": _prepare},
    gates={GATE_STEP: steps.Gate(word=send_document.WORD, open=_open, redo="prepare")},
    footprint=lambda args: (),
    check=check,
    unattended=False,
))


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
