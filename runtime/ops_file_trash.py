#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Move a file to the trash of the person's own Drive or OneDrive, found by its name (slice R2-A): `file-trash`, a class E operation (an effect with a card).

  file_trash(project, file, [account], [folder], [channel, sender])   the operation (the typed command, the page, a messaging app): {"status", ...}, below
  reply(project, ctx, args, said, channel, sender, extras)            the reply a line in words gets (runtime/ops_interpret.py `_carry_out`, and `line` below)
  line(project, ctx, said, channel, sender, extras)                   the reply to a line that asks to delete a file when its name can be read by code alone (runtime/phone_delete.py `name`)
  pick(project, ctx, match, channel, sender, extras)                  the reply to "o 2" said right after a list of files to move to the trash (runtime/ops_file_read.py `take`)
  catches(ctx, said, channel, sender)                                 whether code alone answers a line that asks to delete a file (runtime/ops_say.py, the bridge)

What it finds, and nothing else: the same search as `file-read` (runtime/ops_file_read.py: the folders the project lists under `accounts.<google|microsoft>.folders` and their subfolders,
the same ranking of the name, the same account and folder narrowing, the same list and the same "o 2"). A file outside the listed folders is never listed, never named and never
trashed. One match opens a CARD: the file's name, its folder by the real names of the folders, the account, its size and last change where the listing gave them, and where it goes
("goes to the Google Drive trash, recoverable for about 30 days" / "goes to the OneDrive trash, recoverable while it is in the trash"). When the name found is not the exact name the
person gave, the card's first line asks "Found: <name> in <folder>. Is this the one?"; a file chosen from a list by its number is the person's choice and does not ask it. Several matches are
listed with numbers; none gets the sentence `file-read` gives. NOTHING is moved here: the card is the effect kind `files` with the operation `trash` (runtime/files_document.py,
runtime/step_files.py, runtime/effect_files.py), approved by its hash like every file write (the group `approve-effect-files`, or the terminal and the page), and the move is made once, by
the writer's `trash` verb, only if the grant still holds (the folder is still listed under its name and the file is still found under it) and the file is still the version the card was
made from. The trash is the service's own: the person restores the file from there, and no verb of any writer deletes for good (limit L57).

Who may ask: the group `files-trash` (a group of its own, in no default policy and never part of `files-write`, so a project that accepted that group does not gain the trash) AND `read-files`
beside it (the search lists file names, as a read does; the configuration refuses one without the other, and the right is asked again here). A messaging sender without them gets the refusal
sentence, or for a line that asks to delete a file the plain sentence that it is not done from a message, and no provider is called; the page and the terminal follow the table of operations. What is kept (limits L50, L61 and L63): the conversation stores a neutral word for the reply; the list a number answers is held in process memory
only (runtime/ops_file_read.py), and nothing here logs, prints or stores a name or a folder.

Sibling of runtime/ops.py, which exposes `file_trash` under its name. The shared names come from ops_core, read as `core.<name>`. Standard library only. Runs on Python 3.9:
python3 runtime/ops_file_trash.py --help
"""
from __future__ import annotations

import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import account_start  # noqa: E402
import line_stage  # noqa: E402
import natural  # noqa: E402
import operations  # noqa: E402
import ops_actor  # noqa: E402
import ops_core as core  # noqa: E402
import ops_file_read as reader  # noqa: E402
import phone_delete  # noqa: E402
import phone_refusal  # noqa: E402
import phrases  # noqa: E402
import project_config  # noqa: E402
import turn_gate  # noqa: E402

OP = "file-trash"
KIND = "file-write"


def _natural():
    return importlib.import_module("ops_natural")


def _writes():
    return importlib.import_module("ops_natural_writes")


def _alias(cfg: dict, service: str, root: str):
    """The name the project's configuration gives the granted folder with this id, or None (the document names the grant by this name, and the grant is asked again by it)."""
    folders = (project_config.account_entry(cfg, service) or {}).get("folders") or {}
    names = sorted(name for name, ident in folders.items() if ident == root)
    return names[0] if names else None


def _outcome(cfg: dict, wanted: str, account, said) -> dict:
    """The outcome of one search, as data: {"status": "no-folders"} | {"status": "none", ...} | {"status": "no-folder", ...} | {"status": "unavailable"} | {"status": "several", "matches",
    "count", "refs", ...notes} | {"status": "one", "match", ...notes}. The same statuses as the read (runtime/ops_file_read.py `_find_and_read`), without reading anything."""
    found = reader._search(cfg, wanted, account, said)
    if not found["folders"]:
        return {"status": "no-folders"}
    matches = found["matches"]
    if not matches:
        if found["no_folder"]:
            return {"status": "no-folder", "folders": found["folders"], "cut": found["cut"]}
        if found["all_failed"]:
            return {"status": "unavailable"}
        return {"status": "none", "folders": found["folders"], "failed": found["failed"], "truncated": found["truncated"], "cut": found["cut"]}
    notes = {**({"incomplete": True} if found["incomplete"] else {}), **({"folder_missing": found["folder_missing"]} if found["folder_missing"] else {})}
    if len(matches) > 1:
        shown = matches[:reader.LIST_MAX]
        return {"status": "several", "matches": [{k: m[k] for k in ("name", "folder", "service")} for m in shown], "count": len(matches), "refs": shown, **notes}
    return dict({"status": "one", "match": matches[0]}, **notes)


def _may_list(ctx: dict, channel, sender) -> None:
    """The right to see file names, asked beside the right to trash (a search and a list show the names of the person's files): `read-files` for a messaging sender and for the page; the terminal is
    never narrowed. core.OpsError with the sentence of the read's refusal otherwise."""
    where = "terminal" if channel in (None, "chat", "terminal") else channel
    if where == "terminal":
        return
    refused = operations.refusal("file-read", where, ctx["cfg"]["channels"], sender=sender)
    if refused:
        raise core.OpsError(refused, 1)


def start_card(project: str, cfg: dict, match: dict, exact: bool, channel=None, sender=None) -> dict:
    """Open the card of one file found by the search: the step task `file-write` with the operation `trash`, prepared with no model, stopped at the card. The file's id and the granted
    folder come from the search, never from the person's words. core.OpsError when it cannot be prepared (its message is the sentence the person reads)."""
    alias = _alias(cfg, match["service"], match["root"])
    if alias is None:
        raise core.OpsError(phrases.en("ACCT_TRASH_NOT_GRANTED"), 1)
    args = {"operation": "trash", "account": match["service"], "id": match["id"], "folder": alias, "exact": bool(exact)}
    return account_start.start(project, KIND, args, key_words=OP, title_key="TITLE_FILE_TRASH", account=match["service"], channel=channel, sender=sender)


def file_trash(project: str, file: str, account: str | None = None, folder: str | None = None, channel: str | None = None, sender: str | None = None) -> dict:
    """The operation `file-trash`. From a messaging app the sender's profile must hold the groups `files-trash` and `read-files`. Returns {"status": "card", "request", "task", "pending", "word", "on_cards"}
    for one file, or the outcome of the search for several ({"status": "several", "matches", "count"}) and for none; nothing is moved before the card's hash is approved."""
    ctx = core.context(project)
    ops_actor.guard(ctx, OP, channel, sender)
    _may_list(ctx, channel, sender)
    if not isinstance(file, str) or not natural.normal(file) or len(file) > natural.SPAN_MAX:
        raise core.OpsError("--file is the name of a file (1 to 300 characters)", 2)
    if account is not None and account not in reader.SERVICES:
        raise core.OpsError("--account is google or microsoft", 2)
    if folder is not None and (not isinstance(folder, str) or not folder.strip() or len(folder) > reader.LABEL_MAX or "\n" in folder):
        raise core.OpsError("--folder is the name or the path of a folder (1 to 120 characters)", 2)
    said = f"{file} folder {folder}" if folder else None
    got = _outcome(ctx["cfg"], file, account, said)
    if got["status"] == "one":
        started = start_card(project, ctx["cfg"], got["match"], got["match"]["exact"], channel, sender)
        return {"status": "card", **started}
    return {k: v for k, v in got.items() if k != "refs"}


# --- the reply to a line in words ----------------------------------------------------------------------------------------------------------------


def _private(ctx: dict, extras: dict) -> None:
    extras["stored"] = phrases.text("NW_PRIVATE_REPLY", ctx["cfg"])      # the reply holds a file's name and folder: the conversation keeps a neutral word


def _card(project: str, ctx: dict, match: dict, exact: bool, channel, sender, extras: dict, origin: str = "grounded") -> str:
    """The card of one file, as every write of the family opens it: the policy for the operation (and for cards) is asked again, the gate checks where each argument came from (S41-7: the file
    is `grounded`, found by the search with the words of the line, or `picked`, chosen among those listed; the account and the folder are the configuration's), the card is prepared, and the
    bridge sends it (`extras["resend"]`); the terminal's own shell also gets the lines and the command with the hash."""
    cfg = ctx["cfg"]
    refused = _writes()._admit(ctx, OP, channel, sender)
    if refused:
        return refused
    alias = _alias(cfg, match["service"], match["root"])
    problems = turn_gate.provenance(OP, {"account": match["service"], "file": match["id"], **({"folder": alias} if alias else {})}, {"account": "config", "file": origin, "folder": "config"})
    if problems:
        return _writes().refused_sentence(ctx, OP, problems, channel, extras)
    car = _writes().carrier(channel)
    try:
        with ops_actor.carried_by(car):
            started = start_card(project, cfg, match, exact, car, sender if car == "messaging" else None)
    except core.OpsError as e:
        return _natural()._error(cfg, e, channel)
    extras["resend"] = started["pending"]
    return account_start.reply_text(cfg, started) + _writes()._card_lines(ctx, project, started, channel)


def _render(cfg: dict, got: dict, pick: bool) -> str:
    """The sentence for an outcome that opens no card: the list to choose from (a number on a messaging app, the full name elsewhere), or what the read says when nothing was found."""
    notes = ([phrases.text("FR_FOLDER_MISSING", cfg, folder=got["folder_missing"])] if got.get("folder_missing") else []) + ([phrases.text("FR_INCOMPLETE", cfg)] if got.get("incomplete") else [])
    if got["status"] == "several":
        rows = [phrases.text("FR_ITEM", cfg, n=n, name=m["name"], folder=m["folder"], account=reader._label_of(cfg, m["service"])) for n, m in enumerate(got["matches"], 1)]
        head = phrases.text("FT_SEVERAL_PICK", cfg, count=got["count"]) if pick else phrases.text("FR_SEVERAL_NAME", cfg, count=got["count"])
        return "\n".join([head] + rows + notes)
    return reader._render(cfg, got, pick)


def reply(project: str, ctx: dict, args: dict, said: str, channel, sender, extras: dict) -> str:
    """The reply of `file-trash` chosen by the interpreter or by `line` (runtime/ops_interpret.py `_carry_out` has already asked the policy for the operation). The name is checked to be a
    span of the line, the account word to name exactly one service and to agree with the line (runtime/ops_file_read.py `line_target`); a folder named in the line narrows the search. One
    file opens its card; several are listed and remembered for the sender's next line; none is one sentence. Else the fixed ask-again sentence and nothing is searched."""
    cfg = ctx["cfg"]
    _private(ctx, extras)
    refused = operations.refusal("file-read", "terminal" if channel in (None, "chat") else channel, cfg["channels"], sender=sender)      # the names of files are listed only to one who may read files
    if refused:
        return phone_refusal.said(refused, channel, cfg)
    wanted, account, again = reader.line_target(cfg, args, said)
    if again:
        return again
    line_stage.publish("file")
    got = _outcome(cfg, wanted, account, said)
    if got["status"] == "one":
        text = _card(project, ctx, got["match"], got["match"]["exact"], channel, sender, extras)
        notes = ([phrases.text("FR_FOLDER_MISSING", cfg, folder=got["folder_missing"])] if got.get("folder_missing") else []) + ([phrases.text("FR_INCOMPLETE", cfg)] if got.get("incomplete") else [])
        return text + "".join("\n\n" + n for n in notes) if extras.get("resend") else text      # a card that was opened says what the search could not see; a refusal says only itself
    if got["status"] == "several" and channel == "messaging":
        reader._remember(ctx, channel, sender, got["refs"], bool(got.get("incomplete")), purpose="trash", whole=got["count"] <= len(got["refs"]))
    return _render(cfg, got, channel == "messaging")


def pick(project: str, ctx: dict, match: dict, channel, sender, extras: dict) -> str:
    """The reply to a number said right after a list of files to move to the trash: the card of that file. The sender's right is asked again, and so is the grant: the configured folder the
    file was found under must still be one of the configuration in force, else the plain no-folder sentence and nothing is prepared. The person chose the file, so the card does not ask whether it is the one."""
    cfg = ctx["cfg"]
    _private(ctx, extras)
    refused = operations.refusal(OP, "messaging", cfg["channels"], sender=sender) or operations.refusal("file-read", "messaging", cfg["channels"], sender=sender)
    if refused:
        return phone_refusal.said(refused, channel, cfg)
    granted = {(service, ident) for service in reader.SERVICES for ident in ((project_config.account_entry(cfg, service) or {}).get("folders") or {}).values()}
    if (match["service"], match["root"]) not in granted:
        folders = [(service, None) for service in reader.SERVICES if (project_config.account_entry(cfg, service) or {}).get("folders")]
        return reader._render(cfg, {"status": "no-folder", "folders": folders, "cut": None} if folders else {"status": "no-folders"})
    return _card(project, ctx, match, True, channel, sender, extras, origin="picked")


# --- a line that asks to delete a file ---------------------------------------------------------------------------------------------------------------


def permitted(ctx: dict, channel, sender) -> bool:
    """Whether this messaging sender may ask for a file to be moved to the trash under the project's policy now (the groups `files-trash` and `read-files`)."""
    channels = ctx["cfg"]["channels"]
    return (channel == "messaging" and isinstance(sender, str) and operations.permitted(OP, "messaging", channels, None, sender)
            and operations.permitted("file-read", "messaging", channels, None, sender))      # the trash AND the right to see names: a profile with one alone gets the plain sentence


def catches(ctx: dict, said: str, channel, sender) -> bool:
    """Whether code alone answers this line, a request to delete a file: always for a sender who may not move a file to the trash (the plain sentence that it is not done from a message), and for
    one who may when the name can be read from the line (`phone_delete.name`); a line whose name cannot be read goes on to the interpreter."""
    if channel != "messaging" or not phone_delete.asks(said):
        return False
    return not permitted(ctx, channel, sender) or phone_delete.name(said) is not None


def line(project: str, ctx: dict, said: str, channel, sender, extras: dict):
    """The reply to a line that asks to delete a file, for a sender who may move a file to the trash, or None when its name cannot be read by code (the line then goes on). The name is the
    file's, the folder and the account come from the line's own words."""
    if not permitted(ctx, channel, sender) or not phone_delete.asks(said):
        return None
    found = phone_delete.name(said)
    if found is None:
        return None
    return reply(project, ctx, {"file": found}, said, channel, sender, extras)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
