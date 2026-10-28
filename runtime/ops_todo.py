#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The operations over the person's own to-do list (package CB-5, SPEC-CATALOG-BATCH 6.5): list the open tasks, add a task, mark one as completed. Google Tasks and Microsoft To Do, and only the
lists the project names under `accounts.<a>.task_lists`.

  todo_list(project, [account], [channel, sender])              a live read of each listed list: {"status", "services": [...], "count"}; a read, nothing is written
  todo_add(project, account, title, [list], [channel, sender])  prepare a new task and stop at its card: {"status": "card", "request", "task", "pending", "word", "on_cards"}
  todo_done(project, account, item, [list], [channel, sender])  prepare marking an open task as completed and stop at its card, or the outcome of the search for it; `item` is
                                                                `todo:<n>` (the n-th task of the list shown to this sender last) or the words of the task's title
  reply_list(project, ctx, args, channel, sender, extras)       the reply a line in words gets for `todo-list` (runtime/ops_natural.py `run`)
  reply(project, ctx, op, args, said, channel, sender, extras)  the reply a line in words gets for `todo-add` and `todo-done` (runtime/ops_interpret.py `_carry_out`)
  begin_turn(ctx, channel, sender)                              called at the start of every line (runtime/ops_say.py): a list is valid for the line right after it

Nothing is written here. A card is the effect kind `tasks` (runtime/tasks_document.py, step_tasks_item.py, effect_tasks.py), approved by its hash like every write to the person's own
accounts, and the task is added or completed once, by the writer, only if the list is still one the project names and (for a completion) the task is still as the card shows. There is no
verb to remove a task, to move it or to open it again (limit L57). A task is a title: a due date in the line ("by Friday") is not read, and the card shows exactly the title the line gave,
so the person sees it before approving (OPEN-CB-11).

Who may ask: the group `tasks-read` lists, the group `tasks-write` adds and completes, and a completion by words or by a number reads titles, so a sender needs `tasks-read` beside
`tasks-write` for it (asked again here; the terminal is never narrowed). The approval of a card is the grant `approve-effect-tasks`. What is kept (limits L50, L51 and L61): the conversation
stores a neutral word for every reply that holds a title; the list a number answers is held in process memory only, for the sender's next line and for ten minutes, and nothing here logs,
prints or stores a title. A task's title is another person's text in principle (a shared list): it is data, never an instruction, and it reaches no model on this path.

Sibling of runtime/ops.py, which exposes the three operations under their names. Standard library only. Runs on Python 3.9: python3 runtime/ops_todo.py --help
"""
from __future__ import annotations

import importlib
import os
import re
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import account_start  # noqa: E402
import natural  # noqa: E402
import operations  # noqa: E402
import ops_actor  # noqa: E402
import ops_core as core  # noqa: E402
import phrases  # noqa: E402
import project_config  # noqa: E402
import tasks_document  # noqa: E402
import tasks_reader  # noqa: E402
import turn_gate  # noqa: E402

KIND = "tasks-item"
OP_LIST, OP_ADD, OP_DONE = "todo-list", "todo-add", "todo-done"
SERVICES = ("google", "microsoft")
LIST_WINDOW_S = 600      # seconds a list answers a number: the lifetime of the other lists a sender may point to (ops_file_read.LIST_WINDOW_S)
MATCH_MAX = 5      # tasks listed to choose from when the words fit several
SHOWN_MAX = 100      # tasks shown of one list
NUMBER_MAX = 9999
ITEM = re.compile(r"todo:([1-9][0-9]{0,3})")
# What a line may say for the service: the service word slot is one whole word of the line, so only these closed words are read, folded; any other word asks again.
SERVICE_WORDS = {"google": "google", "microsoft": "microsoft", "todo": "microsoft"}

_LISTS = {}      # (project key, channel, sender) -> {"at", "items": {account: [entry]}, "seen", "pending"}: in process memory only, for the next line; never written, logged or sent anywhere
_lock = threading.Lock()


def _natural():
    return importlib.import_module("ops_natural")


def _writes():
    return importlib.import_module("ops_natural_writes")


def _clock():
    return _natural()._clock()


def forget_lists() -> None:
    """Drop every record (a test, and a process that stops)."""
    with _lock:
        _LISTS.clear()


def _channel(channel) -> str:
    """The channel a call is recorded under: the conversation's shell is the terminal's equal, and a call that names none is the terminal."""
    return "terminal" if channel in (None, "chat", "terminal") else channel


def _slot(ctx: dict, channel, sender) -> tuple:
    return (_natural().project_key(ctx["cfg"]["project"]), _channel(channel), sender or "")


def _last_pending(ctx: dict) -> int:
    return importlib.import_module("event_lookup")._last_pending(ctx)


def _remember(ctx: dict, channel, sender, items: dict) -> None:
    now = _clock()
    with _lock:
        for old in [k for k, v in _LISTS.items() if (now - v["at"]).total_seconds() > LIST_WINDOW_S]:
            del _LISTS[old]
        _LISTS[_slot(ctx, channel, sender)] = {"at": now, "items": {a: list(rows) for a, rows in items.items()}, "seen": 0, "pending": _last_pending(ctx)}


def begin_turn(ctx: dict, channel, sender) -> None:
    """Called by `ops_say.say` at the start of every line of a messaging sender: the list is valid only for the line right after it (as the list of files is, ops_file_read.begin_turn)."""
    if channel == "messaging":
        with _lock:
            found = _LISTS.get(_slot(ctx, channel, sender))
            if found is not None:
                found["seen"] += 1


def _live(ctx: dict, channel, sender):
    """The list this sender was shown, while it answers a number: younger than LIST_WINDOW_S and, on a messaging app, no more than one line old and no card opened after it."""
    now = _clock()
    with _lock:
        found = _LISTS.get(_slot(ctx, channel, sender))
    if found is None:
        return None
    if (now - found["at"]).total_seconds() > LIST_WINDOW_S or (_channel(channel) == "messaging" and (found["seen"] > 1 or _last_pending(ctx) > found["pending"])):
        with _lock:
            _LISTS.pop(_slot(ctx, channel, sender), None)
        return None
    return found


# --- what the configuration lists and what a service holds -------------------------------------------------------------------------------------


def _lists_of(cfg: dict, account: str) -> dict:
    """{name: id} of the task lists the accepted configuration names for the account."""
    return dict((project_config.account_entry(cfg, account) or {}).get("task_lists") or {})


def _accounts_with_lists(cfg: dict) -> list:
    return [a for a in SERVICES if _lists_of(cfg, a)]


def _root() -> str:
    return os.path.dirname(HERE)


def _read_account(cfg: dict, account: str, only=None) -> dict:
    """The open tasks of the account's lists: {"account", "failed": bool, "lists": [{"list": name, "truncated", "tasks": [{"id", "title"}]}]}. A list that cannot be read makes the account `failed`
    (the others are still shown); nothing of an error but its closed code is kept. `only` narrows to one list name."""
    out = {"account": account, "failed": False, "lists": []}
    for name, ident in _lists_of(cfg, account).items():
        if only is not None and name != only:
            continue
        try:
            rid = tasks_reader.default_list(_root(), account) if ident == "default" else ident
            got = tasks_reader.open_tasks(_root(), account, rid, SHOWN_MAX)
        except tasks_reader.ReaderError:
            out["failed"] = True
            continue
        out["lists"].append({"list": name, "truncated": got["truncated"], "tasks": [{"id": t["id"], "title": t["title"]} for t in got["tasks"]]})
    return out


def _entries(read: dict) -> list:
    """The numbered rows of one account's read: [{"list", "id", "title"}], in the order of the lists the file names and of the service within each."""
    return [{"list": item["list"], "id": task["id"], "title": task["title"]} for item in read["lists"] for task in item["tasks"]]


def _may_read(ctx: dict, channel, sender) -> None:
    """The right to see titles, asked beside the right to complete a task by its words or its number: `tasks-read` for a messaging sender and for the page; the terminal is never narrowed.
    core.OpsError with the sentence of the read's refusal otherwise."""
    where = _channel(channel)
    if where == "terminal":
        return
    refused = operations.refusal(OP_LIST, where, ctx["cfg"]["channels"], sender=sender)
    if refused:
        raise core.OpsError(refused, 1)


# --- the operations -------------------------------------------------------------------------------------------------------------------------


def todo_list(project: str, account: str | None = None, channel: str | None = None, sender: str | None = None) -> dict:
    """The operation `todo-list`. From a messaging app the sender's profile must hold the group `tasks-read`. Returns {"status": "ok" | "no-lists" | "unavailable", "services": [{"account",
    "failed", "lists": [{"list", "truncated", "tasks": [{"n", "title"}]}]}], "count"}: the tasks are numbered per service, across its lists, and the list is remembered for this sender
    (the number `todo:<n>` of `todo_done` answers it). The ids of the service are never in the result."""
    ctx = core.context(project)
    ops_actor.guard(ctx, OP_LIST, channel, sender)
    if account is not None and account not in SERVICES:
        raise core.OpsError("--account is google or microsoft", 2)
    accounts = [account] if account else _accounts_with_lists(ctx["cfg"])
    accounts = [a for a in accounts if _lists_of(ctx["cfg"], a)]
    if not accounts:
        return {"status": "no-lists", "services": [], "count": 0}
    kept, services, count = {}, [], 0
    for name in accounts:
        read = _read_account(ctx["cfg"], name)
        kept[name] = _entries(read)
        shown, n = [], 0
        for item in read["lists"]:
            rows = []
            for task in item["tasks"]:
                n += 1
                rows.append({"n": n, "title": task["title"]})
            shown.append({"list": item["list"], "truncated": item["truncated"], "tasks": rows})
        count += n
        services.append({"account": name, "failed": read["failed"], "lists": shown})
    _remember(ctx, channel, sender, kept)
    return {"status": "unavailable" if all(s["failed"] and not s["lists"] for s in services) else "ok", "services": services, "count": count}


def _start(project: str, operation: str, account, args: dict, channel, sender) -> dict:
    """The one start of the family: the arguments the call gave (those that are not None), under the operation's name and the title of its card."""
    given = {k: v for k, v in args.items() if v is not None}
    given.update({k: v for k, v in (("channel", channel if channel is not None else "terminal"), ("sender", sender if channel == "messaging" else None)) if v is not None})
    key, title_key = {"add": (OP_ADD, "TITLE_TODO_ADD"), "complete": (OP_DONE, "TITLE_TODO_DONE")}[operation]
    started = account_start.start(project, KIND, {"account": account, "operation": operation, **given}, key_words=key, title_key=title_key, account=account, channel=channel, sender=sender)
    return {"status": "card", **started}


def todo_add(project: str, account: str, title: str, list: str | None = None, channel: str | None = None, sender: str | None = None) -> dict:  # noqa: A002
    """The operation `todo-add`: prepare a new task and stop at its card. `list` is a name of `accounts.<account>.task_lists` (the first listed when absent); an account with no
    list makes nothing (limit L55)."""
    return _start(project, "add", account, {"title": title, "list": list}, channel, sender)


def _fold(text) -> list:
    return natural.normal(text).split()


def _find(ctx: dict, channel, sender, account: str, item: str, only=None) -> dict:
    """The task `item` names among the open tasks of the account: {"status": "one", "entry"} | {"status": "several", "entries", "count"} | {"status": "none"} | {"status": "no-list"} |
    {"status": "unavailable"}. `todo:<n>` is the n-th task of the account in the list this sender was shown (origin `listed`); words are every folded word found whole in a title among the
    open tasks of the lists read now (origin `grounded`). A list that was not read to the end (a service that did not answer) is never taken for a complete one: an `unavailable`
    is said when no list could be read."""
    found = ITEM.fullmatch(item) if isinstance(item, str) else None
    if isinstance(item, str) and item.startswith("todo:") and not found:
        return {"status": "none"}      # a number outside 1 to 9999 names nothing; it is never read as words
    if found:
        record = _live(ctx, channel, sender)
        rows = (record or {}).get("items", {}).get(account)
        if not rows:
            return {"status": "no-list"}
        n = int(found.group(1))
        entry = rows[n - 1] if n <= len(rows) else None
        if entry is None or (only is not None and entry["list"] != only):
            return {"status": "none"}
        return {"status": "one", "entry": entry, "origin": "listed"}
    words = _fold(item)
    if not words:
        return {"status": "none"}
    read = _read_account(ctx["cfg"], account, only)
    rows = _entries(read)
    if read["failed"] and not read["lists"]:
        return {"status": "unavailable"}
    fits = [row for row in rows if set(words) <= set(_fold(row["title"]))]
    if len(fits) > 1:
        return {"status": "several", "entries": fits[:MATCH_MAX], "count": len(fits), "origin": "grounded"}
    if not fits:
        return {"status": "none"}
    return {"status": "one", "entry": fits[0], "origin": "grounded"}


def todo_done(project: str, account: str, item: str, list: str | None = None, channel: str | None = None, sender: str | None = None) -> dict:  # noqa: A002
    """The operation `todo-done`: prepare marking an open task of the list as completed and stop at its card. Returns {"status": "card", ...} for one task, else the outcome of the search:
    {"status": "several", "matches": [{"n", "list", "title"}], "count"} (the matches become the list a number answers), "none", "no-list" (a number with no list shown) or "unavailable"."""
    ctx = core.context(project)
    account_start.check_channel(ctx, OP_DONE, channel, sender)
    _may_read(ctx, channel, sender)
    if account not in SERVICES:
        raise core.OpsError("--account is google or microsoft", 2)
    if not isinstance(item, str) or not item.strip() or len(item) > natural.SPAN_MAX:
        raise core.OpsError("--item is todo:<n> or the words of the task (1 to 300 characters)", 2)
    got = _find(ctx, channel, sender, account, item.strip(), list)
    if got["status"] == "one":
        started = _start(project, "complete", account, {"task": got["entry"]["id"], "list": got["entry"]["list"]}, channel, sender)
        return dict(started, origin=got["origin"])
    if got["status"] == "several":
        _remember(ctx, channel, sender, {account: got["entries"]})
        return {"status": "several", "count": got["count"], "matches": [{"n": n, "list": e["list"], "title": e["title"]} for n, e in enumerate(got["entries"], 1)]}
    return {"status": got["status"]}


# --- the reply to a line in words -------------------------------------------------------------------------------------------------------------


def _private(ctx: dict, extras: dict) -> None:
    extras["stored"] = phrases.text("NW_PRIVATE_REPLY", ctx["cfg"])      # the reply holds a title: the conversation keeps a neutral word


def _service_arg(args: dict):
    """(the account the line's service word names or None, whether the word asked for one that is not read): only the closed SERVICE_WORDS, folded."""
    word = args.get("account")
    if word is None:
        return None, False
    mapped = SERVICE_WORDS.get(natural.ascii_normal(str(word)))
    return mapped, mapped is None


def _label(cfg: dict, account: str) -> str:
    return phrases.text("OUT_TODO_GOOGLE" if account == "google" else "OUT_TODO_MICROSOFT", cfg)


def _render_list(cfg: dict, got: dict) -> str:
    """The sentence a chat is told for the outcome of `todo_list`, in the project's language."""
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    if got["status"] == "no-lists":
        return t("TODO_NO_LISTS")
    if got["status"] == "unavailable":
        return "\n".join(t("TODO_UNAVAILABLE", service=_label(cfg, s["account"])) for s in got["services"])
    lines = []
    for service in got["services"]:
        label = _label(cfg, service["account"])
        if service["failed"]:
            lines.append(t("TODO_UNAVAILABLE", service=label))
        for item in service["lists"]:
            if not item["tasks"]:
                lines.append(t("TODO_EMPTY", service=label, list=item["list"]))
                continue
            lines.append(t("TODO_HEAD", service=label, list=item["list"]))
            lines += [t("TODO_ITEM", n=row["n"], title=row["title"] or "-") for row in item["tasks"]]
            if item["truncated"]:
                lines.append(t("TODO_MORE"))
    return "\n".join(lines)


def reply_list(project: str, ctx: dict, args: dict, channel, sender, extras: dict) -> str:
    """The reply of `todo-list` (runtime/ops_natural.py `run` has asked the policy already): the open tasks, numbered per service. The service word of a line is read from the closed
    SERVICE_WORDS; any other word asks again. The conversation keeps a neutral word."""
    cfg = ctx["cfg"]
    extras["stored"] = phrases.text("NAT_READ_REPLY", cfg)
    account, bad = _service_arg(args)
    if bad:
        return phrases.text("IX_ASK_AGAIN", cfg)
    car = _writes().carrier(channel)
    try:
        with ops_actor.carried_by(car):
            got = todo_list(project, account, car, sender if car == "messaging" else None)
    except core.OpsError as e:
        return _natural()._error(cfg, e, channel)
    return _render_list(cfg, got)


def _pick_account(ctx: dict, wanted, pool: list, use_default: bool = True):
    """("ok", account, origin) or ("say", the sentence, None): the account the line names (origin `line-span`), else the one account of `pool`, else `accounts.default` when two qualify (origin
    `config`; never for a number, which counts per service: `use_default` False), else the question. An account the line names that is not in `pool` is the sentence that no list is set up."""
    cfg = ctx["cfg"]
    if wanted:
        return ("ok", wanted, "line-span") if wanted in pool else ("say", phrases.text("TODO_NO_LISTS", cfg), None)
    if not pool:
        return "say", phrases.text("TODO_NO_LISTS", cfg), None
    if len(pool) == 1:
        return "ok", pool[0], "config"
    default = project_config.account_default(cfg)
    if use_default and default in pool:
        return "ok", default, "config"
    return "say", phrases.text("TODO_ASK_ACCOUNT", cfg), None


def _card(project: str, ctx: dict, op: str, account: str, given: dict, origins: dict, start, channel, sender, extras: dict) -> str:
    """The card of one change, as every write of the family opens it: the gate checks where each argument came from (S41-7: `given` holds the arguments of the operation and `origins` where each
    came from: the title is a span of the line; the task is a number of the list the sender was shown or was found by the words of the line; the account is the line's word or the
    configuration's; the list is the configuration's), the card is prepared by `start(channel, sender)`, and the bridge sends it (`extras["resend"]`); the terminal's own shell also gets
    the lines and the command with the hash."""
    cfg = ctx["cfg"]
    problems = turn_gate.provenance(op, dict(given, account=account), dict(origins))
    if problems:
        return _writes().refused_sentence(ctx, op, problems, channel, extras)
    car = _writes().carrier(channel)
    try:
        with ops_actor.carried_by(car):
            started = start(car, sender if car == "messaging" else None)
    except core.OpsError as e:
        return _natural()._error(cfg, e, channel)
    extras["resend"] = started["pending"]
    return account_start.reply_text(cfg, started) + _writes()._card_lines(ctx, project, started, channel)


def reply(project: str, ctx: dict, op: str, args: dict, said: str, channel, sender, extras: dict) -> str:
    """The reply of `todo-add` and `todo-done` chosen by the interpreter (runtime/ops_interpret.py `_carry_out`). The policy for the operation (and for cards) is asked again; the title
    is checked to be one clean line; the service word is read from the closed SERVICE_WORDS; a completion names its task by the number the line writes (the list this sender was shown) or by
    the words of the title (a search among the open tasks). One task opens its card; several are listed and remembered for the sender's next line; none is one sentence. Anything the
    code cannot read is the fixed ask-again sentence and nothing is read or prepared."""
    cfg = ctx["cfg"]
    _private(ctx, extras)
    if op not in natural.NATURAL:      # L54: a line reaches only what the served catalog holds; the natural writes' own parse never asks, so this is asked here (rows of a later catalog version are typed commands only)
        return phrases.text("IX_ASK_AGAIN", cfg)
    refused = _writes()._admit(ctx, op, channel, sender)
    if refused:
        return refused
    wanted, bad = _service_arg(args)
    if bad:
        return phrases.text("IX_ASK_AGAIN", cfg)
    if op == OP_ADD:
        title = args.get("title")
        text = title.strip() if isinstance(title, str) else ""
        try:
            tasks_document.line(text, "the title", tasks_document.TITLE_MAX, True)
        except Exception:      # noqa: BLE001 - an EffectError of the document: the sentence names the rule, never the title
            return phrases.text("TODO_BAD_TITLE", cfg)
        state, account, origin = _pick_account(ctx, wanted, _accounts_with_lists(cfg))
        if state == "say":
            return account
        return _card(project, ctx, OP_ADD, account, {"title": text}, {"account": origin, "title": "line-span"},
                     lambda car, who: todo_add(project, account, text, None, car, who), channel, sender, extras)
    return _reply_done(project, ctx, args, wanted, channel, sender, extras)


def _reply_done(project: str, ctx: dict, args: dict, wanted, channel, sender, extras: dict) -> str:
    cfg = ctx["cfg"]
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    number, words = args.get("item"), args.get("target")
    if (number is None) == (not isinstance(words, str) or not words.strip()):      # neither, or both: the line does not say which task
        return t("IX_ASK_AGAIN")
    try:
        _may_read(ctx, channel, sender)
    except core.OpsError as e:
        return _natural()._error(cfg, e, channel)
    if number is not None and not (isinstance(number, int) and not isinstance(number, bool) and 1 <= number <= NUMBER_MAX):
        return t("TODO_NONE")      # a number outside 1 to 9999 names no task: answered before anything is looked at
    if number is not None:
        pool = list((_live(ctx, channel, sender) or {}).get("items", {}))
        if not pool:
            return t("TODO_NO_LIST_SHOWN")
        item = f"todo:{int(number)}"
    else:
        pool, item = _accounts_with_lists(cfg), words.strip()
    state, account, origin = _pick_account(ctx, wanted, pool, use_default=number is None)      # a number counts per service: with two services shown and none named, ask
    if state == "say":
        return account
    got = _find(ctx, channel, sender, account, item)
    status = got["status"]
    if status == "no-list":
        return t("TODO_NO_LIST_SHOWN")
    if status == "unavailable":
        return t("TODO_UNAVAILABLE", service=_label(cfg, account))
    if status == "none":
        return t("TODO_NONE")
    if status == "several":
        _remember(ctx, channel, sender, {account: got["entries"]})
        rows = [t("TODO_ITEM", n=n, title=e["title"] or "-") for n, e in enumerate(got["entries"], 1)]
        return "\n".join([t("TODO_SEVERAL", count=got["count"])] + rows)
    entry = got["entry"]
    return _card(project, ctx, OP_DONE, account, {"item": item, "list": entry["list"]}, {"account": origin, "item": got["origin"], "list": "config"},
                 lambda car, who: _start(project, "complete", account, {"task": entry["id"], "list": entry["list"]}, car, who), channel, sender, extras)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
