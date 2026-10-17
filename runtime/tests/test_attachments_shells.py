"""The shells of the attachment operations (package ATT-1, runtime part): the group `add-sources` that a project's policy turns on and the page keeps by its
ceiling, the grant `add-sources-direct` that only `accept-config --widen` accepts, the terminal's verbs, the conversation's commands, the page's routes against the
real operations layer, and a macro-enabled file refused like any file the converter will not read. Offline; the converter is a stand-in; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_attachments_shells.py
"""
from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

import standin_tree as st
from sources_fixture import make_pdf
from test_attachments import IDENT, SENDER, POLICIES, PDF, accept, case  # noqa: F401  (the project the attachment tests use)
from test_service import PORT, TOKEN, api, call

ops = st.load("ops")
operations = st.load("operations")
cli = st.load("cli")
service = st.load("service")
sources = st.load("sources")
project_config = st.load("project_config")
ops_config = st.load("ops_config")


def real_world(path):
    projects = [{"id": service.project_id(path), "name": "p", "path": path}]
    return types.SimpleNamespace(svc=service.Service(ops, projects, TOKEN, PORT, None, log=lambda line: None), projects=projects)


def test_the_groups_are_the_page_s_by_its_ceiling_and_a_messaging_app_s_only_when_its_policy_lists_them():
    assert operations.permitted("attachments", "messaging", None) is False and operations.permitted("attachment-add", "messaging", {"messaging": ["read"]}) is False
    for name in ("attachments", "attachment-hold", "attachment-add", "attachment-discard"):
        assert operations.permitted(name, "messaging", {"messaging": ["read", "add-sources"]}) is True, name
        assert operations.permitted(name, "mcp", {"mcp": ["read", "add-sources"]}) is False and "mcp" not in operations.by_name(name)["channels"], name
    for name in ("attachments", "attachment-add", "attachment-discard"):
        assert operations.permitted(name, "page", None) is True and operations.permitted(name, "page", {"page": ["read", "add-sources"]}) is True
        assert operations.permitted(name, "page", {"page": ["read"]}) is False, "a page whose policy narrows it loses them"
        assert operations.permitted(name, "terminal", {"terminal": []}) is True
    assert operations.permitted("attachment-hold", "page", None) is False and operations.permitted("attachment-hold", "terminal", None) is False
    assert operations.refusal("attachment-add", "page", {"page": ["read"]}) == operations.not_enabled("attachment-add", "page")
    assert {"attachments", "attachment-add", "attachment-discard"} <= set(operations.permissions("page", None))
    assert "attachment-add" not in operations.permissions("page", {"page": ["read"]}) and "attachment-hold" not in operations.permissions("page", None)
    # the grant is no ceiling group: a messaging app holds it only by listing it, and the whole ceiling of the page never includes it
    assert "add-sources-direct" not in operations.ceiling_groups("messaging") and "add-sources-direct" not in operations.ceiling_groups("page")
    assert operations.permitted("attachment-hold", "messaging", {"messaging": ["add-sources-direct"]}) is True
    assert operations.permitted("attachment-add", "messaging", {"messaging": ["add-sources-direct"]}) is False, "the grant holds the hold and nothing else"


def test_the_grant_that_adds_without_a_card_is_a_widening_that_accept_config_takes_only_with_the_hash_of_its_list(case):
    path = case.path
    file = Path(path) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(file.read_text())
    raw["policies"] = dict(POLICIES, desk=["read", "add-sources", "add-sources-direct"])
    raw["messaging"] = {"senders": {"telegram": [{"id": IDENT, "policy": "desk"}]}}
    file.write_text(json.dumps(raw))
    shown = ops.config(path)
    assert [(g["channel"], g["group"], g["sender"]) for g in shown["grants"]] == [("messaging", "add-sources-direct", f"telegram:{IDENT}")]
    assert shown["grants"][0]["means"] == "a file a listed sender sends becomes a source of the project without a confirmation"
    assert [w["group"] for w in shown["widening"]] == ["add-sources-direct"] and shown["widening_sha256"], "only what the sender did not have before: add-sources was already theirs"
    with pytest.raises(ops.OpsError, match="widen"):
        ops.accept_config(path, shown["sha256"])
    with pytest.raises(ops.OpsError):
        ops.accept_config(path, shown["sha256"], widen="0" * 64)
    done = ops.accept_config(path, shown["sha256"], widen=shown["widening_sha256"])
    assert done["accepted"] == shown["sha256"] and [w["group"] for w in done["widened"]] == ["add-sources-direct"]
    # the group is refused on a channel that cannot hold the file
    raw["channels"] = {"page": ["read", "add-sources-direct"]}
    file.write_text(json.dumps(raw))
    with pytest.raises(ops.OpsError, match="add-sources-direct"):
        ops.config(path)


def test_the_terminal_has_a_verb_for_the_three_and_none_for_the_bridge_s_hold():
    parser = cli.build_parser()
    got = parser.parse_args(["attachments", "--project", "/p"])
    assert got.command == "attachments"
    got = parser.parse_args(["attachment-add", "--project", "/p", "--id", "3"])
    assert (got.command, got.f_id) == ("attachment-add", 3)
    got = parser.parse_args(["attachment-discard", "--project", "/p", "--id", "4"])
    assert got.f_id == 4
    with pytest.raises(cli.Usage):
        parser.parse_args(["attachment-hold", "--project", "/p", "--incoming", "x"])
    for verb in ("attachments", "attachment-add", "attachment-discard"):
        assert verb in operations.terminal_verbs() and verb in cli.__doc__
    assert "attachment-hold" not in operations.terminal_verbs()
    assert operations.command_line("attachment-add", "/p", checkout=None, attachment_id=3) == "python3 runtime/cli.py attachment-add --project /p --id 3"
    assert operations.chat_line("attachment-add", attachment_id=3) == "/attachment-add 3"
    assert operations.parse_chat("/attachment-discard 12") == ("attachment-discard", {"attachment_id": 12})
    assert operations.parse_chat("/attachments") == ("attachments", {})


def test_the_page_lists_adds_and_discards_a_held_file_through_the_service_and_never_holds_one(case):
    world = real_world(case.path)
    first, second = case.hold(PDF)["attachment"]["id"], case.hold(make_pdf("Another plan"), name="Other.pdf")["attachment"]["id"]
    status, _, body = call(world, "GET", api(world, "/attachments"))
    assert status == 200 and [h["id"] for h in body["held"]] == [first, second] and body["today"]["files"] == 2
    assert IDENT not in json.dumps(body) and "sender" not in body["held"][0]
    status, _, body = call(world, "POST", api(world, f"/attachments/{first}/add"), {})
    assert status == 200 and body["version"] == 1 and body["source"] == "q3-plan"
    status, _, body = call(world, "POST", api(world, f"/attachments/{second}/discard"), {})
    assert status == 200 and body["discarded"] is True
    status, _, body = call(world, "POST", api(world, f"/attachments/{second}/discard"), {})
    assert status in (400, 409) and "not waiting" in json.dumps(body)
    status, _, body = call(world, "GET", api(world, "/attachments"))
    assert body["held"] == [] and [r["status"] for r in body["recent"]] == ["discarded", "added"], "the latest first"
    status, _, _ = call(world, "POST", api(world, "/attachments/hold"), {})
    assert status == 404
    status, _, body = call(world, "POST", api(world, f"/attachments/{first}/add"), {"extra": 1})
    assert status == 400


def test_a_page_whose_policy_does_not_list_the_group_is_refused_before_anything_runs(case):
    accept(case.path, channels={"messaging": "staff", "page": ["read"]})
    world = real_world(case.path)
    held = case.hold(PDF)["attachment"]["id"]
    for method, tail in (("GET", "/attachments"), ("POST", f"/attachments/{held}/add"), ("POST", f"/attachments/{held}/discard")):
        status, _, body = call(world, method, api(world, tail), {} if method == "POST" else None)
        assert status == 409 and "is not enabled for this channel" in json.dumps(body), (method, tail)
    assert case.rows()[0]["status"] == "held"
    permissions = ops.config(case.path)["channels"]
    assert "attachment-add" not in operations.permissions("page", permissions)


def test_a_typed_command_from_the_page_s_conversation_is_checked_against_the_page_s_policy(case):
    held = case.hold(PDF)["attachment"]["id"]
    ops_say = st.load("ops_say")
    reply = ops_say._say_command(case.path, case.ctx, f"/attachment-add {held}", "page", 1)[0]
    assert "Added Q3 plan.pdf as `q3-plan`, version 1." in reply
    accept(case.path, channels={"messaging": "staff", "page": ["read", "talk"]})
    ctx = st.load("ops_core").context(case.path)
    other = case.hold(make_pdf("Another plan"), name="Other.pdf")["attachment"]["id"]
    reply = ops_say._say_command(case.path, ctx, f"/attachment-discard {other}", "page", 2)[0]
    assert reply.startswith("error: /attachment-discard is not enabled for this channel")
    assert case.rows()[1]["status"] == "held"


def test_a_macro_enabled_package_is_refused_like_a_file_the_converter_will_not_read(case, monkeypatch):
    held = case.hold(PDF, name="Budget.xlsm", declared="application/vnd.ms-excel.sheet.macroEnabled.12")["attachment"]["id"]

    def refusing(cfg, call=None):
        def convert(*args):
            raise sources.SourcesError("the converter failed (failed): the package holds macros (VBA code or macro sheets): a macro-enabled Office file is not converted",
                                       "convert")
        return convert
    monkeypatch.setattr(sources, "provider_convert", refusing)
    with pytest.raises(ops.OpsError) as caught:
        ops.attachment_add(case.path, held, channel="messaging", sender=SENDER)
    assert str(caught.value) == "Budget.xlsm was not added and was deleted: it holds macros, which are never converted."
    row = case.rows()[0]
    assert (row["status"], row["code"]) == ("refused", "macro") and not (case.data / "attachments" / "held" / "1").exists()
