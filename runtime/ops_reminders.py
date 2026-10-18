#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The operations over reminders (package RM-1): make one, list them, forget one, and what the messaging bridge asks of the store to send them. The
words a person types, the caps and the sentences are runtime/reminders.py; the table is migration 20 of the store; the bridge's part is
runtime/messaging_remind.py.

A reminder is a stored one-shot notice: the person's own words, sent at a moment to the chat that made it, by the messaging bridge, with no model in
between. It is a notice and never an effect (limit L51, contracts/runtime.md): it reaches only a sender the project lists, only in that sender's own
private chat, with text that sender (or the person at the terminal) wrote, and nothing is done in the world.

  remind(project, when, text[, to])     make a reminder. From a messaging app: for the sender who asks, in their own chat (`to` is refused). From the
                                        terminal or the page: for the listed sender `to` names (`<platform>:<id>`), who must hold the group `reminders`
  reminders_read(project)               the waiting reminders and the ones that did not go out in the last 7 days. From a messaging app, only the ones
                                        for the sender who asks, and no text when the project's notices are `count`
  reminder_forget(project, id)          cancel a waiting reminder (from a messaging app, one of yours)

Who may call what is the table of operations (runtime/operations.py: the group `reminders`, in no default policy, never on the MCP mode) and, for a
messaging sender, `ops_actor.guard` (the profile of THAT sender, read from the configuration loaded for this call).

What the bridge asks, not operations of the table (no sender can type them; the bridge calls them from its tick):

  reminders_due(project, platform)      the reminders of the platform that are due now and may go out, each one CLAIMED (`sending`) in the same call;
                                        the ones later than the late window end `missed`; the ones whose sender is no longer listed, or whose profile no
                                        longer holds the group, end `dropped`: the configuration and the profile are read now, not when it was made
  reminders_sent(project, id)           the line went out: `sent`
  reminders_retry(project, id)          it did not (a failed or deferred send): `open` again, tried after a pause of 1, 2, 4, 8 ... minutes until the window ends

The text of a reminder is the person's own words. It is never written to a log, never put in a notice, an error or a catalog, and never in the store's
export; it leaves the store through `reminders_read` and `reminders_due` alone, and only toward the chat of the sender it was made for (or the terminal
and the page, which are the person's own). A text that looks like a credential is refused when the reminder is made.

Sibling of runtime/ops.py, which exposes the operations under their names. The shared names come from ops_core, read as `core.<name>` at call time.
It reaches no operation of ops.py. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import operations  # noqa: E402
import ops_actor  # noqa: E402
import ops_core as core  # noqa: E402
import reminders as rm  # noqa: E402
import workcopy  # noqa: E402

MESSAGING = "messaging"
UTC = datetime.timezone.utc


def now() -> datetime.datetime:
    """The clock a reminder's time is read from: the machine's local time, with its zone. A test replaces this function."""
    return datetime.datetime.now().astimezone()


def local_of(instant: datetime.datetime) -> datetime.datetime:
    """An instant read in the machine's local time of THAT day (its rules then, a clock change included). A test replaces it with the rules of the
    zone it stands for."""
    return instant.astimezone()


def day_start(clock: datetime.datetime) -> datetime.datetime:
    """The real start of the local day of `clock`, by the rules of that day (not the offset `clock` carries: on the day a clock changes the two differ)."""
    return local_at(datetime.datetime.combine(clock.date(), datetime.time(0, 0)))


def local_at(naive: datetime.datetime) -> datetime.datetime:
    """The aware datetime of a local wall time, by the rules of the machine's zone on that day (a clock change included). A test replaces it with the
    rules of the zone it stands for."""
    return naive.astimezone()


def _fail(sentence: str, code: int = 1) -> "core.OpsError":
    return core.OpsError(sentence, code)


def _iso(moment: datetime.datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _moment(text: str) -> datetime.datetime:
    return datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def _listed(cfg: dict, platform: str) -> list:
    return list(((cfg.get("messaging") or {}).get("senders") or {}).get(platform) or [])


def _notices_text(cfg: dict) -> bool:
    return ((cfg.get("messaging") or {}).get("notices") or "text") == "text"


def _key(platform: str, chat: str) -> str:
    return operations.sender_key(platform, chat)


def _shown(row: dict, cfg: dict, with_text: bool) -> dict:
    """A reminder as a shell reads it: when, for whom (the profile and the platform, never the id), and the text only if `with_text`."""
    out = {"id": row["id"], "due": row["due_local"].replace("T", " "), "zone": row["zone"], "status": row["status"], "platform": row["platform"],
           "for": f"{ops_actor.profile_of(cfg, _key(row['platform'], row['chat']))} on {row['platform']}",
           "created_by": ops_actor.public(row["created_by"])}
    if row.get("why"):
        out["why"] = row["why"]
    if with_text:
        out["text"] = row["text"]
    return out


def _own(row: dict, channel, sender) -> None:
    """On a messaging app a sender sees and forgets only the reminders made for THEM (their platform and chat); another's is answered as one that
    does not exist, so that the answer tells nothing of it."""
    if channel != MESSAGING:
        return
    platform, ident = ops_actor.split(sender)
    if (row["platform"], row["chat"]) != (platform, ident):
        raise _fail(rm.NO_SUCH.format(n=row["id"]))


def remind(project: str, when: str, text: str, to: str | None = None, channel: str | None = None, sender: str | None = None) -> dict:
    """Make a reminder. `when` is HH:MM, YYYY-MM-DD HH:MM or in <n>m|h|d (runtime/reminders.py resolve), `text` the words to send. Returns {"reminder":
    the reminder as a shell reads it (with its text), "reply": the sentence a messaging app answers with}. A refusal is an OpsError whose message is
    the sentence the person reads (code 2 for a usage error)."""
    ctx = core.context(project)
    cfg = ctx["cfg"]
    ops_actor.guard(ctx, "remind", channel, sender)
    if channel == MESSAGING:
        if to is not None:
            raise _fail("A reminder made from a messaging app goes to your own chat.", 2)
        recipient = sender
        platform, ident = ops_actor.split(sender)
        if ident not in _listed(cfg, platform):
            raise _fail(rm.NOT_LISTED)
    else:
        platform, ident = ops_actor.split(to)
        if not platform:
            raise _fail(rm.TERMINAL_USAGE, 2)
        recipient = to
        if ident not in _listed(cfg, platform):
            raise _fail(f"{to} is not a listed sender of this project: messaging.senders.{platform} in runtime.json lists the senders", 2)
        if not operations.permitted("remind", MESSAGING, cfg["channels"], None, recipient):
            raise _fail(f"{to} does not hold the group reminders: add it to the sender's profile in runtime.json and accept the file with "
                        "--widen (the group is in no default policy)", 1)
    try:
        words = rm.clean_text(text)
        clock = now()
        found = rm.resolve(when, clock, local_at, local_of)
    except ValueError as e:
        raise _fail(str(e), 2) from None
    labels = workcopy.credential_findings(words)
    if labels:
        raise _fail(rm.CREDENTIAL.format(labels=", ".join(sorted(set(labels)))), 2)
    store = ctx["store"]
    start = _iso(day_start(clock))
    try:
        row = store.reminder_add(ctx["conn"], text=words, due_local=found["wall"], due_utc=_iso(found["due"]), zone=found["zone"], platform=platform,
                                 chat=ident, created_by=ops_actor.label(cfg, channel, sender) or "terminal", max_open=rm.OPEN_MAX, max_day=rm.DAY_MAX, max_open_chat=rm.OPEN_CHAT_MAX,
                                 day_since=start, created_at=_iso(clock))
    except store.StoreError as e:
        if str(e) == store.REMINDER_OPEN_FULL:
            raise _fail(rm.OPEN_FULL.format(n=rm.OPEN_MAX)) from None
        if str(e) == store.REMINDER_CHAT_FULL:
            raise _fail(rm.CHAT_FULL.format(n=rm.OPEN_CHAT_MAX)) from None
        if str(e) == store.REMINDER_DAY_FULL:
            raise _fail(rm.DAY_FULL.format(n=rm.DAY_MAX)) from None
        raise _fail(str(e), e.code) from None
    return {"reminder": _shown(row, cfg, True), "reply": rm.SET.format(id=row["id"], wall=found["wall"].replace("T", " "), zone=found["zone"])}


def reminders_read(project: str, channel: str | None = None, sender: str | None = None) -> dict:
    """The waiting reminders (soonest first) and the ones that went unsent in the last RECENT_DAYS days (`missed`, `dropped`; newest first), the clock
    now and the limits. From a messaging app only the reminders made for the sender who asks, and no text when the project's notices are `count`; the
    terminal and the page, which are the person's own, see them all with their text."""
    ctx = core.context(project)
    cfg = ctx["cfg"]
    ops_actor.guard(ctx, "reminders", channel, sender)
    store, clock = ctx["store"], now()
    platform = chat = None
    if channel == MESSAGING:
        platform, chat = ops_actor.split(sender)
    since = _iso(clock.astimezone(UTC) - datetime.timedelta(days=rm.RECENT_DAYS))
    waiting = core._stored(ctx, store.reminders_list, ("open", "sending"), platform, chat)
    gone = core._stored(ctx, store.reminders_list, ("missed", "dropped"), platform, chat, since, rm.RECENT_MAX)
    with_text = channel != MESSAGING or _notices_text(cfg)
    return {"now": clock.strftime("%Y-%m-%d %H:%M"), "zone": rm.zone_name(clock),
            "open": [_shown(r, cfg, with_text) for r in waiting], "not_sent": [_shown(r, cfg, with_text) for r in gone],
            "limits": {"open": rm.OPEN_MAX, "per_chat_per_day": rm.DAY_MAX, "text_characters": rm.TEXT_MAX, "late_window_hours": rm.LATE_WINDOW // 3600}}


def reminder_forget(project: str, reminder_id: int, channel: str | None = None, sender: str | None = None) -> dict:
    """Cancel a waiting reminder. From a messaging app only one made for the sender who asks (any other is answered as one that does not exist)."""
    if type(reminder_id) is not int or reminder_id < 1:
        raise _fail("a reminder is a whole number", 2)
    ctx = core.context(project)
    cfg = ctx["cfg"]
    ops_actor.guard(ctx, "reminder-forget", channel, sender)
    store = ctx["store"]
    try:
        row = store.reminder_get(ctx["conn"], reminder_id)
    except store.StoreError:
        raise _fail(rm.NO_SUCH.format(n=reminder_id)) from None
    _own(row, channel, sender)
    if row["status"] == "sending":
        raise _fail(rm.BEING_SENT.format(n=reminder_id))
    if row["status"] != "open":
        raise _fail(rm.NOT_WAITING.format(n=reminder_id, status=row["status"]))
    try:
        done = store.reminder_end(ctx["conn"], reminder_id, "cancelled", at=_iso(now()))
    except store.StoreError:      # it was claimed between the read and the end: the bridge is sending it
        raise _fail(rm.BEING_SENT.format(n=reminder_id)) from None
    return {"reminder": _shown(done, cfg, False), "reply": rm.FORGOT.format(id=reminder_id)}


# --- what the bridge asks of the store ----------------------------------------------------------------------------------------------


def reminders_due(project: str, platform: str, moment: datetime.datetime | None = None) -> dict:
    """The reminders of `platform` that go out now: {"send": [{"id", "chat", "late" (seconds), "due_local", "text" (only when the project's notices carry
    text)}], "missed": n, "dropped": n}, each of `send` claimed (`sending`) by this call, at most PER_TICK of them. One that is later than the late window
    ends `missed`. One whose sender is no longer listed for the platform, or whose profile no longer holds the group, ends `dropped`: nothing is sent to
    them. Both are read from the accepted configuration of this call. `moment` is for a test; the clock is `now()`."""
    ctx = core.context(project)
    cfg, store = ctx["cfg"], ctx["store"]
    clock = moment or now()
    core._stored(ctx, store.reminders_reclaim, _iso(clock.astimezone(UTC) - datetime.timedelta(seconds=rm.CLAIM_STALE)))
    with_text = _notices_text(cfg)
    listed = _listed(cfg, platform)
    out = {"send": [], "missed": 0, "dropped": 0}
    for row in core._stored(ctx, store.reminders_due, platform, _iso(clock)):
        word, late = rm.verdict(_moment(row["due_utc"]), clock)
        if word == "missed":
            core._stored(ctx, store.reminder_end, row["id"], "missed", why="late", at=_iso(clock))
            out["missed"] += 1
            continue
        why = None
        if row["chat"] not in listed:
            why = "sender removed"
        elif not operations.permitted("remind", MESSAGING, cfg["channels"], None, _key(platform, row["chat"])):
            why = "not permitted"
        if why:
            core._stored(ctx, store.reminder_end, row["id"], "dropped", why=why, at=_iso(clock))
            out["dropped"] += 1
            continue
        if len(out["send"]) >= rm.PER_TICK:
            break
        if not core._stored(ctx, store.reminder_claim, row["id"], _iso(clock)):
            continue
        item = {"id": row["id"], "chat": row["chat"], "late": late, "due_local": row["due_local"]}
        if with_text:
            item["text"] = row["text"]
        out["send"].append(item)
    return out


def reminders_sent(project: str, reminder_id: int) -> dict:
    """The line of a claimed reminder went out: it ends `sent`."""
    ctx = core.context(project)
    return {"id": core._stored(ctx, ctx["store"].reminder_end, reminder_id, "sent", at=_iso(now()))["id"]}


def reminders_retry(project: str, reminder_id: int) -> dict:
    """The line of a claimed reminder did not go out (a failed or deferred send): it is open again and is not offered before a pause that doubles with
    each failure (1, 2, 4, 8 ... minutes, `reminders.retry_delay`), until the late window ends it `missed`. Returns {"id", "open", "retry_after"}."""
    ctx = core.context(project)
    store = ctx["store"]
    failed = core._stored(ctx, store.reminder_get, reminder_id)["attempts"] + 1
    after = _iso(now().astimezone(UTC) + datetime.timedelta(seconds=rm.retry_delay(failed)))
    return {"id": reminder_id, "open": core._stored(ctx, store.reminder_release, reminder_id, after), "retry_after": after}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
