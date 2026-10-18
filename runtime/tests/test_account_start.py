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
GROUP = "account-test"
ACCOUNTS = {"google": {"address": "Ana@Mail.example", "calendars": {"personal": "primary"}, "folders": {"default": "Folder_ID_01"}}}
TITLE = "Calendar: new event"
ARGS = {"account": "google", "title": "Dentist at 14:00, bring the x-rays", "start": "2026-10-20T14:00"}
SENDER = "telegram:4242"
CALLS = []       # what the stand-in effect's execute was asked: it is the only thing in this file that "writes"


def _check(args):
    if not isinstance(args, dict) or set(args) - {"account", "title", "start", "fail"}:
        raise steps.StepFailure("bad_args", "args")
    if not isinstance(args.get("title"), str) or not args["title"].strip():
        raise steps.StepFailure("bad_args", "title", "", "give a title")
    return dict(args)


def _prepare(ctx, state):
    if ctx.args.get("fail"):
        raise steps.StepFailure("not_configured", "calendar", "", "run the authorize command of the account")
    doc = {"effect": "calendar", "task": ctx.task_id, "account": ctx.args["account"], "title": ctx.args["title"], "start": ctx.args.get("start", "")}
    return {"effect_sha256": ctx.services["effect_files"].write(ctx.task_id, int(state.get("cycle", 0)), doc)}


def _open(ctx, state):
    recorded = state["steps"]["prepare"]["result"]["effect_sha256"]
    doc = ctx.services["effect_files"].read(ctx.task_id, int(state.get("cycle", 0)), recorded)
    lines = [["CARD_ACCOUNT", {"account": doc["account"], "address": "ana@mail.example"}]]
    return {"title": TITLE, "body": phrases.card_text(lines), "payload_sha256": recorded, "payload": {"card": lines}}


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
    path = built["project"] / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["accounts"] = ACCOUNTS
    path.write_text(json.dumps(raw), encoding="utf-8")
    project = str(built["project"])
    ops.accept_config(project, ops.project_config.load(project)["sha256"])
    return {**built, "path": project, "tmp": tmp_path}


def start(world, args=None, kind=KIND, key=OPERATION, title=TITLE, account="google", **more):
    return account_start.start(world["path"], kind, ARGS if args is None else args, key_words=key, title=title, account=account, **more)


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


@pytest.mark.parametrize("title", ["Dentist at 14:00, bring the x-rays", "calendar: new event", "Calendar: New Event", "Calendar:\nnew event", "", "A" * 80,
                                   "Calendar: new event 2", "Calendar: x" + "y" * 70])
def test_a_title_that_is_not_a_few_plain_words_written_by_code_is_refused_and_nothing_is_made(world, title):
    error = refused(world, title=title)
    assert error.code == 2 and "title" in str(error)
    made_nothing(world)


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
    assert start(world, args={**ARGS, "title": "Another"}, key="account-test-two")["pending"]
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


def test_a_preparation_that_fails_says_the_steps_own_sentence_and_leaves_the_task_failed(world):
    error = refused(world, args={**ARGS, "fail": True})
    assert error.code == 1 and "not_configured" in str(error) and "run the authorize command of the account" in str(error)
    tasks, pending = store_rows(world)
    assert pending == [] and [t["state"] for t in tasks if t["step_kind"] == KIND] == ["failed"]
    assert CALLS == []


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
