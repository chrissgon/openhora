#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The files family of the natural writes, with the project (package NR-5a): a new file, a new revision of a file that is a source, the saving of a file the sender sent. Each
slot is code: the account is a service word of the line (or a Google Doc), the one account that lists folders, `accounts.default`, or the person's choice; a folder is a name the
account lists, folded, or the default; a file name must pass the same check the typed command's does (runtime/files_document.py) and is asked when it does not; the file to
replace is `source_resolve.resolve` over the registered Drive and OneDrive sources (one is used and named on the card, several are listed, none is said); the file to save is
a file THIS sender sent: exactly one, or exactly one of the kind the line names, else the sender's files are listed (a file of someone else is never named).

resolve(ctx, op, slots, channel, sender, said) -> {"args"} | {"ask"} | {"say"} (the interface of runtime/natural_writes.py).

Sibling of runtime/ops_natural_writes.py. Standard library only. Runs on Python 3.9: python3 runtime/ops_natural_files.py --help
"""
from __future__ import annotations

import importlib
import sys

import attachments as att
import files_document as fd
import natural
import ops_actor
import ops_core as core
import source_resolve
import sources

SOURCE_ACCOUNT = {"drive": "google", "onedrive": "microsoft"}      # the type of a file source -> the account it belongs to


def _w():
    return importlib.import_module("ops_natural_writes")


def held_files(ctx: dict, channel, sender) -> list:
    """The files held for an answer that THIS caller may name: on a messaging app only those the sender sent; the terminal and the page see them all. Oldest first."""
    rows = core._stored(ctx, ctx["store"].attachments_list, ["held"])
    if channel == att.CHANNEL:
        platform, ident = ops_actor.split(sender)
        rows = [r for r in rows if (r["platform"], r["sender"]) == (platform, ident)]
    return [att.public(r) for r in rows]


def _create(ctx: dict, slots: dict):
    w = _w()
    wanted = slots.get("account") or ("google" if slots.get("gdoc") else None)
    state, account = w.pick_account(ctx, wanted, "folders")
    if state == "spec":
        return account
    state, folder = w.named_target(ctx, account, "folders", slots.get("folder"), "folder")
    if state == "spec":
        return folder
    name = slots["name"]
    if slots.get("gdoc") and not fd.extension_of(name):
        name = name + "." + fd.GDOC_WORD
    if fd.name_problem(name, fd.CREATE_EXTENSIONS + (fd.GDOC_WORD,)):
        return w.ask_spec("name", "NW_ASK_FILE_NAME")
    args = {"account": account, "file_name": name, "content": slots["content"]}
    if folder:
        args["folder"] = folder
    return {"args": args}


def _replace(ctx: dict, slots: dict):
    w = _w()
    rows = [r for r in sources.list_catalog(ctx, hashes=False) if r["type"] in SOURCE_ACCOUNT]
    if "file" in slots:
        chosen = [r for r in rows if r["id"] == slots["file"]]
    else:
        cue = (natural.words_of("cues") or [""])[0]
        found = source_resolve.resolve(f"{cue} {slots['words']}".strip(), rows)
        if found["kind"] == "ask":
            labels = {r["id"]: source_resolve.label(r) for r in found["rows"]}
            return w.ask_spec("file", "NW_ASK_FILE", options=[{"value": i, "label": labels[i]} for i in found["ids"]])
        if found["kind"] != "one":
            return w.say_spec("NAT_NO_SOURCE")
        chosen = found["rows"]
    if not chosen:
        return w.say_spec("NAT_NO_SOURCE")
    row = chosen[0]
    return {"args": {"account": SOURCE_ACCOUNT[row["type"]], "file": row["id"], "content": slots["content"]}}


def _save(ctx: dict, slots: dict, channel, sender):
    w = _w()
    if slots.get("attachment") is not None and slots["attachment"] not in [r["id"] for r in held_files(ctx, channel, sender)]:
        return w.say_spec("ATT_NO_SUCH", n=slots["attachment"])          # a file somebody else sent, or one no longer held, is a file that does not exist
    if slots.get("attachment") is None:
        held = held_files(ctx, channel, sender)
        if not held:
            return w.say_spec("NW_NO_HELD")
        if slots.get("kind"):
            held = [r for r in held if r.get("kind") == slots["kind"] or str(r.get("name") or "").lower().endswith("." + slots["kind"])]
            if not held:
                return w.say_spec("NW_NO_HELD_KIND", kind=slots["kind"])
        if len(held) > 1:
            cfg = ctx["cfg"]
            return w.ask_spec("attachment", "NW_ASK_ATTACHMENT", options=[{"value": r["id"], "label": f"{r['name']} ({att.size_text(r.get('bytes') or 0, cfg)})"} for r in held])
        slots = dict(slots, attachment=held[0]["id"])
    state, account = w.pick_account(ctx, slots.get("account"), "folders")
    if state == "spec":
        return account
    state, folder = w.named_target(ctx, account, "folders", slots.get("folder"), "folder")
    if state == "spec":
        return folder
    args = {"account": account, "attachment": slots["attachment"]}
    if folder:
        args["folder"] = folder
    return {"args": args}


def resolve(ctx: dict, op: str, slots: dict, channel, sender, said):
    if op == "file-create":
        return _create(ctx, slots)
    if op == "file-replace":
        return _replace(ctx, slots)
    return _save(ctx, slots, channel, sender)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
