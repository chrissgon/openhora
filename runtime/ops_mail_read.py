#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The text of ONE message of the mail snapshots (package CB-3, SPEC-CATALOG-BATCH 6.3): `mail-read`, a class R operation behind the group `read-mail-body`.

  mail_read(project[, message, number, match, day, account, channel, sender])   the operation (the typed command, the page, a messaging app): {"status", ...}, below
  reply(project, ctx, args, said, channel, sender, extras)                      the reply a line in words gets (runtime/ops_natural.py `run` calls it for `mail-read`)
  render(outcome, cfg, phone)                                                   the sentence of an outcome, in the project's language

Which message. By NUMBER (`message` is `<source>#<n>`, or `number` is n): the mail sources, narrowed by the account the line names, whose newest snapshot holds that number. One holder:
its text. Two boxes: one sentence that names both (box, who, subject, when) and says how to name the box, and nothing is shown; the reply never picks one. By WORDS (`match`, the words
of the sender or the subject, as `natural_writes_mail.target_words` reads them from the span the interpreter checked in the line, and `day`, read with the time engine as the mail family
reads it): `match_words` over each source's index, then the day (`_on_day`: a candidate with no `received`, or a day the engine cannot read, is asked and never guessed). One match: its text;
two to five: a numbered list with the box and the snapshot's own numbers; more: "say more words"; none: one sentence. Words that leave nothing to look for (only articles and the noun)
and no day are not "every message": the reply asks which one.

What is shown and what is never read. The text is the snapshot's own cleaned body of that message (the credential scan, the links replaced and the cut at 4,000 characters were done when
the snapshot was made; a message that looked like a credential is not in it), parsed by `items_mail.blocks` after `ops_items._text_of` checked that the newest version is the one the index was
read from and that its hash is the store's record (else nothing is shown: MR_UNAVAILABLE). On a messaging app it is cut on a word at MR_PHONE_CHARS, elsewhere at TEXT_CHARS. NOTHING reads the
message by itself: no model, no router, no interpreter, no composer; its words are another person's, so an instruction in it is shown as text and never followed. (`mail-ask`, package MAIL-SUMMARY, runtime/ops_mail_ask.py, names a message with this module's `_run(..., whole=True)` and hands the whole body to the quarantined reader; `mail-read` itself still shows the text and no model reads it.) The reply is private: it goes to the chat
that asked, and the conversation stores a neutral word (`extras["stored"]`, as `file-read` does); nothing here logs, prints or keeps a word of a message, a sender or a subject.

Who may ask. The policy first (`ops_actor.guard` for the typed call, `operations.refusal` in `ops_natural.run` for a line): a messaging sender needs the group `read-mail-body`, which is in no
default and which project_config refuses without `ask-mail` beside it; then `item_refs.may_read` (the right to read the snapshots) again inside `item_refs.read_index`, which gives a caller
who may not read it the sentence of that module and nothing of the mailbox. The MCP mode has no row.

Fresh by words only. A line on a messaging app that names the message BY WORDS reads each source again once when its snapshot is older than `ops_items.FRESH_S` (`ops_items._refresh_failed`:
the one provider read of a snapshot, under the line's refresh budget `turn_gate.turn`, a failure dropped with one closed word on stderr). A line that names a NUMBER never refreshes: a read renumbers
the snapshot, and the number the person says is the one the list they saw gave (the rule of `ops_natural_mail._may_refresh`). The snapshot is refused as old after 26 hours (`item_refs`).

A box that cannot be read is never skipped in silence. By number, when a box of the searched set could not be read (its files changed, its snapshot is too old, it has no index), the reply names it and
shows nothing: that box might hold the number too, and another box's message must not take its place; an account or a `<source>#<n>` that narrows the search to the boxes that were read is the
way round it. By words a single hit is listed, not shown, with a note that a box could not be read. Several holders of one number are all named with their real count, and a suggestion to say
"read 3 from Gmail" is made only for a message that no other box of that account holds (the account's name is the only box word a line carries); what the words cannot tell apart is done on the
page (a phone) or with `--message <source>#<n>` (the terminal and the page). A day the time engine cannot read, or a message with no recorded time, is told as such (`MR_DAY_UNREAD`) and
never guessed. After a failed refresh by words the reply carries the note of the old snapshot, as `items` does. KNOWN LIMIT: a list is not pinned to a snapshot version, so a refresh between a list
(or the which-box sentence) and "read 3 from Gmail" can make the number name another message; the number is read from the newest snapshot, as every reference is (CB-3, finding 7; not fixed here).

Sibling of runtime/ops.py, which exposes `mail_read` under its name. Standard library only. Runs on Python 3.9: python3 runtime/ops_mail_read.py --help
"""
from __future__ import annotations

import datetime
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import event_lookup  # noqa: E402
import item_refs  # noqa: E402
import items_mail as mailtext  # noqa: E402
import line_stage  # noqa: E402
import natural  # noqa: E402
import natural_writes_mail as nwm  # noqa: E402
import ops_actor  # noqa: E402
import ops_core as core  # noqa: E402
import ops_interpret  # noqa: E402
import ops_items  # noqa: E402
import ops_natural  # noqa: E402
import ops_natural_mail  # noqa: E402
import phrases  # noqa: E402
import snapshot_text  # noqa: E402
import source_names  # noqa: E402
import sources  # noqa: E402
import turn_gate  # noqa: E402

ACCOUNTS = ("google", "microsoft")
MR_PHONE_CHARS = 1500      # characters of the text on a messaging app (a message of it holds 4,096 and RENDER_MAX is 1,800)
TEXT_CHARS = 4000          # characters elsewhere: the whole body a snapshot keeps (snapshot_text.BODY_CHARS)
SEVERAL_MAX = 5            # matches listed to choose from; more asks for more words
NUMBER_MAX = 9999          # the snapshot's numbers are 1 to 4 digits (item_refs.ITEM_REF)


def _now() -> datetime.datetime:
    items = ops_items
    return (items.SNAPSHOT_CLOCK() if items.SNAPSHOT_CLOCK else datetime.datetime.now(datetime.timezone.utc)).astimezone()


def _account_of(said, args: dict):
    """(the account the call names or None, whether it was unreadable): a typed `google`/`microsoft`, else the brand word of the slot `service`, else the account the line names on its own
    (as `items` reads it). As `ops_file_read.line_target` does, the word must name exactly one account AND agree with the account the line itself names (a line that names both agrees with
    neither); a word no table reads, or one that does not agree, is "unreadable": the reply asks again, a stated filter is never dropped."""
    word = args.get("account")
    line = said if isinstance(said, str) else ""
    named = event_lookup.account_named(line) if line else None
    if not word:
        return named, False
    if word in ACCOUNTS:      # a typed account (or the project's own word): it may not contradict the account the line names
        return (None, True) if named and named != word else (word, False)
    words = tuple(event_lookup._words(str(word)))
    owners = [account for account, brands in event_lookup._brands().items() if words in [tuple(b) for b in brands]]
    found = owners[0] if len(owners) == 1 else None
    if found is None or not line or event_lookup.account_named(line, hint=str(word)) != found or (named and named != found):      # the brand word must stand in the line and name its account
        return None, True
    return found, False


def _check(args: dict) -> dict:
    """The arguments of the call, checked: {"ref" (source, n) | None, "number", "match" (the span), "day" (the span)}. core.OpsError (2) for a value that is not of its shape."""
    message, number, match, day = args.get("message"), args.get("number"), args.get("match"), args.get("day")
    ref = None
    if message is not None:
        try:
            parsed = item_refs.parse(message)
        except item_refs.ItemRefError as e:
            raise core.OpsError(str(e), 2) from None
        if parsed["kind"] != "item":
            raise core.OpsError("--message is <source>#<n>, the n-th message of the newest snapshot of a mail source", 2)
        ref = (parsed["source"], parsed["n"])
    if number is not None and (type(number) is not int or not 1 <= number <= NUMBER_MAX):
        raise core.OpsError(f"--number is a message number from 1 to {NUMBER_MAX}", 2)
    for name, value in (("match", match), ("day", day)):
        if value is not None and (not isinstance(value, str) or len(value) > natural.SPAN_MAX):
            raise core.OpsError(f"--{name} is words of at most {natural.SPAN_MAX} characters", 2)
    if ref and number is not None and ref[1] != number:
        raise core.OpsError("--message and --number name different messages: give one of them", 2)
    return {"ref": ref, "number": number if number is not None else (ref[1] if ref else None), "match": (match or "").strip(), "day": (day or "").strip()}


def _line(block: dict, entry: dict, cfg: dict) -> dict:
    """The who, the subject and the when of one message, as a phone list reads them (the same helpers as `ops_items._phone_mail`)."""
    return {"who": mailtext.who(block.get("from", ""), entry.get("from_address") or ""), "subject": snapshot_text.one_line(entry.get("subject") or "", mailtext.SUBJECT_MAX),
            "when": mailtext.when_text(block.get("when"), _now(), cfg)}


def _candidate(source: dict, snapshot: dict, entry: dict, names: dict, cfg: dict, parsed: dict) -> dict:
    block = parsed.get(entry["n"], {})
    return {"source": source["id"], "account": source["account"], "box": (names.get(source["id"]) or {}).get("name") or source["id"], "n": entry["n"], "version": snapshot["version"],
            "entry": entry, **_line(block, entry, cfg)}


def _summary(candidate: dict) -> dict:
    return {key: candidate[key] for key in ("source", "account", "box", "n", "who", "subject", "when", "selectable")}


def _selectable(candidate: dict, boxes: list, counts: dict) -> bool:
    """Whether "read <n> from <the account's brand>" would find exactly this message: no other box of its account may hold that number (a box that could not be read might). A
    suggestion that is not selectable is never made: it would lead back to the same question."""
    account = candidate["account"]
    if account is None:
        return False
    possible = [b for b in boxes if b["account"] == account and (counts.get(b["id"]) is None or counts[b["id"]] >= candidate["n"])]
    return len(possible) == 1


def _blocks(ctx: dict, source_id: str, version) -> dict:
    text = ops_items._text_of(ctx, source_id, version)
    return mailtext.blocks(text) if text is not None else {}


def _body(parsed: dict, n: int, phone: bool, whole: bool = False):
    """(the text, whether it was cut here) of message n, or (None, False) when the snapshot's text has no such message. `whole` (`mail-ask`): the snapshot's own body, which the snapshot already cut at
    snapshot_text.BODY_CHARS and marked with its `(cut)` line, is not cut a second time, so that the mark stays in the text and the reader is told the message is longer."""
    block = parsed.get(n)
    if block is None:
        return None, False
    text = "\n".join(block.get("body") or []).strip()
    if not text or text in mailtext.PLACEHOLDERS:
        return "", False
    limit = MR_PHONE_CHARS if phone else TEXT_CHARS
    if whole or len(text) <= limit:
        return text, False
    cut = text[:limit]
    cut = cut[:cut.rfind(" ")] if " " in cut[limit // 2:] else cut
    return cut.rstrip(), True


def _show(ctx: dict, picked: dict, phone: bool, whole: bool = False) -> dict:
    parsed = _blocks(ctx, picked["source"], picked["version"])
    text, cut = _body(parsed, picked["n"], phone, whole)
    if text is None:      # the newest version is not the one the number came from, or its text does not hash to the store's record: nothing is shown
        return {"status": "unavailable"}
    return {"status": "text", **_summary(picked), "version": picked["version"], "text": text, "cut": cut}


def _read_index(ctx: dict, source_id: str, channel, sender):
    """(the index or None, the refusal code or None) of one mail source; a refusal of the right to read is raised (nothing of the mailbox, not even a source's name, is said)."""
    try:
        return item_refs.read_index(ctx, source_id, channel=channel, sender=sender, kinds=("mail",), clock=ops_items.SNAPSHOT_CLOCK), None
    except item_refs.ItemRefError as e:
        if e.code == "not_readable":
            raise core.OpsError(phrases.en("NW_REF_NOT_READABLE"), 1) from None
        return None, e.code
    except sources.SourcesError as e:
        return None, ops_items.reason_of(e.code) or "integrity"


def _list_line(span: str):
    """(who, subject) as word tuples when `span` is a line of a list this platform printed (`ops_items._phone_mail`: who · subject · when), else None. The form is code's own; the when is left out (it reads differently after midnight)."""
    parts = [part.strip() for part in span.split(" · ")]
    if len(parts) < 2 or not all(parts):
        return None
    if len(parts) >= 3 or any(c.isdigit() for c in parts[-1]):
        parts = parts[:2] if len(parts) >= 3 else parts[:1] + [""]
    return tuple(nwm._words_of(parts[0])), tuple(nwm._words_of(parts[1]))


def _read_matches(entries: list, words: list, parsed: dict) -> list:
    """`match_words`, and for a read also the words of the sender's display name as the snapshot printed it: a read changes nothing and never picks among several, so a name the person saw finds it."""
    wanted, hits = set(words), nwm.match_words(entries, words)
    by_name = [e for e in entries if e not in hits and wanted and wanted <= (nwm.entry_words(e) | set(nwm._words_of((parsed.get(e["n"]) or {}).get("from", ""))))]
    return sorted(hits + by_name, key=lambda e: e["n"])


def _find(ctx: dict, project: str, spec: dict, account, day_read, channel, sender, whole: bool = False) -> dict:
    """The outcome of the search, by number or by words (see the module's text). Runs inside the line's refresh budget. A box that cannot be read is never skipped in silence: by number
    the reply does not choose among the boxes that could be read ("box-failed"), by words a single hit is listed and not shown, and a note names the box. `whole` (`mail-ask`, MAIL-SUMMARY):
    the text is the whole body the snapshot keeps, not the phone's cut, because it goes to the reader and not to the chat."""
    cfg = ctx["cfg"]
    phone = channel == ops_actor.MESSAGING
    boxes = [s for s in ops_natural_mail._mail_sources(ctx) if (account is None or s["account"] == account) and (spec["ref"] is None or s["id"] == spec["ref"][0])]
    if not boxes:
        return {"status": "missing", "account": account}
    by_number = spec["number"] is not None
    words, listed, newest = [], None, False
    if not by_number:
        listed = _list_line(spec["match"]) if spec["match"] else None
        words = nwm.target_words(spec["match"], natural._tables(None)) if spec["match"] and not listed else []
        newest = bool(spec["match"]) and not listed and not words and not spec["day"] and nwm.says_newest(spec["match"], natural._tables(None))
        if not words and not spec["day"] and not listed and not newest:
            return {"status": "ask"}      # nothing to look for: never every message
    line_stage.publish("mail")
    names = source_names.catalog(ctx)
    name_of = lambda source_id: (names.get(source_id) or {}).get("name") or source_id  # noqa: E731
    found, failed, old, counts = [], [], [], {}
    told = {}      # a reason only the computer solves -> the plain names of the boxes it holds for (ops_items.reason_lines)
    for source in boxes:
        refresh_failed = not by_number and phone and ops_items._refresh_failed(project, ctx, source["id"])      # the old snapshot is read as it is; the failure was said on stderr with a closed word
        snapshot, why = _read_index(ctx, source["id"], channel, sender)
        reason = turn_gate.failed_reason(source["id"]) or (why if why in ops_items.REASON_KEYS else None)
        if reason and phone:      # the sentence is for a phone (L62: "trying again here will not help"); the terminal, the conversation and the page keep their own words
            told.setdefault(reason, []).append(name_of(source["id"]))
        if snapshot is None:
            failed.append(name_of(source["id"]))
            counts[source["id"]] = None
            continue
        counts[source["id"]] = len(snapshot["entries"])
        if refresh_failed:
            old.append(snapshot["read_at"])
        entries = snapshot["entries"]
        if by_number:
            entries = [e for e in entries if e["n"] == spec["number"]]
            if not entries:
                found.append({"past_end": len(snapshot["entries"]), "source": source})
                continue
        elif newest:
            entries = [e for e in entries if e["n"] == 1]      # the snapshot's numbers are newest first: each box's newest, listed when two boxes have one
        else:
            parsed = _blocks(ctx, source["id"], snapshot["version"])
            if listed:
                seen = [(e, _line(parsed.get(e["n"], {}), e, cfg)) for e in entries]
                entries = [e for e, row in seen if tuple(nwm._words_of(row["who"])) == listed[0] and (not listed[1] or tuple(nwm._words_of(row["subject"])) == listed[1])]
            if words:
                entries = _read_matches(entries, words, parsed)
            if spec["day"] and entries:
                entries = ops_natural_mail._on_day(entries, day_read)
        if not entries:
            continue
        parsed = _blocks(ctx, source["id"], snapshot["version"])
        found += [_candidate(source, snapshot, e, names, cfg, parsed) for e in entries]
    hits = [c for c in found if "entry" in c]
    for c in hits:
        c["selectable"] = _selectable(c, boxes, counts)
    notes = {**({"failed_boxes": failed} if failed else {}), **({"old_at": min(old)} if old else {}), **({"told": told} if told else {})}
    if by_number:
        if not hits:
            past = [c for c in found if "past_end" in c]
            if past:
                return {"status": "past-end", "number": spec["number"], "count": past[0]["past_end"], "box": name_of(past[0]["source"]["id"])}
            return {"status": "unavailable", **({"told": told} if told else {})}
        if failed:      # a box that could not be read might hold the number too: the message of another box is not shown in its place
            return {"status": "box-failed", "number": spec["number"], "failed_boxes": failed, **({"told": told} if told else {})}
        if len(hits) > 1:
            return {"status": "which-box", "number": spec["number"], "options": [_summary(c) for c in hits], **notes}
        return {**_show(ctx, hits[0], phone, whole), **notes}
    if not hits:
        return {"status": "none", **notes} if len(failed) < len(boxes) else {"status": "unavailable", **({"told": told} if told else {})}
    hits.sort(key=lambda c: (c["entry"].get("received") or ""), reverse=True)
    if len(hits) == 1 and not failed:
        return {**_show(ctx, hits[0], phone, whole), **notes}
    if len(hits) <= SEVERAL_MAX:
        return {"status": "several", "count": len(hits), "matches": [_summary(c) for c in hits], **notes}
    return {"status": "too-many", "count": len(hits), **notes}


def _run(project: str, ctx: dict, args: dict, said, channel, sender, whole: bool = False) -> dict:
    spec = _check(args)
    account, unreadable = _account_of(said, args)
    if unreadable:
        return {"status": "again"}
    if not item_refs.may_read(ctx, channel, sender):
        raise core.OpsError(phrases.en("NW_REF_NOT_READABLE"), 1)
    day_read = None
    if spec["day"] and spec["number"] is None:
        day_read = ops_interpret._day_read(spec["day"], ops_natural._clock())
    with turn_gate.turn():      # S41-6: the line's refresh budget (limits L52 and L53); an entry of its own when the operation is called directly
        try:
            return _find(ctx, project, spec, account, day_read, channel, sender, **({"whole": True} if whole else {}))      # two vacuity tests stub `_find` with 7 arguments
        except ops_natural_mail.Say as e:      # a day that cannot be read, or a candidate with no received time: told so, never guessed
            return {"status": "day-unread"} if e.key == "NW_MAIL_BY_DATE" else {"status": "say", "key": e.key, "fields": e.fields}


def mail_read(project: str, message: str | None = None, number: int | None = None, match: str | None = None, day: str | None = None, account: str | None = None,
              channel: str | None = None, sender: str | None = None) -> dict:
    """The operation `mail-read`: {"status": "text", "source", "account", "box", "n", "who", "subject", "when", "text", "cut"} for one message, or {"status": "which-box" | "several" | "too-many" |
    "none" | "past-end" | "box-failed" | "day-unread" | "ask" | "missing" | "unavailable" | "again" | "say", ...} (what is listed carries no text). From a messaging app the sender's profile must hold `read-mail-body` and
    `ask-mail` (OpsError 1 otherwise); the page and the terminal follow the table of operations. A refusal is never a message's text."""
    ctx = core.context(project)
    ops_actor.guard(ctx, "mail-read", channel, sender)
    if account is not None and account not in ACCOUNTS:
        raise core.OpsError("--account is google or microsoft", 2)
    return _run(project, ctx, {"message": message, "number": number, "match": match, "day": day, "account": account}, None, channel, sender)


# --- the sentences ------------------------------------------------------------------------------------------------------------------------------


def _row(cfg: dict, candidate: dict, key: str = "MR_ROW") -> str:
    t = lambda k, **fields: phrases.text(k, cfg, **fields)  # noqa: E731
    line = " · ".join(part for part in (candidate["who"], candidate["subject"], candidate["when"]) if part)
    return t(key, n=candidate["n"], box=candidate["box"], line=line)


def _tail(outcome: dict, rows: list, number, cfg: dict, channel, words: dict = None) -> str:
    """The line that says how to choose, or "" : on a messaging app a form that really selects the box ("read 3 from Gmail": the account's brand, only for a message no other box of its account
    holds) and, for what the words cannot tell apart, the page; on the terminal and the page, the source references the typed command takes. Never a suggestion that leads back to the same question."""
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    if channel != ops_actor.MESSAGING:
        return t("MR_WHICH_TYPED", refs=" or ".join(f"{r['source']}#{r['n']}" for r in rows))
    chosen, seen = [], set()
    for row in rows:
        if row["selectable"] and row["account"] not in seen:
            seen.add(row["account"])
            chosen.append(row)
    brand = lambda row: source_names.LABEL["mail"][row["account"]]  # noqa: E731
    hidden = len(chosen) < len({r["account"] for r in rows}) or any(not r["selectable"] for r in rows)
    parts = []
    if len(chosen) == 2 and not hidden:
        parts.append(t((words or {}).get("MR_WHICH_SAY_TWO", "MR_WHICH_SAY_TWO"), n=chosen[0]["n"], first_box=brand(chosen[0]), second_box=brand(chosen[1])))
    else:
        parts += [t((words or {}).get("MR_WHICH_SAY_ONE", "MR_WHICH_SAY_ONE"), n=r["n"], box=brand(r)) for r in chosen]
        if hidden:
            parts.append(phrases.phone("MR_WHICH_PAGE", cfg))
    return " ".join(parts)


def _notes(outcome: dict, cfg: dict) -> str:
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    out = ""
    if outcome.get("failed_boxes"):
        out += "\n" + t("MR_BOX_NOTE", boxes=", ".join(outcome["failed_boxes"]))
    if outcome.get("old_at"):
        moment = ops_items._local(outcome["old_at"])
        if moment is not None:
            out += "\n" + t("NW_ITEMS_OLD", time=moment.strftime("%H:%M"))
    for line in ops_items.reason_lines(outcome.get("told") or {}, cfg):      # a box only the computer can fix is told by its reason, after the note
        out += "\n" + line
    return out


def render(outcome: dict, cfg: dict, project: str = "", ctx: dict = None, channel=None, words: dict = None) -> str:
    """The sentence of an outcome of `_run`, in the project's language. A text is its header and its words; every other outcome is a sentence of the table that holds no word of a message.
    `words` (`mail-ask`) maps the three phrase keys that tell the person what to say next (MR_PICK, MR_WHICH_SAY_TWO, MR_WHICH_SAY_ONE) to the keys of that operation's own: its tails say "resuma", never "lê"."""
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    status = outcome["status"]
    if status == "text":
        head = _row(cfg, outcome, "MR_HEAD")
        body = outcome["text"] or t("MR_NO_TEXT")
        return f"{head}\n\n{body}" + ("\n" + t("MR_BODY_CUT") if outcome["cut"] else "") + _notes(outcome, cfg)
    if status == "which-box":
        options = outcome["options"]
        line = lambda c: " · ".join(part for part in (c["box"], c["who"], c["subject"], c["when"]) if part)  # noqa: E731
        said = t("MR_WHICH_BOX", count=len(options), n=outcome["number"], list="; ".join(line(c) for c in options))
        return " ".join(part for part in (said, _tail(outcome, options, outcome["number"], cfg, channel, words)) if part) + _notes(outcome, cfg)
    if status == "several":
        rows = outcome["matches"]
        head = t("MR_SEVERAL" if outcome["count"] > 1 else "MR_FOUND_ONE", count=outcome["count"], rows="\n".join(_row(cfg, m) for m in rows))
        if channel == ops_actor.MESSAGING:
            pick = next((r for r in rows if r["selectable"]), None)
            tail = t((words or {}).get("MR_PICK", "MR_PICK"), n=pick["n"], box=source_names.LABEL["mail"][pick["account"]]) if pick else phrases.phone("MR_WHICH_PAGE", cfg)
        else:
            tail = t("MR_WHICH_TYPED", refs=" or ".join(f"{r['source']}#{r['n']}" for r in rows))
        return head + ("\n" + tail if tail else "") + _notes(outcome, cfg)
    if status == "too-many":
        return t("MR_TOO_MANY", count=outcome["count"]) + _notes(outcome, cfg)
    if status == "none":
        return t("MR_NONE") + _notes(outcome, cfg)
    if status == "past-end":
        return t("MR_PAST_END", box=outcome["box"], count=outcome["count"], n=outcome["number"])
    if status == "box-failed":
        return "\n".join([t("MR_BOX_FAILED", boxes=", ".join(outcome["failed_boxes"]), n=outcome["number"]), *ops_items.reason_lines(outcome.get("told") or {}, cfg)])
    if status == "day-unread":
        return t("MR_DAY_UNREAD")
    if status == "ask":
        return t("MR_ASK")
    if status == "again":
        return t("IX_ASK_AGAIN")
    if status == "say":
        return t(outcome["key"], **outcome["fields"])
    if status == "missing":
        return ops_items.reply(project, ctx, {"missing": {"kind": "mail", "account": outcome["account"]}}, channel)
    return "\n".join(ops_items.reason_lines(outcome.get("told") or {}, cfg)) or t("MR_UNAVAILABLE")


def reply(project: str, ctx: dict, args: dict, said: str, channel, sender, extras: dict) -> str:
    """The reply of `mail-read` chosen by the interpreter (runtime/ops_natural.py `run` has already asked the policy and, on a messaging app, the person's OK of the plan). The arguments are
    spans of the line the interpreter checked. The conversation keeps a neutral word whatever the reply is; the text goes to the chat that asked and nowhere else."""
    cfg = ctx["cfg"]
    extras["stored"] = phrases.text("NAT_READ_REPLY", cfg)
    try:
        outcome = _run(project, ctx, {k: args.get(k) for k in ("message", "number", "match", "day", "account")}, said, channel, sender)
    except core.OpsError as e:
        return ops_natural._error(cfg, e, channel)
    return render(outcome, cfg, project, ctx, channel)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
