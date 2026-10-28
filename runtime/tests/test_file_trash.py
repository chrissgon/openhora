"""Move a file to the trash by its name, on a messaging app (slice R2-A: runtime/ops_file_trash.py, runtime/phone_delete.py `name`, runtime/files_document.py,
runtime/step_files.py, runtime/effect_files.py, and the trash verbs of providers/writer/gdrive.py and onedrive.py), end to end against the stand-in services of
providers/writer/tests/ on 127.0.0.1 and a stand-in of the documents providers (the folder listings of the search) that reads the same fictional drives. No Google or
Microsoft host is reached, no credential is real, no model runs (a stand-in answers the one line the interpreter reads), every name is fictional.

What is held here (the spec's tests): the live lines open the card of the file found in the Google subfolder and nothing is trashed before the approval; after it exactly one
request that trashes is made, with the right id; a stale version, a file outside the grant (never found), a folder removed from the configuration between the card and the approval
and a sender without the group each leave the file where it is; two matches give a list and "o 2" opens the right card; OneDrive does the same; no path reaches a permanent delete;
the lines that remove an event or a mail are not caught.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_file_trash.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import phrase_kit as pk
import standin_tree as st
from test_ask import accept
from test_files_write import (approve, ctx_of, effect_doc, fdw, fod, item_of, world, reads, sha)  # noqa: F401  (the fixture and its helpers)

effect_files = st.load("effect_files")
files_document = st.load("files_document")
interpreter_route = st.load("interpreter_route")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_file_read = st.load("ops_file_read")
ops_file_trash = st.load("ops_file_trash")
ops_interpret = st.load("ops_interpret")
ops_step_seams = st.load("ops_step_seams")
operations = st.load("operations")
phone_delete = st.load("phone_delete")
phrases = st.load("phrases")

OWNER, PLAIN, WRITER = "55119000000031", "55119000000032", "55119000000033"
OWNER_KEY, PLAIN_KEY, WRITER_KEY = f"telegram:{OWNER}", f"telegram:{PLAIN}", f"telegram:{WRITER}"
PROFILES = {"owner": ["read", "talk", "interpret", "files-trash", "read-files", "approve-effect-files"], "plain": ["read", "talk", "interpret"],
            "writer": ["read", "talk", "interpret", "files-write", "approve-effect-files"]}      # the writer holds files-write (the writes of new files) and neither files-trash nor read-files
SENDERS = {"telegram": [{"id": OWNER, "policy": "owner"}, {"id": PLAIN, "policy": "plain"}, {"id": WRITER, "policy": "writer"}]}
ACCOUNTS = {"google": {"address": "pat@example.com", "folders": {"default": fdw.FOLDER_ID}},
            "microsoft": {"address": "casey.rivera@mail.example", "folders": {"default": "/Documents/openhora"}}}
PNG = b"\x89PNG\r\n\x1a\n the fictional mark"
SUB, OUTSIDE, OUTSIDE_FILE = "Sub_ID_0001", "Out_ID_0001", "Out_File_0001"
PT = {"language": "pt-BR"}
EN = {"language": "en"}
ZONE = "America/Sao_Paulo"


def item(ident, name, kind="file", size=5120, modified="2026-10-10T09:00:00.000Z"):
    return {"id": ident, "name": name, "kind": kind, "path": "/", "size": size, "modified": modified, "supported": True, "reason": ""}


class Search:
    """The documents providers' `children` and `stat`, read from the fictional drives the writer stand-ins keep, so that the search and the writer see the same files."""

    def __init__(self, world):
        self.gd, self.ms, self.calls = world["gd"], world["ms"], []

    def __call__(self, cls, verb, args, **kw):
        service = "google" if kw.get("implementation") == "gdrive" else "microsoft"
        self.calls.append((service, verb, tuple(args)))
        value = lambda flag: args[args.index(flag) + 1]  # noqa: E731
        if service == "google":
            if verb == "stat":
                meta = self.gd.files.get(value("--id"))
                if meta is None:
                    raise RuntimeError("Drive said: no such folder")
                return {"id": meta["id"], "name": meta["name"], "mime_type": meta["mimeType"], "supported": False}
            folder = value("--id")
            rows = [m for m in self.gd.files.values() if folder in m["parents"] and not m["trashed"]]
            return {"items": [item(m["id"], m["name"], "folder" if m["mimeType"] == fdw.FOLDER else "file", len(m["content"]), m["modifiedTime"]) for m in rows],
                    "count": len(rows), "truncated": False}
        folder = value("--folder-id") if "--folder-id" in args else {"/Documents/openhora": fod.FOLDER_ID}.get(value("--path"))
        rows = [m for m in self.ms.items.values() if m["parent"] == folder]
        return {"items": [item(f"{fod.DRIVE}/{m['id']}", m["name"], "folder" if m["folder"] else "file", len(m["content"]), m["modified"]) for m in rows],
                "count": len(rows), "truncated": False}

    def listed(self):
        return sorted({(s, a[1]) for s, v, a in self.calls if v == "children"})


@pytest.fixture
def desk(world, monkeypatch):  # noqa: F811
    """The files world with the fictional Drive tree (Arquivos > openhora > the mark; a same-named file outside the granted folder), a OneDrive file, the two senders and the stand-in model."""
    gd_, ms_ = world["gd"], world["ms"]
    gd_.files[fdw.FOLDER_ID]["name"] = "Arquivos"
    gd_.add_folder(SUB, "openhora", (fdw.FOLDER_ID,))
    gd_.add_file(fdw.FILE_ID, "openhora-mark.png", PNG, mime="image/png", parents=(SUB,))
    gd_.add_folder(OUTSIDE, "Particular")
    gd_.add_file(OUTSIDE_FILE, "openhora-mark.png", b"outside", mime="image/png", parents=(OUTSIDE,))
    accept(world["path"], policies=PROFILES, messaging={"senders": SENDERS}, accounts=ACCOUNTS, language="pt-BR")
    monkeypatch.setattr(ops_interpret, "_zone", lambda now: ZONE)
    ops_interpret.forget_all()
    ops_file_read.forget_lists()
    search = Search(world)
    answer = {"text": json.dumps({"v": 1, "kind": "op", "op": "file-trash", "slots": {"file": "openhora-mark.png"}})}
    monkeypatch.setattr(ops_file_read, "provider_call", search)
    monkeypatch.setattr(interpreter_route, "complete", lambda route_id, system, user, **kw: {"ok": True, "text": answer["text"], "finish": "stop", "usage": {}, "latency_ms": 5})
    world.update(search=search, answer=answer)
    return world


def say(world, line, key=OWNER_KEY):
    return ops.say(world["path"], line, channel="messaging", sender=key)


def patches(server):
    return [r for r in server.requests if r["method"] in ("PATCH", "DELETE") and "/revisions/" not in r["path"]]


def open_cards(world) -> list:
    return [p for p in open_pending(world) if p["kind"] == "effect"]


def open_pending(world):
    ctx = ctx_of(world)
    return ctx["store"].pending_list(ctx["conn"], "open")


def started_of(world, said):
    """The `started` shape the helpers of the files tests take, for the card a line opened (its pending id and its task)."""
    ctx = ctx_of(world)
    item_ = ctx["store"].pending_get(ctx["conn"], said["resend"])
    return {"pending": item_["id"], "task": item_["task_id"]}


def card_sent(reply, number, cfg=PT):
    """`reply` is exactly the one sentence that says card `number` waits for the approval (one line, nothing else is said)."""
    assert "\n" not in reply, reply
    pk.assert_said(reply, "ACCT_CARD_SENT", cfg, pending=number)


def no_delete(reply):
    return "\n" not in reply and pk.said(reply, "PHONE_NO_FILE_DELETE", PT)


def assert_card(lines, cfg, *expected):
    """The card lines are exactly the sentences of these (key, fields), in this order."""
    assert len(lines) == len(expected), lines
    for line, (key, fields) in zip(lines, expected):
        pk.assert_said(line, key, cfg, **fields)


def card_lines(world, started, language="pt-BR") -> list:
    return phrases.card_text(item_of(world, started)["payload"]["card"], {"language": language}).split("\n")


# --- the live lines ---------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("line", ["Remova o arquivo openhora-mark.png do drive", "Remova o arquivo openhora-mark.png do drive em /openhora"])
def test_the_live_lines_open_the_card_of_the_file_in_the_google_subfolder_and_nothing_is_trashed_before_the_approval(desk, line):
    out = say(desk, line)
    card_sent(out["reply"], out["resend"])
    assert out["ran"] is False
    started = started_of(desk, out)
    lines = card_lines(desk, started)
    assert not pk.said(lines[0], "CARD_FILE_FOUND", PT), "the name given is the file's whole name: the card does not ask"
    assert_card(lines[:7], PT, ("CARD_FILE_CODE_TRASH", {"read_at": effect_doc(desk, started)["read_at"].replace("T", " ").replace("Z", " UTC")}),
                ("CARD_ACCOUNT", {"account": "google", "address": "pat@example.com"}), ("CARD_FILE_NAME", {"name": "openhora-mark.png", "service": "Google Drive"}),
                ("CARD_FILE_FOLDER", {"folder": "Arquivos › openhora"}), ("CARD_FILE_TRASH_SIZE", {"size": f"{len(PNG)} B"}),
                ("CARD_FILE_TRASH_MODIFIED", {"modified": "2026-10-10T09:00:00.000Z"}), ("CARD_FILE_TRASH_DRIVE", {}))
    doc = effect_doc(desk, started)
    assert doc["operation"] == "trash" and doc["content"] is None and doc["target"] == {"kind": "file", "label": "default", "id": fdw.FILE_ID}
    assert doc["base"]["root"] == fdw.FOLDER_ID and doc["base"]["parent"] == SUB and doc["base"]["path"] == "Arquivos › openhora" and doc["base"]["exact"] is True
    assert patches(desk["gd"]) == [] and desk["gd"].files[fdw.FILE_ID]["trashed"] is False, "nothing is trashed before the approval"
    assert OUTSIDE_FILE not in str(desk["search"].calls) and (("google", "children", ("--id", OUTSIDE, "--top", "200")) not in desk["search"].calls)


def test_after_the_approval_exactly_one_trash_request_is_made_with_the_right_id_and_the_file_is_in_the_trash_not_gone(desk):
    out = say(desk, "Remova o arquivo openhora-mark.png do drive")
    started = started_of(desk, out)
    done = approve(desk, started, "messaging", OWNER_KEY)
    assert done["result"]["written"] is True and done["result"]["operation"] == "trash" and done["result"]["id"] == fdw.FILE_ID and done["result"]["moved_to_trash"] is True
    gd_ = desk["gd"]
    assert [(r["method"], r["path"], json.loads(r["body"] or b"null")) for r in patches(gd_)] == [("PATCH", f"/drive/v3/files/{fdw.FILE_ID}", {"trashed": True})]
    assert gd_.files[fdw.FILE_ID]["trashed"] is True and gd_.files[fdw.FILE_ID]["content"] == PNG, "moved, with its content"
    assert gd_.files[OUTSIDE_FILE]["trashed"] is False and gd_.violations == []
    assert {r["method"] for r in gd_.requests} == {"GET", "PATCH"}, "no request that deletes for good was ever made"
    again = ops.pending(desk["path"], started["pending"])
    assert again["status"] == "resolved" and again["resolution"] == "approved"


def test_a_name_that_is_only_part_of_the_files_name_asks_is_this_the_one_on_the_first_line_of_the_card(desk):
    out = say(desk, "Remova o arquivo openhora-ma do drive")
    lines = card_lines(desk, started_of(desk, out))
    pk.assert_said(lines[0], "CARD_FILE_FOUND", PT, name="openhora-mark.png", folder="Arquivos › openhora")
    assert pk.said(lines[1], "CARD_FILE_CODE_TRASH", PT)
    assert patches(desk["gd"]) == []


def test_the_card_in_english_says_only_what_the_docs_support(desk):
    accept(desk["path"], policies=PROFILES, messaging={"senders": SENDERS}, accounts=ACCOUNTS, language="en")
    out = say(desk, "Remove the file openhora-mark.png from my drive")
    started = started_of(desk, out)
    lines = card_lines(desk, started, "en")
    card_sent(out["reply"], out["resend"], EN)
    card = "\n".join(lines)
    assert pk.said(card, "CARD_FILE_TRASH_DRIVE", EN) and pk.said(card, "CARD_FILE_FOLDER", EN, folder="Arquivos › openhora")
    assert pk.said(card, "CARD_FILE_NAME", EN, name="openhora-mark.png", service="Google Drive")
    assert not any("delete" in line.lower() for line in lines), "the card never says the file is deleted"


# --- refusals before any trash ----------------------------------------------------------------------------------------------------------------


def test_a_stale_version_trashes_nothing_and_answers_the_decision(desk):
    out = say(desk, "Remova o arquivo openhora-mark.png do drive")
    started = started_of(desk, out)
    meta = desk["gd"].files[fdw.FILE_ID]
    meta["version"], meta["modifiedTime"] = "4", "2026-10-17T09:00:00.000Z"       # the person edited it in Drive meanwhile
    with pytest.raises(ops.OpsError) as stale:
        approve(desk, started, "messaging", OWNER_KEY)
    assert "not the one the task read" in str(stale.value) and "version" in str(stale.value)
    assert patches(desk["gd"]) == [] and meta["trashed"] is False
    decision = ops.pending(desk["path"], started["pending"])
    assert decision["status"] == "resolved" and decision["resolution"] == "answered", "answered with the reason, not approved"


def test_a_file_that_left_its_folder_between_the_card_and_the_approval_is_not_trashed(desk):
    out = say(desk, "Remova o arquivo openhora-mark.png do drive")
    started = started_of(desk, out)
    desk["gd"].files[fdw.FILE_ID]["parents"] = [OUTSIDE]       # moved to a folder outside the granted one: the version did not change
    with pytest.raises(ops.OpsError) as moved:
        approve(desk, started, "messaging", OWNER_KEY)
    assert "not inside the granted folder" in str(moved.value) and patches(desk["gd"]) == [] and desk["gd"].files[fdw.FILE_ID]["trashed"] is False


def test_the_writer_alone_refuses_a_file_whose_folder_changed_when_the_grant_is_not_asked(desk, monkeypatch):
    """The second layer: even if the grant were not asked again, the writer compares the folder of the base and refuses (exit 1 `changed:`)."""
    monkeypatch.setattr(effect_files, "grant_problem", lambda cfg, doc: None)
    out = say(desk, "Remova o arquivo openhora-mark.png do drive")
    started = started_of(desk, out)
    desk["gd"].files[fdw.FILE_ID]["parents"] = [OUTSIDE]
    with pytest.raises(ops.OpsError) as moved:
        approve(desk, started, "messaging", OWNER_KEY)
    assert "folder" in str(moved.value) and patches(desk["gd"]) == []


def test_a_file_outside_the_granted_folders_is_never_found_nor_prepared(desk):
    for gone in ("openhora-mark.png",):
        desk["gd"].files[fdw.FILE_ID]["trashed"] = True       # the only file inside the grant is out of the way: the same name outside it must not be returned
    out = say(desk, "Remova o arquivo openhora-mark.png do drive")
    assert out["reply"].startswith("Não encontrei um arquivo com esse nome.") and "resend" not in out  # validate: allow english-only -- the Portuguese sentence under test
    assert open_cards(desk) == [] and patches(desk["gd"]) == []
    assert not any(OUTSIDE in " ".join(a) for _, _, a in desk["search"].calls), "a folder outside the granted ones is never listed"
    # the grant is asked by the step too: the id of the outside file, handed to the step directly, is refused and leaves nothing behind
    account_start = st.load("account_start")
    with pytest.raises(ops.OpsError) as refused:
        account_start.start(desk["path"], "file-write", {"operation": "trash", "account": "google", "id": OUTSIDE_FILE, "folder": "default", "exact": True},
                            key_words="file-trash", title_key="TITLE_FILE_TRASH", account="google")
    assert "not inside a folder this project lists" in str(refused.value) and open_cards(desk) == []


def test_vacuity_a_grant_that_found_every_file_would_prepare_the_card_of_the_file_outside_and_be_seen(desk, monkeypatch):
    """The planted fault: the grant is answered yes for any id. The oracle above (a refusal, no card) then fails."""
    monkeypatch.setattr(ops_file_read, "locate", lambda cfg, service, root, ident: {"service": service, "folder": "Arquivos", "root": root, "id": ident, "name": "x", "size": 1, "modified": "m"})
    account_start = st.load("account_start")
    started = account_start.start(desk["path"], "file-write", {"operation": "trash", "account": "google", "id": OUTSIDE_FILE, "folder": "default", "exact": True},
                                  key_words="file-trash", title_key="TITLE_FILE_TRASH", account="google")
    assert started["pending"] and effect_doc(desk, started)["target"]["id"] == OUTSIDE_FILE


def test_a_folder_removed_from_the_configuration_between_the_card_and_the_approval_trashes_nothing(desk):
    out = say(desk, "Remova o arquivo openhora-mark.png do drive")
    started = started_of(desk, out)
    accept(desk["path"], policies=PROFILES, messaging={"senders": SENDERS}, accounts={**ACCOUNTS, "google": {"address": "pat@example.com", "folders": {"cv": "Cv_Folder_0001"}}},
           language="pt-BR")
    with pytest.raises(ops.OpsError) as gone:
        approve(desk, started, "messaging", OWNER_KEY)
    assert "nothing was changed" in str(gone.value) and patches(desk["gd"]) == [] and desk["gd"].files[fdw.FILE_ID]["trashed"] is False


def test_a_folder_name_that_now_points_to_another_folder_trashes_nothing(desk):
    out = say(desk, "Remova o arquivo openhora-mark.png do drive")
    started = started_of(desk, out)
    accept(desk["path"], policies=PROFILES, messaging={"senders": SENDERS}, accounts={**ACCOUNTS, "google": {"address": "pat@example.com", "folders": {"default": OUTSIDE}}},
           language="pt-BR")
    with pytest.raises(ops.OpsError) as other:
        approve(desk, started, "messaging", OWNER_KEY)
    assert "not the one the file was found under" in str(other.value) and patches(desk["gd"]) == []


def test_a_sender_without_the_group_gets_the_plain_sentence_no_card_and_no_provider_call(desk):
    for line in ("Remova o arquivo openhora-mark.png do drive", "Remova o arquivo openhora-ma do drive em /openhora"):
        out = say(desk, line, PLAIN_KEY)
        assert no_delete(out["reply"]) and out["ran"] is False and out["pending_id"] is None and "resend" not in out
    assert desk["search"].calls == [] and desk["gd"].requests == [] and open_cards(desk) == []
    with pytest.raises(ops.OpsError) as typed:
        ops.file_trash(desk["path"], "openhora-mark.png", channel="messaging", sender=PLAIN_KEY)
    assert "is not enabled for this channel" in str(typed.value) and desk["search"].calls == []


def test_vacuity_a_sender_who_holds_the_group_does_not_get_the_sentence(desk):
    assert not pk.said(say(desk, "Remova o arquivo openhora-mark.png do drive")["reply"], "PHONE_NO_FILE_DELETE", PT)


# --- lists ------------------------------------------------------------------------------------------------------------------------------------


def two_matches(desk):
    desk["ms"].add_file(fod.FILE_ID, "openhora-mark.png", b"od mark")
    ops_file_read.forget_lists()


def assert_list(reply):
    """The reply is the numbered list of the two files that fit: the question, then one line for each."""
    pick, first, second = reply.split("\n")
    pk.assert_said(pick, "FT_SEVERAL_PICK", PT, count=2)
    pk.assert_said(first, "FR_ITEM", PT, n=1, name="openhora-mark.png", folder="openhora", account="OneDrive")
    pk.assert_said(second, "FR_ITEM", PT, n=2, name="openhora-mark.png", folder="Arquivos › openhora", account="Google Drive")


def test_two_matches_give_a_numbered_list_and_o_2_opens_the_card_of_that_file(desk):
    two_matches(desk)
    out = say(desk, "Remova o arquivo openhora-mark.png")
    assert_list(out["reply"])
    assert "resend" not in out and open_cards(desk) == []
    picked = say(desk, "o 2")
    started = started_of(desk, picked)
    card_sent(picked["reply"], picked["resend"])
    assert effect_doc(desk, started)["target"]["id"] == fdw.FILE_ID and effect_doc(desk, started)["account"] == "google"
    assert pk.said(card_lines(desk, started)[0], "CARD_FILE_CODE_TRASH", PT), "a file chosen by its number is the person's choice: the card does not ask"
    assert patches(desk["gd"]) == [] and patches(desk["ms"]) == []


def test_o_1_opens_the_card_of_the_other_file_and_the_list_lasts_one_line(desk):
    two_matches(desk)
    say(desk, "Remova o arquivo openhora-mark.png")
    first = say(desk, "o 1")
    assert effect_doc(desk, started_of(desk, first))["target"]["id"] == f"{fod.DRIVE}/{fod.FILE_ID}"
    say(desk, "Remova o arquivo openhora-mark.png")
    say(desk, "bom dia")
    assert not pk.said(say(desk, "o 2")["reply"], "ACCT_CARD_SENT", PT, pending=0) and len(open_cards(desk)) == 1, "a pick after another line opens nothing"


def test_a_ultima_opens_the_card_of_the_second_file_of_a_trash_list_that_printed_every_file(desk):   # validate: allow english-only -- the Portuguese line under test
    two_matches(desk)
    say(desk, "Remova o arquivo openhora-mark.png")
    (record,) = ops_file_read._LISTS.values()
    assert record["purpose"] == "trash" and record["whole"] is True
    started = started_of(desk, say(desk, "a última"))   # validate: allow english-only -- the Portuguese line under test
    assert effect_doc(desk, started)["target"]["id"] == fdw.FILE_ID and effect_doc(desk, started)["account"] == "google", "the last row printed is the second file, as 'o 2' is"


def test_a_ultima_of_a_trash_list_that_printed_fewer_files_than_fit_opens_no_card_but_o_primeiro_does(desk, monkeypatch):   # validate: allow english-only -- the Portuguese line under test
    two_matches(desk)
    real = ops_file_trash._outcome
    monkeypatch.setattr(ops_file_trash, "_outcome", lambda *a, **k: dict(real(*a, **k), count=10))      # the list says 10 files fit and prints 2
    say(desk, "Remova o arquivo openhora-mark.png")
    (record,) = ops_file_read._LISTS.values()
    assert record["whole"] is False
    assert say(desk, "a última")["reply"] != SENT.format(n=0) and open_cards(desk) == []   # validate: allow english-only -- the Portuguese line under test
    say(desk, "Remova o arquivo openhora-mark.png")
    assert effect_doc(desk, started_of(desk, say(desk, "o primeiro")))["target"]["id"] == f"{fod.DRIVE}/{fod.FILE_ID}"


def test_a_pick_asks_the_right_and_the_grant_again(desk):
    two_matches(desk)
    say(desk, "Remova o arquivo openhora-mark.png")
    accept(desk["path"], policies=PROFILES, messaging={"senders": SENDERS}, accounts={**ACCOUNTS, "google": {"address": "pat@example.com", "folders": {"cv": "Cv_Folder_0001"}}},
           language="pt-BR")
    out = say(desk, "o 2")
    assert "resend" not in out and open_cards(desk) == [] and patches(desk["gd"]) == []


# --- OneDrive --------------------------------------------------------------------------------------------------------------------------------


def test_the_same_flow_on_onedrive_opens_the_card_and_after_the_approval_one_delete_with_if_match_moves_it_to_the_recycle_bin(desk):
    item_ = desk["ms"].add_file(fod.FILE_ID, "relatorio.pdf", b"%PDF-1.4 the report", mime="application/pdf")
    out = say(desk, "Remova o arquivo relatorio.pdf do onedrive")
    started = started_of(desk, out)
    doc = effect_doc(desk, started)
    lines = card_lines(desk, started)
    assert doc["account"] == "microsoft" and doc["target"] == {"kind": "file", "label": "default", "id": f"{fod.DRIVE}/{fod.FILE_ID}"} and doc["base"]["parent"] == fod.FOLDER_ID
    assert doc["base"]["root"] == "/Documents/openhora" and doc["base"]["path"] == "openhora" and doc["base"]["etag"] == desk["ms"].etag(item_)
    card = "\n".join(lines)
    assert pk.said(card, "CARD_FILE_NAME", PT, name="relatorio.pdf", service="OneDrive") and pk.said(card, "CARD_FILE_FOLDER", PT, folder="openhora") and pk.said(card, "CARD_FILE_TRASH_ONEDRIVE", PT)
    assert patches(desk["ms"]) == [] and fod.FILE_ID in desk["ms"].items
    done = approve(desk, started, "messaging", OWNER_KEY)
    assert done["result"]["written"] is True and done["result"]["moved_to_trash"] is True and done["result"]["id"] == f"{fod.DRIVE}/{fod.FILE_ID}"
    sent = patches(desk["ms"])
    assert [(r["method"], r["path"], r["if_match"]) for r in sent] == [("DELETE", f"/v1.0/drives/{fod.DRIVE}/items/{fod.FILE_ID}".replace("!", "!"), desk["ms"].etag(item_))]
    assert fod.FILE_ID not in desk["ms"].items and fod.FILE_ID in desk["ms"].bin and desk["ms"].violations == []


def test_a_onedrive_file_that_changed_since_the_card_is_stale_and_nothing_is_deleted(desk):
    item_ = desk["ms"].add_file(fod.FILE_ID, "relatorio.pdf", b"%PDF-1.4 the report", mime="application/pdf")
    started = started_of(desk, say(desk, "Remova o arquivo relatorio.pdf do onedrive"))
    item_["n"] += 1
    with pytest.raises(ops.OpsError) as stale:
        approve(desk, started, "messaging", OWNER_KEY)
    assert "not the one the task read" in str(stale.value) and patches(desk["ms"]) == [] and fod.FILE_ID in desk["ms"].items


# --- the interpreter and the typed form ------------------------------------------------------------------------------------------------------


def test_a_line_the_code_does_not_read_goes_to_the_interpreter_which_chooses_the_operation_and_the_code_finds_the_file(desk):
    desk["answer"]["text"] = json.dumps({"v": 1, "kind": "op", "op": "file-trash", "slots": {"file": "openhora-mark.png", "service": "google drive"}})
    out = say(desk, "Mande para a lixeira o openhora-mark.png do google drive")
    card_sent(out["reply"], out["resend"])
    assert effect_doc(desk, started_of(desk, out))["target"]["id"] == fdw.FILE_ID and patches(desk["gd"]) == []
    assert {s for s, _, _ in desk["search"].calls} == {"google"}, "the account words narrow the search"


def test_the_typed_operation_opens_the_card_lists_or_says_none(desk):
    out = ops.file_trash(desk["path"], "openhora-mark.png", folder="openhora", channel="terminal")
    assert out["status"] == "card" and out["word"] == "files" and out["on_cards"] is True
    assert effect_doc(desk, out)["target"]["id"] == fdw.FILE_ID
    two_matches(desk)
    several = ops.file_trash(desk["path"], "openhora-mark", channel="terminal")
    assert several["status"] == "several" and several["count"] == 2 and "refs" not in several
    none = ops.file_trash(desk["path"], "arquivo que nao existe", channel="terminal")
    assert none["status"] == "none"
    with pytest.raises(ops.OpsError):
        ops.file_trash(desk["path"], "openhora-mark.png", account="dropbox", channel="terminal")


# --- no permanent delete -----------------------------------------------------------------------------------------------------------------------


def test_no_path_of_the_trash_reaches_a_permanent_delete(desk):
    for name in ("files_document", "effect_files", "step_files", "ops_file_trash", "ops_file_read", "phone_delete", "ops_step_seams"):
        text = (st.REPO / "runtime" / f"{name}.py").read_text(encoding="utf-8")
        assert not re.search(r"permanent_?delete|batch_?delete|empty_?trash|\.delete\(|files\.delete", text, re.I), name
    for name in ("gdrive", "onedrive"):
        text = (st.REPO / "providers" / "writer" / f"{name}.py").read_text(encoding="utf-8")
        assert not re.search(r"permanentDelete|batchDelete|emptyTrash|files\.delete", text), name
    assert files_document.OPERATIONS == ("create", "replace", "save", "trash"), "a fifth operation would be a new decision"
    started = started_of(desk, say(desk, "Remova o arquivo openhora-mark.png do drive"))
    doc = effect_doc(desk, started)
    verb, args = files_document.provider_args(doc)
    assert verb == "trash" and "--dry-run" not in args and "--confirmed" not in args
    assert [(r["method"], r["body"]) for r in files_document.requests(doc)] == [("GET", None), ("PATCH", {"trashed": True})]
    approve(desk, started, "messaging", OWNER_KEY)
    assert {r["method"] for r in desk["gd"].requests} <= {"GET", "PATCH"} and desk["gd"].violations == []
    assert [r["method"] for r in desk["gd"].requests].count("PATCH") == 1, "one request that trashes, and the writer's ledger holds the key"


# --- the other removals are unchanged ------------------------------------------------------------------------------------------------------------


NOT_FILES = ["remova o evento de amanhã", "Remova o corte de cabelo de amanhã da agenda", "apague o evento de sexta", "apague o e-mail do João", "mova o email para a lixeira",  # validate: allow english-only -- the lines under test
             "tire o evento da agenda", "delete the meeting from the calendar", "apague o lembrete", "Delete", "mostre o arquivo openhora-mark do drive"]  # validate: allow english-only -- the lines under test


@pytest.mark.parametrize("line", NOT_FILES)
def test_a_line_that_removes_an_event_or_a_mail_is_not_caught_by_the_file_trash(desk, line):
    ctx = ctx_of(desk)
    assert phone_delete.asks(line) is False and ops_file_trash.catches(ctx, line, "messaging", OWNER_KEY) is False and ops_file_trash.line(desk["path"], ctx, line, "messaging", OWNER_KEY, {}) is None


def test_vacuity_a_file_line_is_caught_for_both_senders(desk):
    ctx = ctx_of(desk)
    for key in (OWNER_KEY, PLAIN_KEY):
        assert ops_file_trash.catches(ctx, "Remova o arquivo openhora-mark.png do drive", "messaging", key) is True


@pytest.mark.parametrize("line, expected", [("Remova o arquivo openhora-mark.png do drive", "openhora-mark.png"), ("Remova o arquivo openhora-mark do drive em /openhora", "openhora-mark"),
                                            ('apague o arquivo "contrato de locacao" da pasta Marca', "contrato de locacao"), ("delete the file Report.pdf from my drive.", "Report.pdf"),
                                            ("por favor apague logo.png do onedrive", "logo.png"), ("apague o arquivo do drive", None), ("remova o evento de amanhã", None)])  # validate: allow english-only -- the lines under test
def test_the_name_code_reads_from_a_line_that_asks_to_delete_a_file(line, expected):
    assert phone_delete.name(line) == expected


# --- the group of its own (the independent review of #541) --------------------------------------------------------------------------------------


PROBE = "apague o arquivo e"      # the reviewer's probe: one letter fits a part of nearly every name


def test_the_reviewers_probe_gives_the_plain_sentence_and_lists_no_name_to_a_sender_with_files_write_and_no_read_files(desk):
    desk["gd"].add_file("Probe_ID_0001", "exame-medico.pdf", b"x", mime="application/pdf", parents=(SUB,))
    desk["gd"].add_file("Probe_ID_0002", "senhas.txt", b"x", mime="text/plain", parents=(SUB,))
    out = say(desk, PROBE, WRITER_KEY)
    assert no_delete(out["reply"]) and "resend" not in out and out["pending_id"] is None
    assert "exame" not in out["reply"] and "senhas" not in out["reply"] and "openhora-mark" not in out["reply"]
    assert desk["search"].calls == [] and desk["gd"].requests == [] and open_cards(desk) == []
    for line in ("Remova o arquivo openhora-mark.png do drive", "apague o arquivo senhas"):
        assert no_delete(say(desk, line, WRITER_KEY)["reply"])
    assert desk["search"].calls == []


def test_vacuity_a_sender_who_holds_files_trash_and_read_files_is_listed_the_names_the_probe_fits(desk):
    desk["gd"].add_file("Probe_ID_0001", "exame-medico.pdf", b"x", mime="application/pdf", parents=(SUB,))
    out = say(desk, PROBE, OWNER_KEY)
    assert not pk.said(out["reply"], "PHONE_NO_FILE_DELETE", PT) and "exame-medico.pdf" in out["reply"], "the oracle can fail: the same probe, for the sender who may see names, lists them"


def test_the_typed_operation_and_the_interpreter_also_refuse_a_sender_with_files_write_alone(desk):
    with pytest.raises(ops.OpsError) as typed:
        ops.file_trash(desk["path"], "e", channel="messaging", sender=WRITER_KEY)
    assert "is not enabled for this channel" in str(typed.value)
    desk["answer"]["text"] = json.dumps({"v": 1, "kind": "op", "op": "file-trash", "slots": {"file": "e"}})
    out = say(desk, "Mande para a lixeira o e", WRITER_KEY)
    assert "exame" not in out["reply"] and "resend" not in out and desk["search"].calls == [] and open_cards(desk) == []


def test_the_right_to_see_names_is_asked_again_in_code_when_a_profile_holds_files_trash_without_it(desk, monkeypatch):
    """The configuration refuses that pair at accept; if one slipped through (the file edited by hand), `permitted` and the reply still ask `read-files`."""
    ctx = ctx_of(desk)
    assert ops_file_trash.permitted(ctx, "messaging", OWNER_KEY) is True
    real = operations.permitted
    monkeypatch.setattr(operations, "permitted", lambda op, *a, **k: False if op == "file-read" else real(op, *a, **k))
    assert ops_file_trash.permitted(ctx, "messaging", OWNER_KEY) is False
    monkeypatch.setattr(operations, "refusal", lambda op, *a, **k: "error: /file-read is not enabled for this channel" if op == "file-read" else None)
    out = ops_file_trash.reply(desk["path"], ctx, {"file": "e"}, PROBE, "messaging", OWNER_KEY, {})
    assert "exame" not in out and desk["search"].calls == []


def test_files_write_no_longer_holds_the_trash_and_the_new_group_holds_only_it():
    assert operations.GROUPS["files-write"] == {"operations": ("file-create", "file-replace", "file-save"), "kind": None}
    assert operations.GROUPS["files-trash"] == {"operations": ("file-trash",), "kind": None}
    assert "files-trash" not in operations.DEFAULT_POLICY["messaging"] and "files-write" not in operations.DEFAULT_POLICY["messaging"]
    assert [g for g, v in operations.GROUPS.items() if "file-trash" in v["operations"]] == ["files-trash"]
    assert operations.permitted("file-trash", "messaging", {"messaging": ["read", "talk", "files-write", "approve-effect-files"]}) is False
    assert operations.permitted("file-trash", "messaging", {"messaging": ["read", "talk", "files-trash"]}) is True
    assert operations.GROUP_TEXT["files-trash"] == ("moves a file you name to the trash of your Google Drive or OneDrive, after you approve its card; "
                                                    "recoverable while it is in the trash (adds to read-files)")
    assert "trash" not in operations.GROUP_TEXT["files-write"], "the widening line of files-write is as it was"
    assert operations.group_refusal("messaging", "files-trash") is None


def test_a_project_that_accepted_files_write_sees_files_trash_as_a_widening_with_a_hash_when_it_is_added(desk):
    """The accept-config record keeps group names: a group that is added is a widening, and the hash of its list is typed to accept it."""
    import policy_widening
    path = desk["path"]
    before = ops.config(path)
    assert [w for w in before["widening"] if w["group"] == "files-trash"] == []
    raw = json.loads((Path(path) / "docs" / "workbench" / "runtime.json").read_text(encoding="utf-8"))
    raw["policies"]["writer"] = raw["policies"]["writer"] + ["read-files", "files-trash"]
    (Path(path) / "docs" / "workbench" / "runtime.json").write_text(json.dumps(raw), encoding="utf-8")
    after = ops.config(path)
    mine = [w for w in after["widening"] if w["group"] == "files-trash"]
    assert len(mine) == 1 and mine[0]["place"] == WRITER_KEY and mine[0]["means"] == operations.GROUP_TEXT["files-trash"] == policy_widening.means("messaging", "files-trash")
    assert after["widening_sha256"] and after["widening_sha256"] != before["widening_sha256"]
    with pytest.raises(ops.OpsError):
        ops.accept_config(path, after["sha256"])      # without the hash of the list it is not accepted
    ops.accept_config(path, after["sha256"], widen=after["widening_sha256"])
    assert not pk.said(say(desk, "Remova o arquivo openhora-mark.png do drive", WRITER_KEY)["reply"], "PHONE_NO_FILE_DELETE", PT)


def test_files_trash_without_read_files_is_refused_when_the_file_is_accepted_and_with_it_is_accepted(desk):
    path = desk["path"]
    for place in ("profile", "channel"):
        raw = json.loads((Path(path) / "docs" / "workbench" / "runtime.json").read_text(encoding="utf-8"))
        if place == "profile":
            raw["policies"]["writer"] = ["read", "talk", "files-trash"]
        else:
            raw["policies"] = {}
            raw["messaging"] = {"senders": {"telegram": [WRITER]}}
            raw["channels"] = {"messaging": ["read", "talk", "files-trash"]}
        (Path(path) / "docs" / "workbench" / "runtime.json").write_text(json.dumps(raw), encoding="utf-8")
        with pytest.raises(Exception) as refused:
            ops.accept_config(path, ops.config(path)["sha256"])
        assert "'files-trash' needs 'read-files' beside it" in str(refused.value), place
    accept(path, policies=dict(PROFILES, writer=["read", "talk", "files-trash", "read-files"]), messaging={"senders": SENDERS}, accounts=ACCOUNTS, language="pt-BR", channels=None)      # the vacuity: both groups are accepted
