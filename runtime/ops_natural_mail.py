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
    searched for one); a reply and a reply draft take no recipient: the operation takes it from the index of the message answered (limit L60), never from a body;
  * a message is `<source>#<n>` from digits the person wrote, from the source the person wrote, the one registered mail source of the account, or the one the person chose; or
    it is found BY WORDS in the index of the newest snapshot: the words after "do/da/from" must all be whole words of the message's from-address or subject; a singular
    object needs exactly one match (several are listed, up to five, and asked), a plural object takes every match up to 20 (more are asked);
  * the snapshot is read, and a message is listed, only after `item_refs.read_index` accepted the caller (a messaging sender needs the group `ask-mail`): a caller who may not
    read it gets the sentence of `item_refs` and nothing of the mailbox, not even the names of its sources;
  * the account is the one named by a service word of the line (`google`, `gmail`, `outlook`...), or the account of the mailbox the message is in, or the only account the
    project configures, or the account the project chose as its default (when the configuration has one); with two possible it is asked;
  * a mail folder is a name of `accounts.<account>.mail_folders`, folded equal; a name that is not configured lists the configured ones and asks, never a near match.

External content is data: the index of a snapshot (a message's from-address and subject) is another person's words. It is compared with the person's words and shown, in a
question, only to the caller who passed `item_refs.may_read`; an instruction inside it is never followed (nothing here reads a message's text at all).

Sibling of runtime/ops.py's family; imports no operation. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import item_refs  # noqa: E402
import mail_compose  # noqa: E402
import mail_refs  # noqa: E402
import natural_writes_mail as nwm  # noqa: E402
import ops_core as core  # noqa: E402
import phrases  # noqa: E402
import project_config  # noqa: E402
import sources  # noqa: E402
import sources_mail  # noqa: E402

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


def _ask(need: str, key: str, options=None, slot=None, multi: bool = False, **fields) -> dict:
    """A question in the shape the card-opening path takes (runtime/ops_natural_writes.py `ask_spec`): `options` are (value, label) pairs the person chooses from by the number
    shown or the word; `slot` is where the answer goes (default: the need)."""
    return {"ask": {"need": need, "slot": slot or need, "sentence_key": key, "fields": fields, "multi": multi, "engine": None,
                    "options": [{"value": value, "label": label} for value, label in (options or [])]}}


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


def _read_snapshot(ctx: dict, source_id: str, channel, sender) -> dict:
    try:
        return item_refs.read_index(ctx, source_id, channel=channel, sender=sender, kinds=("mail",))
    except item_refs.ItemRefError as e:
        raise _ref_say(e.code, source_id) from None
    except sources.SourcesError as e:
        raise core.OpsError(" ".join(str(e).split())[:200], 1) from None


def _entry_label(entry: dict) -> str:
    """One message as a list shows it (the sender's address and the subject as the index recorded them): shown only to a caller who passed `item_refs.may_read`."""
    subject = " ".join(str(entry.get("subject") or "").split())
    if len(subject) > SUBJECT_LISTED:
        subject = subject[:SUBJECT_LISTED - 1].rstrip() + "…"
    return f"{entry.get('from_address') or '?'} · {subject or '-'}"


def _by_words(ctx: dict, slots: dict, source_id: str, channel, sender):
    """The references that the words of the line name in the newest snapshot of `source_id`: ([refs], None), or ([], the question), or raises when nothing matches. The index is
    read only now, after the caller's right to read it was checked by `read_index` itself."""
    snapshot = _read_snapshot(ctx, source_id, channel, sender)
    words = " ".join(slots["words"])
    found = nwm.match_words(snapshot["entries"], slots["words"], bool(slots.get("newest")))
    if not found:
        raise _say("NW_MAIL_NONE", source=source_id, words=words)
    plural = bool(slots.get("plural")) and not slots.get("newest")
    if plural and len(found) <= nwm.MESSAGES_MAX:
        return [f"{source_id}#{e['n']}" for e in found], None
    if not plural and len(found) == 1:
        return [f"{source_id}#{found[0]['n']}"], None
    shown = found[:nwm.MESSAGES_MAX if plural else LISTED]      # the newest candidates: a singular object is chosen among five, a plural one among the twenty a card takes
    options = [(f"{source_id}#{e['n']}", _entry_label(e)) for e in shown]
    if plural:
        return [], _ask("message", "NW_MAIL_ASK_MESSAGES_OVER", options, slot="chosen", multi=True, count=len(found), max=nwm.MESSAGES_MAX, shown=len(shown))
    return [], _ask("message", "NW_MAIL_ASK_MESSAGE", options, slot="chosen", count=len(found))


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
    """(account, [references], None) or (None, None, the question) for the messages the line names. Raises when the caller may not read the mailbox or nothing matches."""
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
            snapshot = _read_snapshot(ctx, source_id, channel, sender)      # also the age check: a snapshot older than the limit for an unattended task (L53) names nothing
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
    reply = op == "mail-reply" or op == "mail-draft"
    if reply and len(refs) != 1:
        return _ask("message", "NW_MAIL_ASK_MESSAGE", [(r, r) for r in refs[:LISTED]], slot="chosen", count=len(refs))
    if reply:
        if not slots.get("body"):
            return _ask("body", "NW_MAIL_ASK_BODY_REPLY")
        return {"args": {"account": account, "message": refs[0], **({"text": slots["body"]} if op == "mail-reply" else {"body": slots["body"]})}}
    args = {"account": account, "messages": ",".join(refs)}
    if op == "mail-move":
        name, ask = _folder(ctx, account, slots)
        if ask:
            return ask
        args["folder"] = name
    if op == "mail-mark":
        if slots.get("state") not in nwm.STATES:
            return _ask("state", "NW_MAIL_ASK_STATE", [(state, phrases.text(f"NW_MAIL_STATE_{state.upper()}", ctx["cfg"])) for state in nwm.STATES])
        args["state"] = slots["state"]
    return {"args": args}


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
    if not slots.get("to"):
        names = slots.get("to_names") or []
        return _ask("to", "NW_MAIL_ASK_TO", name=_joined(names) if names else "")
    to = _joined(slots["to"])
    if not slots.get("subject") and not slots.get("_ai_subject"):
        return _ask("subject", "NW_MAIL_ASK_SUBJECT", to=to)
    if not slots.get("body"):
        return _ask("body", _body_key(ctx, channel, sender), to=to)
    subject, body = slots.get("subject"), slots["body"]
    if slots.get("_compose"):
        got = mail_compose.write(ctx, channel, sender, slots["to"], subject, body, bool(slots.get("_ai_subject")))
        subject, body = got["subject"], got["body"]
        if not subject:
            return _ask("subject", "NW_MAIL_ASK_SUBJECT", to=to)
    else:
        body = mail_compose.strip_marker(body)[0]
    if not body.strip():      # "exact text:" with nothing after it
        return _ask("body", _body_key(ctx, channel, sender), to=to)
    args = {"account": account, "to": ",".join(slots["to"]), "subject": subject}
    args["text" if op == "mail-send" else "body"] = body
    return {"args": args}


def resolve(ctx: dict, op: str, slots: dict, channel, sender, said=None) -> dict:
    """See the module's text. `slots` is what the line and the answers so far gave; `said` is the person's lines so far (the caller keeps them for its own check)."""
    slots = dict(slots or {})
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
