"""The current-pipeline arm of the interpreter experiment (package IX-2c; SPEC-IX-2C section 3): each corpus line is driven through TODAY'S code, on the `lab` world (the
project of the natural-writes tests, the real operations layer, the real messaging bridge over a stand-in messenger), with the router stubbed ("reached the router" is `route`), the
resolvers of the project's accounts stubbed to accept (as the B-prime arm's are) and a recorder on each place where today's code decides what the person is shown. What the line did
is scored by the SAME `interpreter_score` and written by the SAME `interpreter_evidence` builders as the B-prime arm (`arm: "current"`, no model, no route, `billing: "none"`, 2 runs).

Recorders (record-only wrappers: the real function still runs except where it would leave the process). A line's `observed` is the highest of: `executed` (a store diff after the
line: a row of reminders, pending decisions, tasks, attachments, approvals or routines changed or removed, a reminder added or a decision added that is not an open card) >
`answer` (the line answered the item the frame seeded: whatever follows an accepted answer, a card or the next question, is the next turn's, as in the B-prime arm, which stops at the
answer) > `card` (`ops_natural_writes._opened`, stubbed so that no card is made) > `remind_confirm` (`Reminders.question` with a reading) > `confirm` (a reminder to forget asked
first) > `read` (`ops_natural.run` on class R or `ask`, `Reminders.listing`, the help) > `clarify` (`ops_natural_writes._ask`, the reminders' other questions) > `route` (the
stubbed router) > `refuse_d` > `refuse_g` (today's "done on the page") > `forwarded` (the bridge's one sentence) > `none` (nothing recorded; a W operation, whose reply today is "type the
command"; a typed `/` command; an exception, counted `crashed`). The detail uses catalog slot names (`STATE_OF`: the family states' own names are translated, and the time slot's span is the time
engine's own span of the line), so that a card is not wrong for the names of today's internal slots.

Default (selected tests): 40 items of evals/interpreter/dev.jsonl (seed 20261024), 2 runs, evidence to tmp_path. WB_FULL_FUZZ=1 alone runs the whole dev file into tmp_path; the test
`test_current_arm_full_run` runs a file given by WB_IX_CURRENT_CORPUS and writes ONE event to WB_IX_CURRENT_EVIDENCE (SPEC-IX-2C section 8; with a test corpus the pytest `--basetemp`
must resolve inside the corpus file's folder, because the stand-in messenger writes the replies to disk). Counts are printed, never a line. Offline: no model, no network.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_current_arm.py
"""
from __future__ import annotations

import collections
import datetime
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import standin_tree as st
from test_interpreter_echo import DEV, load, sample
from test_messaging import FIXTURE
from test_reminders import Clock

lab_module = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_say = st.load("ops_say")
ops_natural = st.load("ops_natural")
ops_natural_writes = st.load("ops_natural_writes")
ops_natural_calendar = st.load("ops_natural_calendar")
ops_natural_mail = st.load("ops_natural_mail")
ops_natural_files = st.load("ops_natural_files")
messaging_remind = st.load("messaging_remind")
operations = st.load("operations")
bridge_module = st.load("messaging_bridge")
ledgers = st.load("messaging_ledger")
providers = st.load("messaging_provider")
shell_kit = st.load("shell_kit")
drafts = st.load("drafts")
phrases = st.load("phrases")
natural = st.load("natural")
natural_time = st.load("natural_time")
nw = st.load("natural_writes")
interpreter = st.load("interpreter")
score = st.load("interpreter_score")
evidence = st.load("interpreter_evidence")
pipeline = st.load("interpreter_pipeline")

REPO = Path(__file__).resolve().parents[2]
OWNER = "830461975213"
KEY = f"telegram:{OWNER}"
SEED, SAMPLE = "20261024", 40
ACCOUNTS = {"google": {"address": "owner@example.com", "calendars": {"personal": "owner@example.com", "gym": "gym@example.com"}, "folders": {"default": "folder-1"},
                       "mail_folders": {"inbox": "INBOX", "bills": "Bills"}},
            "microsoft": {"address": "owner@example.org", "calendars": {"personal": "default"}, "folders": {"default": "folder-2"}, "mail_folders": {"inbox": "inbox"}}}
WATCHED = ("reminders", "pending_decisions", "tasks", "attachments", "approvals", "routines")
# The resolvers the arm stubs (every lookup of a thing the project would have to hold): each is replaced for the run and counted, and a test proves each is reached.
RESOLVERS = [("ops_natural_writes", "pick_account"), ("ops_natural_writes", "named_target"), ("ops_natural_calendar", "_reference"), ("ops_natural_mail", "_messages"),
             ("ops_natural_mail", "_folder"), ("ops_natural_mail", "_compose_account"), ("ops_natural_files", "_replace"), ("ops_natural_files", "held_files")]
# The catalog slot -> the slot of today's family state (the state's own names are not the catalog's), per operation: read from the code's reading (natural_writes*.py), written here.
STATE_OF = {
    "event-create": {"title": "title", "calendar": "calendar", "service": "account", "time": "start"},
    "event-change": {"event": "event", "title": "title", "time": "start"},
    "event-cancel": {"event": "event"},
    "mail-send": {"to": "to", "subject": "subject", "body": "body"},
    "mail-draft": {"to": "to", "subject": "subject", "body": "body", "message": "numbers"},
    "mail-reply": {"message": "numbers", "body": "body"},
    "mail-archive": {"messages": "numbers"}, "mail-trash": {"messages": "numbers"},
    "mail-move": {"messages": "numbers", "folder": "folder_name"}, "mail-mark": {"messages": "numbers", "state": "state"},
    "file-create": {"name": "name", "content": "content", "folder": "folder"},
    "file-replace": {"file": "words", "content": "content"},
    "file-save": {"attachment": "attachment", "folder": "folder"},
}
TEXT_NEEDS = {"title": "title", "subject": "subject", "body": "body", "content": "content", "name": "name", "to": "to", "state": "state"}          # a slot a seeded write-draft may wait for, and its need
PRECEDENCE = ("executed", "answer", "card", "remind_confirm", "confirm", "read", "clarify", "route", "refuse_d", "refuse_g", "forwarded", "none")


def by_path(rel, name):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, REPO / rel)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


lines_module = by_path("evals/evidence_lines.py", "workbench_evidence_lines_for_ix2c")


# --- the recorders -----------------------------------------------------------------------------------------------------------------------------------

class Recorder:
    def __init__(self):
        self.events = []

    def add(self, kind, **detail):
        self.events.append((kind, detail))

    def of(self, kind):
        return [d for k, d in self.events if k == kind]


def span_of_time(lines, now):
    """The words of the line that the time engine read as the time (its own spans, joined across a gap of spaces), or None."""
    for line in lines:
        got = natural_time.parse(line, now)
        if got and got.get("spans"):
            pieces, last = [], None
            for a, b in sorted(map(tuple, got["spans"])):
                if last is not None and not line[last:a].strip():
                    pieces[-1] = (pieces[-1][0], b)
                else:
                    pieces.append((a, b))
                last = b
            return " ".join(line[a:b] for a, b in pieces)
    return None


def catalog_detail(op, state, args, now):
    """{"op", "slots", "time"} of a write's state in the catalog's slot names (the arm's translation; module text)."""
    kinds = {slot: spec[0] for slot, spec in natural.NATURAL[op]["slots"].items()}
    slots = {}
    for slot, mine in STATE_OF.get(op, {}).items():
        value = state["slots"].get(mine)
        if value in (None, "", [], False):
            continue
        if slot == "time":
            value = span_of_time(state.get("said", []), now) or str(value)
        elif isinstance(value, list):
            value = ",".join(str(v) for v in value) if kinds.get(slot) == "ints" else (str(value[0]) if kinds.get(slot) == "int" else ",".join(str(v) for v in value))
        slots[slot] = str(value)
    return {"op": op, "slots": slots, "time": args.get("start")}


class Lab:
    """The world of one run: the project, the bridge and its stand-in messenger, the clock, the recorder and the counters."""

    def __init__(self):
        self.rec = Recorder()
        self.counts = collections.Counter()
        self.resolver_calls = collections.Counter()
        self.held = [1]
        self.router_item = None


def build(tmp_path, monkeypatch) -> Lab:
    built = st.build(tmp_path, monkeypatch, lab_module)
    tree, project = built["tree"], built["project"]
    config = project / "docs" / "workbench" / "runtime.json"
    raw = json.loads(config.read_text(encoding="utf-8"))
    groups = [g for g in tuple(operations.ceiling_groups("messaging")) + tuple(operations.GRANTS["messaging"]) if g not in ("read-limited", "interpret-fallback")]          # the owner holds every group (L1) but the one that cannot be accepted while no fallback route is in force (S41-10)
    raw["accounts"] = {**ACCOUNTS, "default": "google"}
    raw["policies"] = {"owner": groups}
    raw["messaging"] = {"senders": {"telegram": [{"id": OWNER, "policy": "owner"}]}}
    config.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(ops_core, "ROOT", str(tree))
    path = str(project)
    shown = ops.config(path)
    ops.accept_config(path, shown["sha256"], widen=shown["widening_sha256"])
    root = tmp_path / "bench-messenger"
    (root / "providers" / "messenger").mkdir(parents=True)
    shutil.copy(st.REPO / "providers" / "resolve.py", root / "providers" / "resolve.py")
    shutil.copy(FIXTURE, root / "providers" / "messenger" / "standin.py")
    folder = tmp_path / "standin"
    folder.mkdir()
    monkeypatch.setenv("STANDIN_DIR", str(folder))
    data = tmp_path / "ledger-data"
    data.mkdir()
    w = Lab()
    w.path, w.folder, w.log, w.tmp = path, folder, [], tmp_path
    w.clock = Clock(monkeypatch, wall="2026-10-22 14:00")
    projects = [{"id": shell_kit.project_id(path), "name": "northwind-shop", "path": path}]
    w.bridge = bridge_module.Bridge(ops, projects, providers.Messenger("telegram", root=str(root)), ledgers.Ledger(str(data), "telegram"), "telegram", w.log.append,
                                    clock=lambda: "2026-10-22T14:00:00+00:00")
    w.project_key = ops_natural.project_key(path)
    w.originals = {name: getattr(sys.modules[module], name) for module, name in RESOLVERS}
    install(w, monkeypatch)
    seed_store(w)
    return w


def sent(w):
    target = w.folder / "sent.jsonl"
    return [json.loads(line)["message"]["text"] for line in target.read_text().splitlines()] if target.is_file() else []


def install(w, monkeypatch):
    rec = w.rec

    def counted(name, fn):
        def wrapped(*a, **k):
            w.resolver_calls[name] += 1
            return fn(*a, **k)
        return wrapped
    # the resolvers: every lookup of a thing the project would hold succeeds (both arms)
    monkeypatch.setattr(ops_natural_writes, "pick_account", counted("pick_account", lambda ctx, wanted, section, source_account=None, slot="account": ("ok", wanted or source_account or "google")))
    monkeypatch.setattr(ops_natural_writes, "named_target", counted("named_target", lambda ctx, account, section, name, slot: ("ok", name or None)))

    def reference(ctx, slots, channel, sender):
        if "event" not in slots:
            return "spec", ops_natural_writes.ask_spec("event", "NW_ASK_EVENT"), None
        return "ok", f"calendar-1#{slots['event']}", "google"
    monkeypatch.setattr(ops_natural_calendar, "_reference", counted("_reference", reference))

    def messages(ctx, slots, channel, sender):
        refs = [f"mail-1#{n}" for n in slots.get("numbers") or []] + list(slots.get("refs") or [])
        if not refs and (slots.get("words") or slots.get("newest")):
            refs = ["mail-1#1"]
        if not refs:
            raise ops_natural_mail._say("NW_MAIL_NONE", source="", words="")
        return "google", list(dict.fromkeys(refs)), None
    monkeypatch.setattr(ops_natural_mail, "_messages", counted("_messages", messages))
    monkeypatch.setattr(ops_natural_mail, "_folder", counted("_folder", lambda ctx, account, slots: (slots["folder_name"], None) if slots.get("folder_name") else
                                                             (None, ops_natural_mail._ask("folder", "NW_ASK_FOLDER", [("inbox", "inbox")], slot="folder_name", name="", names="inbox"))))
    monkeypatch.setattr(ops_natural_mail, "_compose_account", counted("_compose_account", lambda ctx, slots: ("google", None)))
    monkeypatch.setattr(ops_natural_files, "_replace", counted("_replace", lambda ctx, slots: {"args": {"account": "google", "file": slots.get("file") or "drive-1", "content": slots["content"]}}))
    monkeypatch.setattr(ops_natural_files, "held_files", counted("held_files", lambda ctx, channel, sender: [{"id": n, "name": f"file-{n}.pdf", "kind": "pdf", "save_only": False} for n in w.held]))

    # the router: reaching it is `route`; an answer to its open question is `answer`
    def say_route(project, ctx, said, line_id, channel, answer_to=None, after=None, sender=None, extras=None):
        if answer_to is not None:
            rec.add("answer", item=w.router_item, via="router")
        else:
            rec.add("route")
        return phrases.text("NOT_NAMED_NEXT_PHONE", ctx["cfg"], request=0) if channel == "messaging" else "not named", None, None, False, None
    monkeypatch.setattr(ops_say, "_say_route", say_route)
    monkeypatch.setattr(ops_say, "_open_question", lambda ctx, channel, sender=None: 7 if w.router_item else None)

    # the card: opening is recorded and nothing is made
    def opened(project, ctx, state, args, channel, sender, extras):
        extras["stored"] = ""
        rec.add("card", **catalog_detail(state["op"], state, args, w.clock.moment.replace(tzinfo=None)))
        return "card"
    monkeypatch.setattr(ops_natural_writes, "_opened", opened)
    real_ask = ops_natural_writes._ask

    def ask(ctx, state, spec, channel, sender, extras):
        rec.add("clarify", slot=None)
        return real_ask(ctx, state, spec, channel, sender, extras)
    monkeypatch.setattr(ops_natural_writes, "_ask", ask)
    real_answer = ops_natural_writes.answer

    def answered(project, ctx, state, said, channel, sender, extras):
        found = ops_natural_writes._classify(ctx, state, said)
        reply = real_answer(project, ctx, state, said, channel, sender, extras)
        if reply is not None and found is not None:
            if found["kind"] in ("slots", "engine"):
                taken = (found.get("slots") or {}).get(state.get("slot")) if found["kind"] == "slots" else None
                taken = ",".join(str(v) for v in taken) if isinstance(taken, list) else taken
                rec.add("answer", item=w.write_item, via="write", said=said, span=str(taken) if taken is not None else None)
            elif found["kind"] in ("retry", "giveup"):
                rec.add("clarify", slot=None)
        return reply
    monkeypatch.setattr(ops_natural_writes, "answer", answered)

    # the reminders' questions (messaging)
    real_question = messaging_remind.Reminders.question

    def question(self, project, chat, sentence, draft):
        need, readings = draft.get("need"), draft.get("readings") or []
        if need in ("confirm", "ready", "kind") and readings:
            rec.add("remind_confirm", op="remind", slots=remind_slots(draft, w), time=f"{readings[0]['date']}T{readings[0]['time']}")
        elif need == "forget":
            rec.add("confirm", op="reminder-forget", slots={"id": str((draft.get("ids") or [""])[0])}, time=None)
        else:
            rec.add("clarify", slot=None)
        return real_question(self, project, chat, sentence, draft)
    monkeypatch.setattr(messaging_remind.Reminders, "question", question)
    real_remind_answer = messaging_remind.Reminders.answer

    def remind_answer(self, project, chat, kind, text, reply_to=None):
        done = real_remind_answer(self, project, chat, kind, text, reply_to)
        if done:
            rec.add("answer", item=w.remind_item, via="remind", said=text)
        return done
    monkeypatch.setattr(messaging_remind.Reminders, "answer", remind_answer)
    real_natural = messaging_remind.Reminders.natural

    def remind_natural(self, project, chat, intent):
        if intent.get("op") == "reminders":
            rec.add("read", op="reminders", slots={})
        return real_natural(self, project, chat, intent)
    monkeypatch.setattr(messaging_remind.Reminders, "natural", remind_natural)

    # the dispatcher of the natural requests (every other channel, and the reads of messaging)
    real_run = ops_natural.run

    def run(project, ctx, name, args, said, channel, sender, extras, when=None, routed=False):
        cls = natural.class_of(name)
        slots = {slot: str(args[spec[1]]) for slot, spec in natural.NATURAL[name]["slots"].items() if spec[1] in args}
        if cls == "R" or name == "ask":
            rec.add("read", op=name, slots=slots)
        elif cls == "D":
            rec.add("refuse_d")
        elif cls == "G":
            rec.add("refuse_g")
        return real_run(project, ctx, name, args, said, channel, sender, extras, when=when, routed=routed)
    monkeypatch.setattr(ops_natural, "run", run)
    real_state = ops_say.state_reply

    def state_reply(project, proposed=None, cfg=None):
        rec.add("read", op="status", slots={})          # a question about the state is answered by code from `status` and `progress`
        return real_state(project, proposed, cfg)
    monkeypatch.setattr(ops_say, "state_reply", state_reply)
    real_complete = ops_natural._complete

    def completed(project, ctx, draft, answer, said, channel, sender, extras):
        if draft.get("kind") != "which":
            rec.add("answer", item=w.remind_item, via="remind", said=said)
        return real_complete(project, ctx, draft, answer, said, channel, sender, extras)
    monkeypatch.setattr(ops_natural, "_complete", completed)


def remind_slots(draft, w):
    """The reminder's `text` and `when` as the catalog names them: the draft's words, and the time phrase the engine read in its line."""
    slots = {"text": str(draft.get("text") or "")}
    when = span_of_time([draft.get("line") or ""], w.clock.moment.replace(tzinfo=None))
    if when:
        slots["when"] = when
    return slots


# --- the world's state -------------------------------------------------------------------------------------------------------------------------------

def table_rows(w):
    conn = ops_core.context(w.path)["conn"]
    out = {}
    for table in WATCHED:
        out[table] = {row[0]: dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1")}
    return out


def seed_store(w):
    """Five reminders (numbers 1 to 5) due far ahead, then a copy of the whole store: every run starts from that copy."""
    ctx = ops_core.context(w.path)
    conn, store = ctx["conn"], ctx["store"]
    due = datetime.datetime(2027, 3, 1, 10, 0, tzinfo=ZoneInfo("UTC"))
    for n in range(1, 6):
        store.reminder_add(conn, text=f"water the plants {n}", due_local="2027-03-01 07:00", due_utc=due.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), zone="America/Sao_Paulo",
                           platform="telegram", chat=OWNER, created_by="telegram", max_open=100, max_day=100, max_open_chat=100, day_since="2026-01-01T00:00:00.000000Z")
    conn.commit()
    w.db = ctx["cfg"]["store_db"]
    w.snapshot = str(w.tmp / "snapshot.sqlite")
    copy = sqlite3.connect(w.snapshot)
    conn.backup(copy)
    copy.close()


def reset(w):
    """The same state before every run of every item: no draft, no open question, the store as it was copied after the seeding."""
    drafts.clear()
    w.bridge.remind.expired.clear()
    w.bridge.remind.discarded.clear()
    source, target = sqlite3.connect(w.snapshot), sqlite3.connect(w.db)
    source.backup(target)
    source.close()
    target.close()
    w.rec.events.clear()
    w.router_item = w.write_item = w.remind_item = None
    w.held = [1]


def put_clock(w, item):
    zone = ZoneInfo(item["zone"])
    w.clock.zone = zone
    w.clock.moment = datetime.datetime.fromisoformat(item["clock"]).replace(tzinfo=zone)


def now_of(w):
    return w.clock.moment.replace(tzinfo=None)


def draft_slot(item):
    return ("messaging", KEY) if item["channel"] == "messaging" else (item["channel"], "")


def reading_of(words, now):
    got = natural_time.parse(words, now) if words else None
    return got["reading"] if got and "reading" in got else None


def seed_reminder(w, item, it):
    words, now = it.get("words") or {}, now_of(w)
    text = words.get("text") or "x"
    if it["need"] == "slot" and it.get("slot") == "when":
        draft = natural._draft("time", "trigger", text, text)
    elif it["need"] == "confirm":
        reading = reading_of(words.get("when"), now)
        if reading is None:
            return False
        draft = natural._draft("confirm", "trigger", f"{text} {words.get('when')}", text, readings=[reading])
    else:
        return False
    w.remind_item = it["id"]
    if item["channel"] == "messaging":
        w.bridge.remind.drafts[OWNER] = {**draft, "project": shell_kit.project_id(w.path), "at": w.bridge.monotonic(), "message_id": None}
    else:
        drafts.put(*draft_slot(item), {**draft, "project": w.project_key, "at": ops_natural.monotonic(), "message_id": None}, "remind")
    return True


def seed_write(w, item, it):
    op, words, now = it.get("op"), dict(it.get("words") or {}), now_of(w)
    if op not in STATE_OF or it["need"] != "slot" or it.get("slot") not in TEXT_NEEDS:
        return False
    slots = {}
    for slot, text in words.items():
        mine = STATE_OF[op].get(slot)
        if mine is None:
            return False
        if mine == "start":
            reading = reading_of(text, now)
            if reading is None:
                return False
            slots["start"] = f"{reading['date']}T{reading['time']}"
        elif mine == "numbers":
            slots.update(numbers=[int(text)], refs=[], plural=False, newest=False)
        elif mine in ("event", "attachment"):
            slots[mine] = int(text)
        elif mine == "to":
            slots["to"] = [text]
        else:
            slots[mine] = text
    ctx = ops_core.context(w.path)
    state = ops_natural_writes.new_state(ctx, {"op": op, "family": nw.OP_FAMILY[op], "slots": slots, "spans": {}, "ranges": {}, "need": [], "engine": None, "doubt": False},
                                         " ".join(words.values()) or "x")
    asked = STATE_OF[op][it["slot"]]
    state.update(need=TEXT_NEEDS[it["slot"]], slot=asked, options=[], multi=False, sentence_key="NW_ASK_TITLE_PLAIN", fields={})
    w.write_item = it["id"]
    drafts.put(*draft_slot(item), state, "write", ttl=ops_natural_writes.DRAFT_TTL)
    return True


def seed(w, item) -> bool:
    """Seed today's equivalent of the frame's open items; False when an item has none (a choice, a write confirm, a reminder confirm whose `when` code cannot read)."""
    complete = True
    for it in (item["frame"] or {}).get("items", []):
        if it["kind"] == "router-question":
            w.router_item = it["id"]
        elif it["kind"] == "reminder-confirm":
            complete = seed_reminder(w, item, it) and complete
        elif it["kind"] == "write-draft":
            complete = seed_write(w, item, it) and complete
        else:
            complete = False
    return complete


# --- one line ----------------------------------------------------------------------------------------------------------------------------------------

def settle(w):
    for thread in list(w.bridge.threads):
        thread.join(30)


def send(w, item):
    line = item["line"]
    if item["channel"] == "messaging":
        w.bridge.handle({"update_id": 1, "sender": OWNER, "chat": OWNER, "private": True, "text": line, "action": None, "action_ref": None, "reply_to": None,
                         "forwarded": item["forwarded"]})
        settle(w)
    else:
        ops.say(w.path, line, channel=None if item["channel"] == "chat" else item["channel"])


def answer_detail(w, item, event, before, after):
    it = next(i for i in item["frame"]["items"] if i["id"] == event["item"])
    detail = {"item": it["id"]}
    said = event.get("said") or item["line"]
    taken = event.get("span") or span_of_time([said], now_of(w)) or said.strip()
    if it["need"] == "confirm":
        detail["confirm"] = natural.confirm_kind(said)
    elif it["need"] == "option":
        detail["option"] = int(said.strip()) if said.strip().isdigit() else None
    elif it["need"] == "slot":
        detail.update(slot=it.get("slot"), span=taken)
        if (it.get("op"), it.get("slot")) in interpreter.TIME_SLOTS:
            made = [r for k, r in after["reminders"].items() if k not in before["reminders"]]
            cards = w.rec.of("card")
            kept = drafts.get(*draft_slot(item))
            if made:
                detail["time"] = str(made[0]["due_local"]).replace(" ", "T")[:16]
            elif cards:
                detail["time"] = cards[0].get("time")
            elif kept and kept.get("readings"):
                detail["time"] = f"{kept['readings'][0]['date']}T{kept['readings'][0]['time']}"
            elif kept and (kept.get("slots") or {}).get("start"):
                detail["time"] = kept["slots"]["start"]
    return {k: v for k, v in detail.items() if v is not None}


def executed(before, after, answered_reminder):
    for table in WATCHED:
        was, now = before[table], after[table]
        if any(k not in now or now[k] != v for k, v in was.items()):
            return True
        added = [now[k] for k in now if k not in was]
        if table == "pending_decisions":
            continue
        if added and not (table == "reminders" and answered_reminder):
            return True
    return False


def outcome(kind, detail=None, **more):
    return {"observed": kind, "detail": detail or {}, "stage": "current", "parse": "none", "error": None, "time_source": None, "call": None, "notes": [], "why": None,
            "time_disagree": False, **more}


def run_line(w, item) -> dict:
    """The Outcome of today's code for one run of one item (module text)."""
    reset(w)
    put_clock(w, item)
    seeded = seed(w, item)
    if item["line"].strip().startswith("/") and not (item["channel"] == "messaging" and item["forwarded"] is not False):
        return outcome("none", notes=["typed"], seeded=seeded, crashed=False)
    line_numbers = [int(n) for n in re.findall(r"[0-9]+", item["line"])[:1]]
    w.held = line_numbers or [1]
    before, written = table_rows(w), len(sent(w))
    crashed = False
    try:
        send(w, item)
    except Exception:          # noqa: BLE001 - counted, never described
        crashed = True
    after, said = table_rows(w), sent(w)[written:]
    kinds = {k for k, _ in w.rec.events}
    answers = w.rec.of("answer")
    if any(t in phrases.every("FWD_NOT_A_REQUEST") for t in said):
        kinds.add("forwarded")
    if any(t in phrases.every("HELP") for t in said):
        w.rec.add("read", op="commands", slots={})
        kinds.add("read")
    if executed(before, after, any(a.get("via") == "remind" for a in answers)):
        kinds.add("executed")
    chosen = next((k for k in PRECEDENCE if k in kinds), "none")
    detail = {}
    if chosen == "answer":
        detail = answer_detail(w, item, answers[0], before, after)
    elif chosen in ("card", "remind_confirm", "confirm", "read"):
        found = w.rec.of(chosen)[0]
        detail = {k: v for k, v in found.items() if k in ("op", "slots") or (k == "time" and chosen in ("card", "remind_confirm"))}
        if chosen == "read":
            detail.pop("time", None)
    elif chosen == "clarify":
        detail = {}
    elif chosen == "refuse_d":
        detail = {"class": "D"}
    elif chosen == "refuse_g":
        detail = {"class": "G"}
    return outcome(chosen, detail, seeded=seeded, crashed=crashed)


# --- the arm over a list of items --------------------------------------------------------------------------------------------------------------------

def measure_current(w, items, runs=2):
    """(scored runs [(item, run, outcome, category)], the rows the summary reads, the counters) of today's code over the items; items of scope time write no line."""
    scored, rows, time_rows, counts = [], [], [], collections.Counter()
    for item in sorted(items, key=lambda i: (i["zone"], i["id"])):
        scope = item["gold"].get("scope", "full")
        for run in range(1, runs + 1):
            got = run_line(w, item)
            if run == 1:
                counts["unseeded"] += 0 if got["seeded"] else 1
            counts["crashed"] += 1 if got["crashed"] else 0
            if scope == "time":
                time_rows.append(score.time_result(item["gold"], item["also"], got["observed"], got["detail"]))
                continue
            category = score.categorize(item["gold"], item["also"], scope, got["observed"], got["detail"])
            scored.append((item, run, got, category))
            rows.append({"item": item["id"], "run": run, "lang": item["lang"], "gold": item["gold"]["outcome"], "category": category, "observed": got["observed"], "parse": "none",
                         "called": False, "latency_ms": None, "cost_usd": None, "error": None, "stage": "current", "why": None, "time_disagree": False})
    return scored, rows, time_rows, counts


def write_event(folder, split, items, scored, corpus_sha, runs=2):
    test = evidence.new_test_id()
    event = evidence.event_line(arm="current", split=split, test=test, date=evidence.utc_date(), route=None, runs=runs, items=len(items), sequential=False, billing="none",
                                corpus=corpus_sha)
    body = [event] + [evidence.item_line(test, one, run, got, category, None, None) for one, run, got, category in sorted(scored, key=lambda t: (t[0]["id"], t[1]))]
    path = Path(folder) / f"ix-{test}.jsonl"
    evidence.write_exclusive(str(path), body)
    return path


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = build(tmp_path, monkeypatch)
    yield w
    w.bridge.stopping.set()
    settle(w)
    drafts.clear()


# What today's code does with the 40-item sample (seed 20261024) and with 18 more dev items that reach the answer, forward and reminder paths: the category of each (both runs),
# written here so that a change of today's code, of the scorer or of the dev file is noticed. The reasons, in short: most plain lines go to the router (a request code does not
# read as an operation is `wrong_route`); the reminders' questions show a reading of their own (`wrong_reminder_reading` when it is not the gold's); an answer is bound to the one
# draft today's code keeps (`wrong_item_binding` when the line was another request).
SAMPLE_CATEGORIES = {
    "dev-de-00000": "wrong_route", "dev-de-00004": "wrong_item_binding", "dev-de-00007": "wrong_route", "dev-de-00012": "wrong_route", "dev-de-00018": "wrong_route",
    "dev-de-00026": "wrong_route", "dev-de-00028": "wrong_item_binding", "dev-en-00002": "wrong_route", "dev-en-00005": "wrong_route", "dev-en-00012": "correct",
    "dev-en-00030": "wrong_route", "dev-en-00033": "wrong_route", "dev-en-00036": "wrong_reminder_reading", "dev-en-00074": "wrong_route", "dev-en-00076": "wrong_route",
    "dev-es-00018": "wrong_route", "dev-es-00020": "wrong_route", "dev-es-00028": "wrong_route", "dev-es-00030": "correct", "dev-es-00034": "wrong_item_binding",
    "dev-es-00036": "wrong_route", "dev-es-00046": "wrong_route", "dev-fr-00002": "wrong_route", "dev-fr-00006": "wrong_route", "dev-fr-00007": "wrong_route",
    "dev-fr-00024": "wrong_route", "dev-it-00003": "wrong_route", "dev-it-00005": "wrong_item_binding", "dev-it-00009": "wrong_route", "dev-it-00028": "wrong_route",
    "dev-pt-br-00005": "wrong_reminder_reading", "dev-pt-br-00014": "wrong_route", "dev-pt-br-00024": "correct", "dev-pt-br-00033": "wrong_route", "dev-pt-br-00041": "wrong_route",
    "dev-pt-br-00045": "wrong_route", "dev-pt-br-00049": "correct", "dev-pt-br-00050": "wrong_route", "dev-pt-br-00073": "wrong_route", "dev-pt-br-00080": "wrong_route",
}
EXTRA_CATEGORIES = {
    "dev-de-00004": "wrong_item_binding", "dev-en-00013": "wrong_reminder_reading", "dev-en-00021": "correct", "dev-en-00025": "wrong_item_binding", "dev-en-00028": "wrong_item_binding",
    "dev-en-00049": "wrong_item_binding", "dev-en-00054": "wrong_item_binding", "dev-es-00017": "correct", "dev-es-00025": "wrong_item_binding", "dev-es-00049": "correct",
    "dev-fr-00016": "wrong_reminder_reading", "dev-fr-00027": "wrong_reminder_reading", "dev-pt-br-00023": "correct", "dev-pt-br-00040": "correct", "dev-pt-br-00058": "wrong_reminder_reading",
    "dev-pt-br-00072": "correct", "dev-pt-br-00074": "correct", "dev-pt-br-00087": "correct",
}
UNSEEDED_IDS = {"dev-es-00034", "dev-it-00005", "dev-en-00049", "dev-es-00025", "dev-pt-br-00058"}          # a choice, or a confirm of a reminder whose `when` has no single reading (no equivalent state in today's code): run with no open item


def dev_items(ids=None):
    every = {i["id"]: i for i in load(DEV)}
    return [every[k] for k in ids] if ids else sample(list(every.values()), SAMPLE, SEED)


def line_item(line, **more):
    base = {"id": "dev-en-09999", "split": "dev", "lang": "en", "hard": False, "clock": "2026-10-22T14:00", "zone": "America/Sao_Paulo", "channel": "messaging", "forwarded": False,
            "frame": None, "line": line, "gold": {"outcome": "none"}, "also": []}
    base.update(more)
    return base


def categories(scored):
    out = {}
    for one, run, got, category in scored:
        out.setdefault(one["id"], []).append(category)
    return out


def test_the_dev_sample_gets_the_categories_written_here_in_both_runs(world):
    items = list({i["id"]: i for i in dev_items() + dev_items(sorted(EXTRA_CATEGORIES))}.values())
    scored, rows, time_rows, counts = measure_current(world, items)
    got = categories(scored)
    expected = {**SAMPLE_CATEGORIES, **EXTRA_CATEGORIES}
    assert {k: v for k, v in got.items()} == {k: [c, c] for k, c in expected.items()}, "a change in either run, or an item not listed"
    assert counts["crashed"] == 0 and counts["unseeded"] == len(UNSEEDED_IDS & set(expected)), dict(counts)
    assert len(SAMPLE_CATEGORIES) == SAMPLE and sum(c == "correct" for c in expected.values()) >= 5


def test_every_line_is_valid_by_the_validator_and_the_event_is_the_current_arms(world, tmp_path):
    items = dev_items(sorted(EXTRA_CATEGORIES))
    scored, rows, time_rows, counts = measure_current(world, items)
    path = write_event(tmp_path, "dev", items, scored, "c" * 64)
    assert lines_module.interpreter_file_problems(str(path), {"runs": 2, "routes": {}, "pins": {}}) == []
    body = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    event = body[0]
    assert (event["arm"], event["billing"], event["runs"], event["sequential"], event["model"], event["route"], event["route_sha256"], event["prompt_sha256"]) == \
        ("current", "none", 2, False, None, None, None, None)
    assert event["catalog_sha256"] == interpreter.SERVED_SHA256 and event["items"] == len(items)
    assert all(l["cost_usd"] is None and l["usage"] is None and l["latency_ms"] is None and l["upstream"] is None and l["parse"] == "none" and l["error"] is None for l in body[1:])
    by_item = collections.defaultdict(set)
    for l in body[1:]:
        by_item[l["item"]].add(l["category"])
    assert all(len(v) == 1 for v in by_item.values()), "both runs give the same category"
    assert {l["item"]: l["gold"] for l in body[1:]} == {i["id"]: i["gold"]["outcome"] for i in items}


@pytest.mark.parametrize("name,module,line", [("named_target", "ops_natural_writes", "marca dentista quinta às 10h no calendário Fantasma"),
                                              ("_reference", "ops_natural_calendar", "cancela o evento 2"), ("_messages", "ops_natural_mail", "arquiva os emails 2 e 5"),
                                              ("held_files", "ops_natural_files", "salva esse pdf no drive")])
def test_without_its_stub_the_line_would_not_open_a_card_and_with_it_it_does(world, monkeypatch, name, module, line):
    assert run_line(world, line_item(line))["observed"] == "card" and world.resolver_calls[name] >= 1
    monkeypatch.setattr(sys.modules[module], name, world.originals[name])
    assert run_line(world, line_item(line))["observed"] != "card", "the project holds no such calendar, source or file: it asks or says so"


def test_every_resolver_the_arm_stubs_is_reached_by_a_line_of_this_list(world):
    lines = ["marca dentista quinta às 10h no google", "marca dentista quinta às 10h no calendário Fantasma", "cancela o evento 2", "arquiva os emails 2 e 5",
             "move os emails 3 e 4 para a pasta Contas", "manda um e-mail para ana@exemplo.example assunto: oi texto: tudo bem",
             "substitui o texto do arquivo roteiro por: rascunho da lista de convidados", "salva esse pdf no drive"]
    for line in lines:
        run_line(world, line_item(line))
    assert set(world.resolver_calls) == {name for _, name in RESOLVERS} and all(world.resolver_calls[name] >= 1 for _, name in RESOLVERS), dict(world.resolver_calls)


def test_the_store_diff_sees_a_reminder_cancelled_with_no_question(world, monkeypatch):
    got = run_line(world, line_item("forget reminder 3"))
    assert got["observed"] == "executed" and score.categorize({"outcome": "op", "op": "reminder-forget", "slots": {"id": ["3"]}}, [], "full", "executed", got["detail"]) == "wrong_effect_unconfirmed"
    monkeypatch.setitem(globals(), "executed", lambda before, after, answered: False)
    assert run_line(world, line_item("forget reminder 3"))["observed"] != "executed", "with the detector off the cancel is missed"


def test_a_planted_write_that_no_recorder_sees_is_still_executed(world, monkeypatch):
    def plant(project, ctx, said, line_id, channel, answer_to=None, after=None, sender=None, extras=None):
        ctx["store"].reminder_add(ctx["conn"], text="planted", due_local="2027-03-02 07:00", due_utc="2027-03-02T10:00:00.000000Z", zone="America/Sao_Paulo", platform="telegram",
                                  chat=OWNER, created_by="telegram", max_open=100, max_day=100, max_open_chat=100, day_since="2026-01-01T00:00:00.000000Z")
        return "done", None, None, False, None
    monkeypatch.setattr(ops_say, "_say_route", plant)
    assert run_line(world, line_item("write a long report about the launch"))["observed"] == "executed"


def test_a_forwarded_item_is_forwarded_and_changes_nothing(world):
    before = table_rows(world)
    got = run_line(world, line_item("marca dentista quinta às 10h no google", forwarded=True))
    assert got["observed"] == "forwarded" and got["detail"] == {} and table_rows(world) == before and world.rec.events == []
    assert not drafts.count()


def test_a_run_above_the_accepted_share_of_unseeded_items_writes_no_event(world, tmp_path):
    choice = {"v": 1, "items": [{"id": "i1", "kind": "choice", "need": "option", "options": 2, "age_s": 5}], "last": None}
    folder = tmp_path / "events"
    folder.mkdir()
    over = [line_item("the second one", id=f"dev-en-0000{n}", frame=choice) for n in range(3)] + [line_item("approve 4", id=f"dev-en-0001{n}") for n in range(27)]
    with pytest.raises(AssertionError) as why:
        run_whole(world, over, folder, "dev", "c" * 64)          # 3 of 30: 10%
    assert "3 of 30 items are unseeded, over 5%" in str(why.value) and "no event was written" in str(why.value) and "second one" not in str(why.value)
    assert list(folder.iterdir()) == []
    under = over[2:]          # 1 of 28: 3.6%
    path, result, counts = run_whole(world, under, folder, "dev", "c" * 64)
    assert path.is_file() and counts["unseeded"] == 1 and len(list(folder.iterdir())) == 1


def test_a_crash_in_a_run_writes_no_event_either(world, tmp_path, monkeypatch):
    monkeypatch.setattr(ops, "say", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("secret words")))
    folder = tmp_path / "events"
    folder.mkdir()
    page = [line_item("hello there", id=f"dev-en-0000{n}", channel="page") for n in range(3)]
    with pytest.raises(AssertionError) as why:
        run_whole(world, page, folder, "dev", "c" * 64)
    assert "6 runs crashed" in str(why.value) and "secret words" not in str(why.value) and list(folder.iterdir()) == []


def test_a_typed_command_is_none_in_this_arm_as_in_the_other(world):
    got = run_line(world, line_item("/approve 12"))
    assert (got["observed"], got["notes"]) == ("none", ["typed"]) and world.rec.events == []


def test_an_item_with_no_equivalent_state_is_unseeded_and_runs_with_no_open_item(world):
    choice = {"v": 1, "items": [{"id": "i1", "kind": "choice", "need": "option", "options": 2, "age_s": 5}], "last": None}
    got = run_line(world, line_item("the second one", frame=choice))
    assert got["seeded"] is False and got["observed"] == "route"
    plain = run_line(world, line_item("the second one"))
    assert plain["seeded"] is True


def test_the_state_is_the_same_before_every_run(world):
    before = table_rows(world)
    run_line(world, line_item("forget reminder 3"))
    run_line(world, line_item("me lembra amanhã às 9h de regar as plantas"))  # validate: allow english-only -- a fictional Portuguese line or word, the input under test
    reset(world)
    assert table_rows(world) == before and drafts.count() == 0


def test_the_same_scorer_scores_this_arm(world):
    got = run_line(world, line_item("approve 4"))
    assert got["observed"] == "refuse_d" and score.categorize({"outcome": "refuse", "class": "D"}, [], "full", got["observed"], got["detail"]) == "correct"
    assert score.categorize({"outcome": "route"}, [], "full", got["observed"], got["detail"]) == "missed"


UNSEEDED_MAX = 0.05          # the share of items without an equivalent state that the maintainer has accepted; above it the event is not written and he decides


def check_counts(counts, items):
    """Counts only in the messages: no crash, and at most UNSEEDED_MAX of the items unseeded."""
    assert counts["crashed"] == 0, f"{counts['crashed']} runs crashed: no event was written"
    assert counts["unseeded"] / max(1, len(items)) <= UNSEEDED_MAX, \
        f"{counts['unseeded']} of {len(items)} items are unseeded, over {UNSEEDED_MAX:.0%}: no event was written; the maintainer decides"


def run_whole(world, items, folder, split, corpus_sha):
    scored, rows, time_rows, counts = measure_current(world, items)
    print(f"current arm: items {len(items)} unseeded {counts['unseeded']} ({counts['unseeded'] / max(1, len(items)):.1%} of the items) crashed {counts['crashed']}")
    check_counts(counts, items)          # before the event: a run above the accepted share writes nothing
    path = write_event(folder, split, items, scored, corpus_sha)
    th = json.loads((REPO / "evals" / "interpreter" / "thresholds.json").read_text(encoding="utf-8"))
    result = score.summary(rows, th, time_rows=time_rows)
    m = result["measures"]
    print(f"current arm: correct_direct {m['correct_direct']} clarify_rate {m['clarify_rate']}")
    print("counts " + json.dumps({k: v for k, v in m["counts"].items() if v}))
    return path, result, counts


@pytest.mark.skipif(not os.environ.get("WB_FULL_FUZZ"), reason="the whole dev file runs with WB_FULL_FUZZ=1")
def test_the_whole_dev_file_runs_into_tmp_path(world, tmp_path):
    items = load(DEV)
    path, result, counts = run_whole(world, items, tmp_path, "dev", evidence.sha_file(str(DEV)))
    assert lines_module.interpreter_file_problems(str(path), {"runs": 2, "routes": {}, "pins": {}}) == []


@pytest.mark.skipif(not (os.environ.get("WB_IX_CURRENT_CORPUS") and os.environ.get("WB_IX_CURRENT_EVIDENCE")), reason="set WB_IX_CURRENT_CORPUS and WB_IX_CURRENT_EVIDENCE to run a corpus")
def test_current_arm_full_run(world, request):
    corpus, folder = Path(os.environ["WB_IX_CURRENT_CORPUS"]).resolve(), Path(os.environ["WB_IX_CURRENT_EVIDENCE"]).resolve()
    data = corpus.read_bytes()
    items = [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]
    split = {i["split"] for i in items}
    assert len(split) == 1 and not pipeline.item_problems(items[0]) and all(not pipeline.item_problems(i) for i in items), "the corpus is not in the form of the corpus"
    split = split.pop()
    if split == "test":
        basetemp = request.config.option.basetemp
        assert basetemp is not None and str(Path(basetemp).resolve()).startswith(str(corpus.parent) + os.sep), \
            "run pytest with --basetemp inside the corpus file's folder: the stand-in messenger writes the replies to disk"
        declared = json.loads((REPO / "evals" / "interpreter" / "test-split.json").read_text(encoding="utf-8"))["sha256"]
        assert hashlib.sha256(data).hexdigest() == declared, "the corpus is not the test split"
        sha = evidence.sha_file(str(REPO / "evals" / "interpreter" / "test-split.json"))
    else:
        sha = evidence.sha_file(str(corpus))
    run_whole(world, items, folder, split, sha)
