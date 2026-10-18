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
    assert item["body"] == phrases.card_text(item["payload"]["card"]) and TEXT.rstrip("\n") in item["body"] and "Pat Example" in item["body"]
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
    assert "only if it is still the file as read at" in body and "Replaces revision 3" in body and "stays in the file's history" in body and NEW.rstrip("\n") in body
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
    assert [(r["method"], r["path"]) for r in ms.requests] == [("GET", f"/v1.0/drives/{fod.DRIVE}/items/{fod.FILE_ID}")]
    doc = effect_doc(world, started)
    assert doc["base"]["etag"] == before and doc["base"]["ctag"] == ms.ctag(item) and doc["base"]["size"] == len(b"old text\n") and doc["base"]["source_version"] == ms.ctag(item)
    approve(world, started)
    assert [(r["method"], r["path"]) for r in ms.requests][1:] == [("GET", f"/v1.0/drives/{fod.DRIVE}/items/{fod.FILE_ID}")] * 2 + [
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
    assert pt != en and "O código cria este arquivo depois da sua aprovação" in pt and "Pasta: default" in pt and TEXT.rstrip("\n") in pt  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
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
