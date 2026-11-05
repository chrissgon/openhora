"""A new file the interpreter read is created from its verified spans (package P4 of SPEC-ACEITE-FIX-READING, row 29: runtime/ops_natural_files.py `seed`, opened by
`ops_interpret._carry_out` and read by `ops_natural_writes._read`).

The closed forms of the files family need "chamado <name>"; a line such as "cria um arquivo lista-teste.txt no drive com: arroz, feijao, cafe" read nothing there, and a decision of the
interpreter with a name, a content and a folder ended in `IX_CANNOT_WRITE`. Now the closed forms are tried first, and when they read nothing the seed built from the spans the
interpreter's check verified opens the same card, with the same asks for what is missing. Over the real operations layer and the W4a stand-in services of test_files_write.py (nothing is
written by a line, no Google or Microsoft host is called); a stand-in answers the one line the interpreter reads. Every name is invented.

Held here:
  * `seed`: the slots and origins of the seed; a `folder` span that is a word for a service is no folder (the bare "drive" names nothing, "onedrive" names the account); no `content` or another
    operation gives None;
  * the product's own turn: the decision opens the create card of the file (one account named by "onedrive" or a folder only one account lists; two accounts with "drive" are asked which),
    a decision with no name asks the name, a folder the account does not list is asked, a decision with no content says it could not be prepared, `turn_gate.provenance` passes;
  * the closed form "cria uma nota chamada ideias.txt no onedrive dizendo ..." opens the same card as before, with the interpreter's decision beside it or without.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_file_create_seed.py
"""
from __future__ import annotations

import json

import pytest

import phrase_kit as pk
import standin_tree as st
from test_ask import accept
from test_files_write import GOOGLE, MICROSOFT, world  # noqa: F401  (the files world)

drafts = st.load("drafts")
interpreter_route = st.load("interpreter_route")
ops = st.load("ops")
ops_interpret = st.load("ops_interpret")
ops_natural_files = st.load("ops_natural_files")
phrases = st.load("phrases")
turn_gate = st.load("turn_gate")

OWNER = "55119000000041"
OWNER_KEY = f"telegram:{OWNER}"
PROFILES = {"owner": ["read", "talk", "interpret", "files-write"]}
SENDERS = {"telegram": [{"id": OWNER, "policy": "owner"}]}
PT = {"language": "pt-BR"}
LINE = "cria um arquivo lista-teste.txt no drive com: arroz, feij\u00e3o, caf\u00e9"
CONTENT = "arroz, feij\u00e3o, caf\u00e9"


def op(slots, name="file-create"):
    return json.dumps({"v": 1, "kind": "op", "op": name, "slots": slots}, ensure_ascii=False)


def decision(spans, name="file-create"):
    return {"kind": "op", "error": None, "op": name, "args": dict(spans), "spans": dict(spans), "time": None, "inherited": [], "time_disagree": False}


@pytest.fixture(autouse=True)
def forget():
    drafts.clear()
    ops_interpret.forget_all()
    yield
    drafts.clear()
    ops_interpret.forget_all()


def setup(world, monkeypatch, answer, accounts=None):  # noqa: F811
    accept(world["path"], policies=PROFILES, messaging={"senders": SENDERS}, accounts=accounts or {"google": GOOGLE, "microsoft": MICROSOFT}, language="pt-BR")
    monkeypatch.setattr(ops_interpret, "_zone", lambda now: "America/Sao_Paulo")
    calls = []

    def complete(route_id, system, user, **kw):
        calls.append(user)
        return {"ok": True, "text": answer, "finish": "stop", "usage": {}, "latency_ms": 5}
    monkeypatch.setattr(interpreter_route, "complete", complete)
    return calls


def say(world, line):
    return ops.say(world["path"], line, channel="messaging", sender=OWNER_KEY)


def card(world, out):
    return ops.pending(world["path"], out["resend"])["body"]


# --- the seed ---------------------------------------------------------------------------------------------------------------------------------


def test_the_seed_carries_the_name_the_content_and_the_folder_as_spans_of_the_line():
    got = ops_natural_files.seed("file-create", decision({"name": "lista-teste.txt", "content": CONTENT, "folder": "cv"}), LINE)
    assert dict(got) == {"op": "file-create", "slots": {"name": "lista-teste.txt", "content": CONTENT, "folder": "cv"}}
    assert got.origins == {"name": "line-span", "content": "line-span", "folder": "line-span"}


def test_a_folder_that_is_a_word_for_a_service_is_no_folder_the_bare_drive_names_nothing_and_onedrive_names_the_account():
    bare = ops_natural_files.seed("file-create", decision({"name": "lista-teste.txt", "content": CONTENT, "folder": "drive"}), LINE)
    assert dict(bare)["slots"] == {"name": "lista-teste.txt", "content": CONTENT}
    onedrive = ops_natural_files.seed("file-create", decision({"name": "lista-teste.txt", "content": CONTENT, "folder": "onedrive"}), LINE)
    assert dict(onedrive)["slots"] == {"name": "lista-teste.txt", "content": CONTENT, "account": "microsoft"}
    assert onedrive.origins["account"] == "line-span" and "folder" not in onedrive.origins


@pytest.mark.parametrize("op_name, spans", [
    ("file-create", {"name": "lista-teste.txt"}),
    ("file-create", {"name": "lista-teste.txt", "content": "   "}),
    ("file-replace", {"file": "lista", "content": CONTENT}),
    ("mail-send", {"to": "ana@mail.example", "body": CONTENT}),
])
def test_no_content_or_another_operation_gives_no_seed(op_name, spans):
    assert ops_natural_files.seed(op_name, decision(spans, op_name), LINE) is None


# --- the turn ---------------------------------------------------------------------------------------------------------------------------------


def test_the_live_line_of_row_29_opens_the_create_card_in_the_one_account_that_lists_folders(world, monkeypatch):  # noqa: F811
    setup(world, monkeypatch, op({"name": "lista-teste.txt", "content": CONTENT, "folder": "drive"}), accounts={"google": GOOGLE})
    out = say(world, LINE)
    assert out["resend"]
    text = card(world, out)
    assert pk.said(text, "CARD_FILE_NAME", None, name="lista-teste.txt", service="Google Drive") and CONTENT in text


def test_a_service_word_names_the_account_and_two_accounts_with_the_bare_drive_are_asked_which(world, monkeypatch):  # noqa: F811
    setup(world, monkeypatch, op({"name": "lista-teste.txt", "content": CONTENT, "folder": "drive"}))
    asked = say(world, LINE)
    assert not asked.get("resend") and pk.said(asked["reply"], "NW_ASK_ACCOUNT", PT)
    chosen = say(world, "microsoft")
    assert pk.said(card(world, chosen), "CARD_FILE_NAME", None, name="lista-teste.txt", service="OneDrive") and CONTENT in card(world, chosen)
    drafts.clear()
    setup(world, monkeypatch, op({"name": "lista-teste.txt", "content": CONTENT, "folder": "onedrive"}))
    named = say(world, "cria um arquivo lista-teste.txt no onedrive com: arroz, feij\u00e3o, caf\u00e9")
    assert pk.said(card(world, named), "CARD_FILE_NAME", None, name="lista-teste.txt", service="OneDrive")


def test_a_folder_the_account_lists_is_used_and_one_it_does_not_is_asked(world, monkeypatch):  # noqa: F811
    setup(world, monkeypatch, op({"name": "lista-teste.txt", "content": CONTENT, "folder": "cv"}), accounts={"google": GOOGLE})
    out = say(world, "cria um arquivo lista-teste.txt na pasta cv com: arroz, feij\u00e3o, caf\u00e9")
    assert out["resend"] and "lista-teste.txt" in card(world, out)
    drafts.clear()
    setup(world, monkeypatch, op({"name": "lista-teste.txt", "content": CONTENT, "folder": "contratos"}), accounts={"google": GOOGLE})
    unknown = say(world, "cria um arquivo lista-teste.txt na pasta contratos com: arroz, feij\u00e3o, caf\u00e9")
    assert not unknown.get("resend") and pk.said(unknown["reply"], "NW_ASK_FOLDER", PT, name="contratos", names="default, cv")


def test_a_decision_with_no_name_asks_the_name_and_the_answer_opens_the_card(world, monkeypatch):  # noqa: F811
    setup(world, monkeypatch, op({"content": CONTENT, "folder": "drive"}), accounts={"google": GOOGLE})
    asked = say(world, "cria um arquivo no drive com: arroz, feij\u00e3o, caf\u00e9")
    assert not asked.get("resend") and pk.said(asked["reply"], "NW_ASK_FILE_NAME", PT)
    answered = say(world, "lista-teste.txt")
    assert pk.said(card(world, answered), "CARD_FILE_NAME", None, name="lista-teste.txt", service="Google Drive") and CONTENT in card(world, answered)


def test_a_decision_with_no_content_opens_nothing_and_says_it_could_not_be_prepared(world, monkeypatch):  # noqa: F811
    setup(world, monkeypatch, op({"name": "lista-teste.txt", "folder": "drive"}), accounts={"google": GOOGLE})
    out = say(world, "cria um arquivo lista-teste.txt no drive")
    assert "resend" not in out and pk.said(out["reply"], "IX_CANNOT_WRITE", PT)
    assert world["gd"].requests == [] or all(r["method"] == "GET" or r["path"].endswith("/token") for r in world["gd"].requests), "a line writes nothing"


def test_the_seed_passes_the_gate_with_the_origins_it_declares(world, monkeypatch):  # noqa: F811
    seen = []
    real = turn_gate.provenance

    def provenance(op_name, args, origins):
        seen.append((op_name, dict(args), dict(origins)))
        return real(op_name, args, origins)
    setup(world, monkeypatch, op({"name": "lista-teste.txt", "content": CONTENT, "folder": "onedrive"}))
    monkeypatch.setattr(turn_gate, "provenance", provenance)
    out = say(world, "cria um arquivo lista-teste.txt no onedrive com: arroz, feij\u00e3o, caf\u00e9")
    assert out["resend"]
    assert seen and seen[-1][0] == "file-create" and seen[-1][2] == {"account": "line-span", "file_name": "line-span", "content": "line-span"} and real("file-create", seen[-1][1], seen[-1][2]) == []


def test_the_closed_form_opens_the_same_card_as_before_and_the_seed_is_only_for_a_line_it_reads_nothing_of(world, monkeypatch):  # noqa: F811
    line = "cria uma nota chamada ideias.txt no onedrive dizendo: comprar tinta azul"
    model = op({"name": "ideias.txt", "content": "comprar tinta", "folder": "onedrive"})      # the model's content is shorter than the closed form's: the closed form is the one read
    setup(world, monkeypatch, model)
    text = card(world, say(world, line))
    assert pk.said(text, "CARD_FILE_NAME", None, name="ideias.txt", service="OneDrive") and "comprar tinta azul" in text
