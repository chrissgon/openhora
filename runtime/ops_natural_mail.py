#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The resolution of a mail write asked in words (package NR-5b, SPEC-NATURAL-WRITES 3.3 and 3.4): what runtime/natural_writes_mail.py read from the line, turned into the
arguments of the operation's own function, or into the one question that is still open. It opens nothing and writes nothing: the caller (runtime/ops_natural_writes.py,
`open_line`) calls the operation exactly as the typed command is called, and that ends in `account_start.start` and the card.

  resolve(ctx, op, slots, channel, sender, said)    {"args": {...}} (the arguments of the operation: account, to, subject, text | message, text | messages, folder, state...)
                                                    or {"ask": {"need", "options", "sentence_key", "fields"}} (the next question, one at a time, in this order: the account or the
                                                    mailbox, the message among several, the recipient, the subject, the body, the folder, the state)
                                                    or {"say": {"sentence_key", "fields"}} (a final sentence, nothing is opened: the caller may not read the mailbox, nothing
                                                    matches, a card takes fewer messages); core.OpsError only for a failure of the project's own sources

What is decided here, and from where:
  * an address, a subject and a body are the person's own words (an address only as written in a line; the body, and a subject the person did not give, may be worded by the
    model when the text was described to the interpreter or answered to the body question and composing is on for the sender: runtime/mail_compose.py, S7; a name asks for its address, and no mailbox, snapshot or index is
    searched for one); a reply and a reply draft take no recipient: the operation takes it from the index of the message answered (limit L60), never from a body. BL7-2: the body of a
    reply or a reply draft that DESCRIBES the text ("thanking her and explaining politely...", `mail_reply_compose.described`) may be worded too, from the person's own words alone
    (the composer never sees the message answered, its sender, its subject or the recipient); words reported after a say verb ("saying that...", "en disant que..."), after a colon or an opening quote, or after the literal
    marker ("exact text:", in the body or in the line before it) are the text as written, and the marker itself is never part of a reply's text; when a described reply could not be worded (a limit, the breaker, a failed or refused call, a
    changed prompt, no right to interpret) the card shows the person's own words and the reply carries one line that says so (`MC_REPLY_NOT_WORDED`);
  * a message is `<source>#<n>` from digits the person wrote, from the source the person wrote, the one registered mail source of the account, or the one the person chose; or
    it is found BY WORDS in the index of the newest snapshot: the words after "do/da/from" must all be whole words of the message's from-address or subject; a singular
    object needs exactly one match (several are listed, up to five, and asked), a plural object takes every match up to 20 (more are asked);
  * a message named by the interpreter's `target` and `day` spans (B''-lite, `mail_target_seed`) is found the same way: the span's content words (`natural_writes_mail.target_words`)
    must all be whole words of the from-address or the subject, and the day (`day_read`: read by the caller with the time engine, this module reads no calendar and no clock) keeps the
    messages the index says came in on that local day (`received`, a UTC time) or, for a weekday, in the last 7 days; an index with no `received` for a candidate, or a day the engine
    cannot read, is `NW_MAIL_BY_DATE`: a date is never guessed. The words only choose a message, they are never an address: a reply goes to the index's From (L60);
  * BL7-5: a message the model named by NUMBER, when the closed forms read none (`mail_number_seed`), is `<source>#<n>` of the newest snapshot like a number the closed forms read: the numbers
    must be exactly the line's free numbers (`natural_writes_mail.free_numbers`) and no `target`, `day`, `to` or `subject` stands beside them; the origin is `line-number` and a numbered line
    never refreshes a snapshot. A target that holds its own subject after the sender (the interpreter's `target_ground`) is found by up to GROUND_WORDS_MAX content words, every one required
    (`natural_writes_mail.ground_words`);
  * GROUNDING-FROM: a ground that has a person's part (`target_sender`: BL7-1's widened target and BL7-5's long target) is found with the person's words (`sender_words`, only when fewer than the
    ground's words) required in the From (`natural_writes_mail.from_words`), not in the subject. When no message holds them in a From but some hold all the words through the subject, they are a numbered
    list (`NW_MAIL_ASK_SENDER`), even for one message, never a card; a target that was not widened has no person's part and is read as before. A reply still goes to the index's From (L60);
  * the snapshot is read, and a message is listed, only after `item_refs.read_index` accepted the caller (a messaging sender needs the group `ask-mail`): a caller who may not
    read it gets the sentence of `item_refs` and nothing of the mailbox, not even the names of its sources;
  * BL5E: a stale snapshot is read again once. When the index of the source the line needs is refused as older than 26 hours (or of a time that cannot be trusted), as missing
    or as made before the index existed, and the line found its message BY WORDS or asked for the newest one, a messaging sender who holds `ask-mail` has the source read
    again by the platform (runtime/mail_refresh.py `refresh_once`: one provider read for a line, because the line's refresh budget (`turn_gate.turn`, opened by the entry point of the line, else by `resolve`) allows one mail lookup read and `_read_snapshot` is the only caller;
    only that source, in its own box, days and max; the provider bounded at 60 seconds; one read of a source at a time; a source that failed is not tried again for 120
    seconds), and the index is asked again. A number the person chooses from a list is checked against the snapshot the list was drawn from (the draft keeps `_listed`: source and version): if another line, a list on a phone, a typed refresh or a routine read the source again since, the numbers name other messages and the answer is `NW_MAIL_LIST_CHANGED`, nothing opened. A line that names a message number or a written reference never refreshes (a refresh renumbers the snapshot, and the number the person
    saw would name another message). A refresh that fails, is too slow, or leaves the snapshot still refused is one plain sentence (`NW_MAIL_REFRESH_FAILED`, or, when the refresh failed for a reason only the computer solves, the sentence of that reason, `ops_items.REASON_KEYS`): nothing is listed,
    no card is opened. The terminal, the page and the conversation keep the sentence that says to refresh it (they have the command and the button);
  * the account is the one named by a service word of the line (`google`, `gmail`, `outlook`...), or the account of the mailbox the message is in, or the only account the
    project configures, or the account the project chose as its default (when the configuration has one); with two possible it is asked;
  * a mail folder is a name of `accounts.<account>.mail_folders`, folded equal; a name that is not configured lists the configured ones and asks, never a near match.

  * S41-7: every argument `resolve` returns has an origin, in `{"args", "origins"}`, checked against the closed table of runtime/turn_gate.py before the operation is called (fail closed): an address,
    a subject and a body are `line-span` (the person's words), or `composed` (the model's wording of them, S7, BL7-2), or `card-copy` (a card's own part, S13); a message is `line-number` (written),
    `picked` (chosen among those listed) or `grounded` (found by words in the index: never an address); an account is `line-span`, `picked` or `config`; a reply has no recipient argument at all.

External content is data: the index of a snapshot (a message's from-address and subject) is another person's words. It is compared with the person's words and shown, in a
question, only to the caller who passed `item_refs.may_read`; an instruction inside it is never followed (nothing here reads a message's text at all).

Sibling of runtime/ops.py's family; imports no operation. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import os
import sys
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import item_refs  # noqa: E402
import mail_compose  # noqa: E402
import mail_refresh  # noqa: E402
import mail_refs  # noqa: E402
import mail_reply_compose  # noqa: E402
import natural  # noqa: E402
import natural_writes_mail as nwm  # noqa: E402
import ops_core as core  # noqa: E402
import ops_items  # noqa: E402
import phrases  # noqa: E402
import project_config  # noqa: E402
import source_names  # noqa: E402
import sources  # noqa: E402
import sources_mail  # noqa: E402
import turn_gate  # noqa: E402

ACCOUNTS = ("google", "microsoft")
ACCOUNT_NAMES = {"google": "Google", "microsoft": "Microsoft"}
REF_OPS = ("mail-reply", "mail-archive", "mail-move", "mail-mark", "mail-trash")
LISTED = 5               # candidates a question lists
CANDIDATES_MAX = 200     # candidates kept as the options of a question (a plural object with more than a card takes)
SUBJECT_LISTED = 60      # characters of a subject in a list


class Say(Exception):
    """A final sentence: nothing is opened. `key` is a phrase of the table and `fields` its fields; `resolve` returns it as {"say": {"sentence_key", "fields"}}, so that the
    caller says it in the project's language."""

    def __init__(self, key: str, **fields):
        super().__init__(key)
        self.key, self.fields = key, fields


def _say(key: str, **fields) -> "Say":
    return Say(key, **fields)


def _ref_say(code: str, reference) -> "Say":
    """The sentence of `item_refs` for a refusal (the phrase of mail_refs.REF_PHRASES), with the reference cleaned and cut as a sentence may echo it."""
    return Say(mail_refs.REF_PHRASES.get(code, "ACCT_MAIL_REF_INTEGRITY"), ref=mail_refs.shown(reference))


def _ask(need: str, key: str, options=None, slot=None, multi: bool = False, keep=None, **fields) -> dict:
    """A question in the shape the card-opening path takes (runtime/ops_natural_writes.py `ask_spec`): `options` are (value, label) pairs the person chooses from by the number
    shown or the word; `slot` is where the answer goes (default: the need); `keep` is what the draft keeps among its slots while the question is open
    (`ops_natural_writes._ask`): the snapshot a list of messages was drawn from."""
    return {"ask": {"need": need, "slot": slot or need, "sentence_key": key, "fields": fields, "multi": multi, "engine": None, "keep": keep or {},
                    "options": [{"value": value, "label": label} for value, label in (options or [])]}}


def _refs_origin(slots: dict) -> str:
    """The origin of the references `_messages` returns (S41-7): `picked` when the person chose among the messages code listed, `grounded` when any of them was found by words (or "the
    newest") in the index, else `line-number` (written in the line)."""
    if slots.get("chosen"):
        return "picked"
    return "grounded" if slots.get("words") or slots.get("newest") else "line-number"


def _has_reference(slots: dict) -> bool:
    return bool(slots.get("numbers") or slots.get("refs") or slots.get("words") or slots.get("newest") or slots.get("chosen"))


def _joined(addresses) -> str:
    return ", ".join(addresses)


# --- the account --------------------------------------------------------------------------------------------------------------------------


def _configured(cfg: dict) -> list:
    return [a for a in ACCOUNTS if project_config.account_entry(cfg, a)]


def _named_account(slots: dict):
    given = slots.get("account") or slots.get("service")
    return given if given in ACCOUNTS else None


def _account_origin(slots: dict) -> str:
    """The origin of the account `_named_account` gives (S41-7): the one the person gave or picked (a service word, a pick, a card's own account), else the project's configuration."""
    if _named_account(slots) is None:
        return "config"
    return turn_gate.origin_of(slots, "account", "line-span") if slots.get("account") in ACCOUNTS else "line-span"


def _compose_account(ctx: dict, slots: dict):
    """The account of an e-mail with no message in it: the one named, else the only one configured, else the default, else a question. (account, None) or (None, ask)."""
    cfg = ctx["cfg"]
    named = _named_account(slots)
    if named:
        return named, None
    configured = _configured(cfg)
    if not configured:
        raise _say("NW_NO_ACCOUNT")
    if len(configured) == 1:
        return configured[0], None
    chosen = project_config.account_default(cfg)
    if chosen in configured:
        return chosen, None
    return None, _ask("account", "NW_ASK_ACCOUNT", [(a, f"{ACCOUNT_NAMES[a]} ({project_config.account_entry(cfg, a)['address']})") for a in configured])


# --- the messages -------------------------------------------------------------------------------------------------------------------------


def _mail_sources(ctx: dict) -> list:
    """The registered mail sources: [{"id", "account"}] (a source whose origin this runtime does not read is left out)."""
    try:
        rows = sources.list_catalog(ctx, hashes=False)
    except sources.SourcesError as e:
        raise core.OpsError(" ".join(str(e).split())[:200], 1) from None
    out = []
    for row in rows:
        if row.get("type") != "mail":
            continue
        try:
            implementation = sources_mail.origin_of("mail", row["origin"])["implementation"]
        except (sources.SourcesError, KeyError):
            continue
        out.append({"id": row["id"], "account": mail_refs.ACCOUNT_OF.get(implementation)})
    return out


def _first_written(slots: dict) -> str:
    """The reference the person wrote, as a sentence may echo it (a caller that may not read gets this back and nothing else)."""
    if slots.get("refs"):
        return slots["refs"][0]
    if slots.get("numbers"):
        return f"#{slots['numbers'][0]}"
    return "your messages"


def _may_refresh(slots: dict) -> bool:
    """A line that carries a message number or a written reference never refreshes a snapshot: a refresh renumbers it. (A message the person chose from a list reads no snapshot
    to find it, only `_same_list`, which never refreshes.)"""
    return not (slots.get("numbers") or slots.get("refs"))


def _same_list(ctx: dict, listed, channel, sender) -> None:
    """The person chose a number from a list drawn from the snapshot `listed` ({"source", "version"}): the number names that message only while that snapshot is still the newest
    one. Another line, a list on a phone, a typed refresh or a routine may have read the source again since, and the numbers of a new snapshot name other messages: then nothing is
    opened and the person is asked to ask again. The newest snapshot is read as for any reference (the right to read first, a stale one refused, never refreshed here)."""
    if not (isinstance(listed, dict) and isinstance(listed.get("source"), str) and "version" in listed):
        raise _say("NW_MAIL_LIST_CHANGED")      # a list that records no snapshot cannot be told from a new one: fail closed
    source_id = listed["source"]
    try:
        newest = item_refs.read_index(ctx, source_id, channel=channel, sender=sender, kinds=("mail",))
    except item_refs.ItemRefError as e:
        raise _ref_say(e.code, source_id) from None
    except sources.SourcesError as e:
        raise core.OpsError(" ".join(str(e).split())[:200], 1) from None
    if listed["version"] is None or newest.get("version") != listed["version"]:
        raise _say("NW_MAIL_LIST_CHANGED")


def _reason_say(ctx: dict, source_id: str, reason):
    """The sentence for a refusal only the computer solves (ops_items.REASON_KEYS), naming the source as a phone names it; None when there is no such reason."""
    if not reason:
        return None
    return _say(ops_items.REASON_KEYS[reason], name=(source_names.catalog(ctx).get(source_id) or {}).get("name") or source_id)


def _read_snapshot(ctx: dict, source_id: str, channel, sender, may_refresh: bool = False) -> dict:
    """The index of the newest snapshot of `source_id` for the caller. With `may_refresh`, a snapshot refused as stale, missing or without an index is read again once
    (runtime/mail_refresh.py); every other refusal, and every refusal when the refresh is not allowed, is the sentence it always was."""
    try:
        return item_refs.read_index(ctx, source_id, channel=channel, sender=sender, kinds=("mail",))
    except item_refs.ItemRefError as e:
        if may_refresh and e.code in mail_refresh.TRIGGERS:
            done = mail_refresh.refresh_once(ctx, source_id, channel, sender)
            if done == "refreshed":
                try:
                    return item_refs.read_index(ctx, source_id, channel=channel, sender=sender, kinds=("mail",))
                except item_refs.ItemRefError as again:
                    if again.code in mail_refresh.TRIGGERS:
                        raise _say("NW_MAIL_REFRESH_FAILED", source=source_id) from None
                    raise _ref_say(again.code, source_id) from None
                except sources.SourcesError as again:
                    raise core.OpsError(" ".join(str(again).split())[:200], 1) from None
            if done in ("failed", "spent"):
                raise (_reason_say(ctx, source_id, mail_refresh.last_reason(ctx, source_id)) or _say("NW_MAIL_REFRESH_FAILED", source=source_id)) from None
        raise _ref_say(e.code, source_id) from None      # "not-allowed", a refusal no read cures, or a line that may not refresh: today's sentence
    except sources.SourcesError as e:
        told = _reason_say(ctx, source_id, ops_items.reason_of(e.code)) if channel == "messaging" else None      # a phone is told why, in words; the terminal keeps its own
        if told is not None:
            raise told from None
        raise core.OpsError(" ".join(str(e).split())[:200], 1) from None


def _entry_label(entry: dict) -> str:
    """One message as a list shows it (the sender's address and the subject as the index recorded them): shown only to a caller who passed `item_refs.may_read`."""
    subject = " ".join(str(entry.get("subject") or "").split())
    if len(subject) > SUBJECT_LISTED:
        subject = subject[:SUBJECT_LISTED - 1].rstrip() + "…"
    return f"{entry.get('from_address') or '?'} · {subject or '-'}"


def _received_day(received, zone):
    """The local date of a message's `received` (a UTC time as the index records it), or None when it is not a time with an offset."""
    try:
        moment = datetime.datetime.fromisoformat(str(received).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.astimezone(zone).date() if moment.tzinfo is not None else None


def _on_day(found: list, read: dict) -> list:
    """The messages of `found` that came in on the day `read` names: {"kind": "day" | "weekday" | "none" | "unread", "value" (an ISO date, or a weekday number 0-6), "today" (an ISO
    date), "zone" (an IANA name)}, made by the caller from the person's `day` span with the time engine (runtime/ops_interpret.py `_day_read`). A date keeps the messages that came in
    on that local day, a weekday those of the last 7 days that fall on it. A day the engine cannot read, a zone that cannot be named, or a candidate whose index entry holds no
    `received` (a snapshot made before it was recorded) is `NW_MAIL_BY_DATE`: a date is never guessed."""
    try:
        zone = ZoneInfo(read["zone"])
        kind, value, today = read["kind"], read["value"], datetime.date.fromisoformat(read["today"])
        value = datetime.date.fromisoformat(value) if kind == "day" else value
    except (KeyError, TypeError, ValueError):
        raise _say("NW_MAIL_BY_DATE") from None
    days = [_received_day(e.get("received"), zone) for e in found]
    if kind not in ("day", "weekday") or any(d is None for d in days):
        raise _say("NW_MAIL_BY_DATE")
    if kind == "day":
        return [e for e, d in zip(found, days) if d == value]
    return [e for e, d in zip(found, days) if today - datetime.timedelta(days=6) <= d <= today and d.weekday() == value]


def _by_words(ctx: dict, slots: dict, source_id: str, channel, sender):
    """The references that the words of the line name in the newest snapshot of `source_id`: ([refs], None), or ([], the question), or raises when nothing matches. The index is
    read only now, after the caller's right to read it was checked by `read_index` itself."""
    snapshot = _read_snapshot(ctx, source_id, channel, sender, _may_refresh(slots))
    words = " ".join(slots["words"])
    named = tuple(slots.get("sender_words") or ())
    wanted = bool(slots.get("newest"))
    found = nwm.match_words(snapshot["entries"], slots["words"], wanted, named) if named else nwm.match_words(snapshot["entries"], slots["words"], wanted)
    by_subject = False
    if not found and named:      # GROUNDING-FROM: the person's name is in no From; the messages that hold the words only through the subject are listed, never one card on words the sender does not hold
        found = nwm.match_words(snapshot["entries"], slots["words"], wanted)
        by_subject = bool(found)
    if not found:
        raise _say("NW_MAIL_NONE", source=source_id, words=words)
    if slots.get("day_read"):
        found = _on_day(found, slots["day_read"])
        if not found:
            raise _say("NW_MAIL_NONE", source=source_id, words=words)
    plural = bool(slots.get("plural")) and not slots.get("newest")
    if by_subject:
        shown = found[:nwm.MESSAGES_MAX if plural else LISTED]
        options = [(f"{source_id}#{e['n']}", _entry_label(e)) for e in shown]
        keep = {"_listed": {"source": source_id, "version": snapshot.get("version")}}
        return [], _ask("message", "NW_MAIL_ASK_SENDER", options, slot="chosen", multi=plural, keep=keep, count=len(found))
    if plural and len(found) <= nwm.MESSAGES_MAX:
        return [f"{source_id}#{e['n']}" for e in found], None
    if not plural and len(found) == 1:
        return [f"{source_id}#{found[0]['n']}"], None
    shown = found[:nwm.MESSAGES_MAX if plural else LISTED]      # the newest candidates: a singular object is chosen among five, a plural one among the twenty a card takes
    options = [(f"{source_id}#{e['n']}", _entry_label(e)) for e in shown]
    keep = {"_listed": {"source": source_id, "version": snapshot.get("version")}}      # the numbers of this list are those of this version of the snapshot
    if plural:
        return [], _ask("message", "NW_MAIL_ASK_MESSAGES_OVER", options, slot="chosen", multi=True, keep=keep, count=len(found), max=nwm.MESSAGES_MAX, shown=len(shown))
    return [], _ask("message", "NW_MAIL_ASK_MESSAGE", options, slot="chosen", keep=keep, count=len(found))


def _reference_source(ctx: dict, slots: dict):
    """(source id or None, account or None, ask or None) for the messages the line names: the written source, else the one mailbox of the account, else a question. References
    that carry their own source need none."""
    available = _mail_sources(ctx)
    ids = {s["id"]: s for s in available}
    account = _named_account(slots)
    written = [r.partition("#")[0] for r in slots.get("refs") or []]
    for source_id in written:
        if source_id not in ids:
            raise _ref_say("no_source", f"{source_id}#")
    if written and not slots.get("numbers") and not slots.get("words") and not slots.get("newest"):
        return None, account or ids[written[0]]["account"], None
    chosen = slots.get("source")
    pool = [s for s in available if (not account or s["account"] == account)]
    if chosen:
        pool = [s for s in pool if s["id"] == chosen]
    elif written:
        pool = [s for s in pool if s["id"] == written[0]]
    if not pool:
        raise _say("NW_MAIL_NO_SOURCE")
    if len(pool) > 1:
        return None, account, _ask("source", "NW_MAIL_ASK_SOURCE", [(s["id"], s["id"]) for s in pool])
    return pool[0]["id"], account or pool[0]["account"], None


def _messages(ctx: dict, slots: dict, channel, sender):
    """(account, [references], None) or (None, None, the question) for the messages the line names. Raises when the caller may not read the mailbox or nothing matches. Where the references
    came from is `_refs_origin`."""
    if not item_refs.may_read(ctx, channel, sender):      # before a source, a message or a number is looked at: a caller who may not read learns nothing
        raise _ref_say("not_readable", _first_written(slots))
    if slots.get("over"):
        raise _say("NW_MAIL_TOO_MANY", max=nwm.MESSAGES_MAX)
    if slots.get("by_date"):
        raise _say("NW_MAIL_BY_DATE")      # a message is not found by its date: no match is made, however many words come with it
    chosen = slots.get("chosen")
    if chosen:      # the person chose among the messages code listed: those references are the messages, whatever else the line said of them
        refs = [chosen] if isinstance(chosen, str) else list(chosen)
        known = {s["id"]: s["account"] for s in _mail_sources(ctx)}
        if any(r.partition("#")[0] not in known for r in refs):
            raise _ref_say("no_source", refs[0])
        if slots.get("_listed") is not None:      # BL5E: the list the person chose from must still be the newest snapshot
            _same_list(ctx, slots["_listed"], channel, sender)
        return _named_account(slots) or known[refs[0].partition("#")[0]], refs, None
    source_id, account, ask = _reference_source(ctx, slots)
    if ask:
        return None, None, ask
    refs = list(slots.get("refs") or [])
    if source_id is not None:
        refs += [f"{source_id}#{n}" for n in slots.get("numbers") or []]
        if slots.get("words"):
            found, ask = _by_words(ctx, slots, source_id, channel, sender)
            if ask:
                return None, None, ask
            refs += found
        elif slots.get("newest"):
            snapshot = _read_snapshot(ctx, source_id, channel, sender, _may_refresh(slots))      # also the age check: a snapshot older than the limit for an unattended task (L53) names nothing
            if not snapshot["entries"]:
                raise _say("NW_MAIL_NONE", source=source_id, words="-")
            refs.append(f"{source_id}#1")
    refs = list(dict.fromkeys(refs))
    if len(refs) > nwm.MESSAGES_MAX:
        raise _say("NW_MAIL_TOO_MANY", max=nwm.MESSAGES_MAX)
    if not refs:
        raise _say("NW_MAIL_NONE", source=source_id or "", words=" ".join(slots.get("words") or []))
    if account is None:
        account = next((s["account"] for s in _mail_sources(ctx) if refs[0].partition("#")[0] == s["id"]), None)
    return account, refs, None


# --- the operations -----------------------------------------------------------------------------------------------------------------------


def _folder(ctx: dict, account: str, slots: dict):
    """(name, None) of the configured mail folder the line names, or (None, the question) when it names none the project lists. Never a near match."""
    entry = project_config.account_entry(ctx["cfg"], account)
    names = list((entry or {}).get("mail_folders") or {})
    if not names:
        raise _say("NW_MAIL_NO_FOLDERS", account=ACCOUNT_NAMES.get(account, account))
    given = slots.get("folder_name")
    for name in names:
        if given and nwm.folder_key(str(given)) == nwm.fold(name):
            return name, None
    if given and slots.get("folder_bare"):
        raise _say("NW_MAIL_NO_FORWARD", name=nwm.clean_shown(given), names=", ".join(names))      # `para o joao`: a person after a bare "to", not a folder; forwarding is not built
    return None, _ask("folder", "NW_ASK_FOLDER", [(n, n) for n in names], slot="folder_name", name=given or "", names=", ".join(names))


def _reference_args(ctx: dict, op: str, slots: dict, channel, sender):
    """The arguments of an operation on messages, or the question."""
    account, refs, ask = _messages(ctx, slots, channel, sender)
    if ask:
        return ask
    account_origin, refs_origin = _account_origin(slots), _refs_origin(slots)          # S41-7: where the account and the references came from
    reply = op == "mail-reply" or op == "mail-draft"
    if reply and len(refs) != 1:
        return _ask("message", "NW_MAIL_ASK_MESSAGE", [(r, r) for r in refs[:LISTED]], slot="chosen", count=len(refs))
    if reply:
        if not slots.get("body"):
            return _ask("body", "NW_MAIL_ASK_BODY_REPLY")
        said_text, literal = mail_compose.strip_marker(slots["body"])          # the marker of a literal text ("exact text:") is never part of an e-mail, and a body that was marked is never worded
        if not said_text.strip():
            return _ask("body", "NW_MAIL_ASK_BODY_REPLY")          # "exact text:" with nothing after it
        notice = None
        text_origin = turn_gate.origin_of(slots, "body", "line-span")
        if slots.get("_compose_reply") and not literal:          # BL7-2: the person described the reply (`mail_reply_compose.described`): the model words it from the person's own words alone, never the message answered
            said_text, composed = mail_reply_compose.worded(ctx, channel, sender, said_text)
            notice = None if composed else "MC_REPLY_NOT_WORDED"          # the card shows the person's own words: the reply says so
            text_origin = "composed" if composed else text_origin          # S41-7: the origin of the wording is the model's, and only the text (never an address) may have it
        key = "text" if op == "mail-reply" else "body"
        out = {"args": {"account": account, "message": refs[0], key: said_text}, "origins": {"account": account_origin, "message": refs_origin, key: text_origin}}
        if notice:
            out["notice"] = notice
        return out
    args = {"account": account, "messages": ",".join(refs)}
    origins = {"account": account_origin, "messages": refs_origin}
    if op == "mail-move":
        name, ask = _folder(ctx, account, slots)
        if ask:
            return ask
        args["folder"] = name
        origins["folder"] = turn_gate.origin_of(slots, "folder_name", "line-span")
    if op == "mail-mark":
        if slots.get("state") not in nwm.STATES:
            return _ask("state", "NW_MAIL_ASK_STATE", [(state, phrases.text(f"NW_MAIL_STATE_{state.upper()}", ctx["cfg"])) for state in nwm.STATES])
        args["state"] = slots["state"]
        origins["state"] = turn_gate.origin_of(slots, "state", "line-span")
    return {"args": args, "origins": origins}


def mail_target_seed(op: str, decision: dict, day=None, said: str = ""):
    """The seed of a mail operation on a message the person named by its words (B''-lite), or None when the line gives no word to look for: `{"op", "by": "target", "slots"}`, the
    slots the family reads (`words` from `natural_writes_mail.target_words` over the verified `target` span; `plural` only when the target or the line `said` holds a noun of the tables'
    plural list (one card for every match, as the closed form), else the singular rule: one match is the card, several are a numbered list; `body`
    of a reply or a draft (and `_compose_reply` when that body DESCRIBES the text instead of dictating it, `mail_reply_compose.described`: BL7-2); `folder_name`; `state`; `day_read`, the day the verified `day` span names as the caller read it, see `_on_day`: a `day` span with no reading is a day
    that was not read). Nothing here is an address, a recipient or a message number: the message is chosen by code from the index afterwards (`_by_words`), and a reply goes to
    the index's From (L60). GROUNDING-FROM: for a decision that carries `target_ground` and `target_sender`, `slots["sender_words"]` holds the content words of the person's part when they are fewer than
    the ground's words and all among them: `_by_words` requires them in the From."""
    spans, args = decision.get("spans") or {}, decision.get("args") or {}
    tables = natural._tables(None)
    words = (nwm.ground_words(decision["target_ground"], tables) if decision.get("target_ground")          # BL7-1, BL7-5: a target widened with the line's subject, or one that holds its own, is grounded by the person and the subject, never the marker word (up to GROUND_WORDS_MAX words, every one required)
             else nwm.target_words(spans.get("target") or "", tables))
    if not words and not spans.get("day"):
        return None
    slots = {"words": words}
    sender = nwm.ground_words(decision["target_sender"], tables) if decision.get("target_ground") and decision.get("target_sender") else []          # GROUNDING-FROM: the person's part of a grounded target, whose words a From must hold
    if sender and len(sender) < len(words) and set(sender) <= set(words):          # a person that adds nothing to the ground leaves no rule: nothing then tells a person from a topic
        slots["sender_words"] = sender
    if op not in ("mail-reply", "mail-draft") and (nwm.plural_mentioned(spans.get("target") or "", tables) or nwm.plural_mentioned(said, tables)):
        slots["plural"] = True
    if op in ("mail-reply", "mail-draft") and spans.get("body"):
        slots["body"] = spans["body"]
        if mail_reply_compose.described(spans["body"], said):
            slots["_compose_reply"] = True          # BL7-2: a body that describes the text is worded by the model when composing is on (`_reference_args`); a dictated one is the text
    if op == "mail-move" and args.get("folder"):
        slots["folder_name"] = args["folder"]
    if op == "mail-mark" and spans.get("state"):
        got = nwm.answer("state", spans["state"], {}, tables)
        if got:
            slots["state"] = got["slots"]["state"]
    if spans.get("day"):
        slots["day_read"] = day or {"kind": "unread", "value": None, "today": None, "zone": None}
    return turn_gate.Seed({"op": op, "by": "target", "slots": slots}, {key: "line-span" for key in ("body", "folder_name", "state") if key in slots})      # S41-7: spans of the line that the interpreter's check verified (the message itself is found by code in the index: `grounded`)


def mail_number_seed(op: str, decision: dict, said: str):
    """BL7-5 (gap G1). The seed of a mail operation on messages the model named by NUMBER when the closed forms read nothing in the line, or None: `{"op", "by": "numbers", "slots"}` with the
    slot `numbers` the closed forms' own shape would hold (`_messages` turns it into `<source>#<n>` of the newest snapshot, never a refresh, origin `line-number`). A seed only when all hold:
    the decision's spans hold no `target`, `day`, `to` or `subject` (a number is never joined with words, and no address or subject is dropped in silence); the numbers the model gave
    (`message` or `messages`) are not empty and are EXACTLY the numbers the line writes as message numbers (`#n`, right after a mail noun, or chained to such a number by a joiner and an optional article; never a room, a year, a count, a time or a range) (`natural_writes_mail.free_numbers`, with the decision's text spans
    and word spans as the places that are not numbers), so a model that drops one, adds one or reads one from a time, a date, a quantity or a body gets none. A reply or a reply draft adds
    its `body` (worded when it DESCRIBES the text, as `mail_target_seed` does), a move its `folder_name`, a mark its `state` when the span reads one. Nothing here is an address, a
    recipient or a message: the reference is resolved when the operation runs (`item_refs`: past the end, older than 26 hours, no right to read), and a reply goes to the index's From (L60)."""
    spans, args = decision.get("spans") or {}, decision.get("args") or {}
    if op not in REF_OPS + ("mail-draft",) or any(spans.get(slot) for slot in ("target", "day", "to", "subject")):
        return None
    given = args.get("message") if "message" in args else args.get("messages")
    numbers = [given] if isinstance(given, int) and not isinstance(given, bool) else list(given) if isinstance(given, (list, tuple)) else []
    if not numbers or not all(isinstance(n, int) and not isinstance(n, bool) for n in numbers):
        return None
    row = natural.NATURAL[op]["slots"]
    texts = [str(spans[slot]) for slot, spec in row.items() if spec[0] in ("span", "word") and spans.get(slot)]
    if sorted(set(numbers)) != sorted(nwm.free_numbers(said, texts)):
        return None
    tables = natural._tables(None)
    slots = {"numbers": numbers}
    if op in ("mail-reply", "mail-draft") and spans.get("body"):
        slots["body"] = spans["body"]
        if mail_reply_compose.described(spans["body"], said):
            slots["_compose_reply"] = True          # BL7-2: a body that describes the text is worded by the model when composing is on (`_reference_args`); a dictated one is the text
    if op == "mail-move" and args.get("folder"):
        slots["folder_name"] = args["folder"]
    if op == "mail-mark" and spans.get("state"):
        got = nwm.answer("state", spans["state"], {}, tables)
        if got:
            slots["state"] = got["slots"]["state"]
    return turn_gate.Seed({"op": op, "by": "numbers", "slots": slots}, {"numbers": "line-number", **{key: "line-span" for key in ("body", "folder_name", "state") if key in slots}})


def _body_key(ctx: dict, channel, sender) -> str:
    """The question for the body: the one that also says the text will be worded and how to send it as written, when composing is on for the sender."""
    return "MC_ASK_BODY" if mail_compose.available(ctx, channel, sender) else "NW_MAIL_ASK_BODY"


def _compose_args(ctx: dict, op: str, slots: dict, channel=None, sender=None):
    """The arguments of a new e-mail or a new draft, or the question. When the text was asked of the interpreter's seed or answered to the body question (`_compose`), and
    composing is on for the sender (runtime/mail_compose.py), the model words the body (and the subject when the person gave none: `_ai_subject`) from the person's words;
    the text starts with the marker of a literal text ("exact text:") it is sent as written. Every other body is the person's own words."""
    account, ask = _compose_account(ctx, slots)
    if ask:
        return ask
    account_origin = _account_origin(slots)          # S41-7: the one named (or picked), else the project's configuration
    if not slots.get("to"):
        names = slots.get("to_names") or []
        return _ask("to", "NW_MAIL_ASK_TO", name=_joined(names) if names else "")
    to = _joined(slots["to"])
    if not slots.get("subject") and not slots.get("_ai_subject"):
        return _ask("subject", "NW_MAIL_ASK_SUBJECT", to=to)
    if not slots.get("body"):
        return _ask("body", _body_key(ctx, channel, sender), to=to)
    subject, body = slots.get("subject"), slots["body"]
    subject_origin, body_origin = turn_gate.origin_of(slots, "subject", "line-span"), turn_gate.origin_of(slots, "body", "line-span")
    if slots.get("_compose"):
        got = mail_compose.write(ctx, channel, sender, slots["to"], subject, body, bool(slots.get("_ai_subject")))
        if got["composed"]:      # S41-7: the model worded the body, and the subject too when the person gave none (a subject the person gave stays the person's words)
            body_origin = "composed"
            if not subject:
                subject_origin = "composed"
        subject, body = got["subject"], got["body"]
        if not subject:
            return _ask("subject", "NW_MAIL_ASK_SUBJECT", to=to)
    else:
        body = mail_compose.strip_marker(body)[0]
    if not body.strip():      # "exact text:" with nothing after it
        return _ask("body", _body_key(ctx, channel, sender), to=to)
    args = {"account": account, "to": ",".join(slots["to"]), "subject": subject}
    key = "text" if op == "mail-send" else "body"
    args[key] = body
    return {"args": args, "origins": {"account": account_origin, "to": turn_gate.origin_of(slots, "to", "line-span"), "subject": subject_origin, key: body_origin}}


def resolve(ctx: dict, op: str, slots: dict, channel, sender, said=None) -> dict:
    """See the module's text. `slots` is what the line and the answers so far gave; `said` is the person's lines so far (the caller keeps them for its own check)."""
    slots = dict(slots or {})
    with turn_gate.turn():      # BL5E, S41-6: the line's refresh budget (one provider read at most; an inner reuse inside a line, an entry of its own for a call made directly, cleared when it ends)
        try:
            if op in REF_OPS or (op == "mail-draft" and _has_reference(slots)):
                return _reference_args(ctx, op, slots, channel, sender)
            if op in ("mail-send", "mail-draft"):
                return _compose_args(ctx, op, slots, channel, sender)
        except Say as e:
            return {"say": {"sentence_key": e.key, "fields": e.fields}}
    raise core.OpsError(f"{op} is not an operation of the mail family", 2)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
