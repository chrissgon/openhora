"""A change to the person's own calendar as an external effect (package W1): runtime/step_calendar_event.py, runtime/calendar_document.py,
runtime/effect_calendar.py, runtime/ops_calendar.py, runtime/ops_step_seams.py (`calendar_read`), runtime/ops_step_effects.py, and the two calendar writers
(providers/writer/google-calendar.py and outlook-calendar.py) as the processes the runtime starts. The services are stand-ins on loopback
(providers/writer/tests/fake_gcal_write.py, fake_graph_calendar_write.py): no Google or Microsoft host is ever called, no credential is real, every address is
on a `.example` or `example.com` name. Held here, and the limit each belongs to:

  L55  a write is made only by `approve` with the hash of the exact document: no approval, another hash, an edited effect file or a writer that would send
       another request writes nothing; a calendar the project's `accounts` does not name is refused at the start and again at the approval; the request list of a
       create, a change and a removal is exactly one POST, one PATCH with `If-Match` and one DELETE with `If-Match`, each with `sendUpdates=none`, and no attendee;
  L56  a change or a removal is made only to the event as it was read: another version between the card and the approval is `stale`, nothing is sent, the decision
       is answered and the task starts over from the step that reads;
  L57  Outlook has no removal: the start refuses it, the document refuses it, and the writer has no verb for it;
  L58  the writer is started only by the effect module and the read-only seam: the seam reads one event and asks for a dry run (no credential), nothing else;
  L59  the writer's environment is the minimum plus the one token of the account asked for; no token is in the store, the card or the effect file.

The preparation sends nothing and reads no credential for a create; for a change or a removal it reads the one event. A person's own event with no other
attendee and no recurrence is the only event changed. A lost answer is `unknown` and approving again finds the event by the key.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_calendar_write.py
"""
from __future__ import annotations

import copy
import datetime
import json
import os
import shutil
import sys
import time
import types
from pathlib import Path

import pytest

import standin_tree as st
import test_sources_mail as tsm
from sources_fixture import standin_convert
from test_channel_grants import accept

sys.path.insert(0, str(st.REPO / "providers" / "writer" / "tests"))
import fake_gcal_write as fgw  # noqa: E402  (providers/writer/tests/fake_gcal_write.py: the stand-in for Google Calendar)
import fake_graph_calendar_write as fgc  # noqa: E402  (providers/writer/tests/fake_graph_calendar_write.py: the stand-in for Graph)

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_steps = st.load("ops_steps")
ops_step_effects = st.load("ops_step_effects")
ops_step_seams = st.load("ops_step_seams")
effects = st.load("effects")
effect_calendar = st.load("effect_calendar")
calendar_document = st.load("calendar_document")
step_calendar_event = st.load("step_calendar_event")
steps = st.load("steps")
phrases = st.load("phrases")
operations = st.load("operations")
project_config = st.load("project_config")
cards = st.load("messaging_cards")
sources = st.load("sources")
sources_mail = st.load("sources_mail")
ops_sources = st.load("ops_sources")
item_refs = st.load("item_refs")

ACCOUNTS = {"google": {"address": fgw.ACCOUNT, "calendars": {"personal": fgw.CALENDAR, "side": "side.calendar@example.com"}},
            "microsoft": {"address": fgc.ADDRESS, "calendars": {"personal": "default", "work": fgc.NAMED}}}
START, END = "2026-10-19T13:00:00-03:00", "2026-10-19T14:00:00-03:00"
EVENTS = fgw.EVENTS_PREFIX
GRAPH_EVENTS = "/v1.0/me/calendar/events"
TITLE, NOTES = "Haircut with Joe", "Bring cash"
PIECES = {"location": "Main Street", "reminder_minutes": 30, "notes": NOTES}
SEEDED = "evabc12345"
GRAPH_SEEDED = "AAMkEvent9999="


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(tmp_path / "evidence"))
    built = st.build(tmp_path, monkeypatch, lab)
    tree = built["tree"]
    for rel in ("providers/writer/google-calendar.py", "providers/writer/outlook-calendar.py", "providers/_google.py", "providers/_msgraph.py",
                "providers/_writer_calendar.py", "providers/secrets/resolver.py", "providers/secrets/password_managers.py"):
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(st.REPO / rel, tree / rel)
    state = tmp_path / "writer-state"
    state.mkdir()
    os.chmod(state, 0o700)
    google, graph = fgw.FakeGoogleCalendar(), fgc.FakeGraphCalendar()
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(state))
    monkeypatch.setenv("TZ", "America/Sao_Paulo")
    time.tzset()
    monkeypatch.setenv("GOOGLE_ACCOUNT_TOKEN", google.record_json())
    monkeypatch.setenv("MICROSOFT_ACCOUNT_TOKEN", graph.record_json())
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-reach-a-writer")
    for fake, names in ((google, ("WRITER_CALENDAR_GOOGLE_API_BASE", "WRITER_CALENDAR_GOOGLE_TOKEN_URL")),
                        (graph, ("WRITER_CALENDAR_OUTLOOK_API_BASE", "WRITER_CALENDAR_OUTLOOK_TOKEN_URL"))):
        for name, value in zip(names, (fake.base, fake.token_url)):
            monkeypatch.setenv(name, value)
    path = built["project"] / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["accounts"] = ACCOUNTS
    path.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(ops_core, "ROOT", str(tree))
    resolver = project_config.resolver(str(tree))      # the test variables reach the writer the runtime starts; it runs on this interpreter (no install)
    monkeypatch.setattr(resolver, "ENV_MINIMUM", resolver.ENV_MINIMUM + ("WRITER_CALENDAR_GOOGLE_API_BASE", "WRITER_CALENDAR_GOOGLE_TOKEN_URL",
                                                                         "WRITER_CALENDAR_OUTLOOK_API_BASE", "WRITER_CALENDAR_OUTLOOK_TOKEN_URL"))
    monkeypatch.setattr(resolver, "interpreter_for", lambda script: [sys.executable])
    monkeypatch.setattr(project_config, "resolver", lambda workbench: resolver)      # one resolver module for the seam and the effect
    project = str(built["project"])
    shown = ops.config(project)      # the accounts are a widening: the person types the hash of what `config` lists
    ops.accept_config(project, shown["sha256"], widen=shown["widening_sha256"])
    yield {**built, "path": project, "tmp": tmp_path, "google": google, "graph": graph, "state": state, "resolver": resolver}
    google.close()
    graph.close()
    monkeypatch.undo()
    time.tzset()


def create(world, account="google", title=TITLE, start="2026-10-19T13:00", **more):
    return ops.event_create(world["path"], account, title, start, **more)


def item_of(world, started):
    ctx = ops_core.context(world["path"])
    return ctx["store"].pending_get(ctx["conn"], started["pending"])


def approve(world, started_or_item, channel="terminal"):
    pending = started_or_item["pending"] if "pending" in started_or_item else started_or_item["id"]
    ctx = ops_core.context(world["path"])
    item = ctx["store"].pending_get(ctx["conn"], pending)
    return ops.approve(world["path"], pending, sha256=item["payload_sha256"], channel=channel, sender=("telegram:4242" if channel == "messaging" else None))


def effect_doc(world, started):
    cfg = ops_core.context(world["path"])["cfg"]
    return json.loads((Path(ops_step_effects.effect_dir(cfg, started["task"], 0)) / "effect.json").read_text(encoding="ascii"))


def task_state(world, task):
    ctx = ops_core.context(world["path"])
    return ctx["store"].task_get(ctx["conn"], task)["state"]


def rows(world):
    ctx = ops_core.context(world["path"])
    return ctx["store"].tasks_list(ctx["conn"]), ctx["store"].pending_list(ctx["conn"], "open")


def refused(world, *args, **kw):
    with pytest.raises(ops.OpsError) as why:
        (kw.pop("call", None) or create)(world, *args, **kw)
    return why.value


def calls(fake, token_path="/token"):
    """Every request after the token POSTs: (method, path, query, body)."""
    return [(r["method"], r["path"], r["query"], r["body"]) for r in fake.requests if r["path"] != token_path]


class Snapshots:
    """Real calendar sources behind the real runtime/item_refs.py: the stand-in providers of test_sources_mail.py answer the verbs the runtime sends, a source is
    registered and refreshed with the runtime's own operations, and `<source>#<n>` is resolved through the index of the version they wrote."""

    def __init__(self, world, monkeypatch):
        self.path, self.now, self.providers = world["path"], tsm.NOW, tsm.Providers()
        monkeypatch.setattr(sources, "provider_convert", lambda cfg, call=None: standin_convert)
        monkeypatch.setattr(sources_mail, "CLOCK", lambda: self.now)
        monkeypatch.setattr(sources_mail, "ZONE", tsm.BRT)
        monkeypatch.setattr(ops_step_seams, "SNAPSHOT_CLOCK", lambda: self.now)

        def provider_call(cfg, cls, implementation, verb, args, *, call=None, timeout=sources_mail.PROVIDER_TIMEOUT):
            return tsm.ORIGINAL_CALL(cfg, cls, implementation, verb, args, call=call or self.providers, timeout=timeout)
        monkeypatch.setattr(sources_mail, "provider_call", provider_call)

    def calendar(self, source_id, implementation, calendar, events):
        self.providers.events[(implementation, calendar)] = events
        return ops_sources.source_calendar(self.path, source_id, f"{implementation}:calendar={calendar};past=0;ahead=14")

    def refresh(self, source_id):
        return ops_sources.source_refresh(self.path, source_id)

    def later(self, **delta):
        self.now = self.now + datetime.timedelta(**delta)


def snapshot_event(n, event_id, title="Dentist", day=None, **more):
    """An event as the stand-in provider prints it: the n-th by time (a day each, so that the number the text prints is n)."""
    day = day or 17 + n
    return tsm.event(n, f"2026-10-{day:02d}T09:00:00-03:00", f"2026-10-{day:02d}T10:00:00-03:00", title, id=event_id, **more)


def install_item_refs(world, monkeypatch, mapping):
    """Real snapshots for a table of references: `<source>#<n>` -> {"id", "calendar" (the origin's calendar), "account"}. One source for each source id, whose origin
    is the first entry's account (google or outlook) and calendar; its events are the entries in the order of n."""
    snaps = world.setdefault("snaps", None) or Snapshots(world, monkeypatch)
    world["snaps"] = snaps
    by_source = {}
    for reference, entry in mapping.items():
        source, _, number = reference.partition("#")
        by_source.setdefault(source, {})[int(number)] = entry
    for source, items in by_source.items():
        first = items[min(items)]
        implementation = {"google": "google", "microsoft": "outlook"}[first["account"]]
        top = max(items)
        events = [snapshot_event(n, items[n]["id"] if n in items else f"filler{n:04d}") for n in range(1, top + 1)]
        snaps.calendar(source, implementation, first["calendar"], events)
    return snaps


def seed_google(world, **more):
    return world["google"].add_event(SEEDED, "Dentist", {"dateTime": START}, {"dateTime": END}, **more)


def seed_graph(world, **more):
    return world["graph"].add_event(GRAPH_SEEDED, "Dentist", "2026-10-19T16:00:00", "2026-10-19T17:00:00", **more)


# --- a create: the card, and nothing written ---------------------------------------------------------------------------------------------------------


def test_a_create_prepares_a_card_of_the_whole_event_and_writes_and_reads_nothing(world):
    started = create(world, **PIECES)
    assert set(started) == {"request", "task", "pending", "word", "on_cards"} and started["word"] == "calendar" and started["on_cards"] is True
    assert world["google"].requests == [] and world["graph"].requests == [], "preparing a create opens no connection and reads no credential"
    item = item_of(world, started)
    assert item["kind"] == "effect" and item["title"] == "Calendar: new event" and TITLE not in item["title"]
    assert item["payload"]["step"] == {"kind": "calendar-event", "step": "calendar"} and phrases.card_valid(item["payload"]["card"])
    assert item["body"] == phrases.card_text(item["payload"]["card"])
    lines = item["body"].splitlines()
    assert lines[0] == "Code creates this event after your approval, and nothing else."
    assert lines[1:] == [f"Account: google ({fgw.ACCOUNT})", "Calendar: personal", f"Title: {TITLE}", "When: Mon 19/10/2026 13:00-14:00 (America/Sao_Paulo)",
                         "Where: Main Street", "Calendar reminder: 30 min before", f"Notes: {NOTES}", "No one is invited: no e-mail is sent."]
    doc = effect_doc(world, started)
    assert doc["effect"] == "calendar" and doc["operation"] == "create" and doc["send_updates"] == "none" and doc["implementation"] == "google-calendar"
    assert doc["event"]["start_at"] == START and doc["event"]["end_at"] == END and doc["event_id"] is None and doc["before"] is None
    assert doc["calendar"] == "personal" and doc["calendar_id"] == fgw.CALENDAR and doc["zone"] == "America/Sao_Paulo"
    tasks, pending = rows(world)
    assert {t["id"]: t["title"] for t in tasks}[started["task"]] == "Calendar: new event" and len(pending) == 1


def test_limit_55_a_create_is_one_post_with_send_updates_none_made_only_by_the_approval_of_the_hash(world):
    started = create(world, **PIECES)
    item = item_of(world, started)
    done = approve(world, started)
    assert done["task_state"] == "done" and done["result"]["done"] is True and done["result"]["replayed"] is False and done["result"]["operation"] == "create"
    assert done["result"]["event_id"] == "ev0001" and done["result"]["calendar"] == "personal" and done["result"]["idempotency_key"].startswith("cal-")
    google = world["google"]
    assert [(r["method"], r["path"]) for r in google.requests] == [("POST", "/token"), ("POST", EVENTS)]       # nothing else, not even a read
    [(method, path, query, body)] = calls(google)
    assert (method, path, query) == ("POST", EVENTS, {"sendUpdates": "none", "fields": "id,etag,status"})
    assert body == {"summary": TITLE, "start": {"dateTime": START}, "end": {"dateTime": END}, "location": "Main Street", "description": NOTES,
                    "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 30}]},
                    "extendedProperties": {"private": {"openhora_key": effect_doc(world, started)["idempotency_key"]}}}
    assert "attendees" not in body and google.unexpected() == [] and world["graph"].requests == []
    ctx = ops_core.context(world["path"])
    recorded = ctx["store"].approvals_list(ctx["conn"])
    assert [a["payload_sha256"] for a in recorded] == [item["payload_sha256"]] and all(TITLE not in str(a) for a in recorded), "the record of the approval holds none of the person's words"
    assert google.events["ev0001"]["summary"] == TITLE


def test_limit_55_no_approval_another_hash_an_edited_file_or_a_writer_that_would_send_something_else_writes_nothing(world):
    started = create(world, **PIECES)
    doc = effect_doc(world, started)
    sent = []
    spy = lambda verb, args, implementation=None: sent.append((verb, args)) or {}          # noqa: E731  (a writer that must not be reached)
    for approval in (None, {}, {"scope": "plan", "status": "pending-execution", "payload_sha256": "0" * 64},
                     {"scope": "action", "status": "pending-execution", "payload_sha256": "0" * 64},
                     {"scope": "action", "status": "revoked", "payload_sha256": effect_calendar.sha(effects._text(doc))}):
        with pytest.raises(effects.EffectError) as why:
            effect_calendar.execute(doc, approval, spy, doc["idempotency_key"])
        assert why.value.kind == "deviation"
    good = {"scope": "action", "status": "pending-execution", "payload_sha256": effect_calendar.sha(effects._text(doc))}
    with pytest.raises(effects.EffectError) as other_key:
        effect_calendar.execute(doc, good, spy, "cal-" + "0" * 32)
    assert other_key.value.kind == "deviation" and sent == []
    dry_other = lambda verb, args, implementation=None: {"would_sha256": "f" * 64} if "--dry-run" in args else sent.append(verb)       # noqa: E731
    with pytest.raises(effects.EffectError) as would:
        effect_calendar.execute(doc, good, dry_other, doc["idempotency_key"])
    assert would.value.kind == "deviation" and "previewed" in would.value.reason and sent == []
    # the effect file edited since the preview has another hash: approve reads the document only by the approved hash
    cfg = ops_core.context(world["path"])["cfg"]
    path = Path(ops_step_effects.effect_dir(cfg, started["task"], 0)) / "effect.json"
    path.write_bytes(path.read_bytes().replace(b"Haircut", b"Haircuts"))
    with pytest.raises(ops.OpsError) as edited:
        approve(world, started)
    assert "hash changed" in str(edited.value) and world["google"].requests == [] and task_state(world, started["task"]) == "waiting"
    with pytest.raises(ops.OpsError) as wrong:
        ops.approve(world["path"], started["pending"], sha256="0" * 64, channel="terminal")
    assert "nothing was approved" in str(wrong.value) and world["google"].requests == []


def test_limit_55_a_calendar_or_account_the_accounts_do_not_name_is_refused_before_anything_is_made(world):
    for kw in ({"calendar": "other"}, {"calendar": "Personal"}, {"calendar": "../x"}, {"calendar": 7}):
        error = refused(world, **kw)
        assert error.code in (1, 2), kw
    ctx = ops_core.context(world["path"])
    assert ctx["store"].tasks_list(ctx["conn"]) == [] or {t["state"] for t in ctx["store"].tasks_list(ctx["conn"])} == {"cancelled"}
    path = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["accounts"] = {"google": ACCOUNTS["google"]}
    path.write_text(json.dumps(raw), encoding="utf-8")
    ops.accept_config(world["path"], ops.config(world["path"])["sha256"])
    error = refused(world, account="microsoft")
    assert "not set up for this project" in str(error) and error.code == 3
    assert world["google"].requests == [] and world["graph"].requests == []


def test_limit_55_a_calendar_taken_out_of_the_accounts_after_the_card_is_not_written_to(world):
    started = create(world, calendar="side")
    assert effect_doc(world, started)["calendar_id"] == "side.calendar@example.com"
    path = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["accounts"]["google"]["calendars"] = {"personal": fgw.CALENDAR}
    path.write_text(json.dumps(raw), encoding="utf-8")
    ops.accept_config(world["path"], ops.config(world["path"])["sha256"])
    with pytest.raises(ops.OpsError) as gone:
        approve(world, started)
    assert "side" in str(gone.value) and "nothing was written" in str(gone.value) and world["google"].requests == []
    raw["accounts"]["google"]["calendars"] = {"personal": fgw.CALENDAR, "side": "another.calendar@example.com"}      # the same name, another id
    path.write_text(json.dumps(raw), encoding="utf-8")
    ops.accept_config(world["path"], ops.config(world["path"])["sha256"], widen=ops.config(world["path"])["widening_sha256"])
    with pytest.raises(ops.OpsError) as moved:
        approve(world, started)
    assert "id of the calendar" in str(moved.value) and world["google"].requests == []


def test_a_create_in_the_second_calendar_goes_to_that_calendars_path(world):
    started = create(world, calendar="side")
    with pytest.raises(ops.OpsError):      # the stand-in serves the one calendar `personal`: it answers 405, and what matters here is the path the writer used
        approve(world, started)
    [(method, path, _, _)] = calls(world["google"])
    assert (method, path) == ("POST", "/calendar/v3/calendars/side.calendar%40example.com/events"), "the id is percent-encoded in the path"


@pytest.mark.parametrize("more", [{"title": ""}, {"title": " padded "}, {"title": "x" * 201}, {"title": "two\nlines"}, {"title": "hidden \u202e"},
                                  {"start": "19/10/2026 13:00"}, {"start": "2026-10-19 13:00"}, {"start": "2026-13-19T13:00"}, {"start": "1999-10-19T13:00"},
                                  {"end": "2026-10-19T12:00"}, {"end": "2026-10-19T13:00"}, {"end": "2026-10-19"}, {"end": "2026-12-19T13:00"},
                                  {"location": "x" * 201}, {"reminder_minutes": -1}, {"reminder_minutes": 40321}, {"notes": "x" * 2001},
                                  {"notes": "my key is " + "AKIA" + "ABCDEFGHIJKLMNOP" + " and the secret is wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"}],
                         ids=lambda m: next(iter(m)))
def test_an_argument_that_is_not_in_its_form_is_refused_and_leaves_nothing_behind(world, more):
    error = refused(world, **more)
    assert error.code in (1, 2)
    tasks, pending = rows(world)
    assert pending == [] and {t["state"] for t in tasks} <= {"cancelled"}
    assert world["google"].requests == []


def test_a_title_that_looks_like_a_credential_is_refused_by_the_document_not_written_anywhere(world):
    error = refused(world, title="token " + "ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789")
    assert "credential" in str(error) and world["google"].requests == []


def test_the_words_of_a_title_are_never_mistaken_for_a_key_of_the_request(world):
    started = create(world, title="Planning the attendees list", notes="no attendees here, nobody is invited")
    assert approve(world, started)["task_state"] == "done" and len(world["google"].events) == 1
    step_ok = step_calendar_event._same
    doc = effect_doc(world, started)
    would = {"method": "POST", "path": "/x/events", "query": {"sendUpdates": "none"}, "headers": {}, "body": {"summary": "a", "extendedProperties": {"private": {"k": doc["idempotency_key"]}}}}
    assert step_ok(doc, would) is True
    assert step_ok(doc, {**would, "body": {**would["body"], "attendees": [{"email": "x@example.org"}]}}) is False
    assert step_ok(doc, {**would, "body": {**would["body"], "nested": [{"attendees": []}]}}) is False
    assert step_ok(doc, {**would, "query": {}}) is False and step_ok(doc, {**would, "method": "PATCH"}) is False


def test_an_all_day_event_defaults_to_the_same_day_and_a_timed_event_to_an_hour_and_the_zone_is_the_hosts(world):
    day = create(world, start="2026-10-20")
    doc = effect_doc(world, day)
    assert doc["event"] == {"title": TITLE, "all_day": True, "start": "2026-10-20", "end": "2026-10-20", "start_at": "2026-10-20", "end_at": "2026-10-21",
                            "location": "", "reminder_minutes": None, "notes": ""}
    assert "When: all day Tue 20/10/2026" in item_of(world, day)["body"]
    span = create(world, start="2026-10-20", end="2026-10-22")
    assert "all day Tue 20/10/2026 - Thu 22/10/2026" in item_of(world, span)["body"] and effect_doc(world, span)["event"]["end_at"] == "2026-10-23"
    timed = create(world, start="2026-10-19T23:30")
    assert effect_doc(world, timed)["event"]["end"] == "2026-10-20T00:30" and "Mon 19/10/2026 23:30 - Tue 20/10/2026 00:30 (America/Sao_Paulo)" in item_of(world, timed)["body"]


def test_the_hour_a_clock_change_skips_does_not_exist_and_is_refused(world, monkeypatch):
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    error = refused(world, start="2026-03-08T02:30")
    assert "does not exist" in str(error)
    assert effect_doc(world, create(world, start="2026-11-01T01:30"))["event"]["start_at"] == "2026-11-01T01:30:00-04:00", "the hour that happens twice is its first time"
    ok = create(world, start="2026-03-08T03:30")
    assert effect_doc(world, ok)["event"]["start_at"] == "2026-03-08T03:30:00-04:00"


# --- the card, in two languages -----------------------------------------------------------------------------------------------------------------------


def test_the_card_is_said_line_by_line_in_the_projects_language_with_the_same_hash_and_the_persons_words_unchanged(world):
    started = create(world, **PIECES)
    item = item_of(world, started)
    english = cards.effect_card_text(item, {})
    assert english == item["body"]
    portuguese = cards.effect_card_text(item, {"language": "pt-BR"})
    assert portuguese.splitlines()[0] == "O c\u00f3digo cria este evento depois da sua aprova\u00e7\u00e3o, e nada mais."
    for needle in (f"Conta: google ({fgw.ACCOUNT})", "Agenda: personal", f"T\u00edtulo: {TITLE}", "Quando: Mon 19/10/2026 13:00-14:00 (America/Sao_Paulo)", "Onde: Main Street",
                   "Lembrete da agenda: 30 min antes", f"Notas: {NOTES}", "Ningu\u00e9m \u00e9 convidado: nenhum e-mail \u00e9 enviado."):
        assert needle in portuguese, needle
    caps = {"buttons": True, "max_buttons": 6, "max_text": 4096, "documents": False, "url_buttons": True, "reply_context": True}
    policy = {"messaging": ["read", "approve-effect-calendar"]}
    full = ops.pending(world["path"], started["pending"])
    pt = cards.build("northwind", full, caps, policy, "text", None, operations=operations, effect_command="cmd", cfg={"language": "pt-BR"})
    en = cards.build("northwind", full, caps, policy, "text", None, operations=operations, effect_command="cmd", cfg={})
    assert pt["content_sha256"] == en["content_sha256"] and full["payload_sha256"] in pt["message"]["text"] and "T\u00edtulo: " + TITLE in pt["message"]["text"]
    assert pt["approvable"] is True and pt["whole"] is True


def test_every_line_of_every_card_is_a_phrase_of_both_columns_and_the_english_lines_are_the_stored_body(world):
    seeded = seed_google(world)
    first = create(world, **PIECES)
    approve(world, first)
    made = f"created:{first['pending']}"
    started = [first]
    started.append(ops.event_change(world["path"], "google", made, title="Haircut with Pat", start="2026-10-20T10:00", location="Back Street", notes="", reminder_minutes=10))
    started.append(ops.event_cancel(world["path"], "google", made))
    del seeded
    for each in started:
        item = item_of(world, each)
        card = item["payload"]["card"]
        assert phrases.card_valid(card) and phrases.card_text(card) == item["body"]
        for key, _ in card:
            assert key in phrases.TABLE["en"] and key in phrases.TABLE["pt-BR"], key
        assert phrases.card_text(card, {"language": "pt-BR"}) != item["body"]


# --- a change ----------------------------------------------------------------------------------------------------------------------------------


def made_event(world, **more):
    """An event the runtime created (and the person approved): its reference `created:<decision>`."""
    started = create(world, **{**PIECES, **more})
    approve(world, started)
    world["google"].requests.clear()
    return started


def test_a_change_reads_the_event_and_shows_each_changed_part_as_it_was_and_as_it_will_be(world):
    made = made_event(world)
    started = ops.event_change(world["path"], "google", f"created:{made['pending']}", title="Haircut with Pat", start="2026-10-20T10:00", notes="")
    google = world["google"]
    [(method, path, query, _)] = calls(google)[-1:]
    assert [(m, p) for m, p, _, _ in calls(google)] == [("GET", f"{EVENTS}/ev0001")] and "fields" in query
    assert [r["method"] for r in google.requests] == ["POST", "GET"], "the token, then the one read of the event"
    item = item_of(world, started)
    assert item["title"] == "Calendar: change an event"
    lines = item["body"].splitlines()
    assert lines[0].startswith("Code changes this event after your approval, only if it is still as read at 20")
    assert "Before: Title: Haircut with Joe" in lines and "After: Title: Haircut with Pat" in lines
    assert "Before: When: Mon 19/10/2026 13:00-14:00 (America/Sao_Paulo)" in lines and "After: When: Tue 20/10/2026 10:00-11:00 (America/Sao_Paulo)" in lines
    assert "Before: Notes: Bring cash" in lines and "After: Notes: -" in lines
    assert "Unchanged: Where: Main Street" in lines and "Unchanged: Calendar reminder (min before): 30" in lines
    assert "Event: ev0001" in lines and f"The event now: {TITLE} (Mon 19/10/2026 13:00-14:00 (America/Sao_Paulo))" in lines, "the event as read live, with its id"
    assert lines[-2].startswith("Based on version ") and lines[-1] == "No one is invited: no e-mail is sent."
    doc = effect_doc(world, started)
    assert doc["operation"] == "change" and doc["event_id"] == "ev0001" and doc["changed"] == ["title", "when", "notes"] and doc["base_etag"] == google.events["ev0001"]["etag"]
    assert doc["event"]["end"] == "2026-10-20T11:00", "a start alone moves the event and keeps how long it lasts"


def test_limit_55_a_change_is_one_patch_with_if_match_the_changed_parts_and_send_updates_none(world):
    made = made_event(world)
    started = ops.event_change(world["path"], "google", f"created:{made['pending']}", title="Haircut with Pat")
    doc = effect_doc(world, started)
    google = world["google"]
    google.requests.clear()
    done = approve(world, started)
    assert done["task_state"] == "done" and done["result"]["operation"] == "change" and done["result"]["replayed"] is False
    assert [(r["method"], r["path"]) for r in google.requests] == [("POST", "/token"), ("GET", f"{EVENTS}/ev0001"), ("POST", "/token"), ("PATCH", f"{EVENTS}/ev0001")]
    sent = [(m, p, q, b) for m, p, q, b in calls(google)]
    assert [(m, p) for m, p, _, _ in sent] == [("GET", f"{EVENTS}/ev0001"), ("PATCH", f"{EVENTS}/ev0001")], "the event is read again, then one PATCH"
    assert sent[1][2] == {"sendUpdates": "none", "fields": "id,etag,status"}
    assert sent[1][3] == {"summary": "Haircut with Pat", "extendedProperties": {"private": {"openhora_key": doc["idempotency_key"]}}}
    assert [r for r in google.requests if r["method"] == "PATCH"][0]["if_match"] == doc["base_etag"]
    assert google.events["ev0001"]["summary"] == "Haircut with Pat" and google.unexpected() == []


def test_limit_56_an_event_that_moved_between_the_card_and_the_approval_is_stale_nothing_is_sent_and_the_task_starts_over(world):
    made = made_event(world)
    started = ops.event_change(world["path"], "google", f"created:{made['pending']}", title="Haircut with Pat")
    world["google"].events["ev0001"]["etag"] = world["google"].next_etag()           # somebody moved it
    world["google"].requests.clear()
    with pytest.raises(ops.OpsError) as stale:
        approve(world, started)
    assert "another version" in str(stale.value) and "starts over" in str(stale.value)
    assert [m for m, _, _, _ in calls(world["google"])] == ["GET"], "read again, compared, and nothing written"
    assert world["google"].events["ev0001"]["summary"] == "Haircut with Joe"
    ctx = ops_core.context(world["path"])
    old = ctx["store"].pending_get(ctx["conn"], started["pending"])
    assert old["status"] == "resolved" and old["resolution"] == "answered" and task_state(world, started["task"]) == "ready"
    assert [a["status"] for a in ctx["store"].approvals_list(ctx["conn"])] == ["executed", "revoked"], "the approval of that attempt is revoked when the decision is answered"
    out = ops_steps.run_step(world["path"], started["task"])
    assert out["ok"] is True and out["task_state"] == "waiting"
    [new] = ctx["store"].pending_list(ctx["conn"], "open", started["task"])
    assert new["payload_sha256"] != old["payload_sha256"]
    world["google"].requests.clear()
    assert approve(world, {"pending": new["id"]})["task_state"] == "done" and world["google"].events["ev0001"]["summary"] == "Haircut with Pat"


def test_limit_56_an_event_removed_between_the_card_and_the_approval_is_stale_for_a_change(world):
    made = made_event(world)
    started = ops.event_change(world["path"], "google", f"created:{made['pending']}", title="Haircut with Pat")
    world["google"].removed["ev0001"] = world["google"].events.pop("ev0001")
    with pytest.raises(ops.OpsError) as gone:
        approve(world, started)
    assert "not in the calendar any more" in str(gone.value) and "starts over" in str(gone.value)
    assert not [r for r in world["google"].requests if r["method"] in ("PATCH", "DELETE")]
    assert task_state(world, started["task"]) == "ready"


@pytest.mark.parametrize("more, sentence", [({"attendees": [{"email": "other@example.org", "self": False}, {"email": fgw.ACCOUNT, "self": True}]}, "other attendees"),
                                            ({"recurrence": ["RRULE:FREQ=WEEKLY"]}, "repeats"), ({"recurringEventId": "evseries001"}, "repeats"),
                                            ({"organizer": {"email": "boss@example.org", "self": False}}, "organized by someone else")])
def test_a_meeting_a_series_or_an_event_of_someone_else_is_not_changed_or_removed_and_nothing_is_left_behind(world, monkeypatch, more, sentence):
    seed_google(world, **more)
    install_item_refs(world, monkeypatch, {"calendar#1": {"id": SEEDED, "calendar": fgw.CALENDAR, "account": "google"}})
    for call in (lambda: ops.event_change(world["path"], "google", "calendar#1", title="New"), lambda: ops.event_cancel(world["path"], "google", "calendar#1")):
        with pytest.raises(ops.OpsError) as why:
            call()
        assert sentence in str(why.value) and why.value.code == 1
    tasks, pending = rows(world)
    assert pending == [] and {t["state"] for t in tasks} <= {"cancelled"}
    assert not [r for r in world["google"].requests if r["method"] in ("PATCH", "DELETE")]


def test_an_event_that_is_gone_and_a_change_that_changes_nothing_are_refused(world, monkeypatch):
    seed_google(world)
    install_item_refs(world, monkeypatch, {"calendar#1": {"id": SEEDED, "calendar": fgw.CALENDAR, "account": "google"}, "calendar#2": {"id": "evnone0001", "calendar": fgw.CALENDAR,
                                                                                                                                "account": "google"}})
    with pytest.raises(ops.OpsError) as gone:
        ops.event_change(world["path"], "google", "calendar#2", title="New")
    assert "not on this calendar any more" in str(gone.value)
    with pytest.raises(ops.OpsError) as same:
        ops.event_change(world["path"], "google", "calendar#1", title="Dentist")
    assert "already as asked" in str(same.value)
    with pytest.raises(ops.OpsError) as empty:
        ops.event_change(world["path"], "google", "calendar#1")
    assert empty.value.code in (1, 2) and not [r for r in world["google"].requests if r["method"] in ("PATCH", "DELETE")]


def test_a_reference_that_is_not_in_the_grammar_or_names_nothing_is_refused_with_a_sentence_of_the_table(world, monkeypatch):
    for bad, needle in (("calendar", "not a reference"), ("calendar#0", "start at 1"), ("calendar #1", "not a reference"), ("Calendar#1", "not a reference"),
                        ("created:0", "not a reference"), ("created:x", "not a reference"), ("../x#1", "not a reference"), ("calendar#1; rm", "not a reference"),
                        ("calendar#1", "There is no source calendar"), ("created:9999", "did not create an event")):
        with pytest.raises(ops.OpsError) as why:
            ops.event_change(world["path"], "google", bad, title="New")
        assert why.value.code in (1, 2) and (needle in str(why.value) or "name the event as" in str(why.value)), bad      # the grammar is checked twice: when the task is planned, and by item_refs
    started = create(world)
    with pytest.raises(ops.OpsError) as not_done:
        ops.event_change(world["path"], "google", f"created:{started['pending']}", title="New")      # a card still waiting made no event
    assert "did not create an event" in str(not_done.value)
    install_item_refs(world, monkeypatch, {"calendar#1": {"id": SEEDED, "calendar": "side.calendar@example.com", "account": "google"}})
    with pytest.raises(ops.OpsError) as past:
        ops.event_change(world["path"], "google", "calendar#9", title="New")
    assert "fewer items than that" in str(past.value)
    seed_google(world)
    with pytest.raises(ops.OpsError) as other:      # the source's calendar is the one the project names `side`, and the call is for `personal`
        ops.event_change(world["path"], "google", "calendar#1", title="New", calendar="personal")
    assert "not on the calendar asked for" in str(other.value)


def test_every_refusal_of_item_refs_has_a_sentence_in_both_columns_of_the_table():
    codes = ("malformed", "zero", "not_readable", "past_end", "no_source", "not_snapshot", "wrong_kind", "no_version", "stale", "no_index", "integrity", "created_unknown")
    for code in codes:
        key = "ACCT_REF_" + code.upper()
        assert key in phrases.TABLE["en"] and key in phrases.TABLE["pt-BR"], code
        sentence = ops_step_seams.ref_sentence(code, "agenda#3")
        assert "{" not in sentence and len(sentence) < 300
        if "{source}" in phrases.en(key):
            assert "agenda" in sentence
    assert ops_step_seams.ref_sentence("something_new", "x") == phrases.en("ACCT_REF_NOT_AN_EVENT")


# --- a removal ----------------------------------------------------------------------------------------------------------------------------------


def test_limit_57_a_removal_is_one_delete_with_if_match_and_send_updates_none_the_event_goes_to_the_trash(world):
    made = made_event(world)
    started = ops.event_cancel(world["path"], "google", f"created:{made['pending']}")
    item = item_of(world, started)
    assert item["title"] == "Calendar: remove an event"
    lines = item["body"].splitlines()
    assert lines[0] == ("Code removes this event after your approval. Google is expected to move it to the calendar's trash, where you can restore it for 30 days "
                        "(Google Calendar, Trash); this has not been verified yet.")
    assert f"Removing, title: {TITLE}" in lines and "Event: ev0001" in lines and lines[-1].startswith("Based on version ")
    doc = effect_doc(world, started)
    assert doc["operation"] == "cancel" and doc["event"] is None and doc["changed"] == [] and doc["before"]["title"] == TITLE
    world["google"].requests.clear()
    done = approve(world, started)
    assert done["task_state"] == "done" and done["result"]["operation"] == "cancel"
    assert [(m, p, q, b) for m, p, q, b in calls(world["google"])] == [("GET", f"{EVENTS}/ev0001", calls(world["google"])[0][2], None),
                                                                      ("DELETE", f"{EVENTS}/ev0001", {"sendUpdates": "none"}, None)]
    assert [r for r in world["google"].requests if r["method"] == "DELETE"][0]["if_match"] == doc["base_etag"]
    assert "ev0001" in world["google"].removed and world["google"].events == {} and world["google"].unexpected() == []


def test_limit_57_removing_an_outlook_event_is_refused_at_the_start_in_the_document_and_the_writer_has_no_verb(world, monkeypatch):
    seed_graph(world)
    install_item_refs(world, monkeypatch, {"calendar#1": {"id": GRAPH_SEEDED, "calendar": "default", "account": "microsoft"}})
    with pytest.raises(ops.OpsError) as why:
        ops.event_cancel(world["path"], "microsoft", "calendar#1")
    assert "not available yet" in str(why.value) and world["graph"].requests == []
    doc = {"effect": "calendar", "operation": "cancel", "account": "microsoft", "implementation": "outlook-calendar"}
    with pytest.raises(effects.EffectError) as refused_doc:
        calendar_document.check(doc | {k: None for k in calendar_document.KEYS if k not in doc})
    assert refused_doc.value.kind == "usage"
    cfg = ops_core.context(world["path"])["cfg"]
    assert effect_calendar.preflight(cfg, {**doc, "address": fgc.ADDRESS, "calendar": "personal", "calendar_id": "default"}, str(world["tree"]))[0] == 1
    assert calendar_document.VERBS["microsoft"]["cancel"] == "event-delete"
    writer = (world["tree"] / "providers" / "writer" / "outlook-calendar.py").read_text(encoding="utf-8")
    assert "event-delete" not in writer.split('"""', 2)[2], "the Outlook writer has no verb that removes an event"


# --- Outlook: a create and a change -------------------------------------------------------------------------------------------------------------


def test_an_outlook_create_is_one_post_in_utc_with_no_attendee_and_the_card_says_so(world):
    started = create(world, "microsoft", **PIECES)
    assert world["graph"].requests == [] and item_of(world, started)["body"].splitlines()[1] == f"Account: microsoft ({fgc.ADDRESS})"
    done = approve(world, started)
    assert done["task_state"] == "done" and done["result"]["event_id"] == "AAMkEvent0001="
    [(method, path, query, body)] = [(r["method"], r["path"], r["query"], r["body"]) for r in world["graph"].graph_requests()]
    assert (method, path, query) == ("POST", GRAPH_EVENTS, {})
    assert body["subject"] == TITLE and body["start"] == {"dateTime": "2026-10-19T16:00:00", "timeZone": "UTC"} and "attendees" not in body
    assert body["singleValueExtendedProperties"] == [{"id": fgc.KEY_PROPERTY, "value": effect_doc(world, started)["idempotency_key"]}]
    assert len(world["graph"].token_forms) == 1 and world["google"].requests == [] and world["graph"].unexpected() == []


def test_an_outlook_change_reads_the_event_compares_the_change_key_and_sends_one_patch(world, monkeypatch):
    seed_graph(world)
    install_item_refs(world, monkeypatch, {"calendar#1": {"id": GRAPH_SEEDED, "calendar": "default", "account": "microsoft"}})
    started = ops.event_change(world["path"], "microsoft", "calendar#1", title="Dentist (moved)", start="2026-10-20T09:00")
    doc = effect_doc(world, started)
    assert doc["changed"] == ["title", "when"] and doc["before"]["start_at"] == "2026-10-19T16:00:00Z" and doc["base_etag"] == world["graph"].events[GRAPH_SEEDED]["changeKey"]
    assert "Before: When: Mon 19/10/2026 13:00-14:00 (America/Sao_Paulo)" in item_of(world, started)["body"]
    world["graph"].requests.clear()
    done = approve(world, started)
    assert done["task_state"] == "done" and done["result"]["operation"] == "change"
    sent = [(r["method"], r["path"]) for r in world["graph"].graph_requests()]
    assert sent == [("GET", f"{GRAPH_EVENTS}/{GRAPH_SEEDED}"), ("GET", f"{GRAPH_EVENTS}/{GRAPH_SEEDED}"), ("PATCH", f"{GRAPH_EVENTS}/{GRAPH_SEEDED}")]
    patch = world["graph"].graph_requests()[-1]["body"]
    assert patch["subject"] == "Dentist (moved)" and patch["start"] == {"dateTime": "2026-10-20T12:00:00", "timeZone": "UTC"} and "attendees" not in patch
    assert world["graph"].events[GRAPH_SEEDED]["subject"] == "Dentist (moved)" and world["graph"].unexpected() == []


def test_limit_56_an_outlook_event_whose_change_key_moved_is_stale(world, monkeypatch):
    seed_graph(world)
    install_item_refs(world, monkeypatch, {"calendar#1": {"id": GRAPH_SEEDED, "calendar": "default", "account": "microsoft"}})
    started = ops.event_change(world["path"], "microsoft", "calendar#1", title="Late")
    world["graph"].events[GRAPH_SEEDED]["changeKey"] = world["graph"].next_key()
    world["graph"].requests.clear()
    with pytest.raises(ops.OpsError) as stale:
        approve(world, started)
    assert "another version" in str(stale.value) and not [r for r in world["graph"].graph_requests() if r["method"] == "PATCH"]
    assert world["graph"].events[GRAPH_SEEDED]["subject"] == "Dentist" and task_state(world, started["task"]) == "ready"


def test_an_outlook_meeting_is_not_changed(world, monkeypatch):
    seed_graph(world, attendees=[{"emailAddress": {"address": "other@example.org"}}])
    install_item_refs(world, monkeypatch, {"calendar#1": {"id": GRAPH_SEEDED, "calendar": "default", "account": "microsoft"}})
    with pytest.raises(ops.OpsError) as why:
        ops.event_change(world["path"], "microsoft", "calendar#1", title="Late")
    assert "other attendees" in str(why.value) and not [r for r in world["graph"].graph_requests() if r["method"] == "PATCH"]


# --- the lost answer --------------------------------------------------------------------------------------------------------------------------


def test_a_lost_answer_of_a_create_is_unknown_the_effect_stays_open_and_approving_again_finds_the_event_by_its_key(world):
    started = create(world, **PIECES)
    world["google"].lose_answer_once = True
    with pytest.raises(ops.OpsError) as lost:
        approve(world, started)
    assert "may or may not have landed" in str(lost.value) or "outcome is unknown" in str(lost.value)
    assert task_state(world, started["task"]) == "waiting" and len(world["google"].events) == 1
    ctx = ops_core.context(world["path"])
    assert ctx["store"].pending_get(ctx["conn"], started["pending"])["status"] == "open"
    world["google"].requests.clear()
    done = approve(world, started)
    assert done["task_state"] == "done" and done["result"]["replayed"] is True and done["result"]["event_id"] == "ev0001" and len(world["google"].events) == 1
    assert [m for m, _, _, _ in calls(world["google"])] == ["GET"], "the calendar was looked at by the key, and nothing was sent"


def test_a_lost_answer_of_a_change_goes_on_to_the_writer_which_finds_it_done_and_does_not_call_it_stale(world):
    made = made_event(world)
    started = ops.event_change(world["path"], "google", f"created:{made['pending']}", title="Haircut with Pat")
    world["google"].lose_answer_once = True
    with pytest.raises(ops.OpsError):
        approve(world, started)
    assert world["google"].events["ev0001"]["summary"] == "Haircut with Pat"
    world["google"].requests.clear()
    done = approve(world, started)
    assert done["task_state"] == "done" and done["result"]["replayed"] is True
    assert not [r for r in world["google"].requests if r["method"] == "PATCH"], "the change was not made twice"


def test_a_lost_answer_of_a_removal_is_found_by_the_event_being_gone(world):
    made = made_event(world)
    started = ops.event_cancel(world["path"], "google", f"created:{made['pending']}")
    world["google"].lose_answer_once = True
    with pytest.raises(ops.OpsError):
        approve(world, started)
    assert "ev0001" in world["google"].removed
    world["google"].requests.clear()
    done = approve(world, started)
    assert done["task_state"] == "done" and done["result"]["replayed"] is True
    assert not [r for r in world["google"].requests if r["method"] == "DELETE"]


def test_a_service_that_says_no_leaves_the_effect_open_and_nothing_written(world):
    started = create(world, **PIECES)
    world["google"].refuse_next = (429, "rateLimitExceeded")
    with pytest.raises(ops.OpsError) as busy:
        approve(world, started)
    assert "Retry-After: 30" in str(busy.value) and "nothing was written" in str(busy.value) and world["google"].events == {}
    assert task_state(world, started["task"]) == "waiting"
    assert approve(world, started)["task_state"] == "done" and len(world["google"].events) == 1


# --- the structure: who starts a writer, with what -------------------------------------------------------------------------------------------


def test_limit_58_the_seam_starts_only_an_event_read_and_a_dry_run_and_the_dry_run_carries_no_credential(world, monkeypatch):
    assert ops_step_seams.CALENDAR_READ_VERBS == ("event-get",)
    made = made_event(world)      # the approval of this one writes (that is the effect module's call, not the seam's): it is done before the spy
    seen = []
    real = effect_calendar.provider_call

    def spy(root, implementation, verb, args, secrets=(), timeout=0):
        seen.append((implementation, verb, tuple(secrets), "--dry-run" in args))
        return real(root, implementation, verb, args, secrets, timeout or 60)
    monkeypatch.setattr(effect_calendar, "provider_call", spy)
    ops.event_change(world["path"], "google", f"created:{made['pending']}", title="Haircut with Pat")
    create(world, "microsoft")
    assert ("google-calendar", "event-get", ("GOOGLE_ACCOUNT_TOKEN",), False) in seen
    for implementation, verb, secrets, dry in seen:
        assert (verb == "event-get" and secrets) or (dry and secrets == ()), (implementation, verb, secrets, dry)
    assert {v for _, v, _, d in seen if not d} == {"event-get"} and {v for _, v, _, d in seen if d} == {"event-patch", "event-create"}


def test_limit_59_a_writer_is_started_with_the_minimum_environment_and_the_one_token_of_its_account(world, monkeypatch):
    environments = []
    real = world["resolver"].call

    def spy(cls, verb, args, **kw):
        environments.append((kw["implementation"], dict(kw["env"]), verb, list(args)))
        return real(cls, verb, args, **kw)
    monkeypatch.setattr(world["resolver"], "call", spy)
    approve(world, create(world))
    approve(world, create(world, "microsoft"))
    by = {}
    for implementation, env, verb, args in environments:
        by.setdefault(implementation, []).append((verb, env, args))
    assert set(by) == {"google-calendar", "outlook-calendar"}
    for implementation, token, other in (("google-calendar", "GOOGLE_ACCOUNT_TOKEN", "MICROSOFT_ACCOUNT_TOKEN"), ("outlook-calendar", "MICROSOFT_ACCOUNT_TOKEN", "GOOGLE_ACCOUNT_TOKEN")):
        for verb, env, args in by[implementation]:
            assert other not in env and "UNRELATED_SECRET" not in env and not [k for k in env if k.endswith("_ACCOUNT_TOKEN") and k != token], (implementation, verb)
            assert (token in env) == ("--dry-run" not in args), (implementation, verb, "the token is in the environment of the real call alone")
    for text in ("Bearer", fgw.ACCESS_TOKEN, fgw.REFRESH_TOKEN, fgc.ACCESS_TOKEN, fgc.REFRESH_TOKEN):
        assert text not in json.dumps([e for _, e, _, _ in environments if False])
    for _, _, _, args in environments:
        assert not [a for a in args if a in (TITLE, NOTES)], "the person's words are never on a command line"


def test_limit_59_no_token_is_in_the_store_the_card_the_effect_file_or_the_decision(world):
    started = create(world, **PIECES)
    approve(world, started)
    cfg = ops_core.context(world["path"])["cfg"]
    haystack = [Path(cfg["store_db"]).read_bytes()]
    for folder, _, files in os.walk(cfg["data_dir"]):
        haystack += [Path(folder, f).read_bytes() for f in files]
    blob = b"\n".join(haystack)
    for secret in fgw.SECRETS + fgc.SECRETS + ("fake-refresh-token-1-not-real",):
        assert secret.encode() not in blob, secret


def test_the_kind_is_a_step_kind_that_is_not_unattended_and_the_effect_is_not_a_policy_kind(world):
    kind = steps.kind_of("calendar-event")
    assert kind.unattended is False and kind.footprint({}) == () and kind.order == ("prepare", "calendar") and kind.gates["calendar"].word == "calendar"
    module = effects.module_for("calendar")
    assert module.STEP is True and module.GATE is False and module.POLICY is False and module.PROVIDER_CLASS == "writer:calendar"
    assert module.APPROVAL_GROUP == "approve-effect-calendar" and module.APPROVAL_GROUP in operations.GROUPS
    assert "calendar" in effects.step_only_words() and "calendar" not in effects.policy_kinds()
    assert effect_calendar.is_long({}) is True and effect_calendar.on_cards({}) is True


def test_a_writer_that_does_not_serve_the_class_or_is_not_a_calendar_writer_is_never_started(world):
    tree = world["tree"]
    assert effect_calendar.serves(str(tree), "google-calendar") is None and effect_calendar.serves(str(tree), "outlook-calendar") is None
    assert "not a calendar writer" in effect_calendar.serves(str(tree), "gmail")
    (tree / "providers" / "writer" / "google-calendar.py").write_text("SERVES = \"writer:mailbox\"\n", encoding="utf-8")
    assert "does not declare that it serves writer:calendar" in effect_calendar.serves(str(tree), "google-calendar")
    started = create(world)
    with pytest.raises(ops.OpsError) as why:
        approve(world, started)
    assert "writer:calendar" in str(why.value) and world["google"].requests == []


def test_the_effect_module_calls_the_writer_with_an_implementation_always_never_auto(world):
    call = effect_calendar.caller(ops_core.context(world["path"])["cfg"], str(world["tree"]))
    with pytest.raises(effects.EffectError):
        call("event-get", ["--calendar", fgw.CALENDAR, "--event", SEEDED], implementation=None)
    with pytest.raises(effects.EffectError):
        call("event-get", ["--calendar", fgw.CALENDAR, "--event", SEEDED], implementation="smtp")
    assert world["google"].requests == []


def test_the_approval_row_holds_none_of_the_persons_words(world):
    started = create(world, **PIECES)
    doc = effect_doc(world, started)
    assert calendar_document.describe(doc) == f"create an event in the calendar 'personal' of the google account {fgw.ACCOUNT}"
    approve(world, started)
    state = (Path(world["path"]) / "docs" / "workbench" / "state.md").read_text(encoding="utf-8")
    assert "create an event in the calendar" in state and TITLE not in state and NOTES not in state


# --- the pure half --------------------------------------------------------------------------------------------------------------------------------


def test_the_key_is_derived_from_everything_the_person_approves_and_the_dry_run_hash_is_not_part_of_it(world):
    base = dict(task_id=7, account="google", address=fgw.ACCOUNT, calendar="personal", calendar_id=fgw.CALENDAR, operation="create", zone="America/Sao_Paulo",
                event=calendar_document.event_of(TITLE, "", None, "", calendar_document.times("2026-10-19T13:00", None)), dry_run_sha256="a" * 64)
    first = calendar_document.document(**base)
    assert first["idempotency_key"] == calendar_document.document(**{**base, "dry_run_sha256": "b" * 64})["idempotency_key"]
    other_title = calendar_document.document(**{**base, "event": calendar_document.event_of("Other", "", None, "", calendar_document.times("2026-10-19T13:00", None))})
    other_time = calendar_document.document(**{**base, "event": calendar_document.event_of(TITLE, "", None, "", calendar_document.times("2026-10-19T14:00", None))})
    assert len({first["idempotency_key"], other_title["idempotency_key"], other_time["idempotency_key"],
                calendar_document.document(**{**base, "task_id": 8})["idempotency_key"], calendar_document.document(**{**base, "calendar": "side"})["idempotency_key"]}) == 5
    tampered = copy.deepcopy(first)
    tampered["event"]["title"] = "Tampered"
    with pytest.raises(effects.EffectError):
        calendar_document.check(tampered)
    for key in ("send_updates",):
        bad = copy.deepcopy(first)
        bad[key] = "all"
        with pytest.raises(effects.EffectError):
            calendar_document.check(bad)


def test_times_follow_the_forms_and_the_defaults_and_a_change_keeps_what_it_is_not_given():
    times = calendar_document.times
    assert times("2026-10-19T13:00", None)["end"] == "2026-10-19T14:00" and times("2026-10-19", None) | {} == times("2026-10-19", "2026-10-19")
    current = times("2026-10-19T13:00", "2026-10-19T15:30")
    assert times("2026-10-20T09:00", None, current)["end"] == "2026-10-20T11:30", "a start alone moves the event"
    assert times(None, "2026-10-19T16:00", current)["start"] == "2026-10-19T13:00", "an end alone keeps the start"
    assert times(None, None, current) == {k: current[k] for k in ("all_day", "start", "end", "start_at", "end_at")}
    day = times("2026-10-19", "2026-10-21")
    assert times("2026-10-25", None, day)["end"] == "2026-10-27"
    for bad in (("2026-10-19", "2026-10-18T10:00"), ("2026-10-19T10:00", "2026-10-19"), ("2026-10-19T10:00", "2026-10-19T10:00"), (None, None),
                ("2026-10-19", "2026-12-30"), ("2026-10-19T10:00", "2026-11-30T10:00"), ("2026-02-30", None), ("2026-10-19T25:00", None)):
        with pytest.raises(effects.EffectError):
            times(*bad)
    with pytest.raises(effects.EffectError):
        times(None, "2026-10-19", current)      # an end that is a day for a timed event


# --- the reference fails closed (review of #479, M1) -------------------------------------------------------------------------------------------------


def nothing_left(world):
    tasks, pending = rows(world)
    assert pending == [] and {t["state"] for t in tasks} <= {"cancelled"}


def test_limit_55_an_event_the_index_puts_on_a_calendar_the_project_does_not_list_is_never_changed(world, monkeypatch):
    install_item_refs(world, monkeypatch, {"cal#1": {"id": GRAPH_SEEDED, "calendar": "AAMkUnlistedCalendar=", "account": "microsoft"}})
    seed_graph(world)
    for call in (lambda: ops.event_change(world["path"], "microsoft", "cal#1", title="Hijacked"),
                 lambda: ops.event_change(world["path"], "microsoft", "cal#1", title="Hijacked", calendar="personal")):
        with pytest.raises(ops.OpsError) as why:
            call()
        assert "do not list" in str(why.value) or "not on the calendar asked for" in str(why.value)
    assert world["graph"].events[GRAPH_SEEDED]["subject"] == "Dentist" and not [r for r in world["graph"].graph_requests() if r["method"] != "GET"]
    nothing_left(world)


def test_limit_55_an_event_of_a_snapshot_of_another_account_than_the_call_is_refused(world, monkeypatch):
    seed_google(world)
    install_item_refs(world, monkeypatch, {"outl#1": {"id": SEEDED, "calendar": "default", "account": "microsoft"}})
    with pytest.raises(ops.OpsError) as why:
        ops.event_change(world["path"], "google", "outl#1", title="X")
    assert "not on the account asked for" in str(why.value)
    assert world["google"].requests == [] and world["graph"].requests == []
    nothing_left(world)


def test_limit_55_a_snapshot_whose_origin_names_the_calendar_by_another_id_than_the_projects_is_refused_exactly(world, monkeypatch):
    seed_google(world)
    install_item_refs(world, monkeypatch, {"prim#1": {"id": SEEDED, "calendar": "primary", "account": "google"},
                                           "upper#1": {"id": SEEDED, "calendar": fgw.CALENDAR.upper(), "account": "google"}})
    for reference in ("prim#1", "upper#1"):
        with pytest.raises(ops.OpsError):
            ops.event_change(world["path"], "google", reference, title="X")
    assert world["google"].requests == []
    install_item_refs(world, monkeypatch, {"good#1": {"id": SEEDED, "calendar": fgw.CALENDAR, "account": "google"}})
    assert ops.event_change(world["path"], "google", "good#1", title="X")["pending"]


def test_an_event_created_on_a_second_calendar_is_changed_and_removed_on_that_calendar_without_naming_it(world):
    started = create(world, account="microsoft", calendar="work")
    approve(world, started)
    assert effect_doc(world, started)["calendar_id"] == fgc.NAMED
    world["graph"].requests.clear()
    changed = ops.event_change(world["path"], "microsoft", f"created:{started['pending']}", title="New")
    assert effect_doc(world, changed)["calendar"] == "work" and effect_doc(world, changed)["calendar_id"] == fgc.NAMED
    assert [r["path"] for r in world["graph"].graph_requests()] == [f"/v1.0/me/calendars/{fgc.NAMED}/events/AAMkEvent0001="]
    with pytest.raises(ops.OpsError) as other:       # naming another calendar than the one the event is on is refused, not guessed
        ops.event_change(world["path"], "microsoft", f"created:{started['pending']}", title="New", calendar="personal")
    assert "not on the calendar asked for" in str(other.value)
    google = create(world, calendar="side")
    with pytest.raises(ops.OpsError):       # the stand-in serves one calendar: this only proves the second calendar is the one asked
        approve(world, google)


def test_a_created_reference_to_a_calendar_the_project_no_longer_lists_is_refused(world):
    started = create(world, calendar="side")
    world["google"].events.clear()
    ctx = ops_core.context(world["path"])
    ctx["store"].pending_get(ctx["conn"], started["pending"])
    path = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    made = create(world)
    approve(world, made)
    raw["accounts"]["google"]["calendars"] = {"other": "other.calendar@example.com"}
    path.write_text(json.dumps(raw), encoding="utf-8")
    ops.accept_config(world["path"], ops.config(world["path"])["sha256"], widen=ops.config(world["path"])["widening_sha256"])
    with pytest.raises(ops.OpsError) as why:
        ops.event_change(world["path"], "google", f"created:{made['pending']}", title="X")
    assert "do not list" in str(why.value)


def test_a_reminder_is_not_changed_on_an_event_with_several_reminders(world, monkeypatch):
    seed_google(world, reminders={"useDefault": False, "overrides": [{"method": "popup", "minutes": 15}, {"method": "email", "minutes": 60}]})
    install_item_refs(world, monkeypatch, {"cal#1": {"id": SEEDED, "calendar": fgw.CALENDAR, "account": "google"}})
    with pytest.raises(ops.OpsError) as why:
        ops.event_change(world["path"], "google", "cal#1", reminder_minutes=5)
    assert "several reminders" in str(why.value)
    started = ops.event_change(world["path"], "google", "cal#1", title="Renamed")      # another part of the same event is changed as usual
    assert effect_doc(world, started)["changed"] == ["title"]


def test_a_503_on_a_write_is_unknown_for_the_runtime_too(world):
    started = create(world)
    world["google"].refuse_next = (503, "backendError")
    with pytest.raises(ops.OpsError) as why:
        approve(world, started)
    assert "outcome is unknown" in str(why.value) or "may or may not have landed" in str(why.value)
    assert task_state(world, started["task"]) == "waiting"
