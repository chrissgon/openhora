#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The plain name a phone shows for a mail or calendar source (package BL5D): "Gmail", "Outlook", "Agenda do Google"; never `caixa-gmail`.

  catalog(ctx[, cfg])      {source id: {"name", "type", "account"}} for every mail and calendar source of the project, named by the rule below
  shown(value, table, cfg) the text a phone reads for a source id, or for a reference `<source id>#<n>`; anything else comes back as it is
  words(entry)             the service words of an entry's account (the provider's own words: language data), so that the provider's word can answer "De qual caixa?"
  for_project(project)     {source id: name} for the messaging bridge, which hands it to the card of a decision as `cfg["source_names"]`

Why. A phone does not show the internals of the platform (limit L62, slice S16c): the id of a source is a key for the page and the terminal. The person called the sources "Gmail" and
"Outlook" in a live retest and was asked "De qual caixa? 1. caixa-gmail 2. caixa-outlook". Every phone surface (a question and its options, a sentence that names a source, the phone
list, the list of events of two calendars, the reply card) calls this one module, so one source reads the same everywhere.

The rule, over the whole catalog in the registry's order and in the project's language:
  1. the base is the provider's plain name (a mailbox: the provider's brand, "Gmail", which is no sentence and has no phrase; a calendar: `NW_ITEMS_NAME_CAL`, "Agenda do Google"); a source whose account cannot be read keeps its id;
  2. sources with the same base (twins) get a detail between brackets: the box of a mailbox (a closed word: inbox, important, starred, unread); for a calendar "main" when it is the
     account's own (`primary`, `default`), else the person's description (one line, 24 characters at most) when there is one. The account address is never used: there is one account per
     implementation on a machine (runtime/sources_mail.py), so it cannot tell two sources apart;
  3. whatever is still equal after that is numbered 1, 2, ... in the registry's order. So the names of one project are unique by construction.

Presentation only. The value of an option, a reference, a stored card and every hash stay what they were: this module derives text at the time a phone is drawn and writes nothing. A
failure of the catalog gives `{}`, and the phone then shows the ids it showed before (never a refusal). Nothing is read from a provider and no model is called.

Imports neither runtime/ops_items.py nor runtime/ops_natural_*.py at module level (they import this module). Standard library only. Runs on Python 3.9: python3 runtime/source_names.py --help
"""
from __future__ import annotations

import importlib
import sys

import item_refs
import mail_refs
import natural
import natural_writes
import ops_core
import phrases
import snapshot_text
import sources
import sources_mail

KINDS = ("mail", "calendar")
LABEL = {"mail": {"google": "Gmail", "microsoft": "Outlook"}, "calendar": {"google": "Google", "microsoft": "Outlook"}}      # the provider's plain name, by the account
BOX_KEYS = {"inbox": "SRC_BOX_INBOX", "important": "SRC_BOX_IMPORTANT", "starred": "SRC_BOX_STARRED", "unread": "SRC_BOX_UNREAD"}      # a mailbox is told apart by its box: a closed list
MAIN_CALENDARS = ("primary", "default")      # the calendar that is the account's own (Google's `primary`, Outlook's `default`)
DETAIL_MAX = 24      # characters of a person's description used as a detail


def account_of(row: dict):
    """The account ("google" | "microsoft") a mail or calendar source belongs to, from the implementation its origin names; None when the origin is not one this runtime reads."""
    table = mail_refs.ACCOUNT_OF if row["type"] == "mail" else importlib.import_module("ops_natural_calendar").CAL_ACCOUNT
    try:
        return table.get(sources_mail.origin_of(row["type"], row["origin"])["implementation"])
    except sources.SourcesError:
        return None


def plain(kind: str, label: str, cfg=None) -> str:
    """The base name of a source: a mailbox is the provider's brand ("Gmail", "Outlook": a name, so no phrase of the table, whose sentence that is only a field would count as every text said in
    the language already, runtime/phone_errors.py `spoken`); a calendar is "Agenda do Google" / "Google calendar"."""
    return label if kind == "mail" else phrases.text("NW_ITEMS_NAME_CAL", cfg, service=label)


def _detail(row: dict, cfg: dict):
    """The word that tells a source from its twins, or None: the box of a mailbox; for a calendar "main" or the person's own description."""
    try:
        origin = sources_mail.origin_of(row["type"], row["origin"])
    except sources.SourcesError:
        return None
    if row["type"] == "mail":
        key = BOX_KEYS.get(origin.get("box"))
        return phrases.text(key, cfg) if key else None
    if origin.get("calendar") in MAIN_CALENDARS:
        return phrases.text("SRC_CAL_MAIN", cfg)
    described = row.get("description")
    one = snapshot_text.one_line(snapshot_text.clean_text(described), DETAIL_MAX) if isinstance(described, str) else ""
    return one or None


def _number(named: dict) -> None:
    """Step 3: every group of equal names gets ` 1`, ` 2`, ... in the registry's order (the dict keeps it)."""
    for name in dict.fromkeys(named.values()):
        twins = [i for i in named if named[i] == name]
        if len(twins) > 1:
            named.update({i: f"{name} {k}" for k, i in enumerate(twins, 1)})


def catalog(ctx: dict, cfg=None) -> dict:
    """{source id: {"name", "type", "account"}} of every mail and calendar source, in the registry's order. {} when the catalog cannot be read."""
    cfg = ctx["cfg"] if cfg is None else cfg
    try:
        rows = [r for r in sources.list_catalog(ctx, hashes=False) if r["type"] in KINDS]
    except sources.SourcesError:
        return {}
    entries = {}
    for row in rows:
        account = account_of(row)
        label = LABEL[row["type"]].get(account)
        base = plain(row["type"], label, cfg) if label else row["id"]
        entries[row["id"]] = {"row": row, "base": base, "type": row["type"], "account": account if label else None}
    named = {i: e["base"] for i, e in entries.items()}
    for base in dict.fromkeys(named.values()):      # step 2: twins are told apart by a detail
        twins = [i for i in entries if entries[i]["base"] == base and entries[i]["account"]]
        if len(twins) > 1:
            for i in twins:
                detail = _detail(entries[i]["row"], cfg)
                if detail:
                    named[i] = phrases.text("SRC_TWIN", cfg, name=base, detail=detail)
    _number(named)
    return {i: {"name": named[i], "type": e["type"], "account": e["account"]} for i, e in entries.items()}


def _name_of(entry) -> str:
    return entry["name"] if isinstance(entry, dict) else str(entry)


def shown(value, table: dict, cfg=None) -> str:
    """What a phone reads for `value`: a source id of `table` is its name; `<id>#<n>` (the whole value, with a known id) is "Gmail, message 3"; anything else (a person's own
    words, an address, a folder) is returned unchanged. `table` maps a source id to its entry (`catalog`) or to its name (`for_project`)."""
    if not isinstance(value, str) or not table:
        return value
    if value in table:
        return _name_of(table[value])
    found = item_refs.ITEM_REF.fullmatch(value)
    if found and found.group(1) in table:
        return phrases.text("SRC_ITEM", cfg, name=_name_of(table[found.group(1)]), n=int(found.group(2)))
    return value


def words(entry) -> list:
    """The service words of the account of a catalog entry (language data of runtime/natural_lang_*.py); empty for no account."""
    account = entry.get("account") if isinstance(entry, dict) else None
    if not account:
        return []
    return list(natural_writes.listed(natural._tables(None), "services", account))


def for_project(project: str) -> dict:
    """{source id: name} of a project for the messaging bridge; {} for any failure (a phone then shows what it showed before)."""
    try:
        ctx = ops_core.context(project)
        return {i: e["name"] for i, e in catalog(ctx).items()}
    except Exception:      # noqa: BLE001 - presentation only: never a refusal
        return {}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
