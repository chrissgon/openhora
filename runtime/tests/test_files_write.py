"""Files in the person's own Drive and OneDrive (package W4a: runtime/ops_files.py, runtime/step_files.py, runtime/files_document.py, runtime/effect_files.py, the
writers providers/writer/gdrive.py and providers/writer/onedrive.py), end to end against the stand-in services of providers/writer/tests/ on 127.0.0.1: no Google
or Microsoft host is reached, no credential is real, every name is fictional and every address is on `.example`. The writers run as the processes the runtime
starts, with the minimum environment and the one account secret.

What is held here (the spec's "Done when" for W4a): a create is a card first and a write only after the approval of the hash of the exact document, and never
overwrites; a replace lands as a new revision, the previous one kept before the write, and only if the file is still what was read (stale otherwise, nothing sent);
a file a sender sent is saved only by that sender's approval and writes exactly the held bytes; a folder the project does not list is refused; a file of the
project outside docs/ is refused; a card that is not whole is not approvable from a phone; a lost answer is unknown and approving again writes nothing twice; every
request of every write path is recorded and asserted as the exact list.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_files_write.py
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

import standin_tree as st
from test_channel_grants import accept

sys.path.insert(0, str(st.REPO / "providers" / "writer" / "tests"))
import fake_drive_write as fdw  # noqa: E402
import fake_onedrive_write as fod  # noqa: E402

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_grants = st.load("ops_grants")
effects = st.load("effects")
steps = st.load("steps")
phrases = st.load("phrases")
project_config = st.load("project_config")
files_document = st.load("files_document")
effect_files = st.load("effect_files")
step_files = st.load("step_files")
ops_step_effects = st.load("ops_step_effects")
ops_step_seams = st.load("ops_step_seams")
attachments = st.load("attachments")
cards = st.load("messaging_cards")
operations = st.load("operations")

TEXT = "# CV 2026\n\nPat Example, engineer.\n"
NEW = "# CV 2026\n\nPat Example, senior engineer.\n"
GOOGLE = {"address": "pat@example.com", "folders": {"default": fdw.FOLDER_ID, "cv": "Cv_Folder_0001"}}
MICROSOFT = {"address": "casey.rivera@mail.example", "folders": {"default": fod.FOLDER_ID, "docs": "/Documents/openhora"}}
SENDER = "telegram:4242"
OTHER = "telegram:777"
PDF = b"%PDF-1.4 the signed contract"
TEST_VARIABLES = ("WRITER_GDRIVE_API_BASE", "WRITER_GDRIVE_TOKEN_URL", "WRITER_ONEDRIVE_API_BASE", "WRITER_ONEDRIVE_TOKEN_URL", "WRITER_ONEDRIVE_UPLOAD_HOSTS")
DRIVE_VERSION = "3@2026-10-10T09:00:00.000Z"


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(tmp_path / "evidence"))
    built = st.build(tmp_path, monkeypatch, lab)
    tree = built["tree"]
    for rel in ("providers/_google.py", "providers/_msgraph.py", "providers/secrets/resolver.py", "providers/secrets/password_managers.py",
                "providers/writer/gdrive.py", "providers/writer/onedrive.py", "providers/writer/_files_common.py"):
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(st.REPO / rel, tree / rel)
    gd, ms = fdw.FakeDriveWrite(), fod.FakeOneDriveWrite()
    gd.add_folder("Cv_Folder_0001", "cv")
    state = tmp_path / "writer-state"
    state.mkdir()
    os.chmod(state, 0o700)
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(state))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    for name, value in (("WRITER_GDRIVE_API_BASE", gd.base), ("WRITER_GDRIVE_TOKEN_URL", gd.token_url), ("WRITER_ONEDRIVE_API_BASE", ms.base),
                        ("WRITER_ONEDRIVE_TOKEN_URL", ms.token_url), ("WRITER_ONEDRIVE_UPLOAD_HOSTS", "127.0.0.1"),
                        ("GOOGLE_ACCOUNT_TOKEN", gd.record_json()), ("MICROSOFT_ACCOUNT_TOKEN", ms.record_json())):
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(ops_core, "ROOT", str(tree))
    resolver = project_config.resolver(str(tree))      # the test variables reach the writer the runtime starts; the interpreter is this one (no uv, no network)
    monkeypatch.setattr(resolver, "ENV_MINIMUM", resolver.ENV_MINIMUM + TEST_VARIABLES)
    monkeypatch.setattr(resolver, "interpreter_for", lambda path: [sys.executable])
    monkeypatch.setattr(project_config, "resolver", lambda workbench: resolver)
    path = built["project"] / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["accounts"] = {"google": GOOGLE, "microsoft": MICROSOFT}
    path.write_text(json.dumps(raw), encoding="utf-8")
    project = str(built["project"])
    shown = ops.config(project)
    ops.accept_config(project, shown["sha256"], widen=shown["widening_sha256"])
    (built["project"] / "docs" / "outputs").mkdir(parents=True, exist_ok=True)
    yield {**built, "path": project, "gd": gd, "ms": ms, "tmp": tmp_path, "state": state}
    gd.close()
    ms.close()


# --- helpers ------------------------------------------------------------------------------------------------------------------------------


def ctx_of(world):
    return ops_core.context(world["path"])


def item_of(world, started):
    ctx = ctx_of(world)
    return ctx["store"].pending_get(ctx["conn"], started["pending"])


def effect_doc(world, started):
    ctx = ctx_of(world)
    return json.loads((Path(ops_step_effects.effect_dir(ctx["cfg"], started["task"], 0)) / "effect.json").read_text(encoding="ascii"))


def approve(world, started, channel="terminal", sender=None):
    item = item_of(world, started)
    return ops.approve(world["path"], started["pending"], item["payload_sha256"], channel=channel, sender=sender)


def register(world, source_id, source_type, origin, origin_version):
    ctx = ctx_of(world)
    store = ctx["store"]
    store.source_add(ctx["conn"], source_id=source_id, source_type=source_type, origin=origin)
    store.source_version_add(ctx["conn"], source_id=source_id, version=1, label="import", by="runtime", kind="markdown", original_name="o", original_sha256=sha("x"),
                             original_bytes=1, converted_name="c", converted_sha256=sha("y"), converted_bytes=1, converter="none", converter_version=None,
                             warnings=[], catalog={}, origin_version=origin_version, imported_at="2026-10-10T09:00:00Z")


def seed_drive(world, data=b"old text\n", name="CV 2026.md"):
    meta = world["gd"].add_file(fdw.FILE_ID, name, data)
    register(world, "cv", "drive", fdw.FILE_ID, DRIVE_VERSION)
    return meta


def seed_onedrive(world, data=b"old text\n", name="CV 2026.md"):
    item = world["ms"].add_file(fod.FILE_ID, name, data)
    register(world, "cv-od", "onedrive", f"{fod.DRIVE}/{fod.FILE_ID}", world["ms"].ctag(item))
    return item


def hold(world, data=PDF, name="Contract.pdf", sender="4242", kind="pdf"):
    """A file a sender sent, held as the bridge holds it: the row of the store, and the bytes under <data_dir>/attachments/held/<id>/."""
    ctx = ctx_of(world)
    row = ctx["store"].attachment_add(ctx["conn"], platform="telegram", ref_sha256=sha(f"ref-{sender}-{name}"), sender=sender, profile=None, name=name, declared_type=None,
                                      declared_bytes=len(data), kind=kind, sha256=sha(data), size=len(data), target=None, label=None)
    token, incoming = attachments.make_incoming(ctx["cfg"]["data_dir"])
    with open(os.path.join(incoming, attachments.CONTENT), "wb") as f:
        f.write(data)
    attachments.keep_held(ctx["cfg"]["data_dir"], row["id"], incoming, attachments.CONTENT)
    return row["id"]


def reads(requests):
    return [(r["method"], r["path"]) for r in requests]


def open_decisions(world):
    ctx = ctx_of(world)
    return ctx["store"].pending_list(ctx["conn"], "open")


# --- create -------------------------------------------------------------------------------------------------------------------------------


def test_a_create_is_a_card_first_and_a_write_only_after_the_approval_of_the_hash_of_its_exact_document(world):
    gd = world["gd"]
    started = ops.file_create(world["path"], "google", "CV 2026.md", content=TEXT)
    assert started["word"] == "files" and started["on_cards"] is True
    assert reads(gd.requests) == [("GET", f"/drive/v3/files/{fdw.FOLDER_ID}"), ("GET", "/drive/v3/files")], "the preparation only reads"
    assert [f for f in gd.files if f != fdw.FOLDER_ID and f != "Cv_Folder_0001"] == []
    item = item_of(world, started)
    doc = effect_doc(world, started)
    assert item["kind"] == "effect" and item["title"] == "Files: new file" and item["payload"]["card"] and not item["payload"]["effect"].get("content")
    assert item["body"] == phrases.card_text(item["payload"]["card"]) and files_document.guttered(TEXT) in item["body"] and "Pat Example" in item["body"]
    assert doc["effect"] == "files" and doc["operation"] == "create" and doc["content"]["text"] == TEXT and doc["content"]["sha256"] == sha(TEXT)
    assert doc["target"] == {"kind": "folder", "label": "default", "id": fdw.FOLDER_ID} and doc["name"] == "CV 2026.md" and doc["account"] == "google"
    assert doc["dry_run_sha256"] == files_document.dry_run_sha256(doc) and item["payload_sha256"] == sha(effects._text(doc))
    assert item["payload_sha256"] in item["body"], "the card says the hash the approval covers"
    done = approve(world, started)
    assert done["task_state"] == "done" and done["result"]["written"] is True and done["result"]["replayed"] is False
    assert reads(gd.requests) == [("GET", f"/drive/v3/files/{fdw.FOLDER_ID}"), ("GET", "/drive/v3/files"),
                                  ("GET", f"/drive/v3/files/{fdw.FOLDER_ID}"), ("GET", "/drive/v3/files"), ("POST", "/upload/drive/v3/files")]
    created = [m for m in gd.files.values() if m["name"] == "CV 2026.md"]
    assert len(created) == 1 and created[0]["content"] == TEXT.encode("utf-8") and created[0]["parents"] == [fdw.FOLDER_ID]
    assert gd.violations == [] and all(r["bearer"] for r in gd.requests)
    assert done["result"]["sha256"] == sha(TEXT) and done["result"]["idempotency_key"] == doc["idempotency_key"] and done["result"]["id"] == created[0]["id"]


def test_limit_55_nothing_is_written_for_another_hash_a_wrong_approval_or_an_edited_effect_file(world):
    gd = world["gd"]
    started = ops.file_create(world["path"], "google", "CV 2026.md", content=TEXT)
    item = item_of(world, started)
    with pytest.raises(ops.OpsError):
        ops.approve(world["path"], started["pending"], "0" * 64, channel="terminal")
    ctx = ctx_of(world)
    path = Path(ops_step_effects.effect_dir(ctx["cfg"], started["task"], 0)) / effects.EFFECT_FILE
    original = path.read_bytes()
    path.write_bytes(original.replace(b"senior", b"junior").replace(b"engineer", b"manager"))      # an effect file edited after the preview has another hash
    with pytest.raises(ops.OpsError) as edited:
        ops.approve(world["path"], started["pending"], item["payload_sha256"], channel="terminal")
    assert "nothing was written" in str(edited.value)
    path.write_bytes(original.replace(b"Pat Example, engineer", b"Pat Example, boss"))
    with pytest.raises(ops.OpsError):
        ops.approve(world["path"], started["pending"], item["payload_sha256"], channel="terminal")
    assert [m for m, _ in reads(gd.requests) if m != "GET"] == [], "no write was sent"
    path.write_bytes(original)
    assert approve(world, started)["result"]["written"] is True
    with pytest.raises(ops.OpsError):
        approve(world, started)
    assert [m for m, _ in reads(gd.requests)].count("POST") == 1, "written once"


def test_the_effect_module_refuses_an_approval_of_another_document_even_when_called_directly(world):
    started = ops.file_create(world["path"], "google", "CV 2026.md", content=TEXT)
    doc = effect_doc(world, started)
    calls = []
    for approval in ({"scope": "action", "status": "pending-execution", "payload_sha256": "0" * 64}, {"scope": "plan", "status": "pending-execution", "payload_sha256": sha(effects._text(doc))},
                     {"scope": "action", "status": "done", "payload_sha256": sha(effects._text(doc))}, None):
        with pytest.raises(effects.EffectError) as refused:
            effect_files.execute(doc, approval, lambda verb, args, implementation: calls.append(verb), doc["idempotency_key"], str(world["data"]), world["path"])
        assert refused.value.kind == "deviation"
    with pytest.raises(effects.EffectError):
        effect_files.execute(doc, {"scope": "action", "status": "pending-execution", "payload_sha256": sha(effects._text(doc))},
                             lambda verb, args, implementation: calls.append(verb), "files-" + "0" * 32, str(world["data"]), world["path"])
    assert calls == [] and world["gd"].requests[2:] == []


def test_a_create_never_overwrites_and_the_refusal_leaves_nothing_behind(world):
    gd = world["gd"]
    gd.add_file(fdw.FILE_ID, "CV 2026.md", b"the person's own text\n")
    with pytest.raises(ops.OpsError) as taken:
        ops.file_create(world["path"], "google", "CV 2026.md", content=TEXT)
    assert "already in that folder" in str(taken.value) and "never replaces" in str(taken.value)
    assert open_decisions(world) == [] and gd.files[fdw.FILE_ID]["content"] == b"the person's own text\n"
    assert [m for m, _ in reads(gd.requests)] == ["GET", "GET"]


def test_a_folder_the_project_does_not_list_is_refused_even_though_the_token_could_reach_it(world):
    with pytest.raises(ops.OpsError) as refused:
        ops.file_create(world["path"], "google", "CV 2026.md", content=TEXT, folder="elsewhere")
    assert "elsewhere" in str(refused.value) and "accounts.google.folders" in str(refused.value) and "default" in str(refused.value)
    assert world["gd"].requests == [] and open_decisions(world) == []
    with pytest.raises(ops.OpsError):
        ops.file_create(world["path"], "google", "CV 2026.md", content=TEXT, folder="../x")
    assert world["gd"].requests == []


def test_the_folder_a_name_lists_is_the_one_written_to_and_a_changed_accounts_file_stops_the_write(world):
    gd = world["gd"]
    started = ops.file_create(world["path"], "google", "CV 2026.md", content=TEXT, folder="cv")
    assert effect_doc(world, started)["target"] == {"kind": "folder", "label": "cv", "id": "Cv_Folder_0001"}
    path = Path(world["project"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["accounts"]["google"]["folders"]["cv"] = fdw.FOLDER_ID      # the file now lists another folder under that name, and it is not accepted yet
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ops.OpsError) as moved:
        approve(world, started)
    assert "configuration" in str(moved.value), "a changed accounts file is not accepted yet: the project is not configured for the write"
    assert [m for m, _ in reads(gd.requests) if m == "POST"] == []
    ops.accept_config(world["path"], ops.config(world["path"])["sha256"], widen=ops.config(world["path"])["widening_sha256"])
    with pytest.raises(ops.OpsError) as changed:
        approve(world, started)
    assert "nothing was written" in str(changed.value) and "not the one the file was prepared for" in str(changed.value)
    assert [m for m, _ in reads(gd.requests) if m == "POST"] == []


def test_a_create_in_a_onedrive_folder_given_by_id_or_by_path_sends_exactly_the_folder_read_and_one_put(world):
    ms = world["ms"]
    started = ops.file_create(world["path"], "microsoft", "CV 2026.md", content=TEXT)
    prepared = [(r["method"], r["path"]) for r in ms.requests]
    assert prepared == [("GET", f"/v1.0/me/drive/items/{fod.FOLDER_ID}"), ("GET", f"/v1.0/me/drive/items/{fod.FOLDER_ID}:/CV 2026.md")]
    done = approve(world, started)
    assert done["result"]["written"] is True
    assert [(r["method"], r["path"]) for r in ms.requests][len(prepared):] == [("GET", f"/v1.0/me/drive/items/{fod.FOLDER_ID}"),
                                                                              ("PUT", f"/v1.0/me/drive/items/{fod.FOLDER_ID}:/CV 2026.md:/content")]
    put = ms.requests[-1]
    assert put["query"] == {"@microsoft.graph.conflictBehavior": "fail"} and put["body"] == TEXT.encode("utf-8")
    ms.requests.clear()
    started = ops.file_create(world["path"], "microsoft", "Notes.txt", content="a line\n", folder="docs")
    assert effect_doc(world, started)["target"] == {"kind": "folder", "label": "docs", "id": "/Documents/openhora"}
    assert approve(world, started)["result"]["written"] is True
    assert ("PUT", "/v1.0/me/drive/root:/Documents/openhora/Notes.txt:/content") in [(r["method"], r["path"]) for r in ms.requests]
    assert ms.violations == [] and sorted(i["name"] for i in ms.items.values() if not i["folder"]) == ["CV 2026.md", "Notes.txt"]


def test_a_google_doc_is_made_from_markdown_text_in_a_google_drive_only(world):
    started = ops.file_create(world["path"], "google", "CV 2026.gdoc", content=TEXT)
    doc = effect_doc(world, started)
    assert doc["content"]["gdoc"] is True and doc["name"] == "CV 2026" and doc["content"]["media_type"] == "text/markdown"
    assert "Google Doc" in item_of(world, started)["body"]
    approve(world, started)
    post = world["gd"].requests[-1]
    metadata, media = fdw.split_multipart(post["body"], post["content_type"])
    assert json.loads(metadata[1])["mimeType"] == fdw.DOC and media[0]["content-type"] == "text/markdown" and media[1] == TEXT.encode("utf-8")
    with pytest.raises(ops.OpsError) as no:
        ops.file_create(world["path"], "microsoft", "CV 2026.gdoc", content=TEXT)
    assert "Google" in str(no.value) and world["ms"].requests == []


def test_a_file_of_the_project_is_the_content_only_from_docs_and_a_binary_one_is_not_on_a_card(world):
    project = Path(world["path"])
    (project / "docs" / "outputs" / "cv.md").write_text(TEXT, encoding="utf-8")
    (project / "docs" / "outputs" / "cv.docx").write_bytes(b"PK\x03\x04 a stand-in word file")
    (project / "notes.md").write_text("outside docs\n", encoding="utf-8")
    started = ops.file_create(world["path"], "google", "CV 2026.md", from_path="docs/outputs/cv.md")
    doc = effect_doc(world, started)
    assert doc["content"]["kind"] == "text" and doc["content"]["path"] == "docs/outputs/cv.md" and doc["content"]["text"] == TEXT and started["on_cards"] is True
    for bad in ("notes.md", "docs/../notes.md", "/etc/passwd", "docs/outputs/missing.md", "docs/workbench/state.md.comments.md"):
        with pytest.raises(ops.OpsError):
            ops.file_create(world["path"], "google", "Other.md", from_path=bad)
    binary = ops.file_create(world["path"], "google", "Report.docx", from_path="docs/outputs/cv.docx")
    assert binary["on_cards"] is False and effect_doc(world, binary)["content"]["kind"] == "file" and effect_doc(world, binary)["content"]["text"] is None
    assert "Its content is not on this card" in item_of(world, binary)["body"]
    accept(world["path"], {"messaging": ["read", "approve-effect-files"]})
    with pytest.raises(ops.OpsError) as card:
        approve(world, binary, "messaging", SENDER)
    assert "more than a card can show" in str(card.value)
    assert approve(world, binary)["result"]["written"] is True
    assert [m for m in world["gd"].files.values() if m["name"] == "Report.docx"][0]["content"] == b"PK\x03\x04 a stand-in word file"
    (project / "docs" / "outputs" / "cv.docx").write_bytes(b"PK\x03\x04 edited after the preview")
    again = ops.file_create(world["path"], "google", "Report2.docx", from_path="docs/outputs/cv.docx")
    (project / "docs" / "outputs" / "cv.docx").write_bytes(b"PK\x03\x04 edited again, after the card")
    with pytest.raises(ops.OpsError) as stale:
        approve(world, again)
    assert "not the file the task read" in str(stale.value) or "changed" in str(stale.value)
    assert [m for m in world["gd"].files.values() if m["name"] == "Report2.docx"] == []


@pytest.mark.parametrize("name, content, why", [
    ("CV 2026.pdf", "x\n", "must end in one of"), ("CV/2026.md", "x\n", "file name"), ("-x.md", "x\n", "file name"), ("x.md.", "x\n", "file name"),
    ("CV 2026.docx", "a text cannot become a word file\n", "cannot replace"), ("CV 2026.md", "  \n", "empty"), ("CV 2026.md", "a\u202eb\n", "invisible"),
    ("CV 2026.md", "token = ghp_" + "a" * 36 + "\n", "credential"), ("CV 2026.md", "x" * (64 * 1024 + 1), "over 65536 bytes")])
def test_a_name_or_a_text_outside_the_closed_rules_is_refused_and_nothing_is_made(world, name, content, why):
    with pytest.raises(ops.OpsError) as refused:
        ops.file_create(world["path"], "google", name, content=content)
    assert why in str(refused.value), str(refused.value)
    assert open_decisions(world) == [] and world["gd"].requests == [], "the arguments are refused before the service is asked anything"


def test_one_source_of_the_content_and_an_account_the_project_lists_are_needed(world):
    for kwargs in ({}, {"content": "a", "content_file": "b"}, {"content": "a", "from_path": "docs/x.md"}):
        with pytest.raises(ops.OpsError) as refused:
            ops.file_create(world["path"], "google", "CV 2026.md", **kwargs)
        assert refused.value.code == 2 and "one of the two" in str(refused.value)
    path = Path(world["project"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["accounts"].pop("microsoft")
    path.write_text(json.dumps(raw), encoding="utf-8")
    ops.accept_config(world["path"], ops.config(world["path"])["sha256"])
    with pytest.raises(ops.OpsError) as missing:
        ops.file_create(world["path"], "microsoft", "CV 2026.md", content=TEXT)
    assert missing.value.code == 3 and world["ms"].requests == []


def test_a_lost_answer_is_unknown_and_approving_again_finds_the_file_and_writes_nothing_twice(world):
    gd = world["gd"]
    started = ops.file_create(world["path"], "google", "CV 2026.md", content=TEXT)
    gd.lose_answer = "POST"
    with pytest.raises(ops.OpsError) as unknown:
        approve(world, started)
    assert "unknown" in str(unknown.value) and ctx_of(world)["store"].pending_get(ctx_of(world)["conn"], started["pending"])["status"] == "open"
    assert len([m for m in gd.files.values() if m["name"] == "CV 2026.md"]) == 1
    gd.lose_answer = None
    done = approve(world, started)
    assert done["task_state"] == "done" and done["result"]["replayed"] is True
    assert len([m for m in gd.files.values() if m["name"] == "CV 2026.md"]) == 1 and [m for m, _ in reads(gd.requests)].count("POST") == 1


# --- replace ------------------------------------------------------------------------------------------------------------------------------


def test_a_replace_on_drive_keeps_the_replaced_revision_before_it_writes_and_lands_as_a_new_revision(world):
    gd = world["gd"]
    meta = seed_drive(world)
    head = meta["revisions"][-1]["id"]
    started = ops.file_replace(world["path"], "google", "cv", content=NEW)
    assert reads(gd.requests) == [("GET", f"/drive/v3/files/{fdw.FILE_ID}")], "the preparation reads the file once"
    doc = effect_doc(world, started)
    assert doc["operation"] == "replace" and doc["target"] == {"kind": "file", "label": "cv", "id": fdw.FILE_ID} and doc["name"] == "CV 2026.md"
    assert doc["base"] == {"version": "3", "modified": "2026-10-10T09:00:00.000Z", "mime": "text/markdown", "md5": fdw.md5(b"old text\n"), "head_revision": head,
                           "source_version": DRIVE_VERSION}
    body = item_of(world, started)["body"]
    assert "only if it is still the file as read at" in body and "Replaces revision 3" in body and "belongs to this account: pat@example.com" in body
    assert "Drive keeps the replaced revision for ever (a file keeps at most 200 revisions for ever)" in body and files_document.guttered(NEW) in body
    done = approve(world, started)
    assert done["result"]["written"] is True
    assert reads(gd.requests)[1:] == [("GET", f"/drive/v3/files/{fdw.FILE_ID}"), ("GET", f"/drive/v3/files/{fdw.FILE_ID}"),
                                      ("PATCH", f"/drive/v3/files/{fdw.FILE_ID}/revisions/{head}"), ("PATCH", f"/upload/drive/v3/files/{fdw.FILE_ID}")]
    assert meta["content"] == NEW.encode("utf-8") and meta["version"] == "4" and meta["revisions"][0] == {"id": head, "keepForever": True} and len(meta["revisions"]) == 2
    assert gd.violations == []


def test_limit_56_a_replace_of_a_file_that_moved_since_it_was_read_writes_nothing_asks_again_and_says_so(world):
    gd = world["gd"]
    meta = seed_drive(world)
    started = ops.file_replace(world["path"], "google", "cv", content=NEW)
    meta["version"], meta["modifiedTime"] = "4", "2026-10-17T09:00:00.000Z"       # the person edited it in Drive meanwhile
    with pytest.raises(ops.OpsError) as stale:
        approve(world, started)
    assert "not the one the task read" in str(stale.value) and "version" in str(stale.value)
    assert [m for m, _ in reads(gd.requests) if m != "GET"] == [] and meta["content"] == b"old text\n" and meta["revisions"][0]["keepForever"] is False
    ctx = ctx_of(world)
    decision = ctx["store"].pending_get(ctx["conn"], started["pending"])
    assert decision["status"] == "resolved" and decision["resolution"] == "answered", "the decision is answered with the reason, not approved"
    assert ctx["store"].task_get(ctx["conn"], started["task"])["state"] != "done"


def test_a_replace_is_refused_when_the_source_is_behind_the_file_and_when_it_is_not_a_file_of_the_account(world):
    meta = seed_drive(world)
    meta["version"] = "4"
    with pytest.raises(ops.OpsError) as behind:
        ops.file_replace(world["path"], "google", "cv", content=NEW)
    assert "was read at version" in str(behind.value) and "refresh the source" in str(behind.value) and open_decisions(world) == []
    with pytest.raises(ops.OpsError) as wrong:
        ops.file_replace(world["path"], "microsoft", "cv", content=NEW)
    assert "not a file of your OneDrive account" in str(wrong.value)
    with pytest.raises(ops.OpsError) as none:
        ops.file_replace(world["path"], "google", "no-such-source", content=NEW)
    assert "not a file of your Google Drive account" in str(none.value)
    assert [m for m, _ in reads(world["gd"].requests) if m != "GET"] == [] and world["ms"].requests == []


def test_a_replace_of_a_google_native_doc_has_no_binary_revision_to_keep_and_a_text_cannot_replace_a_word_file(world):
    gd = world["gd"]
    meta = gd.add_file(fdw.NATIVE_ID, "CV 2026", b"doc text\n", native=True)
    register(world, "cv-doc", "drive", fdw.NATIVE_ID, f"{meta['version']}@{meta['modifiedTime']}")
    started = ops.file_replace(world["path"], "google", "cv-doc", content=NEW)
    assert effect_doc(world, started)["base"]["md5"] is None and effect_doc(world, started)["content"]["media_type"] == "text/markdown"
    approve(world, started)
    assert reads(gd.requests)[-1] == ("PATCH", f"/upload/drive/v3/files/{fdw.NATIVE_ID}") and not any("/revisions/" in p for _, p in reads(gd.requests))
    word = gd.add_file("Word_ID_00001", "Report.docx", b"PK", mime=files_document.MEDIA_TYPES["docx"])
    register(world, "report", "drive", "Word_ID_00001", f"{word['version']}@{word['modifiedTime']}")
    with pytest.raises(ops.OpsError) as mismatch:
        ops.file_replace(world["path"], "google", "report", content=NEW)
    assert "cannot replace a docx" in str(mismatch.value)
    sheet = gd.add_file("Sheet_ID_0001", "Budget", b"", native=True)
    sheet["mimeType"] = "application/vnd.google-apps.spreadsheet"
    register(world, "budget", "drive", "Sheet_ID_0001", f"{sheet['version']}@{sheet['modifiedTime']}")
    with pytest.raises(ops.OpsError) as kind:
        ops.file_replace(world["path"], "google", "budget", content=NEW)
    assert "cannot be written yet" in str(kind.value)


def test_limit_56_a_replace_on_onedrive_goes_through_an_upload_session_with_the_etag_and_a_moved_file_is_refused(world):
    ms = world["ms"]
    item = seed_onedrive(world)
    before = ms.etag(item)
    started = ops.file_replace(world["path"], "microsoft", "cv-od", content=NEW)
    assert [(r["method"], r["path"]) for r in ms.requests] == [("GET", f"/v1.0/drives/{fod.DRIVE}/items/{fod.FILE_ID}"), ("GET", "/v1.0/me/drive")], \
        "the preparation reads the item and the account's own drive (the file must be the account's)"
    doc = effect_doc(world, started)
    assert doc["base"]["etag"] == before and doc["base"]["ctag"] == ms.ctag(item) and doc["base"]["size"] == len(b"old text\n") and doc["base"]["source_version"] == ms.ctag(item)
    approve(world, started)
    assert [(r["method"], r["path"]) for r in ms.requests][2:] == [("GET", f"/v1.0/drives/{fod.DRIVE}/items/{fod.FILE_ID}"), ("GET", "/v1.0/me/drive"),
                                                                  ("GET", f"/v1.0/drives/{fod.DRIVE}/items/{fod.FILE_ID}"),
                                                                  ("POST", f"/v1.0/drives/{fod.DRIVE}/items/{fod.FILE_ID}/createUploadSession")]
    assert ms.requests[-1]["if_match"] == before and len(ms.uploads) == 1 and ms.uploads[0]["auth"] is None and item["content"] == NEW.encode("utf-8")
    seed2 = ms.add_file("01FILE000002!103", "Other.md", b"x\n")
    register(world, "other-od", "onedrive", f"{fod.DRIVE}/01FILE000002!103", ms.ctag(seed2))
    again = ops.file_replace(world["path"], "microsoft", "other-od", content=NEW)
    seed2["n"] += 1
    ms.uploads.clear()
    with pytest.raises(ops.OpsError) as stale:
        approve(world, again)
    assert "not the one the task read" in str(stale.value) and ms.uploads == [] and seed2["content"] == b"x\n"
    assert ms.violations == []


def test_a_file_that_moves_between_the_last_read_and_the_session_is_refused_by_the_precondition(world):
    ms = world["ms"]
    item = seed_onedrive(world)
    started = ops.file_replace(world["path"], "microsoft", "cv-od", content=NEW)
    ms.edit_during = lambda: item.__setitem__("n", item["n"] + 1)
    with pytest.raises(ops.OpsError) as moved:
        approve(world, started)
    assert "changed:" in str(moved.value) or "not the one the task read" in str(moved.value)
    assert ms.uploads == [] and item["content"] == b"old text\n"


def test_a_replace_with_a_file_of_the_same_type_from_the_project(world):
    ms = world["ms"]
    item = ms.add_file("01FILE000003!104", "Report.docx", b"PK old", mime=files_document.MEDIA_TYPES["docx"])
    register(world, "report-od", "onedrive", f"{fod.DRIVE}/01FILE000003!104", ms.ctag(item))
    project = Path(world["path"])
    (project / "docs" / "outputs" / "report.docx").write_bytes(b"PK new word file")
    (project / "docs" / "outputs" / "report.md").write_text("text\n", encoding="utf-8")
    with pytest.raises(ops.OpsError) as mismatch:
        ops.file_replace(world["path"], "microsoft", "report-od", from_path="docs/outputs/report.md")
    assert "cannot replace a docx" in str(mismatch.value)
    started = ops.file_replace(world["path"], "microsoft", "report-od", from_path="docs/outputs/report.docx")
    assert started["on_cards"] is False and effect_doc(world, started)["content"]["kind"] == "file"
    approve(world, started)
    assert item["content"] == b"PK new word file"


# --- save ---------------------------------------------------------------------------------------------------------------------------------


def test_a_save_writes_exactly_the_held_bytes_and_leaves_the_hold_as_it_was(world):
    gd = world["gd"]
    number = hold(world)
    started = ops.file_save(world["path"], "google", number)
    assert started["on_cards"] is True
    doc = effect_doc(world, started)
    assert doc["operation"] == "save" and doc["name"] == "Contract.pdf" and doc["content"]["kind"] == "held" and doc["content"]["attachment"] == number
    assert doc["content"]["sha256"] == sha(PDF) and doc["content"]["text"] is None and "sender" not in json.dumps(doc) and "4242" not in json.dumps(doc)
    body = item_of(world, started)["body"]
    assert "Saves the file you sent: Contract.pdf, 28 B, sha256 " + sha(PDF)[:12] in body and PDF.decode() not in body
    done = approve(world, started)
    assert done["result"]["written"] is True
    saved = [m for m in gd.files.values() if m["name"] == "Contract.pdf"]
    assert len(saved) == 1 and saved[0]["content"] == PDF and hashlib.sha256(saved[0]["content"]).hexdigest() == doc["content"]["sha256"]
    row = ctx_of(world)["store"].attachment_get(ctx_of(world)["conn"], number)
    assert row["status"] == "held" and attachments.read_held(str(world["data"]), number) == PDF, "the file stays held until a person adds or discards it"


def test_a_save_takes_a_name_and_a_listed_folder_and_refuses_a_type_the_bytes_are_not(world):
    number = hold(world)
    started = ops.file_save(world["path"], "microsoft", number, file_name="Signed contract.pdf", folder="docs")
    assert effect_doc(world, started)["name"] == "Signed contract.pdf" and effect_doc(world, started)["target"]["label"] == "docs"
    approve(world, started)
    assert world["ms"].uploads == [] and [i for i in world["ms"].items.values() if i["name"] == "Signed contract.pdf"][0]["content"] == PDF
    for name in ("Contract.docx", "Contract.md"):
        with pytest.raises(ops.OpsError) as mismatch:
            ops.file_save(world["path"], "google", number, file_name=name)
        assert "cannot replace" in str(mismatch.value) or "A pdf" in str(mismatch.value) or "type" in str(mismatch.value)
    with pytest.raises(ops.OpsError):
        ops.file_save(world["path"], "google", number, file_name="Contract.exe")
    with pytest.raises(ops.OpsError):
        ops.file_save(world["path"], "google", 99)
    with pytest.raises(ops.OpsError):
        ops.file_save(world["path"], "google", number, folder="elsewhere")


def test_a_save_from_a_messaging_app_is_for_the_sender_who_sent_the_file_and_only_that_sender_approves_it(world):
    gd = world["gd"]
    mine, theirs = hold(world, name="Mine.pdf", sender="4242"), hold(world, data=b"%PDF-1.4 theirs", name="Theirs.pdf", sender="777")
    accept(world["path"], {"messaging": ["read", "files-write", "approve-effect-files"]})
    with pytest.raises(ops.OpsError) as notmine:
        ops.file_save(world["path"], "google", theirs, channel="messaging", sender=SENDER)
    assert str(notmine.value) == attachments.NO_SUCH.format(n=theirs), "a file of someone else is answered as one that does not exist"
    assert open_decisions(world) == []
    started = ops.file_save(world["path"], "google", mine, channel="messaging", sender=SENDER)
    item = item_of(world, started)
    full = ops.pending(world["path"], started["pending"])
    assert full["effect_word"] == "files" and full["effect_on_cards"] is True
    with pytest.raises(ops.OpsError) as stranger:
        ops.approve(world["path"], started["pending"], item["payload_sha256"], channel="messaging", sender=OTHER)
    assert str(stranger.value) == attachments.NO_SUCH.format(n=mine)
    assert [m for m, _ in reads(gd.requests) if m != "GET"] == []
    done = ops.approve(world["path"], started["pending"], item["payload_sha256"], channel="messaging", sender=SENDER)
    assert done["result"]["written"] is True and [m for m in gd.files.values() if m["name"] == "Mine.pdf"][0]["content"] == PDF
    # the person at the terminal or on the page approves any save: the restriction is for a phone
    other = ops.file_save(world["path"], "google", theirs, file_name="Theirs copy.pdf")
    assert approve(world, other)["result"]["written"] is True


def test_a_save_needs_the_group_and_the_grant_on_a_messaging_app_and_the_default_has_neither(world):
    number = hold(world)
    with pytest.raises(ops.OpsError) as no:
        ops.file_save(world["path"], "google", number, channel="messaging", sender=SENDER)
    assert "not enabled" in str(no.value)
    accept(world["path"], {"messaging": ["read", "files-write"]})
    started = ops.file_save(world["path"], "google", number, channel="messaging", sender=SENDER)
    with pytest.raises(ops.OpsError) as card:
        approve(world, started, "messaging", SENDER)
    assert "terminal" in str(card.value)
    for channel in ("mcp", "chat", "invented"):
        with pytest.raises(ops.OpsError):
            ops.file_save(world["path"], "google", number, channel=channel, sender=SENDER)
    assert world["gd"].requests[-1]["method"] == "GET" and not [f for f in world["gd"].files.values() if f["name"] == "Contract.pdf"]


def test_limit_48_a_held_file_that_changed_or_is_gone_before_the_approval_writes_nothing(world):
    gd = world["gd"]
    number = hold(world)
    started = ops.file_save(world["path"], "google", number)
    held = Path(world["data"]) / "attachments" / "held" / str(number) / "original"
    os.chmod(held, 0o600)
    held.write_bytes(b"%PDF-1.4 swapped")
    with pytest.raises(ops.OpsError) as swapped:
        approve(world, started)
    assert "not the file the task read" in str(swapped.value) or "changed" in str(swapped.value)
    attachments.delete_held(str(world["data"]), number)
    again = ops.file_save(world["path"], "google", hold(world, name="Other.pdf"), file_name="Other copy.pdf")
    attachments.delete_held(str(world["data"]), effect_doc(world, again)["content"]["attachment"])
    with pytest.raises(ops.OpsError):
        approve(world, again)
    assert [m for m, _ in reads(gd.requests) if m == "POST"] == []
    with pytest.raises(ops.OpsError):
        ops.file_save(world["path"], "google", number)       # the row is held but the file is gone: nothing to save


# --- what the person reads -----------------------------------------------------------------------------------------------------------------


def test_the_card_is_said_line_by_line_in_the_projects_language_and_the_hash_is_the_same(world):
    started = ops.file_create(world["path"], "google", "CV 2026.md", content=TEXT)
    item = ops.pending(world["path"], started["pending"])
    en = cards.effect_card_text(item, None)
    pt = cards.effect_card_text(item, {"language": "pt-BR"})
    assert en == phrases.card_text(item["payload"]["card"]) and en.strip() == item["body"].strip()
    assert pt != en and "O código cria este arquivo depois da sua aprovação" in pt and "Pasta: default" in pt and files_document.guttered(TEXT) in pt  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    assert all(key.startswith("CARD_") for key, _ in item["payload"]["card"]) and phrases.card_valid(item["payload"]["card"])
    assert phrases.heading(item["title"], {"language": "pt-BR"}) == "Arquivos: novo arquivo"
    assert item["payload_sha256"] in en and item["payload_sha256"] in pt


def test_a_card_for_a_replace_and_a_save_has_a_portuguese_form_too(world):
    seed_drive(world)
    replace = ops.pending(world["path"], ops.file_replace(world["path"], "google", "cv", content=NEW)["pending"])
    save = ops.pending(world["path"], ops.file_save(world["path"], "google", hold(world))["pending"])
    for item, words in ((replace, ("Fonte: @cv", "Substitui a revisão 3")), (save, ("Salva o arquivo que você enviou: Contract.pdf",))):  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
        pt = cards.effect_card_text(item, {"language": "pt-BR"})
        assert pt and all(word in pt for word in words), pt
    assert phrases.heading(replace["title"], {"language": "pt-BR"}) == "Arquivos: nova revisão"  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    assert phrases.heading(save["title"], {"language": "pt-BR"}) == "Arquivos: salvar o arquivo que você enviou"  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column


def test_the_decision_payload_holds_a_summary_and_never_the_text(world):
    started = ops.file_create(world["path"], "google", "CV 2026.md", content=TEXT)
    payload = item_of(world, started)["payload"]
    assert payload["effect"] == files_document.summary(effect_doc(world, started)) and "Pat Example" not in json.dumps(payload["effect"])


# --- the structure ---------------------------------------------------------------------------------------------------------------------------


def test_the_operations_are_in_one_group_each_and_the_group_and_the_grant_exist():
    for name in ("file-create", "file-replace", "file-save"):
        row = operations.by_name(name)
        assert row["channels"] == ("terminal", "page", "messaging") and row["model"] is False and row.get("channel_arg") is True and "mcp" not in row["channels"]
        assert [g for g, v in operations.GROUPS.items() if name in v["operations"]] == ["files-write"]
    assert operations.GROUPS["approve-effect-files"] == {"operations": ("approve",), "kind": "effect:files"}
    assert "files" in operations.EFFECT_APPROVAL_WORDS and "approve-effect-files" in operations.GRANTS["messaging"]
    assert "approve-effect-files" in operations.IMPLIED["approve-effects"] and "approve-effect-files" not in operations.GRANTS["mcp"]
    assert "files-write" not in operations.DEFAULT_POLICY["messaging"]


def test_the_effect_kind_is_registered_under_its_word_and_is_a_step_kind_with_no_policy_or_gate():
    module = effects.module_for("files")
    assert module is effect_files and module.STEP is True and module.GATE is False and module.POLICY is False
    assert module.PROVIDER_CLASS == "writer:files" and module.APPROVAL_GROUP == "approve-effect-files" and "files" in effects.step_only_words()
    assert steps.kind_of("file-write").gates["approve"].word == "files" and steps.kind_of("file-write").unattended is False


def test_the_effect_module_starts_only_a_writer_that_declares_it_serves_the_class(world, tmp_path):
    tree = Path(world["tree"])
    assert effect_files.serves(str(tree), "gdrive") is None and effect_files.serves(str(tree), "onedrive") is None
    assert "not a writer of files" in effect_files.serves(str(tree), "google-calendar") and "not a writer of files" in effect_files.serves(str(tree), "../x")
    text = (tree / "providers" / "writer" / "gdrive.py").read_text(encoding="utf-8")
    (tree / "providers" / "writer" / "gdrive.py").write_text(text.replace('SERVES = "writer:files"', 'SERVES = "writer:calendar"'), encoding="utf-8")
    assert "does not declare" in effect_files.serves(str(tree), "gdrive")
    started_ok = effect_files.preflight(ops_core.context(world["path"])["cfg"], {"account": "google", "address": "pat@example.com", "operation": "replace",
                                                                                   "target": {}, "implementation": "gdrive"}, str(tree))
    assert started_ok is not None and started_ok[0] == 3


# --- from a phone -------------------------------------------------------------------------------------------------------------------------

CAPS = {"buttons": True, "max_buttons": 6, "max_text": 4096, "documents": False, "url_buttons": True, "reply_context": True}


def card_of(world, started, caps=None, cfg=None):
    item = ops.pending(world["path"], started["pending"])
    return cards.build("office", item, caps or CAPS, ops.config(world["path"])["channels"], "text", None, operations=operations, sender=SENDER, cfg=cfg)


def test_a_new_file_asked_for_and_approved_on_a_phone_needs_the_group_the_grant_and_a_whole_card(world):
    accept(world["path"], {"messaging": ["read", "files-write"]})
    started = ops.file_create(world["path"], "google", "CV 2026.md", content=TEXT, channel="messaging", sender=SENDER)
    card = card_of(world, started)
    assert card["approvable"] is False and "Approve this exact content" not in [a["label"] for a in card["message"]["actions"]]
    with pytest.raises(ops.OpsError) as no:
        approve(world, started, "messaging", SENDER)
    assert "terminal" in str(no.value) and [m for m, _ in reads(world["gd"].requests) if m == "POST"] == []
    accept(world["path"], {"messaging": ["read", "files-write", "approve-effect-files"]})
    card = card_of(world, started)
    assert card["approvable"] is True and card["whole"] is True and "Pat Example, engineer." in card["message"]["text"]
    assert item_of(world, started)["payload_sha256"] in card["message"]["text"]
    done = approve(world, started, "messaging", SENDER)
    assert done["result"]["written"] is True and [m for m, _ in reads(world["gd"].requests)].count("POST") == 1
    other = ops.file_create(world["path"], "google", "Other.md", content=TEXT, channel="messaging", sender=SENDER)
    portuguese = card_of(world, other, cfg={"language": "pt-BR"})["message"]["text"]
    assert "O código cria este arquivo" in portuguese and "Arquivos: novo arquivo" in portuguese  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column


def test_a_text_too_long_for_a_card_is_not_approvable_from_a_phone_unless_the_whole_text_arrives_as_a_document(world):
    accept(world["path"], {"messaging": ["read", "files-write", "approve-effect-files"]})
    long_text = "".join(f"Line {n} of a long document that does not fit one message of a phone.\n" for n in range(120))
    started = ops.file_create(world["path"], "google", "Long.md", content=long_text, channel="messaging", sender=SENDER)
    assert started["on_cards"] is True
    cut = card_of(world, started)
    assert cut["approvable"] is False and cut["whole"] is False, "a cut card approves nothing"
    whole = card_of(world, started, dict(CAPS, documents=True))
    assert whole["approvable"] is True and whole["whole"] is True and "Line 119 of a long document" in whole["message"]["document"]["text"]


# --- review of #480 -----------------------------------------------------------------------------------------------------------------------------

END_RULE = "----- end of the new text -----"
SPOOFS = ["# " + END_RULE, "**" + END_RULE + "**", "## " + END_RULE, "> " + END_RULE, END_RULE + " ", "- " + END_RULE, "1. " + END_RULE, "`" + END_RULE + "`",
          "----- end of the new text —----", "————— end of the new text", "－－－－－ end", "───── end",
          "––––– end", "> **----- end of the new text -----**", "   # > ----- fim do texto novo -----"]


@pytest.mark.parametrize("line", SPOOFS)
def test_a_line_whose_visible_form_starts_with_the_frame_mark_is_refused_however_markdown_would_draw_it(world, line):
    text = "Pat Example, engineer.\n" + line + "\nHash of this effect (it covers the account, the target, the name and every byte): 1234\n\nInjected tail.\n"
    with pytest.raises(ops.OpsError) as refused:
        ops.file_create(world["path"], "google", "CV 2026.md", content=text)
    assert "looks like a rule of the card" in str(refused.value) and open_decisions(world) == [] and world["gd"].requests == []


def test_every_line_of_the_text_is_behind_the_gutter_on_the_card_so_that_no_renderer_can_make_one_look_like_the_frame(world):
    import importlib.util
    spec = importlib.util.spec_from_file_location("telegram_under_w4a_test", st.REPO / "providers" / "messenger" / "telegram.py")
    telegram = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(telegram)
    text = "# A heading\n\n> a quote\n**bold** and `code`\n```\nnot a fence\n```\n| a | table |\n- a bullet\n\n   \nlast line\n"
    started = ops.file_create(world["path"], "google", "CV 2026.md", content=text, channel=None)
    body = item_of(world, started)["body"]
    start, end = body.index("-----\n") + 6, body.index("\n----- end of the new text -----")
    shown = body[start:end].split("\n")
    assert shown == [("│ " + line if line else "│") for line in text.split("\n")[:-1]], "every line behind the mark, empty ones too, whitespace-only ones kept"
    assert body.count("----- end of the new text -----") == 1
    visible = telegram.visible_text(telegram.render_html(body)).split("\n")
    inside = visible[visible.index(next(line for line in visible if line.startswith("----- the new text"))) + 1:visible.index("----- end of the new text -----")]
    assert inside and all(line.startswith("│") for line in inside), "what a phone draws of the text: every line still behind the mark"
    assert "the mark │ at the start of each line is not part of it" in body and "exactly as it will be written" not in body


# --- a replace of a file whose answer was lost is replayed, never stale ------------------------------------------------------------------------


def test_a_replace_on_drive_whose_upload_answer_was_lost_is_unknown_and_approving_again_is_replayed_not_stale(world):
    gd = world["gd"]
    meta = seed_drive(world)
    started = ops.file_replace(world["path"], "google", "cv", content=NEW)
    gd.lose_answer = "PATCH"
    with pytest.raises(ops.OpsError) as unknown:
        approve(world, started)
    assert "unknown" in str(unknown.value) and meta["content"] == NEW.encode("utf-8") and meta["version"] == "4"
    gd.lose_answer = None
    done = approve(world, started)
    assert done["task_state"] == "done" and done["result"]["replayed"] is True
    assert meta["version"] == "4" and len(meta["revisions"]) == 2, "no second revision"


def test_a_replace_on_onedrive_whose_upload_answer_was_lost_is_replayed_on_the_hash_and_the_persons_edit_is_stale(world):
    ms = world["ms"]
    item = seed_onedrive(world)
    started = ops.file_replace(world["path"], "microsoft", "cv-od", content=NEW)
    ms.lose_answer = "UPLOAD"
    with pytest.raises(ops.OpsError) as unknown:
        approve(world, started)
    assert "unknown" in str(unknown.value) and item["content"] == NEW.encode("utf-8")
    ms.lose_answer = None
    done = approve(world, started)
    assert done["task_state"] == "done" and done["result"]["replayed"] is True and len(ms.uploads) == 1
    other = ms.add_file("01FILE000009!109", "Other.md", b"x\n")
    register(world, "other-od", "onedrive", f"{fod.DRIVE}/01FILE000009!109", ms.ctag(other))
    again = ops.file_replace(world["path"], "microsoft", "other-od", content=NEW)
    ms.upload = lambda token, entry: (200, {})            # the upload does not land and the answer is lost ...
    ms.lose_answer = "UPLOAD"
    with pytest.raises(ops.OpsError):
        approve(world, again)
    other["content"], other["n"] = b"y" * len(NEW), other["n"] + 1       # ... and the person edits the file to bytes of the same size
    ms.lose_answer = None
    with pytest.raises(ops.OpsError) as stale:
        approve(world, again)
    assert "not the one the task read" in str(stale.value) and other["content"] == b"y" * len(NEW)
    ctx = ctx_of(world)
    assert ctx["store"].pending_get(ctx["conn"], again["pending"])["resolution"] == "answered"


# --- a replace is made only of a file the account owns -----------------------------------------------------------------------------------------


def test_a_replace_is_refused_for_a_file_the_account_does_not_own_and_the_card_names_the_account_that_does(world):
    gd, ms = world["gd"], world["ms"]
    shared = gd.add_file(fdw.FILE_ID, "Shared.md", b"x\n", owned=False)
    register(world, "shared", "drive", fdw.FILE_ID, f"{shared['version']}@{shared['modifiedTime']}")
    with pytest.raises(ops.OpsError) as refused:
        ops.file_replace(world["path"], "google", "shared", content=NEW)
    assert "is not owned by your Google Drive account" in str(refused.value)
    viewer = gd.add_file("Viewer_ID_001", "Viewer.md", b"x\n", can_edit=False)
    register(world, "viewer", "drive", "Viewer_ID_001", f"{viewer['version']}@{viewer['modifiedTime']}")
    with pytest.raises(ops.OpsError):
        ops.file_replace(world["path"], "google", "viewer", content=NEW)
    foreign = ms.add_file(fod.FILE_ID, "Foreign.md", b"x\n")
    foreign["drive"] = "b!SomeoneElsesDrive"
    register(world, "foreign", "onedrive", f"{fod.DRIVE}/{fod.FILE_ID}", ms.ctag(foreign))
    with pytest.raises(ops.OpsError) as other:
        ops.file_replace(world["path"], "microsoft", "foreign", content=NEW)
    assert "is not owned by your OneDrive account" in str(other.value)
    assert open_decisions(world) == [] and [m for m, _ in reads(gd.requests) if m != "GET"] == [] and ms.uploads == []
    seed_drive_owned = gd.add_file("Owned_ID_0001", "Mine.md", b"x\n")
    register(world, "mine", "drive", "Owned_ID_0001", f"{seed_drive_owned['version']}@{seed_drive_owned['modifiedTime']}")
    assert "belongs to this account: pat@example.com" in item_of(world, ops.file_replace(world["path"], "google", "mine", content=NEW))["body"]


# --- what becomes of the replaced revision is said for the service and the type ----------------------------------------------------------------


def test_the_card_says_what_becomes_of_the_replaced_revision_for_each_service_and_type_of_file(world):
    gd, ms = world["gd"], world["ms"]
    seed_drive(world)
    drive = item_of(world, ops.file_replace(world["path"], "google", "cv", content=NEW))["body"]
    assert "Drive keeps the replaced revision for ever" in drive and "at most 200" in drive and "stays in the file's history" not in drive
    native = gd.add_file(fdw.NATIVE_ID, "CV 2026", b"doc\n", native=True)
    register(world, "cv-doc", "drive", fdw.NATIVE_ID, f"{native['version']}@{native['modifiedTime']}")
    doc = item_of(world, ops.file_replace(world["path"], "google", "cv-doc", content=NEW))["body"]
    assert "A Google Doc keeps its own revision history" in doc and "not kept for ever" in doc and "Drive keeps the replaced revision" not in doc
    seed_onedrive(world)
    one = item_of(world, ops.file_replace(world["path"], "microsoft", "cv-od", content=NEW))["body"]
    assert "OneDrive keeps earlier versions by its own retention settings, not for ever" in one and "Drive keeps" not in one.replace("OneDrive keeps", "")


# --- a name taken at the write answers the decision; a token of another account writes nothing --------------------------------------------------


def test_a_name_taken_between_the_card_and_the_approval_answers_the_decision_and_writes_nothing(world):
    gd = world["gd"]
    started = ops.file_create(world["path"], "google", "CV 2026.md", content=TEXT)
    gd.add_file(fdw.FILE_ID, "CV 2026.md", b"made meanwhile\n")
    with pytest.raises(ops.OpsError) as taken:
        approve(world, started)
    assert "a file with that name is in the folder now" in str(taken.value)
    ctx = ctx_of(world)
    decision = ctx["store"].pending_get(ctx["conn"], started["pending"])
    assert decision["status"] == "resolved" and decision["resolution"] == "answered"
    assert [m for m, _ in reads(gd.requests) if m == "POST"] == [] and gd.files[fdw.FILE_ID]["content"] == b"made meanwhile\n"


def test_the_config_address_must_be_the_one_of_the_token_or_nothing_is_read_or_written(world):
    path = Path(world["project"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["accounts"]["google"]["address"] = "someone.else@example.org"
    path.write_text(json.dumps(raw), encoding="utf-8")
    shown = ops.config(world["path"])
    ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])
    with pytest.raises(ops.OpsError) as refused:
        ops.file_create(world["path"], "google", "CV 2026.md", content=TEXT)
    assert open_decisions(world) == [] and world["gd"].requests == [] and world["gd"].token_forms == []
    assert "another account" in str(refused.value) or "could not be read" in str(refused.value) or "account" in str(refused.value)


# --- the lessons of W1, for files -----------------------------------------------------------------------------------------------------------------


def test_a_plan_or_a_flow_cannot_carry_a_file_write_step_and_the_refused_words_are_the_ones_the_account_entry_uses(world):
    import account_start
    args = {"operation": "create", "account": "google", "name": "CV 2026.md", "content": TEXT}
    with pytest.raises(steps.StepFailure) as why:
        steps.plan_task("file-write", args, key="k", title="t", text="x")
    assert why.value.code == "not_plannable"
    ctx = ctx_of(world)
    with pytest.raises(steps.StepFailure) as again:
        steps.add_task(ctx["store"], ctx["conn"], "file-write", args, key="k", title="t", text="x")
    assert again.value.code == "not_plannable" and open_decisions(world) == []
    assert set(steps.ACCOUNT_WORDS) | {"send"} == set(account_start.WORDS) and step_files.fd.WORD in steps.ACCOUNT_WORDS


def test_the_current_name_of_a_file_and_the_name_of_a_file_a_sender_sent_are_not_shown_to_a_reader_who_may_not_see_them(world):
    seed_drive(world)
    replace = ops.file_replace(world["path"], "google", "cv", content=NEW)
    mine = hold(world, name="Private contract.pdf", sender="4242")
    save = ops.file_save(world["path"], "google", mine)
    accept(world["path"], {"messaging": ["read"]})
    for started, secret in ((replace, "CV 2026.md"), (save, "Private contract.pdf")):
        whole = json.dumps(ops.pending(world["path"], started["pending"]))
        assert secret in whole, "the person at the terminal sees it"
        for channel, sender in (("mcp", None), ("messaging", OTHER), ("messaging", None)):
            shown = ops.pending(world["path"], started["pending"], channel=channel, sender=sender)
            assert secret not in json.dumps(shown), (channel, sender)
            assert shown["body"].endswith(phrases.en("CARD_HIDDEN_NOTE_FILE")), (channel, sender)
        listed = ops.pending(world["path"], channel="mcp")
        assert secret not in json.dumps(listed)
    owner = ops.pending(world["path"], save["pending"], channel="messaging", sender=SENDER)
    assert "Private contract.pdf" in json.dumps(owner), "the sender who sent the file sees its name on the card they approve"
    assert "CV 2026.md" not in json.dumps(ops.pending(world["path"], replace["pending"], channel="messaging", sender=SENDER)), "the current name of a file is for a reader who holds ask-mail"
    # the card the bridge draws: from the whole decision (channel None), for the sender it is sent to
    def card_for(started, groups, sender):
        full = ops.pending(world["path"], started["pending"], reader=sender)      # the bridge asks per reader: booleans, never the sender's account
        return cards.build("office", full, CAPS, {"messaging": groups}, "text", None, operations=operations, sender=sender)
    for started, secret in ((replace, "CV 2026.md"), (save, "Private contract.pdf")):
        reader = card_for(started, ["read", "approve-effect-files", "ask-mail"], OTHER)
        other = card_for(started, ["read", "approve-effect-files"], OTHER)
        assert secret in reader["message"]["text"] and secret not in other["message"]["text"]
        assert other["approvable"] is False, "a card that leaves a line out is not approved where it is partial"
        assert reader["approvable"] is (started is replace), "a reader of mail sees the whole card of a replace; the save of a file a sender sent is approved by that sender alone"
    mine_card = card_for(save, ["read", "approve-effect-files"], SENDER)
    assert "Private contract.pdf" in mine_card["message"]["text"] and mine_card["approvable"] is True, "the sender of the file sees its name and may approve the save"
    assert "CV 2026.md" not in card_for(replace, ["read", "approve-effect-files"], SENDER)["message"]["text"]


def test_a_start_over_that_finds_the_source_pointing_to_another_file_is_refused_and_asks_to_name_it_again(world, monkeypatch):
    gd = world["gd"]
    meta = seed_drive(world)
    started = ops.file_replace(world["path"], "google", "cv", content=NEW)
    meta["version"] = "4"
    with pytest.raises(ops.OpsError):
        approve(world, started)       # stale: the task starts over from the step that reads
    other = gd.add_file("Other_ID_0001", "Other.md", b"x\n")
    real = ops_step_seams.FileSources.lookup
    monkeypatch.setattr(ops_step_seams.FileSources, "lookup", lambda self, source_id: {**real(self, source_id), "origin": "Other_ID_0001",
                                                                                          "origin_version": f"{other['version']}@{other['modifiedTime']}"})
    out = ops.run_step(world["path"], started["task"])
    assert out["ok"] is not True and out["code"] == "target_changed" and "name it again" in out["next"]
    assert [m for m, _ in reads(gd.requests) if m != "GET"] == []


@pytest.mark.parametrize("channel", ["invented", "chat", "mcp", ""])
def test_a_channel_the_policy_does_not_know_is_refused_never_taken_for_the_terminal(world, channel):
    number = hold(world)
    for call in (lambda: ops.file_create(world["path"], "google", "CV 2026.md", content=TEXT, channel=channel, sender=SENDER),
                 lambda: ops.file_save(world["path"], "google", number, channel=channel, sender=SENDER)):
        with pytest.raises(ops.OpsError):
            call()
    seed_drive(world)
    with pytest.raises(ops.OpsError):
        ops.file_replace(world["path"], "google", "cv", content=NEW, channel=channel, sender=SENDER)
    assert open_decisions(world) == [] and [m for m, _ in reads(world["gd"].requests) if m != "GET"] == []


# --- the second review of #480: what the readers other than the person at the terminal can see ------------------------------------------------


def approved_world(world):
    """A replace and a save, approved at the terminal: the person's file name and the name of the file a sender sent are in the world now."""
    seed_drive(world, name="Divorce papers.md")
    replace = ops.file_replace(world["path"], "google", "cv", content=NEW)
    mine = hold(world, name="Private contract.pdf", sender="4242")
    save = ops.file_save(world["path"], "google", mine)
    for started in (replace, save):
        approve(world, started)
    return replace, save


def test_the_record_of_an_executed_write_holds_no_name_and_a_reader_who_may_not_see_the_card_gets_no_result_at_all(world):
    replace, save = approved_world(world)
    secrets = ("Divorce papers.md", "Private contract.pdf")
    whole = ops.task(world["path"], save["task"])
    result = [p for p in whole["pending"] if p.get("payload", {}).get("result")][0]["payload"]["result"]
    assert result["written"] is True and "name" not in result and result["sha256"] and result["id"], "ids, numbers and hashes only"
    for started in (replace, save):
        for channel, sender in (("mcp", None), ("messaging", OTHER), ("messaging", None)):
            shown = ops.task(world["path"], started["task"], channel=channel, sender=sender)
            listed = ops.pending(world["path"], started["pending"], channel=channel, sender=sender)
            for secret in secrets:
                assert secret not in json.dumps(shown) and secret not in json.dumps(listed), (channel, sender, secret)
            assert all("result" not in (p.get("payload") or {}) for p in shown["pending"]) and "result" not in listed.get("payload", {}), (channel, sender)


def test_the_approval_row_the_state_file_and_the_artifact_hold_no_name_of_a_file(world):
    approved_world(world)
    ctx = ctx_of(world)
    state = (Path(world["path"]) / "docs" / "workbench" / "state.md").read_text(encoding="utf-8")
    rows = [a["what"] for a in ctx["store"].approvals_list(ctx["conn"])]
    assert len(rows) == 2 and "Divorce papers.md" not in state and "Private contract.pdf" not in state
    assert all("Divorce papers.md" not in what and "Private contract.pdf" not in what for what in rows)
    assert any("write a new revision of a registered file" in what and "the source cv" in what for what in rows)
    assert any("save a file the person sent" in what and "the folder default" in what for what in rows)
    shown = json.dumps(ops.artifact(world["path"], "docs/workbench/state.md"))
    assert "Private contract.pdf" not in shown and "Divorce papers.md" not in shown and "4242" not in shown


def test_a_refusal_made_when_the_card_is_prepared_does_not_echo_the_name_of_a_file(world):
    world["gd"].add_file("Taken_0001", "Private contract.pdf", b"x", mime="application/pdf")
    mine = hold(world, name="Private contract.pdf", sender="4242")
    with pytest.raises(ops.OpsError) as taken:
        ops.file_save(world["path"], "google", mine, file_name="Private contract.pdf")          # a name the person chose is never changed
    assert "name_taken" in str(taken.value) and "Private contract.pdf" not in str(taken.value)
    seed_drive(world, name="Divorce papers.md")
    world["gd"].files["File_ID_0001"]["owned"] = False
    with pytest.raises(ops.OpsError) as shared:
        ops.file_replace(world["path"], "google", "cv", content=NEW)
    assert "not_owned" in str(shared.value) and "Divorce papers.md" not in str(shared.value)
    assert "the file named on the request" in str(shared.value).lower() or "named on the request" in str(shared.value)
    ctx = ctx_of(world)
    for found in ctx["store"].tasks_list(ctx["conn"]):
        for channel in ("mcp", "messaging"):
            seen = json.dumps(ops.task(world["path"], found["id"], channel=channel, sender=OTHER if channel == "messaging" else None))
            assert "Private contract.pdf" not in seen and "Divorce papers.md" not in seen, (found["id"], channel)
    assert "Private contract.pdf" not in json.dumps(ops.status(world["path"])) and "Divorce papers.md" not in json.dumps(ops.status(world["path"]))
    for language in ("en", "pt-BR"):
        for key in ("ACCT_FILE_NOT_OWNED", "ACCT_FILE_NAME_TAKEN"):
            assert "{name}" not in phrases.text(key, {"language": language}, service="Google Drive"), (language, key)


def test_a_decision_never_returns_the_senders_account_and_the_card_of_a_save_is_approved_by_that_sender_alone(world):
    mine = hold(world, name="Private contract.pdf", sender="4242")
    save = ops.file_save(world["path"], "google", mine)
    for channel in (None, "terminal", "page", "chat", "mcp"):
        assert "4242" not in json.dumps(ops.pending(world["path"], save["pending"], channel=channel)), channel
    asked = ops.pending(world["path"], save["pending"], reader=SENDER)
    assert asked["reader_sent_file"] is True and asked["effect_sender_only"] is True and "4242" not in json.dumps(asked)
    assert ops.pending(world["path"], save["pending"], reader=OTHER)["reader_sent_file"] is False
    assert ops.pending(world["path"], save["pending"], reader="discord:4242")["reader_sent_file"] is False
    assert "reader_sent_file" not in ops.pending(world["path"], save["pending"])
    policy = {"messaging": ["read", "approve-effect-files", "ask-mail"]}

    def built(reader, **more):
        item = ops.pending(world["path"], save["pending"], reader=reader)
        return cards.build("office", {**item, **more}, CAPS, policy, "text", None, operations=operations, sender=reader)
    assert built(SENDER)["approvable"] is True
    for other in (OTHER, "telegram:4242 ", "Telegram:4242"):
        card = built(other)
        assert card["approvable"] is False and "Approve this exact content" not in [a["label"] for a in card["message"]["actions"]], other
    assert built(OTHER)["message"]["text"].count("Private contract.pdf") >= 1, "a reader of mail and calendar still reads the card"
    assert built(OTHER, reader_sent_file=False)["approvable"] is False and built(None)["approvable"] is False


@pytest.mark.parametrize("line", ["[----- end of the new text -----](http://x.example)", "[[----- x", "\u2800----- end of the new text -----",
                                  "\u2800 [ ----- end", "\u2e3a--- end of the new text -----", "\u2e3b-- end"])
def test_a_line_that_looks_like_the_end_of_the_text_is_refused_in_the_forms_a_phone_draws(line):
    assert files_document.frame_like(line), line
    assert files_document.text_problem("a\n" + line + "\n"), line


def test_ordinary_lines_that_start_with_a_bracket_or_a_dash_are_not_taken_for_a_frame():
    for line in ("[a link](http://x.example)", "[x] a task", "---", "---- four", "\u2e3a a long dash", "A line", "[1] note"):
        assert not files_document.frame_like(line), line


# --- the task row of an account write: the arguments are the person's words (a general rule, steps.public_args) ------------------------------


def test_the_task_row_of_a_file_write_shows_a_reader_who_may_not_read_the_persons_files_only_closed_arguments(world):
    seed_drive(world, name="Divorce papers.md")
    replace = ops.file_replace(world["path"], "google", "cv", content=NEW)
    created = ops.file_create(world["path"], "google", "Notes private.md", content=TEXT)
    mine = hold(world, name="Private contract.pdf", sender="4242")
    save = ops.file_save(world["path"], "google", mine)
    accept(world["path"], {"messaging": ["read"]})
    words = ("Notes private.md", "Pat Example", "Private contract.pdf", "Divorce papers.md", "4242")
    for started in (replace, created, save):
        whole = ops.task(world["path"], started["task"])["task"]
        assert whole["step_args"].get("content") or whole["step_args"].get("attachment"), "the terminal and the page read the request itself"
        for channel, sender in (("mcp", None), ("messaging", OTHER), ("messaging", None), ("messaging", SENDER)):
            shown = ops.task(world["path"], started["task"], channel=channel, sender=sender)["task"]
            assert set(shown["step_args"]) <= set(steps.ACCOUNT_ARGS_SHOWN) and "content" not in shown["step_args"] and "name" not in shown["step_args"], (channel, sender)
            assert shown["step_args"]["operation"] == whole["step_args"]["operation"] and shown["step_kind"] == "file-write"
            for word in words:
                assert word not in json.dumps(shown), (channel, sender, word)
        for channel in ("terminal", "page", "chat"):
            assert ops.task(world["path"], started["task"], channel=channel)["task"]["step_args"] == whole["step_args"], channel


def test_a_failure_sentence_of_a_file_write_is_cut_to_its_code_for_those_readers_and_a_reader_of_mail_gets_the_row_whole(world, monkeypatch):
    ctx = ctx_of(world)
    row = {"id": 1, "step_kind": "file-write", "step_args": {"operation": "create", "account": "google", "name": "Private contract.pdf", "content": "x"},
           "step_state": {"kind": "file-write", "failure": {"step": "prepare", "code": "name_taken", "field": "name", "provider": "", "next": "Private contract.pdf is taken", "at": "t"}}}
    cut = ops_grants.task_view(ctx, row, "mcp")
    assert cut["step_args"] == {"operation": "create", "account": "google"} and cut["step_state"]["failure"] == {"step": "prepare", "code": "name_taken", "field": "name", "provider": "", "at": "t"}
    assert row["step_args"]["name"] == "Private contract.pdf", "the stored row is untouched"
    assert ops_grants.task_view(ctx, row, None) is row and ops_grants.task_view(ctx, row, "page") is row
    other = {"id": 2, "step_kind": None, "step_args": None, "step_state": None}
    assert ops_grants.task_view(ctx, other, "mcp") is other, "a task that is not an account write is returned as it is"
    monkeypatch.setattr(ops_grants.item_refs, "may_read", lambda *a, **k: True)
    assert ops_grants.task_view(ctx, row, "messaging", SENDER) is row, "a reader of the person's mail and files gets the row whole"


def test_the_private_lines_of_a_files_card_show_and_approve_for_the_sender_whose_own_profile_lists_ask_mail_alone(world):
    """The real configuration (NR-2): `ask-mail` is in one listed sender's own profile, never in the channel's list. A replace shows the current name of the file
    to that sender alone; the save of a file a sender sent keeps its own rule (the sender who sent it, whatever the profile)."""
    from test_channel_grants_mailbox import accept as accept_holder      # the channel keeps the list without ask-mail; SENDER's profile `holder` lists it
    seed_drive(world)
    replace = ops.file_replace(world["path"], "google", "cv", content=NEW)
    accept_holder(world["path"], {"messaging": ["read", "approve-effect-files", "ask-mail"]})
    channels = ops.config(world["path"])["channels"]
    full = ops.pending(world["path"], replace["pending"], reader=SENDER)
    holder = cards.build("office", full, CAPS, channels, "text", None, operations=operations, sender=SENDER)
    full_other = ops.pending(world["path"], replace["pending"], reader=OTHER)
    other = cards.build("office", full_other, CAPS, channels, "text", None, operations=operations, sender=OTHER)
    assert "CV 2026.md" in holder["message"]["text"] and holder["approvable"] is True
    assert "CV 2026.md" not in other["message"]["text"] and other["approvable"] is False
