"""The document of a change to the person's own task list, its card, the sentences that say it landed or did not (package CB-5: runtime/tasks_document.py, the card keys and sentences
of runtime/phrases.py, runtime/messaging_outcome.py, runtime/messaging_failure.py, runtime/messaging_cards.py). Pure: no service, no model, every name fictional.

What is held here: a document has exactly its keys and every one is checked, and each planted fault is seen by the check (each case has a vacuity companion: the same document without the
fault passes); the key of a request changes with every part of the content and not with the dry-run hash; the card is a well-formed list of lines whose English text is the stored body,
carries no id and no version, and has exactly one private line, the title of a task the service holds now (which a messaging app draws only for a sender who may read the person's own
items); the title of a card is code's; the outcome of an add may name the title the card showed and the outcome of a completion never does; a failure is said in plain words.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_tasks_document.py
"""
from __future__ import annotations

import copy
import json

import pytest

import phrase_kit as pk
import standin_tree as st

effects = st.load("effects")
messaging_cards = st.load("messaging_cards")
messaging_failure = st.load("messaging_failure")
messaging_outcome = st.load("messaging_outcome")
phrases = st.load("phrases")
tasks_document = st.load("tasks_document")

PT = {"language": "pt-BR"}
SHA = "a" * 64


def add_doc(**over):
    kw = dict(task_id=7, account="google", address="pat@example.com", list_name="tarefas", list_id="default", operation="add", title="comprar café", asker="terminal", dry_run_sha256=SHA)
    kw.update(over)
    return tasks_document.document(**kw)


def done_doc(**over):
    kw = dict(task_id=8, account="microsoft", address="casey.rivera@mail.example", list_name="trabalho", list_id="AAMkADIyAAAAABrJAAA=", operation="complete", title="enviar o relatório",
              remote_id="m1", base_etag='"LTE1001"', read_at="2026-10-27T12:00:00Z", asker="telegram:830461975213", dry_run_sha256=SHA)
    kw.update(over)
    return tasks_document.document(**kw)


def refused(doc) -> bool:
    try:
        tasks_document.check(doc)
    except effects.EffectError as e:
        return e.kind == "usage"
    return False


def mutated(base: dict, **over) -> dict:
    out = copy.deepcopy(base)
    out.update(over)
    out["idempotency_key"] = tasks_document.key_of(out)      # a fault that is not about the key is checked with the key the content derives
    return out


# --- the document ---------------------------------------------------------------------------------------------------------------------------


def test_a_well_formed_add_and_completion_are_documents_and_name_nothing_else():
    add, done = add_doc(), done_doc()
    for doc in (add, done):
        assert set(doc) == set(tasks_document.KEYS) and doc["effect"] == "tasks" and doc["idempotency_key"].startswith("todo-") and tasks_document.check(doc) is doc
    assert add["task_id"] is None and add["base_etag"] is None and add["read_at"] is None
    assert done["task_id"] == "m1" and done["implementation"] == "microsoft-todo" and add["implementation"] == "google-tasks"
    assert not {"due", "notes", "note", "body", "parent", "category", "reminder"} & set(add), "a task is a title: nothing else is a part of the document (OPEN-CB-11)"


FAULTS = (
    ("a key is missing", lambda d: {k: v for k, v in d.items() if k != "title"}),
    ("an extra key", lambda d: dict(d, due="2026-11-01")),
    ("another effect", lambda d: mutated(d, effect="calendar")),
    ("a step task that is not an id", lambda d: mutated(d, task=0)),
    ("an account that is neither", lambda d: mutated(d, account="notion")),
    ("a writer that does not serve the account", lambda d: mutated(d, implementation="outlook-calendar")),
    ("an operation that removes", lambda d: mutated(d, operation="delete")),
    ("an address that is no address", lambda d: mutated(d, address="not-an-address")),
    ("a list name that is not a name", lambda d: mutated(d, list="Minha Lista")),
    ("a list id that starts with a hyphen", lambda d: mutated(d, list_id="-x")),
    ("a title with a hidden character", lambda d: mutated(d, title="comprar \u202ecafé")),
    ("a title with space around it", lambda d: mutated(d, title=" comprar café")),
    ("a title of 201 characters", lambda d: mutated(d, title="x" * 201)),
    ("an empty title", lambda d: mutated(d, title="")),
    ("a title that looks like a credential", lambda d: mutated(d, title="key " + "AKIA" + "ABCDEFGHIJKLMNOP")),
    ("an add that names an earlier task", lambda d: mutated(d, task_id="t1")),
    ("an add with a version", lambda d: mutated(d, base_etag='"LTE1"')),
    ("an asker that is no sender", lambda d: mutated(d, asker="Pat Example")),
    ("a dry-run hash that is not a hash", lambda d: mutated(d, dry_run_sha256="abc")),
    ("a key the content does not derive", lambda d: dict(d, idempotency_key="todo-" + "0" * 32)),
)


@pytest.mark.parametrize("name,fault", FAULTS, ids=[n for n, _ in FAULTS])
def test_each_planted_fault_of_an_add_is_seen_and_the_unplanted_document_passes(name, fault):
    base = add_doc()
    assert not refused(base), "vacuity: the document without the fault is accepted"
    assert refused(fault(base)), name


COMPLETION_FAULTS = (
    ("no task", lambda d: mutated(d, task_id=None)),
    ("no version", lambda d: mutated(d, base_etag=None)),
    ("no reading time", lambda d: mutated(d, read_at=None)),
    ("a reading time that is no time", lambda d: mutated(d, read_at="yesterday")),
    ("a title with a line end", lambda d: mutated(d, title="enviar\no relatório")),
    ("Microsoft's default list by the word", lambda d: mutated(d, list_id="default")),
    ("a task id that starts with a hyphen", lambda d: mutated(d, task_id="-m1")),
)


@pytest.mark.parametrize("name,fault", COMPLETION_FAULTS, ids=[n for n, _ in COMPLETION_FAULTS])
def test_each_planted_fault_of_a_completion_is_seen(name, fault):
    base = done_doc()
    assert not refused(base)
    assert refused(fault(base)), name


def test_a_completion_may_hold_an_empty_title_the_service_gave_and_google_takes_the_word_default():
    assert tasks_document.check(done_doc(title="")) and add_doc(list_id="default")["list_id"] == "default"
    with pytest.raises(effects.EffectError):
        done_doc(account="microsoft", list_id="default")


def test_the_key_of_a_request_follows_every_part_of_the_content_and_not_the_dry_run_hash():
    base = add_doc()
    keys = {tasks_document.key_of(mutated(base, **{part: value})) for part, value in (("title", "comprar leite"), ("list_id", "OutraLista"), ("list", "mercado"), ("task", 9),
                                                                                         ("address", "other@example.com"), ("asker", "page"))}
    assert base["idempotency_key"] not in keys and len(keys) == 6
    assert tasks_document.key_of(dict(base, dry_run_sha256="b" * 64)) == base["idempotency_key"]
    assert tasks_document.key_of(done_doc()) != tasks_document.key_of(done_doc(base_etag='"LTE1002"')), "the version a completion rests on is content"


def test_a_title_the_service_gave_is_cleaned_to_one_line_and_cut():
    assert tasks_document.line_or_blank("a\u202eb\nc   d") == "ab c d" and tasks_document.line_or_blank(None) == "" and len(tasks_document.line_or_blank("x" * 500)) == 200
    assert tasks_document.line_or_blank("café \u200bda manhã") == "café da manhã"  # validate: allow english-only -- a Portuguese line is the input under test


def test_the_writers_flags_are_the_documents_and_the_words_of_the_person_are_never_in_them():
    add, done = add_doc(), done_doc()
    flags = tasks_document.provider_args(add, "/private/spec.json")
    assert flags == ["--account", "pat@example.com", "--list", "default", "--spec-file", "/private/spec.json", "--idempotency-key", add["idempotency_key"]]
    assert "comprar café" not in " ".join(flags) and tasks_document.spec_of(add) == {"title": "comprar café"} and tasks_document.verb_of(add) == "task-insert"
    assert tasks_document.provider_args(done, None) == ["--account", "casey.rivera@mail.example", "--list", "AAMkADIyAAAAABrJAAA=", "--task", "m1", "--base-etag", '"LTE1001"',
                                                         "--idempotency-key", done["idempotency_key"]]
    assert tasks_document.spec_of(done) == {} and tasks_document.verb_of(done) == "task-complete"
    assert tasks_document.get_args(done) == ["--account", "casey.rivera@mail.example", "--list", "AAMkADIyAAAAABrJAAA=", "--task", "m1"]
    assert set(tasks_document.VERBS.values()) == {"task-insert", "task-complete"}, "there is no verb that removes, moves or opens a task again (limit L57)"


# --- the card -------------------------------------------------------------------------------------------------------------------------------


def test_the_cards_are_well_formed_lines_whose_english_text_is_the_body_and_whose_title_is_codes():
    add, done = add_doc(), done_doc()
    for doc in (add, done):
        card = tasks_document.card_lines(doc, SHA)
        assert phrases.card_valid(card) and tasks_document.body(doc, SHA) == phrases.card_text(card)
        text = phrases.card_text(card) + phrases.card_text(card, PT)
        assert doc["idempotency_key"] not in text, "no key on the card (limit L62)"
        assert not doc["task_id"] or doc["task_id"] not in text, "no id on the card (limit L62)"
        assert "LTE1001" not in text
    pk.assert_said(tasks_document.title(add), "TITLE_TODO_ADD")
    pk.assert_said(tasks_document.title(done), "TITLE_TODO_DONE")
    lines = tasks_document.body(add, SHA).splitlines()
    assert len(lines) == 5
    pk.assert_said(lines[0], "CARD_TODO_ADD")
    pk.assert_said(lines[1], "CARD_ACCOUNT", account="google", address="pat@example.com")
    pk.assert_said(lines[2], "CARD_TODO_LIST", list="tarefas", service="Google Tasks")
    pk.assert_said(lines[3], "CARD_TODO_TITLE", title="comprar café")
    pk.assert_said(lines[4], "CARD_TODO_PLAIN")
    lines = tasks_document.body(done, SHA).splitlines()[1:]
    assert len(lines) == 3
    pk.assert_said(lines[0], "CARD_ACCOUNT", account="microsoft", address="casey.rivera@mail.example")
    pk.assert_said(lines[1], "CARD_TODO_LIST", list="trabalho", service="Microsoft To Do")
    pk.assert_said(lines[2], "CARD_TODO_NOW_TITLE", title="enviar o relatório")
    lines = phrases.card_text(tasks_document.card_lines(add, SHA), PT).splitlines()[2:4]
    assert len(lines) == 2
    pk.assert_said(lines[0], "CARD_TODO_LIST", PT, list="tarefas", service="Google Tasks")
    pk.assert_said(lines[1], "CARD_TODO_TITLE", PT, title="comprar café")


def test_only_the_title_of_a_task_the_service_holds_now_is_a_private_line():
    add, done = add_doc(), done_doc()
    private = {key for key in phrases.CARD_PRIVATE if key.startswith("CARD_TODO_")}
    assert private == {"CARD_TODO_NOW_TITLE"}
    assert phrases.card_without_private(tasks_document.card_lines(add, SHA)) == tasks_document.card_lines(add, SHA), "the title the person is adding is their own words"
    shown = phrases.card_without_private(tasks_document.card_lines(done, SHA))
    assert [line[0] for line in shown] == ["CARD_TODO_DONE", "CARD_ACCOUNT", "CARD_TODO_LIST"]
    assert phrases.hidden_note_key(tasks_document.card_lines(done, SHA), shown) == "CARD_HIDDEN_NOTE_TODO"
    assert phrases.hidden_note_key(tasks_document.card_lines(done, SHA), shown) in phrases.TABLE["en"] and phrases.hidden_note_key(tasks_document.card_lines(done, SHA), shown) in phrases.TABLE["pt-BR"]


def test_a_card_whose_title_has_a_hidden_character_is_no_card():
    card = tasks_document.card_lines(add_doc(), SHA)
    card[3] = ["CARD_TODO_TITLE", {"title": "comprar \u202ecafé"}]
    assert phrases.card_valid(card) is False
    assert phrases.card_valid(tasks_document.card_lines(add_doc(), SHA)) is True


def test_the_decision_payload_says_closed_words_and_the_one_line_of_the_ledger_names_no_title():
    add = add_doc()
    assert tasks_document.summary(add) == {"operation": "add", "account": "google", "list": "tarefas"} and "comprar" not in json.dumps(tasks_document.summary(add))
    assert tasks_document.describe(add) == "add a task to the task list 'tarefas' of the google account pat@example.com" and "comprar" not in tasks_document.describe(add)
    done = done_doc()
    assert tasks_document.describe(done).startswith("mark a task as completed in") and "relatório" not in tasks_document.describe(done)
    facts = tasks_document.facts(done, "done", {"task_id": "m1", "etag": '"LTE1002"'})
    assert facts["done"] is True and facts["replayed"] is False and facts["operation"] == "complete" and facts["list"] == "trabalho" and "title" not in facts
    assert tasks_document.facts(add, "replayed", {"task_id": "g9"})["replayed"] is True


# --- what a phone is told ---------------------------------------------------------------------------------------------------------------------


def item_of(doc) -> dict:
    card = tasks_document.card_lines(doc, SHA)
    return {"effect_word": "tasks", "payload": {"card": card}, "body": phrases.card_text(card)}


def test_the_outcome_of_an_add_names_the_title_the_card_showed_and_the_outcome_of_a_completion_never_does():
    got = messaging_outcome.sentence(item_of(add_doc()), tasks_document.facts(add_doc(), "done", {"task_id": "g1"}), PT)
    pk.assert_said(got, "OUT_TODO_ADDED", PT, title="comprar café", service="Google Tasks")
    done = done_doc()
    said = messaging_outcome.sentence(item_of(done), tasks_document.facts(done, "done", {"task_id": "m1"}), PT)
    pk.assert_said(said, "OUT_TODO_DONE", PT, service="Microsoft To Do")
    assert "relatório" not in said
    pk.assert_said(messaging_outcome.sentence(item_of(done), tasks_document.facts(done, "done", {}), None), "OUT_TODO_DONE", None, service="Microsoft To Do")
    pk.assert_said(messaging_outcome.sentence(item_of(add_doc()), tasks_document.facts(add_doc(), "replayed", {}), PT), "OUT_REPLAYED", PT)  # a replay claims nothing was written again
    bare = dict(item_of(add_doc()), payload={"card": [line for line in item_of(add_doc())["payload"]["card"] if line[0] != "CARD_TODO_TITLE"]})
    pk.assert_said(messaging_outcome.sentence(bare, tasks_document.facts(add_doc(), "done", {}), PT), "OUT_TODO_ADDED_BARE", PT, service="Google Tasks")


def test_a_failed_task_change_is_told_in_plain_words_with_the_service_named():
    said = messaging_failure.from_step("tasks-item", "google", "not_configured", "list", None, PT)
    assert pk.said(said, "FAIL_NOT_AUTHORIZED", PT, service="Google Tasks") and "http" not in said
    assert pk.said(messaging_failure.from_step("tasks-item", "microsoft", "provider_failed", "task", None, PT), "FAIL_NETWORK", PT, service="Microsoft To Do")
    unknown = messaging_failure.from_error(Exception("task-insert: the outcome is unknown: look in the list"), PT, word="tasks", account="google")
    pk.assert_said(unknown, "FAIL_UNKNOWN", PT)
    pk.assert_said(pk.which(unknown, PT)[1]["place"], "FAIL_LOOK_TASKS", PT)
    assert pk.said(messaging_failure.from_error(Exception("quota exceeded"), PT, word="tasks", account="google"), "FAIL_QUOTA", PT, service="Google Tasks")


def test_a_completion_card_the_phone_may_not_read_is_cut_and_says_so_while_an_add_card_is_whole(tmp_path):
    for doc, whole in ((add_doc(), True), (done_doc(), False)):
        item = item_of(doc)
        shown = messaging_cards.effect_card_text(item, PT, False, False, False)
        assert (doc["title"] in shown) is whole
        assert (phrases.text("CARD_HIDDEN_NOTE_TODO", PT) in shown) is (not whole)
        assert doc["title"] in messaging_cards.effect_card_text(item, PT, True, False, False), "a reader of the person's own items sees it"


def test_the_flag_that_the_id_was_resolved_from_the_default_list_is_content_and_only_microsoft_has_it():
    plain, flagged = done_doc(), done_doc(default_list=True)
    assert plain["default_list"] is False and flagged["default_list"] is True and tasks_document.check(flagged)
    assert plain["idempotency_key"] != flagged["idempotency_key"], "a change prepared for the default list is another request than one prepared for that id by name"
    for bad in ("yes", 1, None, 0):
        assert refused(mutated(plain, default_list=bad)), bad
    assert refused(mutated(add_doc(), default_list=True)), "Google takes the word default as it is: nothing is resolved, so the flag is never true"
    assert tasks_document.check(add_doc()) and add_doc()["default_list"] is False
    without = {k: v for k, v in plain.items() if k != "default_list"}
    assert refused(without), "a document with no flag is not a document"


def test_a_card_key_names_its_own_group_and_the_cut_follows_the_groups_held():
    done = tasks_document.card_lines(done_doc(), SHA)
    assert phrases.private_group("CARD_TODO_NOW_TITLE") == "tasks-read"
    assert phrases.card_without_private(done, False, {"tasks-read"}) == done, "tasks-read shows the title"
    assert phrases.card_without_private(done, False, {"ask-mail"}) != done, "ask-mail does not"
    assert phrases.card_without_private(done) != done and phrases.card_without_private(done, False, set()) != done
    assert phrases.card_without_private(done, False, {"ask-mail", "tasks-read"}) == done
