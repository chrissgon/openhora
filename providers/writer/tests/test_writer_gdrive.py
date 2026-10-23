"""Tests of the Drive writer (providers/writer/gdrive.py, package W4a) against the stand-in Drive (fake_drive_write.py) on 127.0.0.1: no Google host is
reached and no real credential exists. Every write path records each request (method, path, query, body) and asserts the exact list; nothing is written
without the content and the key the flags state; create never overwrites; update lands as a new revision after the replaced one was marked keepForever,
and only if the file is still the base the runtime read; a lost answer is found again by the file's own mark; no token is in anything it prints.

Run: uv run --with pytest==9.1.1 pytest providers/writer/tests/test_writer_gdrive.py
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import urllib.parse
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
import fake_drive_write as fdw  # noqa: E402

WRITER = REPO / "providers" / "writer" / "gdrive.py"
KEY = "files-" + "1" * 32
OTHER_KEY = "files-" + "2" * 32
FIELDS = "id,name,mimeType,version,modifiedTime,md5Checksum,headRevisionId,size,parents,trashed,appProperties,ownedByMe,capabilities/canEdit"
TEXT = "# CV 2026\n\nPat Example, engineer.\n".encode("utf-8")


@pytest.fixture
def fake():
    f = fdw.FakeDriveWrite()
    yield f
    f.close()


@pytest.fixture
def home(tmp_path):
    (tmp_path / "home").mkdir()
    return tmp_path


def base_env(tmp_path):
    kept = {k: v for k, v in os.environ.items() if not k.startswith(("GOOGLE_", "WRITER_", "OPENHORA_", "MICROSOFT_"))}
    kept["HOME"] = str(tmp_path / "home")
    kept["OPENHORA_STATE_DIR"] = str(tmp_path / "state")
    return kept


def run(args, fake, tmp_path, **env):
    if args and args[0] != "--check" and "--account" not in args:
        args = [*args, "--account", fdw.ACCOUNT]      # every verb names the account of the document; a test of another account gives its own
    proc = subprocess.run([sys.executable, str(WRITER), *args], env={**base_env(tmp_path), **fake.env(**env)}, capture_output=True, text=True, timeout=60)
    for stream in (proc.stdout, proc.stderr):    # no run ever prints a credential, not even partially
        for secret in fdw.SECRETS:
            assert secret not in stream and secret[:16] not in stream, args
    return proc


def content_file(tmp_path, data=TEXT, name="content"):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def flags(data, tmp_path, media="text/markdown"):
    return ["--media-type", media, "--content-file", content_file(tmp_path, data), "--bytes", str(len(data)),
            "--sha256", hashlib.sha256(data).hexdigest()]


def create_args(data, tmp_path, name="CV 2026.md", key=KEY, mode="--confirmed", folder=fdw.FOLDER_ID, extra=()):
    return ["create", "--folder", folder, "--name", name, *flags(data, tmp_path), "--idempotency-key", key, mode, *extra]


def update_args(data, tmp_path, ident=fdw.FILE_ID, base=None, key=KEY, mode="--confirmed", media="text/markdown"):
    base = base or {"version": "3", "modified": "2026-10-10T09:00:00.000Z", "mime": "text/markdown", "md5": fdw.md5(b"old text\n"), "head": None}
    args = ["update", "--id", ident, *flags(data, tmp_path, media), "--base-version", base["version"], "--base-modified", base["modified"],
            "--base-mime", base["mime"], "--idempotency-key", key, mode]
    if base.get("md5"):
        args += ["--base-md5", base["md5"]]
    if base.get("head"):
        args += ["--base-head-revision", base["head"]]
    return args


def seeded(fake):
    meta = fake.add_file(fdw.FILE_ID, "CV 2026.md", b"old text\n")
    return meta, meta["revisions"][-1]["id"]


# --- the check -------------------------------------------------------------------------------------------------------------------------


def test_the_check_refreshes_the_token_and_sends_nothing_else(fake, home):
    done = run(["--check"], fake, home)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert out["ok"] is True and out["record"] == "account" and out["account"] == fdw.ACCOUNT and out["implementation"] == "gdrive"
    assert fake.requests == [] and len(fake.token_forms) == 1 and fake.token_forms[0]["grant_type"] == "refresh_token"


def test_a_token_that_lacks_a_scope_or_carries_another_is_refused_before_any_request(fake, home):
    for scope, word in ((" ".join(fdw.SCOPES[:3]), "lacks"), (" ".join(fdw.SCOPES) + " https://mail.google.com/", "carries")):
        fake.scope = scope
        fake.requests.clear()
        done = run(create_args(TEXT, home), fake, home)
        assert done.returncode == 3 and word in done.stderr and "google_auth.py authorize" in done.stderr
        assert fake.requests == [] and len(fake.files) == 1


def test_a_redirect_at_the_token_endpoint_is_never_followed(fake, home):
    fake.redirect_token = True
    done = run(["--check"], fake, home)
    assert done.returncode != 0 and fake.requests == []


def test_no_account_record_is_exit_3_and_no_legacy_record_is_read(fake, home):
    env = {k: v for k, v in fake.env().items() if k != "GOOGLE_ACCOUNT_TOKEN"}
    env["GDRIVE_SOURCES_TOKEN"] = json.dumps({"refresh_token": fdw.REFRESH_TOKEN, "client_id": fdw.CLIENT_ID, "client_secret": fdw.CLIENT_SECRET})
    done = subprocess.run([sys.executable, str(WRITER), *create_args(TEXT, home), "--account", fdw.ACCOUNT], env={**base_env(home), **env}, capture_output=True, text=True, timeout=60)
    assert done.returncode == 3 and "google_auth.py authorize" in done.stderr
    assert fake.requests == [] and fake.token_forms == []


# --- create ----------------------------------------------------------------------------------------------------------------------------


def test_a_create_sends_exactly_the_folder_read_the_name_check_and_one_upload(fake, home):
    done = run(create_args(TEXT, home), fake, home)
    assert done.returncode == 0, done.stderr
    assert [(m, p) for m, p, _ in fake.listing()] == [("GET", f"/drive/v3/files/{fdw.FOLDER_ID}"), ("GET", "/drive/v3/files"),
                                                      ("POST", "/upload/drive/v3/files")]
    folder, listing, upload = fake.requests
    assert folder["query"] == {"fields": "id,name,mimeType,trashed"} and listing["query"]["pageSize"] == "10"
    assert listing["query"]["q"] == f"'{fdw.FOLDER_ID}' in parents and name = 'CV 2026.md' and trashed = false"
    assert upload["query"] == {"fields": FIELDS, "uploadType": "multipart"} and upload["content_type"].startswith("multipart/related; boundary=oh")
    metadata, media = fdw.split_multipart(upload["body"], upload["content_type"])
    assert json.loads(metadata[1]) == {"appProperties": {"openhora_key": KEY}, "mimeType": "text/markdown", "name": "CV 2026.md", "parents": [fdw.FOLDER_ID]}
    assert media[0]["content-type"] == "text/markdown" and media[1] == TEXT, "the bytes sent are the bytes approved"
    assert all(r["bearer"] for r in fake.requests) and fake.violations == []
    created = [m for m in fake.files.values() if m["name"] == "CV 2026.md"]
    assert len(created) == 1 and created[0]["content"] == TEXT
    out = json.loads(done.stdout)
    assert out["written"] is True and out["replayed"] is False and out["name"] == "CV 2026.md" and out["bytes"] == len(TEXT) and out["md5"] == fdw.md5(TEXT)


def test_a_create_never_overwrites_a_file_of_the_same_name_whatever_its_content(fake, home):
    fake.add_file(fdw.FILE_ID, "CV 2026.md", b"the person's own text\n")
    done = run(create_args(TEXT, home), fake, home)
    assert done.returncode == 1 and "already in the folder" in done.stderr and "never replaces" in done.stderr
    assert [m for m, _, _ in fake.listing()] == ["GET", "GET"], "no write was sent"
    assert fake.files[fdw.FILE_ID]["content"] == b"the person's own text\n" and len(fake.files) == 2
    again = run(create_args(TEXT, home), fake, home)
    assert again.returncode == 1, "the key was given back: the refusal is the same, not a stale pending key"


def test_a_create_of_a_google_doc_sends_the_google_type_and_markdown_media(fake, home):
    done = run(create_args(TEXT, home, name="CV 2026", extra=["--gdoc"]), fake, home)
    assert done.returncode == 0, done.stderr
    metadata, media = fdw.split_multipart(fake.requests[-1]["body"], fake.requests[-1]["content_type"])
    assert json.loads(metadata[1])["mimeType"] == fdw.DOC and json.loads(metadata[1])["name"] == "CV 2026" and media[0]["content-type"] == "text/markdown"
    bad = run(["create", "--folder", fdw.FOLDER_ID, "--name", "y", "--media-type", "text/plain", "--bytes", "1", "--sha256", "0" * 64,
               "--idempotency-key", KEY, "--dry-run", "--gdoc"], fake, home)
    assert bad.returncode == 2 and "text/markdown" in bad.stderr


def test_a_create_in_a_folder_that_is_not_a_folder_or_is_in_the_trash_writes_nothing(fake, home):
    fake.add_file(fdw.FILE_ID, "notes.md", b"x")
    done = run(create_args(TEXT, home, folder=fdw.FILE_ID), fake, home)
    assert done.returncode == 1 and "not a folder" in done.stderr and [m for m, _, _ in fake.listing()] == ["GET"]
    fake.files[fdw.FOLDER_ID]["trashed"] = True
    fake.requests.clear()
    assert run(create_args(TEXT, home), fake, home).returncode == 1 and [m for m, _, _ in fake.listing()] == ["GET"]
    missing = run(create_args(TEXT, home, folder="Nope_Folder_01"), fake, home)
    assert missing.returncode == 1 and "does not know" in missing.stderr


def test_a_lost_answer_is_unknown_and_approving_again_finds_the_file_by_its_mark_and_creates_no_second(fake, home):
    fake.lose_answer = "POST"
    first = run(create_args(TEXT, home), fake, home)
    assert first.returncode == 4 and "unknown" in first.stderr
    assert len([m for m in fake.files.values() if m["name"] == "CV 2026.md"]) == 1, "the first request landed"
    fake.lose_answer = None
    fake.requests.clear()
    second = run(create_args(TEXT, home), fake, home)
    assert second.returncode == 0, second.stderr
    assert [m for m, _, _ in fake.listing()] == ["GET", "GET"], "found by the key's mark: no second upload"
    assert json.loads(second.stdout)["replayed"] is True and len([m for m in fake.files.values() if m["name"] == "CV 2026.md"]) == 1
    fake.requests.clear()
    third = run(create_args(TEXT, home), fake, home)
    assert third.returncode == 0 and json.loads(third.stdout)["replayed"] is True and fake.requests == [], "a done key asks the service nothing"
    assert len(fake.token_forms) == 2, "and not even for a token"


def test_a_key_used_for_other_requests_is_refused(fake, home):
    assert run(create_args(TEXT, home), fake, home).returncode == 0
    fake.requests.clear()
    other = run(create_args(b"another text\n", home, name="Other.md"), fake, home)
    assert other.returncode == 1 and "other requests" in other.stderr and fake.requests == []


def test_a_refused_write_changes_nothing_and_gives_the_key_back_and_a_server_error_is_unknown(fake, home):
    fake.fail_write = 403
    refused = run(create_args(TEXT, home), fake, home)
    assert refused.returncode == 1 and "Drive refused" in refused.stderr and [m for m in fake.files if m != fdw.FOLDER_ID] == []
    fake.fail_write = 429
    limited = run(create_args(TEXT, home), fake, home)
    assert limited.returncode == 1 and "retry after 7 seconds" in limited.stderr
    ok = run(create_args(TEXT, home), fake, home)
    assert ok.returncode == 0, "the key was given back after each refusal"
    fake.fail_write = 503
    unknown = run(create_args(b"third\n", home, name="Third.md", key=OTHER_KEY), fake, home)
    assert unknown.returncode == 4 and "unknown" in unknown.stderr


def test_the_content_must_be_the_approved_bytes(fake, home):
    path = content_file(home)
    base = ["create", "--folder", fdw.FOLDER_ID, "--name", "CV 2026.md", "--media-type", "text/markdown", "--idempotency-key", KEY, "--confirmed",
            "--content-file", path]
    for bytes_, sha in ((str(len(TEXT) + 1), hashlib.sha256(TEXT).hexdigest()), (str(len(TEXT)), "0" * 64)):
        done = run([*base, "--bytes", bytes_, "--sha256", sha], fake, home)
        assert done.returncode == 2 and "nothing was sent" in done.stderr
    assert fake.requests == [] and fake.token_forms == []
    link = home / "link"
    link.symlink_to(path)
    done = run([*base[:-1], str(link), "--bytes", str(len(TEXT)), "--sha256", hashlib.sha256(TEXT).hexdigest()], fake, home)
    assert done.returncode == 2 and fake.requests == []
    relative = run([*base[:-1], "content", "--bytes", str(len(TEXT)), "--sha256", hashlib.sha256(TEXT).hexdigest()], fake, home)
    assert relative.returncode == 2 and "absolute" in relative.stderr


@pytest.mark.parametrize("name", ["a/b.md", "..md", " x.md", "x.md ", "-x.md", "a'b.md", 'a"b.md', "x\u202e.md", "a\nb.md", "a\\b.md", ""])
def test_a_file_name_outside_the_closed_character_set_is_refused(fake, home, name):
    done = run(create_args(TEXT, home, name=name, mode="--dry-run"), fake, home)
    assert done.returncode == 2 and "--name" in done.stderr and fake.requests == []


def test_a_name_with_accents_and_parentheses_is_accepted_and_percent_encoding_is_never_skipped(fake, home):
    done = run(create_args(TEXT, home, name="Currículo (2026).md", mode="--dry-run"), fake, home)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["requests"][1]["query"]["q"].endswith("name = 'Currículo (2026).md' and trashed = false")


@pytest.mark.parametrize("ident", ["a/b", "..", "a b", "a%2Fb", "a?b", "x" * 129, ""])
def test_an_id_outside_the_pattern_is_refused_before_it_enters_a_path(fake, home, ident):
    assert run(["file-meta", "--id", ident], fake, home).returncode == 2
    assert run(create_args(TEXT, home, folder=ident, mode="--dry-run"), fake, home).returncode == 2
    assert fake.requests == []


# --- update ------------------------------------------------------------------------------------------------------------------------------


def test_an_update_keeps_the_replaced_revision_before_it_writes_and_lands_as_a_new_revision(fake, home):
    meta, head = seeded(fake)
    base = {"version": "3", "modified": "2026-10-10T09:00:00.000Z", "mime": "text/markdown", "md5": fdw.md5(b"old text\n"), "head": head}
    new = b"new text\n"
    done = run(update_args(new, home, base=base), fake, home)
    assert done.returncode == 0, done.stderr
    assert [(m, p) for m, p, _ in fake.listing()] == [("GET", f"/drive/v3/files/{fdw.FILE_ID}"), ("PATCH", f"/drive/v3/files/{fdw.FILE_ID}/revisions/{head}"),
                                                      ("PATCH", f"/upload/drive/v3/files/{fdw.FILE_ID}")], "the revision is kept BEFORE the content is written"
    get, keep, upload = fake.requests
    assert get["query"] == {"fields": FIELDS} and keep["query"] == {} and json.loads(keep["body"]) == {"keepForever": True}
    assert upload["query"] == {"fields": FIELDS, "uploadType": "multipart"}
    metadata, media = fdw.split_multipart(upload["body"], upload["content_type"])
    assert json.loads(metadata[1]) == {"appProperties": {"openhora_key": KEY}} and media[1] == new
    assert meta["content"] == new and meta["version"] == "4" and len(meta["revisions"]) == 2
    assert meta["revisions"][0]["id"] == head and meta["revisions"][0]["keepForever"] is True, "the previous revision is kept for ever"
    out = json.loads(done.stdout)
    assert out["written"] is True and out["replayed"] is False and out["kept_revision"] == head and out["md5"] == fdw.md5(new) and fake.violations == []


@pytest.mark.parametrize("field", ["version", "modified", "mime", "md5", "head"])
def test_an_update_of_a_file_that_moved_since_it_was_read_writes_nothing_and_says_changed(fake, home, field):
    meta, head = seeded(fake)
    base = {"version": "3", "modified": "2026-10-10T09:00:00.000Z", "mime": "text/markdown", "md5": fdw.md5(b"old text\n"), "head": head}
    base[field] = {"version": "2", "modified": "2026-10-09T09:00:00.000Z", "mime": "text/plain", "md5": "0" * 32, "head": "OtherRev_1"}[field]
    done = run(update_args(b"new text\n", home, base=base), fake, home)
    assert done.returncode == 1 and done.stderr.startswith("error: changed:"), done.stderr
    assert [m for m, _, _ in fake.listing()] == ["GET"] and meta["content"] == b"old text\n" and meta["revisions"][0]["keepForever"] is False
    again = run(update_args(b"new text\n", home, base=base), fake, home)
    assert again.returncode == 1, "the key was given back: the refusal does not stick"


def test_an_update_of_a_trashed_file_or_a_folder_is_refused(fake, home):
    meta, head = seeded(fake)
    meta["trashed"] = True
    base = {"version": "3", "modified": "2026-10-10T09:00:00.000Z", "mime": "text/markdown", "md5": fdw.md5(b"old text\n"), "head": head}
    assert run(update_args(b"new\n", home, base=base), fake, home).returncode == 1
    assert [m for m, _, _ in fake.listing()] == ["GET"]


def test_an_update_of_a_google_native_file_has_no_binary_revision_to_keep(fake, home):
    meta = fake.add_file(fdw.NATIVE_ID, "CV 2026", b"doc text\n", native=True)
    base = {"version": "3", "modified": "2026-10-10T09:00:00.000Z", "mime": fdw.DOC}
    done = run(update_args(b"new doc text\n", home, ident=fdw.NATIVE_ID, base=base), fake, home)
    assert done.returncode == 0, done.stderr
    assert [(m, p) for m, p, _ in fake.listing()] == [("GET", f"/drive/v3/files/{fdw.NATIVE_ID}"), ("PATCH", f"/upload/drive/v3/files/{fdw.NATIVE_ID}")]
    assert meta["content"] == b"new doc text\n"


def test_an_update_whose_answer_was_lost_is_unknown_and_approving_again_finds_its_mark_and_writes_nothing_more(fake, home):
    meta, head = seeded(fake)
    base = {"version": "3", "modified": "2026-10-10T09:00:00.000Z", "mime": "text/markdown", "md5": fdw.md5(b"old text\n"), "head": head}
    fake.lose_answer = "PATCH"
    first = run(update_args(b"new text\n", home, base=base), fake, home)
    assert first.returncode == 4 and meta["content"] == b"new text\n"
    fake.lose_answer = None
    fake.requests.clear()
    second = run(update_args(b"new text\n", home, base=base), fake, home)
    assert second.returncode == 0 and json.loads(second.stdout)["replayed"] is True
    assert [m for m, _, _ in fake.listing()] == ["GET"] and meta["version"] == "4", "found by its mark: no second revision"


def test_an_update_needs_a_head_revision_for_a_binary_file(fake, home):
    seeded(fake)
    base = {"version": "3", "modified": "2026-10-10T09:00:00.000Z", "mime": "text/markdown", "md5": fdw.md5(b"old text\n"), "head": None}
    done = run(update_args(b"new\n", home, base=base), fake, home)
    assert done.returncode == 2 and "head revision" in done.stderr and fake.requests == []


# --- file-meta ---------------------------------------------------------------------------------------------------------------------------


def test_file_meta_reads_one_file_or_looks_for_a_name_in_a_folder_and_changes_nothing(fake, home):
    meta, head = seeded(fake)
    out = json.loads(run(["file-meta", "--id", fdw.FILE_ID], fake, home).stdout)
    assert out == {"id": fdw.FILE_ID, "name": "CV 2026.md", "mime_type": "text/markdown", "version": "3", "modified": "2026-10-10T09:00:00.000Z",
                   "md5": fdw.md5(b"old text\n"), "head_revision": head, "size": 9, "in_trash": False, "parents": [fdw.FOLDER_ID], "native": False,
                   "folder": False, "key": None, "owned": True}
    found = json.loads(run(["file-meta", "--folder", fdw.FOLDER_ID, "--name", "CV 2026.md"], fake, home).stdout)
    assert found == {"folder": {"id": fdw.FOLDER_ID, "name": "openhora"}, "exists": True, "matches": [{"id": fdw.FILE_ID, "name": "CV 2026.md"}]}
    none = json.loads(run(["file-meta", "--folder", fdw.FOLDER_ID, "--name", "Other.md"], fake, home).stdout)
    assert none["exists"] is False and none["matches"] == []
    assert {m for m, _, _ in fake.listing()} == {"GET"}, "a read sends GET only"


# --- the dry run ----------------------------------------------------------------------------------------------------------------------


def test_a_dry_run_reads_no_credential_opens_no_connection_and_prints_the_requests_it_would_send(fake, home):
    env = {k: v for k, v in base_env(home).items()}      # no account token, no override: nothing it could connect to
    done = subprocess.run([sys.executable, str(WRITER), *create_args(TEXT, home, mode="--dry-run")], env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert out["dry_run"] is True and out["ledger"] == "absent" and len(out["requests"]) == 3
    canonical = json.dumps(out["requests"], sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    assert out["would_sha256"] == hashlib.sha256(canonical).hexdigest()
    assert out["requests"][2]["body"]["media"] == {"bytes": len(TEXT), "content_type": "text/markdown", "sha256": hashlib.sha256(TEXT).hexdigest()}
    assert not (home / "state").exists(), "a dry run makes no folder and no ledger"
    again = subprocess.run([sys.executable, str(WRITER), *create_args(TEXT, home, mode="--dry-run")], env=env, capture_output=True, text=True, timeout=60)
    assert json.loads(again.stdout)["would_sha256"] == out["would_sha256"]
    changed = subprocess.run([sys.executable, str(WRITER), *create_args(TEXT, home, name="Other.md", mode="--dry-run")], env=env, capture_output=True, text=True,
                             timeout=60)
    assert json.loads(changed.stdout)["would_sha256"] != out["would_sha256"], "the hash covers the name"


def test_the_requests_a_confirmed_run_sent_are_those_its_dry_run_printed(fake, home):
    dry = json.loads(run(create_args(TEXT, home, mode="--dry-run"), fake, home).stdout)["requests"]
    assert fake.requests == []
    assert run(create_args(TEXT, home), fake, home).returncode == 0
    sent = [{"method": r["method"], "path": r["path"], "query": r["query"]} for r in fake.requests]
    assert sent == [{"method": r["method"], "path": r["path"], "query": r["query"]} for r in dry]


def test_a_run_needs_exactly_one_of_dry_run_and_confirmed_and_a_key(fake, home):
    assert run(create_args(TEXT, home, mode="--dry-run") + ["--confirmed"], fake, home).returncode == 2
    assert run(create_args(TEXT, home)[:-1], fake, home).returncode == 2
    assert run(create_args(TEXT, home, key="not-a-key"), fake, home).returncode == 2
    assert fake.requests == [] and fake.token_forms == []


# --- limits L57 and L58 --------------------------------------------------------------------------------------------------------------


def writer_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("writer_gdrive_under_test", WRITER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_limit_58_the_request_function_refuses_every_method_and_path_outside_its_allow_list():
    module = writer_module()
    session = module.Session("http://127.0.0.1:1", "token", {})
    refused = [("DELETE", "/drive/v3/files/File_ID_0001"), ("DELETE", "/drive/v3/files"), ("PUT", "/upload/drive/v3/files/File_ID_0001"),
               ("POST", "/drive/v3/files"), ("PATCH", "/drive/v3/files/File_ID_0001/permissions"), ("PATCH", "/drive/v3/files"), ("DELETE", "/drive/v3/files/File_ID_0001/revisions/r1"), ("POST", "/drive/v3/files/File_ID_0001/copy"),
               ("GET", "/drive/v3/about"), ("GET", "/drive/v3/files/a/b"), ("GET", "/drive/v3/files/File_ID_0001/permissions"),
               ("POST", "/drive/v3/files/trash"), ("DELETE", "/drive/v3/files/trash"), ("POST", "/drive/v3/files/emptyTrash"),
               ("PATCH", "/drive/v3/files/File_ID_0001/revisions/"), ("GET", "/drive/v3/files/%2e%2e"), ("PATCH", "/upload/drive/v3/files/a/../b"),
               ("POST", "/gmail/v1/users/me/messages/send"), ("POST", "/token")]
    for method, path in refused:
        with pytest.raises(module.WriterError, match="allow-list"):
            module.send(session, {"method": method, "path": path, "query": {}})


def test_limit_57_the_writer_holds_no_delete_no_emptying_of_the_trash_and_no_permanent_removal():
    """R2-A: the one removal is the move to the trash (`trashed` true, one constant); nothing deletes for good."""
    module = writer_module()
    assert {m for m, _ in module.ALLOWED} == {"GET", "POST", "PATCH"}
    source = WRITER.read_text(encoding="utf-8") + (HERE.parent / "_files_common.py").read_text(encoding="utf-8")
    for word in ("permanentDelete", "batchDelete", "emptyTrash", "files.delete", '"DELETE"', "'DELETE'", "trashed=True", "/trash"):
        assert word not in source, word
    assert source.count('"trashed": True') == 1 and 'TRASH_BODY = {"trashed": True}' in source, "the one trashed=true is the constant"
    assert module.TRASH_BODY == {"trashed": True}
    assert "keepForever" in source


def test_limit_58_every_request_the_fake_saw_is_on_the_allow_list(fake, home):
    seeded(fake)
    meta = fake.files[fdw.FILE_ID]
    head = meta["revisions"][-1]["id"]
    run(create_args(TEXT, home), fake, home)
    run(update_args(b"new\n", home, base={"version": "3", "modified": "2026-10-10T09:00:00.000Z", "mime": "text/markdown", "md5": fdw.md5(b"old text\n"),
                                           "head": head}, key=OTHER_KEY), fake, home)
    module = writer_module()
    for r in fake.requests:
        module.common.guarded(module.ALLOWED, r["method"], r["path"])
    assert fake.violations == [] and fake.requests


# --- review of #480: the account, the owner, the cap, the name taken --------------------------------------------------------------------------


def test_a_token_of_another_account_reads_and_writes_nothing(fake, home):
    meta, head = seeded(fake)
    base = {"version": "3", "modified": "2026-10-10T09:00:00.000Z", "mime": "text/markdown", "md5": fdw.md5(b"old text\n"), "head": head}
    for build in (lambda: create_args(TEXT, home), lambda: ["file-meta", "--id", fdw.FILE_ID], lambda: update_args(b"new\n", home, base=base)):
        args = build()
        done = run([*args, "--account", "someone.else@example.org"], fake, home)
        assert done.returncode == 1 and "another account" in done.stderr, args
    assert fake.requests == [] and fake.token_forms == [], "the check comes before the token is even refreshed"
    assert run(create_args(TEXT, home, mode="--dry-run"), fake, home).returncode == 0
    assert run([*create_args(TEXT, home), "--account", "not an address"], fake, home).returncode == 2
    assert run(["file-meta", "--id", fdw.FILE_ID], fake, home, GOOGLE_ACCOUNT_TOKEN=fake.record_json(account=None)).returncode == 1


def test_an_update_of_a_file_the_account_does_not_own_or_may_not_edit_is_refused_and_file_meta_says_so(fake, home):
    meta, head = seeded(fake)
    base = {"version": "3", "modified": "2026-10-10T09:00:00.000Z", "mime": "text/markdown", "md5": fdw.md5(b"old text\n"), "head": head}
    for field in ("owned", "can_edit"):
        meta[field] = False
        assert json.loads(run(["file-meta", "--id", fdw.FILE_ID], fake, home).stdout)["owned"] is False
        fake.requests.clear()
        done = run(update_args(b"new text\n", home, base=base, key=KEY if field == "owned" else OTHER_KEY), fake, home)
        assert done.returncode == 1 and "not owned by the account" in done.stderr and [m for m, _, _ in fake.listing()] == ["GET"]
        meta["owned"] = meta["can_edit"] = True
    assert meta["content"] == b"old text\n"


def test_a_keep_forever_the_service_refuses_names_the_cap_of_200_and_writes_nothing(fake, home):
    meta, head = seeded(fake)
    fake.keep_cap = True
    base = {"version": "3", "modified": "2026-10-10T09:00:00.000Z", "mime": "text/markdown", "md5": fdw.md5(b"old text\n"), "head": head}
    done = run(update_args(b"new text\n", home, base=base), fake, home)
    assert done.returncode == 1 and "200 revisions" in done.stderr and meta["content"] == b"old text\n"
    assert [m for m, _, _ in fake.listing()] == ["GET", "PATCH"], "no upload followed the refused keep"


def test_a_name_taken_at_the_write_is_said_with_the_word_the_runtime_answers_the_decision_by(fake, home):
    fake.add_file(fdw.FILE_ID, "CV 2026.md", b"the person's own text\n")
    done = run(create_args(TEXT, home), fake, home)
    assert done.returncode == 1 and done.stderr.startswith("error: taken: a file named")


# --- trash (slice R2-A): a file the account owns goes to the trash, never for good -------------------------------------------------------------


def trash_args(ident=fdw.FILE_ID, key=KEY, mode="--confirmed", version="3", modified="2026-10-10T09:00:00.000Z", mime="text/markdown", parent=fdw.FOLDER_ID):
    return ["trash", "--id", ident, "--base-version", version, "--base-modified", modified, "--base-mime", mime, "--base-parent", parent, "--idempotency-key", key, mode]


def test_a_trash_dry_run_prints_the_exact_requests_and_touches_nothing(fake, home):
    seeded(fake)
    done = run(trash_args(mode="--dry-run"), fake, home, GOOGLE_ACCOUNT_TOKEN="")
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert out["dry_run"] is True and out["requests"] == [
        {"method": "GET", "path": f"/drive/v3/files/{fdw.FILE_ID}", "query": {"fields": FIELDS}, "body": None},
        {"method": "PATCH", "path": f"/drive/v3/files/{fdw.FILE_ID}", "query": {"fields": FIELDS}, "body": {"trashed": True}}]
    assert fake.requests == [] and fake.token_forms == [] and fake.files[fdw.FILE_ID]["trashed"] is False


def test_a_confirmed_trash_reads_the_file_again_and_sends_exactly_one_trashed_patch(fake, home):
    seeded(fake)
    done = run(trash_args(), fake, home)
    assert done.returncode == 0, done.stderr
    assert [(m, p, q) for m, p, q in fake.listing()] == [("GET", f"/drive/v3/files/{fdw.FILE_ID}", {"fields": FIELDS}),
                                                         ("PATCH", f"/drive/v3/files/{fdw.FILE_ID}", {"fields": FIELDS})]
    assert json.loads(fake.requests[1]["body"]) == {"trashed": True} and fake.violations == []
    assert fake.files[fdw.FILE_ID]["trashed"] is True and fake.files[fdw.FILE_ID]["content"] == b"old text\n", "moved to the trash: the file and its content are still there"
    out = json.loads(done.stdout)
    assert out["written"] is True and out["replayed"] is False and out["moved_to_trash"] is True and out["id"] == fdw.FILE_ID


def test_vacuity_a_trash_that_skipped_the_comparison_would_trash_the_moved_file(fake, home):
    """The planted fault: the base the runtime read is not the file's now. The refusal is the only thing between the card and the trash."""
    seeded(fake)
    for field, value in (("version", "2"), ("modified", "2026-10-09T09:00:00.000Z"), ("mime", "application/pdf"), ("parent", "Other_Folder_01")):
        done = run(trash_args(**{field: value}), fake, home)
        assert done.returncode == 1 and "changed:" in done.stderr and "nothing was changed" in done.stderr, field
    assert [r["method"] for r in fake.requests] == ["GET"] * 4 and fake.files[fdw.FILE_ID]["trashed"] is False


@pytest.mark.parametrize("trouble", ["folder", "foreign", "readonly", "trashed"])
def test_a_trash_refuses_a_folder_a_file_of_someone_else_a_file_it_may_not_edit_and_a_file_already_in_the_trash(fake, home, trouble):
    meta, _ = seeded(fake)
    if trouble == "folder":
        fake.add_folder("Folder_ID_02", "sub", [fdw.FOLDER_ID])
        ident, mime = "Folder_ID_02", fdw.FOLDER
    else:
        ident, mime = fdw.FILE_ID, "text/markdown"
        if trouble == "foreign":
            meta["owned"] = False
        if trouble == "readonly":
            meta["can_edit"] = False
        if trouble == "trashed":
            meta["trashed"] = True
    done = run(trash_args(ident=ident, mime=mime, version="1" if trouble == "folder" else "3", modified="2026-10-01T08:00:00.000Z" if trouble == "folder" else "2026-10-10T09:00:00.000Z"), fake, home)
    assert done.returncode == 1 and "changed:" in done.stderr
    assert [r["method"] for r in fake.requests] == ["GET"], "nothing but the read was sent"


def test_a_trash_whose_answer_was_lost_is_unknown_and_approving_again_trashes_nothing_twice(fake, home):
    seeded(fake)
    fake.lose_answer = "TRASH"
    first = run(trash_args(), fake, home)
    assert first.returncode == 4 and "unknown" in first.stderr
    assert fake.files[fdw.FILE_ID]["trashed"] is True
    fake.lose_answer = None
    fake.requests.clear()
    again = run(trash_args(), fake, home)
    assert again.returncode == 0, again.stderr
    out = json.loads(again.stdout)
    assert out["replayed"] is True and out["moved_to_trash"] is True
    assert [r["method"] for r in fake.requests] == ["GET"], "the second approval only looked: no second PATCH"


def test_a_done_trash_is_answered_again_from_the_ledger_with_no_request(fake, home):
    seeded(fake)
    assert run(trash_args(), fake, home).returncode == 0
    fake.requests.clear()
    again = run(trash_args(), fake, home)
    assert again.returncode == 0 and json.loads(again.stdout)["replayed"] is True and fake.requests == []


def test_a_trash_the_service_refuses_changes_nothing_and_gives_the_key_back(fake, home):
    seeded(fake)
    fake.fail_write = 403
    done = run(trash_args(), fake, home)
    assert done.returncode == 1 and fake.files[fdw.FILE_ID]["trashed"] is False
    assert run(trash_args(), fake, home).returncode == 0, "the key went back: the next attempt starts clean"


def test_a_server_error_on_the_trash_is_unknown_not_a_refusal(fake, home):
    seeded(fake)
    fake.fail_write = 500
    done = run(trash_args(), fake, home)
    assert done.returncode == 4 and "unknown" in done.stderr


def test_a_trash_needs_the_base_the_runtime_read(fake, home):
    seeded(fake)
    done = run(["trash", "--id", fdw.FILE_ID, "--idempotency-key", KEY, "--confirmed"], fake, home)
    assert done.returncode == 2 and fake.requests == []


def test_limit_57_a_trash_of_the_writer_is_never_a_permanent_delete_every_request_is_on_the_list_and_no_other_was_served(fake, home):
    seeded(fake)
    run(trash_args(), fake, home)
    module = writer_module()
    for r in fake.requests:
        module.common.guarded(module.ALLOWED, r["method"], r["path"])
    assert {r["method"] for r in fake.requests} == {"GET", "PATCH"} and fake.violations == []
    assert fake.files[fdw.FILE_ID]["trashed"] is True, "the file is in the trash, not gone"
