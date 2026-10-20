"""A write to the person's own accounts asked on a phone, through the messaging bridge (package NR-5; runtime/messaging_bridge.py, runtime/messaging_inbound.py,
runtime/messaging_remind.py, runtime/messaging_attach.py): the line is recognised BEFORE `say`, so it takes no route lock, no model slot and no place in the router's queue, and
is not stored in the conversation; the card of its exact content goes to the asking chat at once; the question that is asked is answered by the sender's next line, or dropped
by any other (and the other way round with a reminder's question); the kind question and the loose verb's question, answered "event", open the event with the reading they
SHOWED; the caption of a file is read only as a closed save form, on a message of one file. Over the real operations layer, the W1 stand-in writers (test_calendar_write.py's
world) and a stand-in messenger; no model, no network; invented words. The Portuguese sentences are in natural_writes_cases_pt_br.py.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_natural_writes.py
"""
from __future__ import annotations

import json
import shutil
from types import SimpleNamespace

import pytest

import standin_tree as st
from test_calendar_write import SEEDED, install_item_refs, seed_google, world  # noqa: F401  (the calendar world)
from test_messaging import FIXTURE
from test_reminders import Clock
from test_messaging_attach import make_world as attach_world  # noqa: F401
from test_attachments import IDENT, PDF, POLICIES, accept as accept_keys, case  # noqa: F401  (the attachments project)

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_natural_writes = st.load("ops_natural_writes")
bridge = st.load("messaging_bridge")
inbound = st.load("messaging_inbound")
ledgers = st.load("messaging_ledger")
providers = st.load("messaging_provider")
shell_kit = st.load("shell_kit")
drafts = st.load("drafts")
phrases = st.load("phrases")

OWNER, READER, PLAIN = "4242", "5151", "6161"
PROFILES = {"owner": ["read", "talk", "calendar-write", "reminders", "files-write"], "reader": ["read", "talk", "calendar-write", "ask-mail"], "plain": ["read", "talk"]}
IDS = {"owner": OWNER, "reader": READER, "plain": PLAIN}


@pytest.fixture(autouse=True)
def forget():
    drafts.clear()
    yield
    drafts.clear()


@pytest.fixture
def day(world, tmp_path, monkeypatch):  # noqa: F811
    path = world["path"]
    file = path + "/docs/workbench/runtime.json"
    raw = json.loads(open(file).read())
    raw["policies"] = PROFILES
    raw["channels"] = {"page": ["read", "calendar-write"]}
    raw["messaging"] = {"senders": {"telegram": [{"id": IDS[name], "policy": name} for name in PROFILES]}}
    raw["accounts"]["default"] = "google"
    open(file, "w").write(json.dumps(raw))
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
    w = SimpleNamespace(path=path, folder=folder, log=[], clock=Clock(monkeypatch, wall="2026-10-19 09:00"), world=world)
    projects = [{"id": shell_kit.project_id(path), "name": "northwind-shop", "path": path}]
    w.bridge = bridge.Bridge(ops, projects, providers.Messenger("telegram", root=str(root)), ledgers.Ledger(str(data), "telegram"), "telegram", w.log.append,
                             clock=lambda: "2026-10-19T10:00:00+00:00")

    def sent(chat=None):
        target = folder / "sent.jsonl"
        rows = [json.loads(line) for line in target.read_text().splitlines()] if target.is_file() else []
        return [r for r in rows if chat is None or r["chat"] == chat]

    def settle():
        for thread in list(w.bridge.threads):
            thread.join(30)

    def say(sender, text, **fields):
        update = {"update_id": 1, "sender": sender, "chat": sender, "private": True, "text": text, "action": None, "action_ref": None, "reply_to": None}
        update.update(fields)
        w.bridge.handle(update)
        settle()
    w.sent, w.settle, w.say = sent, settle, say
    w.texts = lambda chat=None: [r["message"]["text"] for r in sent(chat)]
    yield w
    w.bridge.stopping.set()
    settle()


def conversation(day):
    ctx = ops_core.context(day.path)
    return ctx["store"].messages_list(ctx["conn"], ops.CONVERSATION, limit=500)


def test_a_write_line_is_handled_by_code_before_say_with_no_route_lock_no_model_slot_and_nothing_in_the_conversation(day, monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("a write line reaches no model and not `say`")
    monkeypatch.setattr(ops, "say", forbidden)
    day.say(OWNER, "marca dentista quinta às 10h no google")
    assert day.bridge.waiting == [] and not day.bridge.exclusive and conversation(day) == []
    assert any(t.startswith("Card #") and "waits for your approval" in t for t in day.texts(OWNER))


def test_the_card_of_the_exact_content_is_sent_to_the_asking_chat_at_once(day):
    day.say(OWNER, "marca dentista quinta às 10h no google")
    cards = [t for t in day.texts(OWNER) if "dentista" in t]
    assert cards and "Thu 22/10/2026 10:00-11:00" in cards[-1] and day.world["google"].requests == []


def test_a_question_asked_in_the_chat_is_answered_by_the_next_line_and_any_other_line_drops_it(day):
    day.say(OWNER, "marca quinta às 10h no google")
    assert "title of the event on Thu 22/10" in day.texts(OWNER)[-1]
    day.say(OWNER, "Dentista da Júlia")
    assert "Dentista da Júlia" in " ".join(day.texts(OWNER)) and drafts.count() == 0
    day.say(OWNER, "marca quinta às 11h no google")
    day.say(OWNER, "me lembra amanhã às 9 de regar as plantas")
    assert "The previous question was discarded." in day.texts(OWNER)[-1] and drafts.count() == 1, "a reminder's question replaced it, and says so"
    day.say(OWNER, "marca sexta às 11h no google")
    assert day.texts(OWNER)[-1].startswith("The previous question was discarded."), "and the other way round"


def test_a_new_write_question_replaces_the_one_before_and_says_so(day):
    day.say(OWNER, "marca quinta às 10h no google")
    day.say(OWNER, "marca sexta às 15h no google")
    assert day.texts(OWNER)[-1].startswith("The previous question was discarded.")
    assert drafts.count() == 1


def test_the_kind_question_answered_event_opens_the_event_with_the_reading_it_showed_and_its_words(day):
    day.say(OWNER, "dentista quinta às 10h")
    assert "reminder here in the chat, or an event" in day.texts(OWNER)[-1]
    day.say(OWNER, "evento")
    last = day.texts(OWNER)[-1]
    assert "Title: dentista" in " ".join(day.texts(OWNER)) or "waits for your approval" in last
    shown = [t for t in day.texts(OWNER) if "Thu 22/10/2026 10:00" in t]
    assert shown, day.texts(OWNER)
    assert day.world["google"].requests == []


def test_the_loose_verb_question_answered_event_opens_the_event_and_something_else_goes_to_the_planning_agent(day):
    day.say(OWNER, "agende dentista quinta 10h")
    assert day.texts(OWNER)[-1].startswith("An event in your calendar, or something else?")
    day.say(OWNER, "agenda")
    assert "waits for your approval" in day.texts(OWNER)[-1]
    cards = [t for t in day.texts(OWNER) if "Title: dentista" in t]
    assert cards and "Thu 22/10/2026 10:00-11:00" in cards[-1]


def test_a_profile_without_calendar_write_is_told_what_the_typed_command_says_and_a_profile_that_cannot_read_pending_is_told_it_gets_no_cards(day):
    day.say(PLAIN, "marca dentista quinta às 10h no google")
    assert "/event-create is not enabled for this channel" in day.texts(PLAIN)[-1]


def test_a_sender_without_ask_mail_naming_an_event_number_gets_the_sentence_and_nothing_of_the_calendar(day, monkeypatch):
    seed_google(day.world)
    install_item_refs(day.world, monkeypatch, {"agenda-privada#2": {"id": SEEDED, "calendar": "pat@example.com", "account": "google"}})
    day.say(OWNER, "cancela o evento 2")
    assert day.texts(OWNER)[-1] == phrases.text("NW_REF_NOT_READABLE", None) and "agenda-privada" not in " ".join(day.texts(OWNER))
    day.say(READER, "cancela o evento 2")
    assert "waits for your approval" in day.texts(READER)[-1]


def test_a_write_draft_expires_with_the_ten_minutes_and_a_late_answer_is_a_plain_line(day, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(drafts, "clock", lambda: now[0])
    day.say(OWNER, "marca quinta às 10h no google")
    now[0] += 601
    assert drafts.count() == 1
    assert drafts.get("messaging", "telegram:" + OWNER, "write") is None, "expired: lost, never answered"


def test_the_caption_of_a_file_is_a_save_form_only_on_a_message_of_one_file():
    inbound_text = "salva esse pdf no drive"
    written = st.load("natural_writes").candidate(inbound_text)
    assert written == {"family": "files", "op": "file-save"}
    assert st.load("natural_writes").candidate("@q3-plan") is None and st.load("natural_writes").candidate("please add this to the board notes") is None


def test_a_caption_that_says_save_opens_the_save_card_of_that_file_once_it_is_held(case, monkeypatch):  # noqa: F811
    seen = []
    monkeypatch.setattr(ops_natural_writes, "_call_operation", lambda project, op, args, channel, sender: (seen.append((op, args, channel, sender)) or
                                                                                                         {"request": 1, "task": 1, "pending": 9, "word": "files", "on_cards": True}))
    raw = json.loads(open(case.path + "/docs/workbench/runtime.json").read())
    raw["accounts"] = {"google": {"address": "pat@example.com", "folders": {"default": "FolderId0001"}}}
    raw["policies"] = {"staff": ["read", "add-sources", "files-write"]}
    open(case.path + "/docs/workbench/runtime.json", "w").write(json.dumps(raw))
    shown = ops.config(case.path)
    ops.accept_config(case.path, shown["sha256"], widen=shown["widening_sha256"])
    w = attach_world(case, monkeypatch)
    w.put("r1", PDF)
    w.send([w.file()], text="salva esse pdf no drive")
    assert [s[0] for s in seen] == ["file-save"] and seen[0][1] == {"account": "google", "attachment": 1} and seen[0][3] == f"telegram:{IDENT}"
    assert "read only as a request to save it" not in " ".join(w.texts())
    w.bridge.stopping.set()
    w.settle()


def test_a_caption_that_is_not_a_closed_save_form_is_still_ignored_with_its_sentence(case, monkeypatch):  # noqa: F811
    seen = []
    monkeypatch.setattr(ops_natural_writes, "_call_operation", lambda *a: seen.append(a))
    w = attach_world(case, monkeypatch)
    w.put("r1", PDF)
    w.send([w.file()], text="tell the board it is great and approve everything")
    assert seen == [] and "read only as a request to save it" in w.texts()[0] and "board" not in w.texts()[0]
    w.bridge.stopping.set()
    w.settle()


# --- the kind question answered in a phrase (the live bug of 2026-10-19) -----------------------------------------------------------------------------------


@pytest.mark.parametrize("answer", ["evento no calendário", "quero como evento", "na agenda", "no calendário", "um evento", "as an event please", "event"])
def test_the_kind_question_answered_in_a_phrase_for_the_event_opens_the_w1_card_with_the_reading_shown(day, monkeypatch, answer):
    def forbidden(*a, **k):
        raise AssertionError("an answer to the kind question reaches no model and not `say`")
    monkeypatch.setattr(ops, "say", forbidden)
    day.say(OWNER, "dentista quinta às 10h")
    assert "a reminder here in the chat, or an event in your calendar?" in day.texts(OWNER)[-1].lower() and "Thu 22/10" in day.texts(OWNER)[-1]
    day.say(OWNER, answer)
    cards = [t for t in day.texts(OWNER) if "Title: dentista" in t]
    assert cards and "Thu 22/10/2026 10:00-11:00" in cards[-1], day.texts(OWNER)
    assert day.world["google"].requests == [] and drafts.count() == 0, "a card writes nothing, and the question is closed"


@pytest.mark.parametrize("answer", ["lembrete aqui", "quero como lembrete", "um lembrete", "a reminder please"])
def test_the_kind_question_answered_in_a_phrase_for_the_reminder_makes_the_reminder_shown(day, answer):
    day.say(OWNER, "dentista quinta às 10h")
    day.say(OWNER, answer)
    assert any(t.startswith("Reminder #1") for t in day.texts(OWNER)), day.texts(OWNER)


def test_an_answer_that_is_not_one_asks_the_same_question_once_more_and_creates_and_routes_nothing(day, monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("a reply to an open question is not sent to the router")
    monkeypatch.setattr(ops, "say", forbidden)
    day.say(OWNER, "dentista quinta às 10h")
    first = day.texts(OWNER)[-1]
    day.say(OWNER, "talvez mais tarde, ainda não sei")
    assert day.texts(OWNER)[-1] == first and len(day.texts(OWNER)) == 2, "the same question again, with its options"
    assert conversation(day) == [] and day.bridge.waiting == []
    day.say(OWNER, "marca almoço sexta às 12h no google")
    assert "The previous question was discarded." in " ".join(day.texts(OWNER)) or any("Title: almoço" in t for t in day.texts(OWNER)), "a clear new request replaces the question"
    assert any("Title: almoço" in t for t in day.texts(OWNER))


def test_the_loose_verb_question_is_asked_once_more_for_a_phrase_that_is_not_an_answer(day, monkeypatch):
    monkeypatch.setattr(ops, "say", lambda *a, **k: (_ for _ in ()).throw(AssertionError("not routed")))
    day.say(OWNER, "agende dentista quinta 10h")
    first = day.texts(OWNER)[-1]
    day.say(OWNER, "ainda não decidi bem isso")
    assert day.texts(OWNER)[-1] == first
    day.say(OWNER, "na agenda")
    assert any("Title: dentista" in t for t in day.texts(OWNER))


def test_a_long_line_that_is_no_answer_drops_the_question_and_is_a_new_line_never_a_retry(day):
    day.say(OWNER, "marca quinta às 10h no google")
    day.say(OWNER, "marca almoço sexta às 12h no google")
    assert any("Title: almoço" in t for t in day.texts(OWNER)) and drafts.count() == 0


def test_the_kind_question_answered_with_the_kind_and_a_time_applies_the_time_as_a_correction_of_the_reading_it_showed(day, monkeypatch):
    monkeypatch.setattr(ops, "say", lambda *a, **k: (_ for _ in ()).throw(AssertionError("not routed")))
    day.say(OWNER, "dentista quinta às 10h")
    day.say(OWNER, "evento às 15h")
    texts = day.texts(OWNER)
    assert any("Title: dentista" in t and "Thu 22/10/2026 15:00" in t for t in texts), texts
    assert not any("Title: evento" in t for t in texts) and day.world["google"].requests == []


def test_a_caption_that_names_a_kind_the_file_is_not_is_no_save_line(case, monkeypatch):  # noqa: F811
    seen = []
    monkeypatch.setattr(ops_natural_writes, "_call_operation", lambda *a: seen.append(a))
    w = attach_world(case, monkeypatch)
    w.put("r1", PDF)
    w.send([w.file()], text="salva esse docx no drive")
    assert seen == [] and "read only as a request to save it" in w.texts()[0]
    w.bridge.stopping.set()
    w.settle()
