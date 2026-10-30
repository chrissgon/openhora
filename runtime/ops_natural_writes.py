#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The card-opening path of the natural writes (package NR-5): the ONE place that opens a write to the person's own accounts for a line (limit L61, contracts/runtime.md).

A plain line ("marca dentista quinta as 10h", "salva esse pdf no drive") is read by code into the slots of an operation (runtime/natural_writes.py and its family modules);
what the line leaves open is asked back, one question at a time, in a fixed order (the draft waits in the one store, runtime/drafts.py, owner `write`: memory only, ten
minutes, one per channel and sender, never logged, never in the store); and when every slot is filled the operation's OWN function is called, as the typed command is,
with the carrying channel and the sender, so that `account_start.start` asks the policy again, checks `accounts`, the gate and its group, prepares with no model and
stops at the card. The card is the confirmation: this path asks no "yes" before it, executes no write, approves nothing and never uses a standing approval.

The order of `open_line` (SPEC-NATURAL-WRITES 5.1):
  1. the operation is an E operation whose row lists the carrying channel (else the typed command's sentence);
  2. `operations.refusal(op, channel, policy, sender=sender)`: the sentence the typed command gets, before anything is read; on a messaging app the sender must also be
     sent a card (`pending`), else nothing is opened that nobody could see;
  3. the pure reading, then the resolution of what needs the project (the family's `ops_natural_<family>.resolve`: the account, the calendar, the folder, the reference,
     the held file); any gap is a question and nothing is opened;
  4. the gate's provenance check (`turn_gate.provenance`, S41-7): every argument the resolver returned carries the origin it came from (`{"args", "origins"}`; a pick is `picked`, a seed's part has the origin
     its producer gave it, `turn_gate.Seed`), and an argument with none, or with one its key may not have, opens nothing: the draft is dropped, the stored row is the neutral word and the reply is
     `refused_sentence` (one plain sentence on a phone; one line on stderr with the operation and the argument names, never a value); then
     the operation's own function (the conversation's shell is the terminal's equal, so it opens the card as the terminal); an `OpsError` is the reply;
  5. the reply: the doubt or rolled line when there is one, then `ACCT_CARD_SENT`; `extras["resend"]` carries the decision so that the messaging bridge sends the card to the
     asking chat; on the terminal the reply also carries the card's lines and the approve command (the exact hash).

The answers to a question: the number of an option or its word, or (LP-1, runtime/list_pick.py) an ordinal word, the word for last, the sender of a message question by the words of
its address or a brand for an account question (a single choice only; a multiple choice is answered by numbers alone); for a time, a reading or a weekday the time engine (`natural.complete`); for a title, a subject, a body, a
content or a file name the line itself, verbatim; a number for an event; "no" or "cancel" drops the draft. A short reply that fits nothing is asked once more; any other line
drops the draft and is handled as new, as is a line that starts a request of its own.

The conversation stores a neutral word for the line, the questions and the replies (`stored_line`, `extras["stored"]`); a messaging line is not stored at all.

Sibling of runtime/ops_natural.py (which calls `open_line` and `answer`) and runtime/ops_say.py (`natural_write`). Reaches ops.py at call time. Standard library only.
Runs on Python 3.9: python3 runtime/ops_natural_writes.py --help
"""
from __future__ import annotations

import importlib
import re
import sys

import drafts
import line_stage
import list_pick
import natural
import natural_writes as nw
import operations
import ops_actor
import ops_core as core
import ops_natural
import phone_refusal
import phrases
import project_config
import recurrence
import source_names
import turn_gate

DRAFT_TTL = ops_natural.DRAFT_TTL
KIND = "write"
ONE_LINE = ("title", "subject", "name")        # a text slot that is one line
TEXT_NEEDS = {"title": "title", "subject": "subject", "body": "body", "content": "content", "name": "name"}      # need -> the cap of nw.SPAN_MAX
NUMBER_NEEDS = ("event",)
ANSWER_RETRIES = 1
REASKS = 2                       # a question asked again after answers that left it open (a file name that fails the check) is given up at the second


def _t(ctx: dict, key: str, **fields) -> str:
    return phrases.text(key, ctx["cfg"], **fields)


def family_ops(family: str):
    return importlib.import_module("ops_natural_" + family)


def _slot(channel, sender):
    return ops_natural._slot(channel, sender)


def live(channel, sender):
    """The sender's live write draft, or None."""
    return drafts.get(*_slot(channel, sender), "write")


def forget(channel, sender) -> None:
    """Drop the sender's open question."""
    if live(channel, sender) is not None:
        drafts.drop(*_slot(channel, sender))


def has_live(project: str, channel, sender) -> bool:
    ctx = core.context(project)
    draft = live(channel, sender)
    return draft is not None and draft.get("project") == ops_natural.project_key(ctx["cfg"]["project"])


# --- shared steps of the families --------------------------------------------------------------------------------------------------------------------


def ask_spec(need: str, sentence_key: str, fields=None, options=None, slot=None, multi: bool = False, engine=None) -> dict:
    """The question a resolver asks: `need` (the kind of answer), the phrase key and fields of the sentence, the options (a list of {"value", "label"}) the person chooses
    from by number or word, the slot the answer fills (default: the need), and, for a time, the engine's draft."""
    return {"ask": {"need": need, "slot": slot or need, "sentence_key": sentence_key, "fields": fields or {}, "options": options or [], "multi": multi, "engine": engine}}


def cards_spec(ids: list, sentence_key: str) -> dict:
    """The reply that is a sentence and the cards of held files, sent again by the messaging bridge (package ATT-3): a file to choose among several, or the place to save one."""
    return {"cards": {"ids": list(ids), "sentence_key": sentence_key}}


def say_spec(sentence_key: str, **fields) -> dict:
    return {"say": {"sentence_key": sentence_key, "fields": fields}}


SERVICE_NAME = {"google": "Google", "microsoft": "Microsoft"}


def accounts_with(ctx: dict, section: str) -> list:
    """The configured accounts whose section (calendars, folders, mail_folders) is not empty, in a fixed order."""
    out = []
    for account in ("google", "microsoft"):
        entry = ((ctx["cfg"].get("accounts") or {}).get(account))
        if isinstance(entry, dict) and entry.get(section):
            out.append(account)
    return out


def pick_account(ctx: dict, wanted, section: str, source_account=None, slot: str = "account"):
    """The account a write goes to: ("ok", account), or ("spec", the question or sentence to return). Order of the sources (SPEC 3.2): a service word of the line, the
    account of the reference, the one account whose section is configured, `accounts.default` when two qualify, else the question with both names. The answer to the question
    fills the slot `account`."""
    if wanted:
        return "ok", wanted
    if source_account:
        return "ok", source_account
    candidates = accounts_with(ctx, section)
    if not candidates:
        return "spec", say_spec("NW_NO_ACCOUNT")
    if len(candidates) == 1:
        return "ok", candidates[0]
    default = project_config.account_default(ctx["cfg"])
    if default in candidates:
        return "ok", default
    options = [{"value": a, "label": f"{SERVICE_NAME[a]} ({ctx['cfg']['accounts'][a]['address']})"} for a in candidates]
    return "spec", ask_spec("account", "NW_ASK_ACCOUNT", options=options, slot=slot)


def named_target(ctx: dict, account: str, section: str, name, slot: str):
    """("ok", the configured name or None), or ("spec", the question). A name is taken only when it equals, folded, a name the account lists; one it does not is answered with
    the names that are configured (never a near match). With no name, folders and calendars take their default in the operation; a folder with no default is asked."""
    listed = list(((ctx["cfg"].get("accounts") or {}).get(account) or {}).get(section) or {})
    if name is None:
        if section == "folders" and "default" not in listed and listed:
            return "spec", ask_spec("folder", "NW_ASK_FOLDER_NONE", {"names": ", ".join(listed)}, [{"value": n, "label": n} for n in listed], slot=slot)
        return "ok", None
    if name in listed:
        return "ok", name
    key = "NW_ASK_CALENDAR" if section == "calendars" else "NW_ASK_FOLDER"
    return "spec", ask_spec("folder" if section != "calendars" else "calendar", key, {"name": name, "names": ", ".join(listed) or "-"}, [{"value": n, "label": n} for n in listed],
                            slot=slot)


def engine_spec(ctx: dict, slots: dict):
    """The question for a time the engine has not settled, or None."""
    engine = slots.get("_engine")
    if not engine:
        return None
    return ask_spec(engine["need"], "", engine=engine)


def title_spec(ctx: dict, slots: dict):
    when = slots.get("_when")
    if when:
        return ask_spec("title", "NW_ASK_TITLE", {"when": natural.describe(when, ctx["cfg"])})
    return ask_spec("title", "NW_ASK_TITLE_PLAIN")


# --- the sentences of a spec ----------------------------------------------------------------------------------------------------------------------------


def sentence_of(ctx: dict, spec: dict, slots: dict) -> str:
    cfg = ctx["cfg"]
    engine = spec.get("engine")
    if engine:
        if engine["need"] == "time" and not engine.get("day"):
            title = slots.get("title")
            return phrases.text("NW_ASK_TIME", cfg, title=title) if title else phrases.text("NW_ASK_TIME_PLAIN", cfg)
        return natural.question(engine, cfg, False, "write")[0]
    text = phrases.text(spec["sentence_key"], cfg, **spec["fields"])
    if spec["options"]:
        text += "\n" + "\n".join(f"{n}. {o['label']}" for n, o in enumerate(spec["options"], 1))
    return text


# --- the draft ----------------------------------------------------------------------------------------------------------------------------------------


def new_state(ctx: dict, reading: dict, said_line: str) -> dict:
    slots = dict(reading["slots"])
    if reading.get("engine"):
        slots["_engine"] = reading["engine"]
    if reading.get("reading"):
        slots["_when"] = reading["reading"]
    return {"kind": KIND, "op": reading["op"], "family": reading["family"], "project": ops_natural.project_key(ctx["cfg"]["project"]), "slots": slots,
            "origins": dict(reading.get("origins") or {}),
            "need": None, "slot": None, "options": [], "multi": False, "said": [said_line], "retries": 0, "doubt": bool(reading.get("doubt")),
            "end_clock": reading.get("end_clock"), "all_day": bool(reading.get("all_day")), "end_ok": reading.get("end_ok", True),
            "recurring": bool(reading.get("recurring")), "seeded": bool(reading.get("seeded"))}


def _now():
    return ops_natural._clock()


def _admit(ctx: dict, op: str, channel, sender):
    """The sentence that refuses the operation to this caller (SPEC 5.1 steps 1 and 2), or None."""
    cfg = ctx["cfg"]
    try:
        row = operations.by_name(op)
    except KeyError:
        return f"error: {op} is not an operation of the table"
    if natural.class_of(op) != "E":
        return f"error: {op} is not a write to your accounts"
    where = "terminal" if channel == "chat" else channel          # the conversation's shell is the terminal's equal for the channels a row lists and for the policy
    if where not in row["channels"]:
        if channel == "messaging":      # a phone has no terminal: what and where, never a command (limit L62)
            return ops_natural.phone_sentence(ctx, op)
        extra = ops_natural._command(ctx, op, {}, "terminal", channel)
        return f"error: /{op} is done in the terminal or on the page" + (f". {extra}" if extra else "")
    refused = operations.refusal(op, where, cfg["channels"], sender=sender)
    if refused:
        return phone_refusal.said(refused, channel, cfg)
    if channel == "messaging" and not operations.permitted("pending", where, cfg["channels"], None, sender):
        return _t(ctx, "NW_NO_CARDS")
    return None


# --- opening ------------------------------------------------------------------------------------------------------------------------------------------


def carrier(channel) -> str:
    """The channel an operation is called as and records. The conversation's shell (`chat`) is called as the terminal, its equal: the rows of the table list the terminal,
    and the account step refuses `chat` as a channel it does not know (test_files_write, W4a) so that a channel is never taken for the terminal by accident. This is the one
    place where the shell is named, and the decision record says so (decisions.md, NR-5)."""
    return "terminal" if channel == "chat" else channel


def _call_operation(project: str, op: str, args: dict, channel, sender):
    """The operation's own function, as the typed command calls it: the carrying channel (the conversation's shell is the terminal's equal) and, on a messaging app, the
    sender, inside `ops_actor.carried_by`."""
    row = operations.by_name(op)
    function = getattr(importlib.import_module("ops"), row["call"])
    found = dict(args)
    car = carrier(channel)
    found["channel"] = car
    if car == "messaging":
        found["sender"] = sender
    with ops_actor.carried_by(car):
        return function(project, **found)


def _card_lines(ctx: dict, project: str, started: dict, channel) -> str:
    """On the terminal (the person's own) the card's lines and the approve command with the exact hash; elsewhere nothing: the card is sent or is on the page."""
    if channel not in ("chat", "terminal"):
        return ""
    try:
        item = importlib.import_module("ops").pending(project, pending_id=started["pending"])
    except core.OpsError:
        return ""
    command = core._command("approve", ctx["cfg"]["project"], pending_id=started["pending"], sha256=item.get("payload_sha256") or "<hash>")
    return "\n" + str(item.get("body") or "").strip() + "\n" + _t(ctx, "NW_APPROVE_WITH", command=command)


def refused_sentence(ctx: dict, op: str, problems: list, channel, extras: dict) -> str:
    """The reply of a card that the gate's provenance check refused (S41-7, limits L55, L60 and L61): nothing was opened, the stored row is the neutral word, one line with the operation and the
    names of the arguments (never a value) goes to stderr, and the person is asked again in a plain sentence on a phone (limit L62) and told what happened where the error text is read."""
    print(turn_gate.refusal_line(op, problems), file=sys.stderr)
    extras["stored"] = _t(ctx, "NW_PRIVATE_REPLY")
    if channel == ops_actor.MESSAGING:
        return _t(ctx, "IX_ASK_AGAIN")
    return turn_gate.refusal_text(op, problems)


def _opened(project: str, ctx: dict, state: dict, args: dict, channel, sender, extras: dict) -> str:
    cfg = ctx["cfg"]
    extras["stored"] = _t(ctx, "NW_PRIVATE_REPLY")
    problems = turn_gate.provenance(state["op"], args, state.get("arg_origins") or {})      # S41-7: every argument carries where it came from, checked before the operation is called (fail closed)
    if problems:
        return refused_sentence(ctx, state["op"], problems, channel, extras)
    try:
        started = _call_operation(project, state["op"], args, channel, sender)
    except core.OpsError as e:
        return ops_natural._error(cfg, e, channel)
    account_start = importlib.import_module("account_start")
    lines = []
    when = state["slots"].get("_when")
    if when and when.get("rolled"):
        lines.append(_t(ctx, "NT_ROLLED", time=when["time"], when=natural.describe(when, cfg)))
    if state.get("doubt") and when:
        lines.append(_t(ctx, "NW_CHECK_DATE", when=natural.describe(when, cfg)))
    if state.get("notice"):          # a line the family asks the reply to carry (BL7-2: the text of a described reply could not be worded)
        lines.append(_t(ctx, state["notice"]))
    extras["resend"] = started["pending"]
    return "\n".join(lines + [account_start.reply_text(cfg, started)]) + _card_lines(ctx, project, started, channel)


def advance(project: str, ctx: dict, state: dict, channel, sender, extras: dict) -> str:
    """Resolve what the project decides and either open the card or ask the next question. The draft is kept only while a question is open."""
    slot = _slot(channel, sender)
    if state.get("recurring"):
        drafts.drop(*slot)
        extras["stored"] = _t(ctx, "NW_PRIVATE_REPLY")
        return _t(ctx, "RECUR_NOT_READ")      # S41-11 (A11-6): "an event that repeats is not available yet" is false since CB-7; the one sentence for a repetition code cannot read
    if state["op"] == "event-create" and not state.get("seeded") and any(recurrence.mentions(line) for line in state["said"]):      # CB-7: the closed forms read "marca academia semanal amanha as 7h" as one event; a repetition phrase that no seed carried (the interpreter's `_repeat` seeds the only one code reads) opens no event card
        drafts.drop(*slot)
        extras["stored"] = _t(ctx, "NW_PRIVATE_REPLY")
        return _t(ctx, "RECUR_NOT_READ")
    if not state.get("end_ok", True) and "end" not in state["slots"]:
        spec = ask_spec("end", "NW_ASK_END")
        return _ask(ctx, state, spec, channel, sender, extras)
    if state.get("day_needed") and "start" not in state["slots"]:
        return _ask(ctx, state, ask_spec("day", "NW_ASK_DAY"), channel, sender, extras)
    out = family_ops(state["family"]).resolve(ctx, state["op"], dict(state["slots"], **({"_origins": dict(state["origins"])} if state.get("origins") else {})), channel, sender, state["said"])
    if "args" in out:
        drafts.drop(*slot)
        opened = dict(state, arg_origins=dict(out.get("origins") or {}), **({"notice": out["notice"]} if out.get("notice") else {}))      # what the resolver made of each argument, for the gate (S41-7)
        return _opened(project, ctx, opened, out["args"], channel, sender, extras)
    extras["stored"] = _t(ctx, "NW_PRIVATE_REPLY")
    if out.get("silent"):          # nothing to ask and nothing to say: the caller has the file's card (a caption never opens a question)
        drafts.drop(*slot)
        extras["silent"] = True
        return ""
    if "cards" in out:
        drafts.drop(*slot)
        extras["cards"] = out["cards"]["ids"]
        return _t(ctx, out["cards"]["sentence_key"])
    if "say" in out:
        drafts.drop(*slot)
        fields = out["say"]["fields"]
        if channel == ops_actor.MESSAGING:      # BL5D: a phone reads the plain name of a source, never its id (the stored values are not touched)
            fields = _phone_fields(ctx, fields)
        return phrases.text(out["say"]["sentence_key"], ctx["cfg"], **fields)
    return _ask(ctx, state, out, channel, sender, extras)


def _phone_options(ctx: dict, options: list) -> list:
    """The options of a question as a phone shows them (BL5D): an option whose label is a source id, or a reference `<source id>#<n>`, is shown by the plain name of the source
    ("Gmail", "Gmail, message 3") and, for a source, also stores the service words of its account, so that the provider's word answers it. The VALUE of an option is never changed: whatever
    the person answers selects exactly what it selected before. Any other label (a message, a folder, an account) is untouched."""
    table = source_names.catalog(ctx)
    out = []
    for option in options:
        label = source_names.shown(option["label"], table, ctx["cfg"])
        if label == option["label"]:
            out.append(option)
            continue
        entry = table.get(option["label"])
        out.append({"value": option["value"], "label": label, "words": source_names.words(entry) if entry else []})
    return out


def _phone_fields(ctx: dict, fields: dict) -> dict:
    """The fields of a sentence for a phone (BL5D): `source` and `ref` name a source or a message by its plain name, and no other field is touched."""
    table = source_names.catalog(ctx)
    return {k: (source_names.shown(v, table, ctx["cfg"]) if k in ("source", "ref") else v) for k, v in fields.items()}


def _ask(ctx: dict, state: dict, spec: dict, channel, sender, extras: dict) -> str:
    ask = spec["ask"]
    if state.get("answered") == ask["need"]:           # the answer left this very question open: asked again, and given up when it happens twice
        state["repeats"] = state.get("repeats", 0) + 1
        if state["repeats"] >= REASKS:
            drafts.drop(*_slot(channel, sender))
            extras["stored"] = _t(ctx, "NW_PRIVATE_REPLY")
            return _t(ctx, "NW_GIVE_UP")
    else:
        state["repeats"] = 0
    state["answered"] = None
    options = _phone_options(ctx, ask["options"]) if channel == ops_actor.MESSAGING and ask["options"] else ask["options"]
    state.update(need=ask["need"], slot=ask["slot"], options=options, multi=ask["multi"], sentence_key=ask["sentence_key"], fields=ask["fields"],
                 retries=state.get("retries", 0))
    if ask.get("engine"):
        state["slots"]["_engine"] = ask["engine"]
    state["slots"].update(ask.get("keep") or {})          # what the family asks the draft to remember while the question is open (BL5E: the snapshot a list of mail was drawn from)
    drafts.put(*_slot(channel, sender), state, "write", ttl=DRAFT_TTL)
    extras["stored"] = _t(ctx, "NW_PRIVATE_REPLY")
    extras["asked"] = True
    text = sentence_of(ctx, {**ask, "options": options}, state["slots"])
    if extras.pop("discarded", False):
        text = _t(ctx, "NT_DISCARDED") + " " + text
    return text


# --- the reading of a line ----------------------------------------------------------------------------------------------------------------------------


def _declared(seed) -> dict:
    """The origins a seed declares for its own parts (S41-7): `turn_gate.Seed.origins`, or the `origins` key of a seed that a messaging module built (it may not import the gate: data only)."""
    found = getattr(seed, "origins", None)
    if found is None and isinstance(seed.get("origins"), dict):
        found = seed["origins"]
    return dict(found or {})


def _origins_of(seed, own) -> dict:
    """The origin of each slot the SEED supplied (`own`): the one it declares, else `undeclared`, which is no origin, so the argument made of that slot opens no card. A slot that the closed
    reading of a line or an answer to a question made has the default origin of its key and is not listed here."""
    declared = _declared(seed)
    return {**{key: turn_gate.UNDECLARED for key in own if not str(key).startswith("_")}, **declared}


def _read(ctx: dict, said: str, seed, hint):
    now = _now()
    if seed:
        op = seed["op"]
        if op in ("event-change", "event-cancel") and seed.get("slots"):          # an event found by its words (runtime/event_lookup.py): its source and number, and what to change
            return {"op": op, "family": "calendar", "slots": dict(seed["slots"]), "spans": {}, "ranges": {}, "need": [], "engine": None, "doubt": False, "origins": _origins_of(seed, seed["slots"])}
        if op in ("event-change", "event-cancel") and seed.get("line"):          # a number said after a list (runtime/event_lookup.py `take`): the numbered line, read as such, bound to the source the list showed
            got = nw.read(seed["line"], now, op=op)
            if got is not None:
                got["slots"].update(seed.get("bind") or {})
                got["origins"] = _origins_of(seed, seed.get("bind") or {})
            return got
        if op == "event-create" and seed.get("reading"):
            reading = seed["reading"]
            slots = {"start": f"{reading['date']}T{reading['time']}"}
            if seed.get("text"):
                slots["title"] = seed["text"]
            if seed.get("account"):          # the account the line names (runtime/event_lookup.py `seed_service`): the family does not ask which
                slots["account"] = seed["account"]
            if seed.get("repeat"):          # CB-7: the repetition code read from the closed words of the line (runtime/recurrence.py); declared with its origin like the other parts
                slots["repeat"] = seed["repeat"]
            return {"op": op, "family": "calendar", "slots": slots, "spans": {}, "ranges": {}, "need": [], "engine": None, "doubt": False, "reading": reading, "origins": _origins_of(seed, slots), "seeded": True}
        if op in ("mail-reply", "mail-draft", "mail-archive", "mail-trash", "mail-move", "mail-mark") and seed.get("slots") is not None and seed.get("by") in ("target", "numbers"):          # a message named by its words (runtime/ops_natural_mail.py `mail_target_seed`) or by the numbers the model gave (`mail_number_seed`, BL7-5): its slots, never the closed forms
            return {"op": op, "family": "mail", "slots": dict(seed["slots"]), "spans": {}, "ranges": {}, "need": [], "engine": None, "doubt": False, "origins": _origins_of(seed, seed["slots"])}
        if op in ("mail-send", "mail-draft") and seed.get("slots") is not None:          # a new e-mail the interpreter decided (runtime/mail_compose.py `seed`): its slots, never the closed forms
            return {"op": op, "family": "mail", "slots": dict(seed["slots"]), "spans": {}, "ranges": {}, "need": [], "engine": None, "doubt": False, "origins": _origins_of(seed, seed["slots"])}
        if op == "file-save" and seed.get("attachment") is not None:          # a held file named by its number (the caption of a file, a button of its card): the text may add a folder
            got = nw.read(said, now, op=op) if said.strip() else None
            got = got or {"op": op, "family": "files", "slots": {}, "spans": {}, "ranges": {}, "need": [], "engine": None, "doubt": False}
            got["slots"]["attachment"] = seed["attachment"]
            own = ["attachment"]
            if seed.get("account"):
                got["slots"]["account"] = seed["account"]
                own.append("account")
            if seed.get("folders"):
                got["slots"]["_folders"] = seed["folders"]
            got["origins"] = _origins_of(seed, own)
            return got
        return nw.read(said, now, op=op)
    return nw.read(said, now, op=hint)      # S41-11: `nw.read` reads nothing without an operation (no closed head claims a line any more): a decision of the interpreter, a number said after a list, a seed


def open_line(project: str, ctx: dict, said: str, channel, sender, extras: dict, *, seed=None, hint=None):
    """The reply for a line that is a write form of a family (or the seed of one), or None when it is not (the line goes on as before). Nothing is executed here: the reply
    is a question, a sentence, or the card's notice (see the module's text)."""
    reading = _read(ctx, said, seed, hint)
    if reading is None:
        return None
    op = reading["op"]
    if channel == "mcp":
        return None
    refused = _admit(ctx, op, channel, sender)
    if refused:
        extras["stored"] = _t(ctx, "NW_PRIVATE_REPLY")
        return refused
    if reading.get("say"):          # a form that is no write form but that NR-1 would have taken for a new event: the sentence only (a typed number form with a number that is not one)
        extras["stored"] = _t(ctx, "NW_PRIVATE_REPLY")
        return _t(ctx, reading["say"])
    if reading.get("by_name"):          # a change with no number in the line (slice S16b): the event is found by its name, the card that follows is the question
        return importlib.import_module("event_lookup").by_name(project, ctx, said, sender, extras, importlib.import_module("ops_natural_writes"), _now())
    line_stage.publish("card")      # S19: the card of the exact content is being prepared (a later stage, the e-mail's wording, replaces it)
    state = new_state(ctx, reading, said)
    return advance(project, ctx, state, channel, sender, extras)


# --- the answers --------------------------------------------------------------------------------------------------------------------------------------


def _folded(text: str) -> str:
    return natural.normal(text)


def _classify(ctx: dict, state: dict, said: str):
    """What a line says to the open question, without changing anything: None (not an answer), or {"kind": "cancel" | "retry" | "slots" | "engine", ...}."""
    cfg_project = ops_natural.project_key(ctx["cfg"]["project"])
    if state.get("project") != cfg_project or not said.strip() or said.lstrip().startswith("/"):
        return None
    if natural.confirm_kind(said) == "no":
        return {"kind": "cancel"}
    need, tables, now = state["need"], natural._tables(None), _now()
    if turn_gate.lead_kind(said) is not None or natural.match(said) is not None or _starts_with_head(said, tables):      # S41-11: a line that starts as a new request (a reminder or an event lead of the private words, a closed form of the tables, the head of a write family) is not an answer. `match` is only a recogniser here, no claimer: a read said while a title is asked ("mostra minha agenda") is still not the title
        return None
    module = importlib.import_module(nw.FAMILIES[state["family"]])
    if need in getattr(module, "NEEDS", ()):          # a need the family answers itself (the answer may be a number it showed, not a place in the list)
        got = module.answer(need, said, state["slots"], tables, now, options=state["options"])
        if got is not None and need == "body" and state["op"] in ("mail-send", "mail-draft"):
            got["slots"]["_compose"] = True          # the answer describes the e-mail: the model words it when composing is on, "exact text:" sends it as written (runtime/mail_compose.py)
        return {"kind": "slots", "slots": got["slots"]} if got is not None else _retry(state, said, tables)
    if need in ("time", "reading", "weekday"):
        engine = state["slots"].get("_engine")
        got = turn_gate.complete_reminder(engine, said, now, tables) if engine else None
        if got is None:
            return None
        if got.get("cancel"):
            return {"kind": "cancel"}
        return {"kind": "engine", "got": got}
    if state["options"]:
        picked = _option(state, said)
        if picked is not None:
            return {"kind": "slots", "slots": {state["slot"]: picked}, "origin": "picked"}          # the person chose it among the options code listed (S41-7: its origin is a pick)
        return _retry(state, said, tables)
    if need in TEXT_NEEDS:
        text = said.strip()
        if need in ONE_LINE and _another_request(text, tables):
            return None
        if not text or len(text) > nw.SPAN_MAX[TEXT_NEEDS[need]] or (need in ONE_LINE and "\n" in text) or (need in ONE_LINE and natural.confirm_kind(text) == "yes"):
            return _retry(state, said, tables)
        return {"kind": "slots", "slots": {state["slot"]: text}}
    if need in NUMBER_NEEDS:
        m = re.fullmatch(r"\s*#?\s*([0-9]{1,4})\s*[.!]?\s*", said)
        if m and int(m.group(1)) >= 1:
            return {"kind": "slots", "slots": {state["slot"]: int(m.group(1))}}
        return _retry(state, said, tables)
    return _retry(state, said, tables)


def _another_request(text: str, tables: list) -> bool:
    """Whether a line offered as a title, a subject or a name is rather a question or a request (it is then a new line, never the title). What NR-1's text need refuses is
    refused here: a question mark, a line over its word limit, a recurrence; and, for a line of three words or more, a work verb anywhere, a question or request word first;
    and, for a line of two words or more, a write head of any family first ("cria um documento sobre..."). A short line is a title."""
    if text.endswith("?") or len(text.split()) > natural.TEXT_MAX_WORDS or natural.nt.recurring(text, tables):
        return True
    words = text.split()
    tokens = natural._words(natural.nt.normalise(text)[0])
    if len(words) >= 3:
        verbs = {w for table in tables for w in table["work_verbs"]}
        starters = {w for table in tables for w in table["work_starters"]}
        if verbs & set(tokens) or (tokens and tokens[0] in starters):
            return True
    if len(words) >= 2:
        return _starts_with_head(text, tables)
    return False


def _starts_with_head(text: str, tables: list) -> bool:
    """Whether a line starts with a write head of any family. A family that knows its CLOSED head (`is_head`: the verb, the articles and the object, as the mail family does) says
    it itself, so that a title that begins with a bare verb ("Passa no banco", "Send flowers", "Reply to Ana") is a title; a family without it is asked by its verbs."""
    shaped = nw.Line(text)
    for name in nw.FAMILIES:
        module = importlib.import_module(nw.FAMILIES[name])
        closed = getattr(module, "is_head", None)
        if closed is not None:
            if closed(text, tables):
                return True
        elif module.HEADS(tables) and _object_follows(shaped, module.HEADS(tables), name, tables):
            return True
    return False


def _object_follows(shaped, heads: list, family: str, tables: list) -> bool:
    """Whether a verb of the family is followed, after the articles, by an object noun of the family ("cria um documento", "salva esse pdf", "marca na agenda"): a bare verb followed
    by anything else ("Envia proposta", "Send flowers", "Marca presenca") is the start of a title. A family without such nouns is asked by its verbs alone."""
    end = shaped.lead(heads, tables)
    if end is None:
        return False
    nouns = [p for key in ("nouns", "nouns_plural", "held_nouns", "in_calendar", "this") for p in nw.listed(tables, family, key)]
    if not nouns:
        return True
    at = nw.skip_articles(shaped, end, tables)
    here = re.compile(r"\s*").match(shaped.norm, at).end()
    found = shaped.find(nouns, here, here + 40)
    return bool(found and found[0] == here)


def _retry(state: dict, said: str, tables: list):
    """The same question once more for a short reply that does not answer it; the second time the question is given up (a sentence says nothing was opened); a reply that is
    not short is a new line (None)."""
    if not natural.short_answer(said, tables, new=turn_gate.new_request(said)):
        return None
    return {"kind": "retry"} if state.get("retries", 0) < ANSWER_RETRIES else {"kind": "giveup"}


def _keys(option: dict) -> set:
    """The folded words and phrases that name one option as a whole line: its value, its label, the label without a parenthesis, the service words of an account option and the words of a
    source option shown by its plain name."""
    keys = {_folded(str(option["value"])), _folded(option["label"]), _folded(option["label"].split("(")[0])}
    keys |= {_folded(p) for p in nw.listed(natural._tables(None), "services", str(option["value"]))}          # an account option is also named by its service words, language data
    keys |= {_folded(w) for w in option.get("words") or []}          # BL5D: a source option shown by its plain name is also named by the service words of its account
    return keys


def _option_pick(state: dict, said: str):
    """LP-1: the option a reply names without its number, or None (runtime/list_pick.py reads it; the options are numbered 1..k, so a position is the place in the question the person read):
    an ordinal word or the word for last ("a última", "o segundo"), the sender of a message question by the words of its address ("o do banco", "o da ana": exactly one option's address
    holds every word), a brand for an account or a mailbox question ("o do outlook": the same keys a whole-line answer is matched with). Never with a verb, never inside a longer line."""
    form = list_pick.read(said)
    options = state["options"]
    if form is None or form["verb"] is not None or not options:
        return None
    if form["kind"] == "last":
        return options[-1]["value"]
    if form["kind"] == "ordinal":
        return options[form["position"] - 1]["value"] if form["position"] <= len(options) else None
    if state.get("need") == "message" and form["kind"] in ("words", "account"):
        hits = [o for o in options if set(form["words"]) <= list_pick.address_words(o["label"])]
    elif state.get("need") in ("account", "source") and form["kind"] == "account":
        wanted = " ".join(form["words"])
        hits = [o for o in options if wanted in _keys(o)]
    else:
        return None
    return hits[0]["value"] if len(hits) == 1 else None


def _option(state: dict, said: str):
    """The value of the option(s) the line names by number or word, or None."""
    options = state["options"]
    if state["multi"]:
        line = nw.Line(said)
        listed = nw.numbers(line, 0, len(line.norm), natural._tables(None))
        if listed and all(1 <= n <= len(options) for n in listed):
            return [options[n - 1]["value"] for n in listed]
        return None
    digits = _folded(said)
    if digits.isdigit() and 1 <= int(digits) <= len(options):
        return options[int(digits) - 1]["value"]
    matches = [option["value"] for option in options if digits in _keys(option)]
    if matches:
        return matches[0] if len(matches) == 1 else None
    return _option_pick(state, said)          # LP-1: an ordinal, the word for last, or a value the question shows


def answers(ctx: dict, state: dict, said: str) -> bool:
    """Whether a line is an answer to the sender's open write question (reads, changes nothing)."""
    return _classify(ctx, state, said) is not None


def answer(project: str, ctx: dict, state: dict, said: str, channel, sender, extras: dict):
    """The reply to a line that answers the open question, or None (the draft is then dropped and the line is a new one)."""
    slot = _slot(channel, sender)
    found = _classify(ctx, state, said)
    if found is None:
        drafts.drop(*slot)
        return None
    extras["stored"] = _t(ctx, "NW_PRIVATE_REPLY")
    state = dict(state, said=state["said"] + [said])
    if found["kind"] == "cancel":
        drafts.drop(*slot)
        return _t(ctx, "NW_CANCELLED")
    if found["kind"] == "giveup":
        drafts.drop(*slot)
        return _t(ctx, "NW_GIVE_UP")
    if found["kind"] == "retry":
        state["retries"] = state.get("retries", 0) + 1
        drafts.put(*slot, state, "write", ttl=DRAFT_TTL)
        extras["asked"] = True
        return sentence_of(ctx, {"engine": state["slots"].get("_engine") if state["need"] in ("time", "reading", "weekday") else None, "sentence_key": state["sentence_key"],
                                 "fields": state["fields"], "options": state["options"]}, state["slots"])
    state["retries"] = 0
    slots = dict(state["slots"])
    origins = dict(state.get("origins") or {})          # S41-7: what a slot was last made of (an answer replaces the record of the slot it fills)
    if found["kind"] == "engine":
        got = found["got"]
        if "ask" not in got:
            drafts.drop(*slot)
            return _t(ctx, "NW_CANCELLED")
        fold = importlib.import_module("natural_writes_calendar").from_engine(got["ask"], state.get("end_clock"), state.get("all_day", False))
        slots.pop("_engine", None)
        if fold["slots"].get("title") and "title" in slots:
            fold["slots"].pop("title")
        slots.update(fold["slots"])
        for key in fold["slots"]:
            origins.pop(key, None)          # the engine's reading of the person's words: the default origin of the slot
        if fold["engine"]:
            slots["_engine"] = fold["engine"]
        if fold["reading"]:
            slots["_when"] = fold["reading"]
        state.update(doubt=state["doubt"] or fold["doubt"], recurring=fold["recurring"], end_ok=fold["end_ok"])
    else:
        slots.update(found["slots"])
        for key in found["slots"]:
            if found.get("origin"):
                origins[key] = found["origin"]
            else:
                origins.pop(key, None)          # typed words, a number or a family's answer: the default origin of the slot
        if state["need"] == "end":
            state["end_ok"] = True
        if state["need"] == "day":
            state["day_needed"] = False
    state["slots"] = slots
    state["origins"] = origins
    state["answered"] = state["need"]
    return advance(project, ctx, state, channel, sender, extras)


# --- the entries ---------------------------------------------------------------------------------------------------------------------------------------


def natural_write(project: str, line: str, *, channel: str = "messaging", sender=None, seed=None) -> dict:
    """The messaging bridge's entry (ops.natural_write; not a row of the table): the sender's live write draft is tried first, then the line as a new write, then the seed
    (a reminder question answered "event", the loose verb's question, the caption of a file). Returns {"reply": the sentence | None, "resend": the decision whose card the
    bridge sends, "asked": true when a question was kept}. `reply` None: the line is no write form and answers nothing: the caller handles it as any plain line."""
    with turn_gate.turn():      # S41-6: the line's refresh budget (limits L52 and L53); an inner reuse inside a line, an entry of its own when the entry is called directly
        ops_actor.require(channel, sender)
        ctx = core.context(project)
        said = "" if seed and not str(line or "").strip() else core._text(line, "the line")          # a seed may come with no text (a button of a file's card)
        extras: dict = {}
        draft = live(channel, sender)
        reply = None
        if draft is not None and seed is None:
            reply = answer(project, ctx, draft, said, channel, sender, extras)
            if reply is None:
                extras["discarded"] = True          # the line answers nothing: the question is dropped, and a question this line asks says so
        elif draft is not None:
            drafts.drop(*_slot(channel, sender))
        if draft is None and drafts.get(*_slot(channel, sender)) is not None:
            extras["discarded"] = True          # a question of a reminder (or of an `ask`) is replaced by this line's, and the reply says so
        if reply is None:
            reply = open_line(project, ctx, said, channel, sender, extras, seed=seed)
        return {"reply": reply, **({"resend": extras["resend"]} if "resend" in extras else {}), **({"lead": extras["lead"]} if channel == "messaging" and "lead" in extras else {}), **({"cards": extras["cards"]} if "cards" in extras else {}), **({"silent": True} if extras.get("silent") else {}),
                "asked": bool(extras.get("asked"))}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
