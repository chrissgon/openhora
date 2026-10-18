"""The start of a write to the person's own accounts (package FND; runtime/account_start.py), over a stand-in step kind and a stand-in effect kind: one request,
one step task, a preparation that runs in this process with no model, and a card that waits for the approval of the hash of the exact document. What is held
here: nothing is written by the start (the stand-in effect's `execute` is never reached except through `approve`, with the hash of the exact document, and
by structure); a group refused makes nothing; an account the configuration does not list makes nothing; the title of the card is code's; a preparation that
fails says the step's own sentence; the MCP mode never starts one. No account is ever called: the kinds here are stand-ins, every name is fictional and every
address is on `.example`. Offline, no model.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_account_start.py
"""
from __future__ import annotations

import ast
import hashlib
import json
import sys
import types
from pathlib import Path

import pytest

import standin_tree as st
from test_channel_grants import accept

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
effects = st.load("effects")
steps = st.load("steps")
phrases = st.load("phrases")
operations = st.load("operations")
account_start = st.load("account_start")

KIND = "account-test-event"
OTHER_KIND = "account-test-wrong-word"
NO_GATE_KIND = "account-test-no-gate"
STUB = "account_stub_effect"
OPERATION = "account-test-write"
GROUP = "calendar-write"      # the group of the effect word `calendar`: the operation of these tests is put in it, as W1 will
TITLE_KEY = "TITLE_TEST_EVENT"
ACCOUNTS = {"google": {"address": "Ana@Mail.example", "calendars": {"personal": "primary"}, "folders": {"default": "Folder_ID_01"}}}
TITLE = "Calendar: new event"
HIDDEN = "Dentist \u202e"      # a right-to-left override: a line that would not say what it does
ARGS = {"account": "google", "title": "Dentist at 14:00, bring the x-rays", "start": "2026-10-20T14:00"}
SENDER = "telegram:4242"
CALLS = []       # what the stand-in effect's execute was asked: it is the only thing in this file that "writes"


def _check(args):
    if not isinstance(args, dict) or set(args) - {"account", "title", "start", "fail", "mode"}:
        raise steps.StepFailure("bad_args", "args")
    if not isinstance(args.get("title"), str) or not args["title"].strip():
        raise steps.StepFailure("bad_args", "title", "", "give a title")
    return dict(args)


def _prepare(ctx, state):
    if ctx.args.get("fail"):
        raise steps.StepFailure("not_configured", "calendar", "", "run the authorize command of the account")
    doc = {"effect": "mailbox" if ctx.args.get("mode") == "other-word" else "calendar", "task": ctx.task_id, "account": ctx.args["account"], "title": ctx.args["title"], "start": ctx.args.get("start", "")}
    return {"effect_sha256": ctx.services["effect_files"].write(ctx.task_id, int(state.get("cycle", 0)), doc)}


def _open(ctx, state):
    """The gate of the stand-in kind. `mode` makes it misbehave the way a kind could: echo the person's words into the title, put a hidden character in a field,
    say a body that is not its lines, carry no card, or hold the document of another effect word."""
    recorded = state["steps"]["prepare"]["result"]["effect_sha256"]
    doc = ctx.services["effect_files"].read(ctx.task_id, int(state.get("cycle", 0)), recorded)
    mode = ctx.args.get("mode")
    lines = [["CARD_ACCOUNT", {"account": HIDDEN if mode == "hidden" else doc["account"], "address": "ana@mail.example"}]]
    out = {"title": ctx.args["title"] if mode == "echo-title" else TITLE, "body": phrases.card_text(lines), "payload_sha256": recorded, "payload": {"card": lines}}
    if mode == "body-mismatch":
        out["body"] = "Account: google (somebody@mail.example)"
    if mode == "no-card":
        out["payload"] = {}
    return out


def _kind(name, word):
    return steps.Kind(name=name, order=("prepare", "gate"), executors={"prepare": _prepare}, check=_check, footprint=lambda args: (),
                      gates={"gate": steps.Gate(word=word, open=_open, redo="prepare")})


for _name, _word in ((KIND, "calendar"), (OTHER_KIND, "write")):
    if _name not in steps.REGISTRY:
        steps.register(_kind(_name, _word))
if NO_GATE_KIND not in steps.REGISTRY:
    steps.register(steps.Kind(name=NO_GATE_KIND, order=("only",), executors={"only": lambda c, s: {}}, check=_check, footprint=lambda args: ()))


def _stub_module():
    """The stand-in effect kind of the word `calendar`: a STEP kind that records what it is asked to execute, and refuses an approval of another hash."""
    module = types.ModuleType(STUB)
    module.STEP, module.GATE, module.POLICY, module.PROVIDER_CLASS = True, False, False, "writer:calendar"
    module.APPROVAL_GROUP, module.NOTHING_DONE, module.FORGETS_KEYS = "approve-effect-calendar", "nothing was written", False
    module.check = lambda doc: doc
    module.describe = lambda doc: f"create the event {doc['title'][:40]}"
    module.preflight = lambda cfg, doc, root: None
    module.caller = lambda cfg, root: None
    module.idempotency_key = lambda doc, default: default
    module.on_cards = lambda doc: True

    def execute(doc, approval, call, key, work_dir=None, project=None):
        if approval.get("payload_sha256") != hashlib.sha256(effects._text(doc)).hexdigest():
            raise effects.EffectError("deviation", "there is no approval of this exact content")
        CALLS.append(doc["title"])
        return {"written": True}
    module.execute = execute
    return module


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(tmp_path / "evidence"))
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    CALLS.clear()
    monkeypatch.setitem(sys.modules, STUB, _stub_module())
    monkeypatch.setitem(effects.KINDS, "calendar", STUB)
    row = {"name": OPERATION, "call": "account_test_write", "args": (), "channels": ("terminal", "page", "messaging"), "model": False,
           "channel_arg": True, "help": "a stand-in operation of the tests of account_start"}
    monkeypatch.setattr(operations, "OPERATIONS", operations.OPERATIONS + (row,))
    monkeypatch.setitem(operations.GROUPS, GROUP, {"operations": (OPERATION,), "kind": None})
    monkeypatch.setitem(operations.GROUP_TEXT, GROUP, "prepares a stand-in change; each one waits for approval of its card")
    monkeypatch.setitem(phrases.TABLE["en"], TITLE_KEY, TITLE)
    monkeypatch.setitem(phrases.TABLE["pt-BR"], TITLE_KEY, "Agenda: novo evento")
    path = built["project"] / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["accounts"] = ACCOUNTS
    path.write_text(json.dumps(raw), encoding="utf-8")
    project = str(built["project"])
    shown = ops.config(project)      # the accounts are a widening: the person types the hash of what `config` lists
    ops.accept_config(project, shown["sha256"], widen=shown["widening_sha256"])
    return {**built, "path": project, "tmp": tmp_path}


def start(world, args=None, kind=KIND, key=OPERATION, title_key=TITLE_KEY, account="google", **more):
    return account_start.start(world["path"], kind, ARGS if args is None else args, key_words=key, title_key=title_key, account=account, **more)


def store_rows(world):
    ctx = ops_core.context(world["path"])
    return ctx["store"].tasks_list(ctx["conn"]), ctx["store"].pending_list(ctx["conn"], "open")


def refused(world, **kw):
    with pytest.raises(ops.OpsError) as why:
        start(world, **kw)
    return why.value


def made_nothing(world):
    tasks, pending = store_rows(world)
    assert tasks == [] and pending == []


def left_nothing(world):
    """A start that was refused after its task was made leaves no planned or ready row and no open decision: everything it made is cancelled."""
    tasks, pending = store_rows(world)
    assert pending == [] and tasks and {t["state"] for t in tasks} == {"cancelled"}, [(t["id"], t["state"]) for t in tasks]


# --- the start ---------------------------------------------------------------------------------------------------------------------------------


def test_the_start_makes_one_request_and_one_step_task_runs_the_preparation_and_stops_at_the_card(world):
    started = start(world)
    assert set(started) == {"request", "task", "pending", "word", "on_cards"} and started["word"] == "calendar" and started["on_cards"] is True
    tasks, pending = store_rows(world)
    assert len(tasks) == 2 and {t["id"] for t in tasks} == {started["request"], started["task"]}
    task = next(t for t in tasks if t["id"] == started["task"])
    assert task["state"] == "waiting" and task["step_kind"] == KIND and task["parent_id"] == started["request"]
    [item] = pending
    assert item["id"] == started["pending"] and item["kind"] == "effect" and item["task_id"] == started["task"]
    assert item["payload"]["card"] == [["CARD_ACCOUNT", {"account": "google", "address": "ana@mail.example"}]] and phrases.card_valid(item["payload"]["card"])
    assert item["body"] == phrases.card_text(item["payload"]["card"]), "the stored body is the English lines"
    assert CALLS == [], "the start writes nothing"


def test_the_hash_of_the_card_is_the_hash_of_the_effect_document_and_the_effect_is_read_by_it(world):
    started = start(world)
    ctx = ops_core.context(world["path"])
    item = ctx["store"].pending_get(ctx["conn"], started["pending"])
    path = Path(ops.ops_step_effects.effect_dir(ctx["cfg"], started["task"], 0)) / effects.EFFECT_FILE
    assert hashlib.sha256(path.read_bytes()).hexdigest() == item["payload_sha256"]
    doc = effects.read_document(str(path), item["payload_sha256"])
    assert doc["effect"] == "calendar" and doc["task"] == started["task"] and doc["account"] == "google"
    full = ops.pending(world["path"], started["pending"])
    assert full["effect_word"] == "calendar" and full["effect_on_cards"] is True


def test_the_title_is_the_codes_and_the_persons_words_are_in_no_title_of_the_request_or_the_task(world):
    started = start(world)
    ctx = ops_core.context(world["path"])
    rows = {t["id"]: t for t in ctx["store"].tasks_list(ctx["conn"])}
    assert rows[started["task"]]["title"] == TITLE and rows[started["task"]]["key"] == OPERATION
    for row in rows.values():
        assert "Dentist" not in row["title"] and "Dentist" not in (row.get("text") or "")
    item = ctx["store"].pending_get(ctx["conn"], started["pending"])
    assert item["title"] == TITLE and "Dentist" not in item["title"]


@pytest.mark.parametrize("title_key", ["Dentist at 14:00, bring the x-rays", "TITLE_NOT_IN_THE_TABLE", "title_test_event", "STALE", "", None, 5, "TITLE_" + "X" * 60, "HEADER"])
def test_a_title_that_is_not_a_fixed_phrase_of_the_family_title_is_refused_and_nothing_is_made(world, title_key):
    error = refused(world, title_key=title_key)
    assert error.code == 2 and "title" in str(error)
    made_nothing(world)


def test_a_title_phrase_with_a_field_is_refused(world, monkeypatch):
    monkeypatch.setitem(phrases.TABLE["en"], "TITLE_TEST_FIELD", "Calendar: {title}")
    monkeypatch.setitem(phrases.TABLE["pt-BR"], "TITLE_TEST_FIELD", "Agenda: {title}")
    assert refused(world, title_key="TITLE_TEST_FIELD").code == 2
    made_nothing(world)


def test_the_title_is_a_phrase_of_the_table_so_a_portuguese_phone_reads_it_in_portuguese(world):
    started = start(world)
    ctx = ops_core.context(world["path"])
    item = ctx["store"].pending_get(ctx["conn"], started["pending"])
    assert item["title"] == TITLE, "stored in English, like every title"
    assert phrases.heading(item["title"], {"language": "pt-BR"}) == "Agenda: novo evento" and phrases.heading(item["title"], None) == TITLE


@pytest.mark.parametrize("key", ["Event Create", "event_create", "", "event--create", "x" * 60, "event create"])
def test_a_key_that_is_not_the_operations_name_is_refused_and_nothing_is_made(world, key):
    assert refused(world, key=key).code == 2
    made_nothing(world)


# --- the policy -----------------------------------------------------------------------------------------------------------------------------------


def test_a_messaging_app_needs_the_sender_the_group_and_nothing_is_made_without_them(world):
    assert "not enabled" in str(refused(world, channel="messaging", sender=SENDER)), "the default policy of a messaging app does not list the group"
    made_nothing(world)
    assert "names the sender" in str(refused(world, channel="messaging")), "a messaging call that names no sender is refused"
    made_nothing(world)
    accept(world["path"], {"messaging": ["read", GROUP]})
    started = start(world, channel="messaging", sender=SENDER)
    assert started["pending"] and CALLS == []


def test_the_mcp_mode_never_starts_one_whatever_its_policy(world):
    error = refused(world, channel="mcp")
    assert error.code == 1 and "connected AI client" in str(error)
    made_nothing(world)
    assert refused(world, channel="mcp", sender=SENDER).code == 1
    assert refused(world, channel="chat").code == 1, "any channel the policy does not know is refused, not trusted"
    assert refused(world, channel="invented").code == 1
    made_nothing(world)


def test_the_page_is_asked_the_policy_too(world):
    accept(world["path"], {"page": ["read"]})
    assert "not enabled" in str(refused(world, channel="page"))
    made_nothing(world)
    accept(world["path"], {"page": ["read", GROUP]})
    assert start(world, channel="page")["pending"]


def test_the_terminal_and_a_call_with_no_channel_are_never_narrowed(world):
    assert start(world, channel="terminal")["pending"]
    assert start(world, args={**ARGS, "title": "Another"})["pending"]
    assert len(store_rows(world)[1]) == 2


# --- the account ---------------------------------------------------------------------------------------------------------------------------------


def test_limit_55_an_account_the_configuration_does_not_list_makes_nothing(world):
    error = refused(world, args={**ARGS, "account": "microsoft"}, account="microsoft")
    assert error.code == 3 and str(error) == phrases.en("ACCT_NOT_CONFIGURED").format(account="microsoft")
    made_nothing(world)
    assert refused(world, account="aws", args={**ARGS, "account": "aws"}).code == 3
    assert refused(world, account=None).code == 3
    made_nothing(world)


def test_a_project_with_no_accounts_key_writes_to_no_account(world):
    path = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.pop("accounts")
    path.write_text(json.dumps(raw), encoding="utf-8")
    ops.accept_config(world["path"], ops.project_config.load(world["path"])["sha256"])
    assert refused(world).code == 3
    made_nothing(world)


def test_the_account_of_the_arguments_must_be_the_account_of_the_call(world):
    assert "not the account of the call" in str(refused(world, args={**ARGS, "account": "microsoft"}))
    made_nothing(world)


def test_a_configuration_changed_after_it_was_accepted_starts_nothing(world):
    path = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["accounts"]["google"]["calendars"]["added"] = "other"
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert "accept" in str(refused(world)).lower()


# --- the kind ------------------------------------------------------------------------------------------------------------------------------------


def test_this_is_not_a_way_to_start_any_step_a_kind_must_end_in_a_gate_of_an_account_word(world):
    assert "does not open a write" in str(refused(world, kind=OTHER_KIND))        # a gate whose word is `write`
    assert "does not open a write" in str(refused(world, kind=NO_GATE_KIND))
    assert "no step kind" in str(refused(world, kind="not-a-kind"))
    assert "no step kind" in str(refused(world, kind=None))
    made_nothing(world)


def test_arguments_the_kind_refuses_are_a_usage_error_naming_the_field_and_nothing_is_made(world):
    error = refused(world, args={**ARGS, "title": "  "})
    assert error.code == 2 and "title" in str(error) and "give a title" in str(error)
    assert refused(world, args={**ARGS, "stray": 1}).code == 2
    assert "an object" in str(refused(world, args=["not", "an", "object"]))
    made_nothing(world)


def test_a_preparation_that_fails_says_the_steps_own_sentence_and_leaves_nothing_behind(world):
    error = refused(world, args={**ARGS, "fail": True})
    assert error.code == 1 and "not_configured" in str(error) and "run the authorize command of the account" in str(error)
    left_nothing(world)
    assert CALLS == []
    for _ in range(3):      # retries do not pile up planned or ready rows
        refused(world, args={**ARGS, "fail": True})
    tasks, _ = store_rows(world)
    assert len(tasks) == 8 and {t["state"] for t in tasks} == {"cancelled"}


def test_a_start_held_by_a_cap_leaves_nothing_behind(world, monkeypatch):
    monkeypatch.setattr(st.load("parallel"), "admit", lambda *a, **k: (False, "at the limit of running tasks"))
    assert "limit of running tasks" in str(refused(world))
    left_nothing(world)


# --- limit L55: the start writes nothing; the approval of the exact document does ------------------------------------------------------------------


def test_limit_55_the_effect_is_executed_only_through_the_approval_of_the_hash_of_its_exact_document(world):
    started = start(world)
    ctx = ops_core.context(world["path"])
    item = ctx["store"].pending_get(ctx["conn"], started["pending"])
    with pytest.raises(ops.OpsError):
        ops.approve(world["path"], started["pending"], "0" * 64, channel="terminal")
    assert CALLS == []
    path = Path(ops.ops_step_effects.effect_dir(ctx["cfg"], started["task"], 0)) / effects.EFFECT_FILE
    original = path.read_bytes()
    path.write_bytes(original.replace(b"Dentist", b"Doctor"))      # an effect file edited after the preview has another hash
    with pytest.raises(ops.OpsError) as edited:
        ops.approve(world["path"], started["pending"], item["payload_sha256"], channel="terminal")
    assert "nothing was written" in str(edited.value) and CALLS == []
    path.write_bytes(original)
    done = ops.approve(world["path"], started["pending"], item["payload_sha256"], channel="terminal")
    assert done["result"] == {"written": True} and CALLS == [ARGS["title"]]


def test_a_messaging_app_approves_the_effect_only_when_its_word_is_granted(world):
    started = start(world)
    ctx = ops_core.context(world["path"])
    item = ctx["store"].pending_get(ctx["conn"], started["pending"])
    with pytest.raises(ops.OpsError) as no:
        ops.approve(world["path"], started["pending"], item["payload_sha256"], channel="messaging", sender=SENDER)
    assert "terminal" in str(no.value) and CALLS == []
    with pytest.raises(ops.OpsError):
        ops.approve(world["path"], started["pending"], item["payload_sha256"], channel="mcp")
    assert CALLS == []


def test_limit_55_the_start_module_reaches_no_effect_module_no_provider_and_no_writer():
    source = (st.RUNTIME / "account_start.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not [m for m in imported if m.startswith(("effect_", "step_", "send_document", "resolve", "subprocess"))], sorted(imported)
    assert "writer:" not in source and ".execute(" not in source and "resolve.call" not in source and "module_for" not in source


# --- the reply -----------------------------------------------------------------------------------------------------------------------------------


def test_the_reply_of_a_messaging_app_is_said_in_the_projects_language(world):
    started = start(world)
    assert account_start.reply_text(None, started) == f"Card #{started['pending']} waits for your approval."
    said = account_start.reply_text({"language": "pt-BR"}, started)
    assert said == phrases.TABLE["pt-BR"]["ACCT_CARD_SENT"].format(pending=started["pending"]) and said != account_start.reply_text(None, started)
    assert phrases.localize(phrases.en("ACCT_NOT_CONFIGURED").format(account="google"), {"language": "pt-BR"}) == \
        phrases.text("ACCT_NOT_CONFIGURED", {"language": "pt-BR"}, account="google")


# --- the card is checked, and a card that is not what the operation prepared fails closed -----------------------------------------------------------


def test_a_gate_that_echoes_the_persons_words_into_the_title_fails_closed_and_leaves_no_decision(world):
    error = refused(world, args={**ARGS, "mode": "echo-title"})
    assert error.code == 1 and "title is not the one written by code" in str(error) and "cancelled" in str(error)
    left_nothing(world)
    assert CALLS == [] and ops.pending(world["path"])["pending"] == []


@pytest.mark.parametrize("mode, why", [("hidden", "no well-formed card"), ("body-mismatch", "its lines are not its body"), ("no-card", "no well-formed card"),
                                       ("other-word", "its effect is not the gate's")])
def test_a_card_with_a_hidden_character_a_body_that_is_not_its_lines_no_lines_or_another_effect_fails_closed(world, mode, why):
    args = {**ARGS, "mode": mode, "title": HIDDEN} if mode == "hidden" else {**ARGS, "mode": mode}
    error = refused(world, args=args)
    assert error.code == 1 and why in str(error)
    left_nothing(world)
    assert CALLS == []


# --- the group of the word, and the brake --------------------------------------------------------------------------------------------------------


def test_the_operation_must_belong_to_the_policy_group_of_the_words_effect(world):
    error = refused(world, key="account-test-other")
    assert error.code == 2 and "not one of the group calendar-write" in str(error)
    made_nothing(world)


def test_a_word_whose_group_does_not_exist_yet_starts_nothing(world, monkeypatch):
    monkeypatch.delitem(operations.GROUPS, GROUP)
    assert "not one of the group calendar-write" in str(refused(world))
    made_nothing(world)


def test_the_words_of_the_family_have_their_groups_and_send_is_not_one(world):
    assert account_start.GROUP_OF_WORD == {"calendar": "calendar-write", "mailbox": "mail-organize", "files": "files-write"}
    assert "send" not in account_start.WORDS and set(account_start.WORDS) == set(ops.project_config.ACCOUNT_EFFECT_WORDS)


def test_a_messaging_start_is_refused_while_the_step_brake_is_stopped_and_the_terminals_is_not(world):
    accept(world["path"], {"messaging": ["read", GROUP]})
    st.load("ops_steps").set_steps_mode(world["path"], "stopped")
    error = refused(world, channel="messaging", sender=SENDER)
    assert error.code == 1 and "stopped" in str(error)
    made_nothing(world)
    assert start(world, channel="terminal")["pending"], "the person's own start still runs one"
    st.load("ops_steps").set_steps_mode(world["path"], "autonomous")
    assert start(world, channel="messaging", sender=SENDER)["pending"]


def test_the_account_named_in_a_refusal_is_cleaned_of_line_ends_and_odd_characters(world):
    error = refused(world, account="aws\nCalendar: work \u202e", args={**ARGS, "account": "x"})
    assert "\n" not in str(error) and "\u202e" not in str(error) and error.code == 3
    made_nothing(world)
