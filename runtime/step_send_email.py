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

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import send_document  # noqa: E402
import steps  # noqa: E402

KEYS = ("to", "cc", "bcc", "subject", "body", "attach", "in_reply_to")
SERVICE_CODES = {"not_configured": "not_configured", "provider_failed": "provider_failed", "refused": "refused"}
GATE_STEP = "send"


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


def check(args) -> dict:
    """The arguments of a send-email, checked and normalised (the addresses in their normal form, joined by ', ')."""
    if not isinstance(args, dict) or set(args) - set(KEYS):
        raise steps.StepFailure("bad_args", "args")
    lists = {name: _checked(send_document.addresses, _text(args, name) if name in args else "", name, field=name) for name in ("to", "cc", "bcc")}
    if "to" not in args:
        raise steps.StepFailure("bad_args", "to", "", "give at least one address")
    _checked(send_document.check_recipients, "", lists["to"], lists["cc"], lists["bcc"], field="to")
    subject = _checked(send_document.check_subject, _text(args, "subject") if "subject" in args else None, field="subject")
    _checked(send_document.check_body, _text(args, "body") if "body" in args else None, field="body")
    out = {"to": ", ".join(lists["to"]), "subject": subject, "body": args["body"]}
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
        raise steps.StepFailure(SERVICE_CODES.get(getattr(e, "code", ""), "provider_failed"), "outbox", "mailer") from None


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
            and shown.get("body_sha256") == doc["body_sha256"] and shown.get("idempotency_key") == doc["idempotency_key"]
            and [(a.get("name"), a.get("bytes"), a.get("sha256")) for a in shown.get("attachments") or []]
            == [(a["name"], a["bytes"], a["sha256"]) for a in doc["attachments"]])


def _prepare(ctx: steps.Context, state: dict) -> dict:
    args = ctx.args
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
    return {"title": send_document.title(doc)[:200], "body": send_document.body(doc, recorded), "payload_sha256": recorded,
            "payload": {"effect": send_document.summary(doc)}}


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
