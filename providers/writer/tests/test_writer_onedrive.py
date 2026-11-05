"""Tests of the OneDrive writer (providers/writer/onedrive.py, package W4a) against the stand-in Graph (fake_onedrive_write.py) on 127.0.0.1: no Microsoft
host is reached and no real credential exists. Every write path records each request (method, path as sent, query, body) and asserts the exact list; a
create is `conflictBehavior=fail` and never overwrites; a replace goes through an upload session made with the eTag the runtime read, so a moved file is
refused by Graph (412) and by a fresh read before; the upload address is checked, called with no Authorization header and never printed; a lost answer is
found again; no token is in anything it prints.

Run: uv run --with pytest==9.1.1 pytest providers/writer/tests/test_writer_onedrive.py
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import urllib.parse
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
import fake_onedrive_write as fod  # noqa: E402

WRITER = REPO / "providers" / "writer" / "onedrive.py"
KEY = "files-" + "1" * 32
OTHER_KEY = "files-" + "2" * 32
TEXT = "# CV 2026\n\nCasey Rivera, engineer.\n".encode("utf-8")
OLD = b"old text\n"
ITEM = f"{fod.DRIVE}/{fod.FILE_ID}"
ITEM_FIELDS = "id,name,eTag,cTag,size,file,folder,package,remoteItem,deleted,malware,parentReference,lastModifiedDateTime,createdDateTime"


@pytest.fixture
def fake():
    f = fod.FakeOneDriveWrite()
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
        args = [*args, "--account", fod.ADDRESS]      # every verb names the account of the document; a test of another account gives its own
    proc = subprocess.run([sys.executable, str(WRITER), *args], env={**base_env(tmp_path), **fake.env(**env)}, capture_output=True, text=True, timeout=60)
    for stream in (proc.stdout, proc.stderr):    # no run ever prints a credential, not even partially, nor an upload address
        for secret in fod.SECRETS:
            assert secret not in stream and secret[:16] not in stream, args
        assert "/upload/S0" not in stream, "an upload address is a bearer credential"
    return proc


def flags(data, tmp_path, media="text/markdown"):
    path = tmp_path / "content"
    path.write_bytes(data)
    return ["--media-type", media, "--content-file", str(path), "--bytes", str(len(data)), "--sha256", hashlib.sha256(data).hexdigest()]


def create_args(data, tmp_path, name="CV 2026.md", folder=fod.FOLDER_ID, key=KEY, mode="--confirmed"):
    return ["create", "--folder", folder, "--name", name, *flags(data, tmp_path), "--idempotency-key", key, mode]


def replace_args(data, tmp_path, fake, ident=ITEM, key=KEY, mode="--confirmed", etag=None, ctag=None, size=None):
    item = fake.items[fod.FILE_ID]
    return ["replace", "--id", ident, *flags(data, tmp_path), "--base-etag", etag or fake.etag(item), "--base-ctag", ctag or fake.ctag(item),
            "--base-size", str(len(item["content"]) if size is None else size), "--idempotency-key", key, mode]


def seeded(fake):
    return fake.add_file(fod.FILE_ID, "CV 2026.md", OLD)


# --- the check ---------------------------------------------------------------------------------------------------------------------------


def test_the_check_refreshes_the_token_and_sends_nothing_else(fake, home):
    done = run(["--check"], fake, home)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert out["ok"] is True and out["record"] == "account" and out["implementation"] == "onedrive" and out["scope"] == " ".join(fod.PLATFORM)
    assert fake.requests == [] and len(fake.token_forms) == 1 and "client_secret" not in fake.token_forms[0]


@pytest.mark.parametrize("scope, word", [(" ".join(fod.PREFIX + n for n in fod.PLATFORM[:3]) + " offline_access", "lacks"),
                                         (" ".join(fod.PREFIX + n for n in fod.PLATFORM) + " " + fod.PREFIX + "Mail.ReadWrite.All offline_access", "carries")])
def test_a_token_that_lacks_a_permission_or_carries_another_is_refused_before_any_request(fake, home, scope, word):
    fake.scope = scope
    done = run(create_args(TEXT, home), fake, home)
    assert done.returncode == 3 and word in done.stderr and "microsoft_auth.py authorize" in done.stderr
    assert fake.requests == []


def test_no_account_record_is_exit_3_and_no_legacy_record_is_read(fake, home):
    env = {k: v for k, v in fake.env().items() if k != "MICROSOFT_ACCOUNT_TOKEN"}
    env["ONEDRIVE_SOURCES_TOKEN"] = json.dumps({"refresh_token": fod.REFRESH_TOKEN, "client_id": fod.CLIENT_ID, "scope": "Files.Read"})
    done = subprocess.run([sys.executable, str(WRITER), *create_args(TEXT, home), "--account", fod.ADDRESS], env={**base_env(home), **env}, capture_output=True, text=True, timeout=60)
    assert done.returncode == 3 and "microsoft_auth.py authorize" in done.stderr
    assert fake.requests == [] and fake.token_forms == []


# --- create ----------------------------------------------------------------------------------------------------------------------------


def test_a_create_sends_exactly_the_folder_read_and_one_put_with_conflict_behavior_fail(fake, home):
    done = run(create_args(TEXT, home), fake, home)
    assert done.returncode == 0, done.stderr
    assert fake.listing() == [("GET", f"/v1.0/me/drive/items/{fod.FOLDER_ID}", {"$select": "id,name,folder,deleted"}),
                              ("PUT", f"/v1.0/me/drive/items/{fod.FOLDER_ID}:/CV 2026.md:/content", {"@microsoft.graph.conflictBehavior": "fail"})]
    folder, put = fake.requests
    assert "%21" in folder["raw_path"] and "%20" in put["raw_path"] and ":/content" in put["raw_path"], "ids and names enter the path percent-encoded"
    assert put["body"] == TEXT and put["content_type"] == "text/markdown" and all(r["bearer"] for r in fake.requests) and fake.violations == []
    made = [i for i in fake.items.values() if i["name"] == "CV 2026.md"]
    assert len(made) == 1 and made[0]["content"] == TEXT and made[0]["parent"] == fod.FOLDER_ID
    out = json.loads(done.stdout)
    assert out["written"] is True and out["replayed"] is False and out["name"] == "CV 2026.md" and out["bytes"] == len(TEXT) and out["id"] == f"{fod.DRIVE}/{made[0]['id']}"


def test_a_create_in_a_folder_given_as_a_path_names_the_path_in_the_request(fake, home):
    done = run(create_args(TEXT, home, folder="/Documents/openhora"), fake, home)
    assert done.returncode == 0, done.stderr
    assert fake.listing() == [("GET", "/v1.0/me/drive/root:/Documents/openhora", {"$select": "id,name,folder,deleted"}),
                              ("PUT", "/v1.0/me/drive/root:/Documents/openhora/CV 2026.md:/content", {"@microsoft.graph.conflictBehavior": "fail"})]
    assert fake.requests[1]["raw_path"] == "/v1.0/me/drive/root:/Documents/openhora/CV%202026.md:/content"


def test_a_create_never_overwrites_a_file_of_the_same_name_whatever_its_content(fake, home):
    seeded(fake)
    done = run(create_args(TEXT, home), fake, home)
    assert done.returncode == 1 and "already in the folder" in done.stderr and "never replaces" in done.stderr
    assert [m for m, _, _ in fake.listing()] == ["GET", "PUT", "GET"], "Graph refused the PUT (409) and the verb looked at what is there"
    assert fake.items[fod.FILE_ID]["content"] == OLD and fake.items[fod.FILE_ID]["n"] == 3
    assert run(create_args(TEXT, home), fake, home).returncode == 1, "the key was given back"


def test_a_create_in_a_folder_that_is_a_file_or_missing_writes_nothing(fake, home):
    seeded(fake)
    done = run(create_args(TEXT, home, folder=fod.FILE_ID), fake, home)
    assert done.returncode == 1 and "not a folder" in done.stderr and [m for m, _, _ in fake.listing()] == ["GET"]
    gone = run(create_args(TEXT, home, folder="01MISSING000!999"), fake, home)
    assert gone.returncode == 1 and "does not know" in gone.stderr
    assert [m for m, _, _ in fake.listing() if m == "PUT"] == []


def test_a_lost_answer_is_unknown_and_approving_again_finds_the_file_it_made_and_makes_no_second(fake, home):
    fake.lose_answer = "PUT"
    first = run(create_args(TEXT, home), fake, home)
    assert first.returncode == 4 and "unknown" in first.stderr
    assert len([i for i in fake.items.values() if i["name"] == "CV 2026.md"]) == 1
    fake.lose_answer = None
    fake.requests.clear()
    second = run(create_args(TEXT, home), fake, home)
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout)["replayed"] is True and [m for m, _, _ in fake.listing()] == ["GET", "PUT", "GET"]
    assert len([i for i in fake.items.values() if i["name"] == "CV 2026.md"]) == 1
    fake.requests.clear()
    third = run(create_args(TEXT, home), fake, home)
    assert third.returncode == 0 and json.loads(third.stdout)["replayed"] is True and fake.requests == [] and len(fake.token_forms) == 2


def test_a_file_of_the_same_name_that_an_earlier_attempt_did_not_make_is_never_taken_for_the_key_s_own(fake, home):
    fake.lose_answer = "PUT"
    assert run(create_args(TEXT, home), fake, home).returncode == 4
    made = next(i for i in fake.items.values() if i["name"] == "CV 2026.md")
    made["content"] = b"the person edited it meanwhile, so it is not the bytes of the key\n"      # a different size: not ours
    fake.lose_answer = None
    again = run(create_args(TEXT, home), fake, home)
    assert again.returncode == 1 and "already in the folder" in again.stderr
    assert made["content"].startswith(b"the person edited")


def test_a_refused_write_gives_the_key_back_and_a_server_error_is_unknown(fake, home):
    fake.fail_write = 403
    refused = run(create_args(TEXT, home), fake, home)
    assert refused.returncode == 1 and [i for i in fake.items.values() if i["name"] == "CV 2026.md"] == []
    fake.fail_write = 429
    limited = run(create_args(TEXT, home), fake, home)
    assert limited.returncode == 1 and "retry after 7 seconds" in limited.stderr
    assert run(create_args(TEXT, home), fake, home).returncode == 0
    fake.fail_write = 503
    unknown = run(create_args(b"third\n", home, name="Third.md", key=OTHER_KEY), fake, home)
    assert unknown.returncode == 4 and "unknown" in unknown.stderr


def test_the_content_must_be_the_approved_bytes_and_a_key_belongs_to_one_set_of_requests(fake, home):
    path = home / "content"
    path.write_bytes(TEXT)
    base = ["create", "--folder", fod.FOLDER_ID, "--name", "CV 2026.md", "--media-type", "text/markdown", "--idempotency-key", KEY, "--confirmed",
            "--content-file", str(path)]
    assert run([*base, "--bytes", str(len(TEXT)), "--sha256", "0" * 64], fake, home).returncode == 2
    assert run([*base, "--bytes", "3", "--sha256", hashlib.sha256(TEXT).hexdigest()], fake, home).returncode == 2
    assert fake.requests == [] and fake.token_forms == []
    assert run(create_args(TEXT, home), fake, home).returncode == 0
    fake.requests.clear()
    other = run(create_args(b"another\n", home, name="Other.md"), fake, home)
    assert other.returncode == 1 and "other requests" in other.stderr and fake.requests == []


@pytest.mark.parametrize("name", ["a/b.md", "..md", " x.md", "x.md ", "x.", "-x.md", "a'b.md", "a:b.md", "a*b.md", "x\u202e.md", "a\nb.md", "..", ""])
def test_a_file_name_outside_the_closed_character_set_is_refused(fake, home, name):
    done = run(create_args(TEXT, home, name=name, mode="--dry-run"), fake, home)
    assert done.returncode == 2 and "--name" in done.stderr and fake.requests == []


@pytest.mark.parametrize("folder", ["", "a/b", "/", "//x", "/a/../b", "/a/./b", "/a:b", "/a?b", "/a#b", "/a%b", "/x/y.", "..", "a b", "x" * 201,
                                    "/" + "x" * 101])
def test_a_folder_outside_the_forms_of_a_folder_is_refused_before_it_enters_a_path(fake, home, folder):
    assert run(create_args(TEXT, home, folder=folder, mode="--dry-run"), fake, home).returncode == 2
    assert fake.requests == []


@pytest.mark.parametrize("ident", ["", "a", "a/b/c", "../x", "x/..", "a/b c", "a/%2e", "./x", "x/" + "y" * 201])
def test_an_item_id_outside_the_pattern_is_refused(fake, home, ident):
    assert run(["file-meta", "--id", ident], fake, home).returncode == 2
    assert fake.requests == []


# --- replace -----------------------------------------------------------------------------------------------------------------------------


def test_a_replace_sends_exactly_the_read_the_session_with_the_etag_and_one_upload_with_no_credential(fake, home):
    item = seeded(fake)
    before = fake.etag(item)
    new = b"new text\n"
    done = run(replace_args(new, home, fake), fake, home)
    assert done.returncode == 0, done.stderr
    assert fake.listing() == [("GET", f"/v1.0/drives/{fod.DRIVE}/items/{fod.FILE_ID}", {"$select": ITEM_FIELDS}),
                              ("POST", f"/v1.0/drives/{fod.DRIVE}/items/{fod.FILE_ID}/createUploadSession", {})]
    get, post = fake.requests
    assert "%21" in post["raw_path"] and post["if_match"] == before, "the session carries the eTag the runtime read"
    assert json.loads(post["body"]) == {"item": {"@microsoft.graph.conflictBehavior": "replace"}}
    assert len(fake.uploads) == 1
    upload = fake.uploads[0]
    assert upload["body"] == new and upload["content_range"] == f"bytes 0-{len(new) - 1}/{len(new)}" and upload["auth"] is None, "no Authorization at the upload host"
    assert item["content"] == new and fake.etag(item) != before and fake.violations == []
    out = json.loads(done.stdout)
    assert out["written"] is True and out["replayed"] is False and out["bytes"] == len(new) and out["etag"] == fake.etag(item)


def test_a_replace_of_a_file_that_moved_since_it_was_read_writes_nothing_and_says_changed(fake, home):
    item = seeded(fake)
    for field, over in (("eTag", {"etag": '"{other},9"'}), ("cTag", {"ctag": '"c:{other},9"'}), ("size", {"size": 99})):
        fake.requests.clear()
        done = run(replace_args(b"new text\n", home, fake, **over), fake, home)
        assert done.returncode == 1 and done.stderr.startswith("error: changed:") and field in done.stderr, done.stderr
        assert [m for m, _, _ in fake.listing()] == ["GET"] and item["content"] == OLD and fake.uploads == []


def test_a_file_that_moves_between_the_read_and_the_session_is_refused_by_graph_and_nothing_is_written(fake, home):
    item = seeded(fake)
    args = replace_args(b"new text\n", home, fake)

    def edit():
        item["n"] += 1
    fake.edit_during = edit
    done = run(args, fake, home)
    assert done.returncode == 1 and done.stderr.startswith("error: changed:") and "412" in done.stderr
    assert [m for m, _, _ in fake.listing()] == ["GET", "POST"] and fake.uploads == [] and item["content"] == OLD
    assert run(replace_args(b"new text\n", home, fake), fake, home).returncode == 0, "the key was given back; the fresh eTag works"


def test_a_replace_of_a_folder_a_package_or_a_missing_item_is_refused(fake, home):
    seeded(fake)
    fake.add_file(fod.PACKAGE_ID, "Notes", b"x", package=True)
    done = run(replace_args(b"new\n", home, fake, ident=f"{fod.DRIVE}/{fod.PACKAGE_ID}"), fake, home)
    assert done.returncode == 1 and "changed" in done.stderr and "package" in done.stderr and fake.uploads == []
    folder = run(["replace", "--id", f"{fod.DRIVE}/{fod.FOLDER_ID}", *flags(b"x\n", home), "--base-etag", '"{x},1"', "--base-ctag", '"c:{x},1"', "--base-size", "0",
                  "--idempotency-key", OTHER_KEY, "--confirmed"], fake, home)
    assert folder.returncode == 1 and fake.uploads == []
    missing = run(["replace", "--id", f"{fod.DRIVE}/01NOPE000000!1", *flags(b"x\n", home), "--base-etag", '"{x},1"', "--base-ctag", '"c:{x},1"', "--base-size", "0",
                   "--idempotency-key", "files-" + "3" * 32, "--confirmed"], fake, home)
    assert missing.returncode == 1 and "does not know" in missing.stderr


def test_a_replace_whose_upload_answer_was_lost_is_unknown_and_approving_again_finds_it_and_writes_nothing_more(fake, home):
    item = seeded(fake)
    args = replace_args(b"new text\n", home, fake)
    fake.lose_answer = "UPLOAD"
    first = run(args, fake, home)
    assert first.returncode == 4 and item["content"] == b"new text\n" and len(fake.uploads) == 1
    fake.lose_answer = None
    fake.requests.clear()
    second = run(args, fake, home)
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout)["replayed"] is True and [m for m, _, _ in fake.listing()] == ["GET"] and len(fake.uploads) == 1


def test_an_upload_address_off_the_closed_list_is_refused_and_never_printed_and_nothing_is_uploaded(fake, home):
    seeded(fake)
    fake.upload_host = "localhost"
    done = run(replace_args(b"new text\n", home, fake), fake, home)
    assert done.returncode == 1 and "not an OneDrive upload host" in done.stderr and fake.uploads == []
    assert [m for m, _, _ in fake.listing()] == ["GET", "POST"]
    fake.upload_host, fake.no_upload_url = "127.0.0.1", True
    assert run(replace_args(b"new text\n", home, fake), fake, home).returncode == 1 and fake.uploads == []


def module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("writer_onedrive_under_test", WRITER)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


@pytest.mark.parametrize("address, ok", [("https://api.onedrive.com/rup/abc", True), ("https://x.files.1drv.com/up/abc", True),
                                         ("https://tenant-my.sharepoint.com/path", True), ("http://api.onedrive.com/rup/abc", False),
                                         ("https://evil.example/rup/abc", False), ("https://api.onedrive.com.evil.example/x", False),
                                         ("https://notsharepoint.com/x", False), ("https://user@api.onedrive.com/x", False),
                                         ("https://api.onedrive.com:8443/x", False), ("https://api.onedrive.com/x y", False), ("", False), (None, False),
                                         ("file:///etc/passwd", False), ("https://127.0.0.1/x", False)])
def test_the_upload_address_rules_outside_test_mode(address, ok):
    m = module()
    session = m.Session(None, m.UPLOAD_HOST_SUFFIXES, False)
    if ok:
        assert m.checked_upload_address(address, session) == address
    else:
        with pytest.raises(m.WriterError):
            m.checked_upload_address(address, session)


# --- file-meta -----------------------------------------------------------------------------------------------------------------------------


def test_file_meta_reads_one_item_or_looks_for_a_name_in_a_folder_and_sends_get_only(fake, home):
    item = seeded(fake)
    out = json.loads(run(["file-meta", "--id", ITEM], fake, home).stdout)
    assert out["id"] == ITEM and out["name"] == "CV 2026.md" and out["etag"] == fake.etag(item) and out["ctag"] == fake.ctag(item) and out["size"] == len(OLD)
    assert out["kind"] == "file" and out["writable"] is True
    found = json.loads(run(["file-meta", "--folder", fod.FOLDER_ID, "--name", "CV 2026.md"], fake, home).stdout)
    assert found["exists"] is True and found["match"]["name"] == "CV 2026.md" and found["folder"]["name"] == "openhora"
    by_path = json.loads(run(["file-meta", "--folder", "/Documents/openhora", "--name", "CV 2026.md"], fake, home).stdout)
    assert by_path["exists"] is True
    none = json.loads(run(["file-meta", "--folder", fod.FOLDER_ID, "--name", "Other.md"], fake, home).stdout)
    assert none["exists"] is False and none["match"] is None
    folder = json.loads(run(["file-meta", "--id", f"{fod.DRIVE}/{fod.FOLDER_ID}"], fake, home).stdout)
    assert folder["kind"] == "folder" and folder["writable"] is False
    assert {m for m, _, _ in fake.listing()} == {"GET"}


# --- the dry run ----------------------------------------------------------------------------------------------------------------------


def test_a_dry_run_reads_no_credential_opens_no_connection_and_prints_the_requests_it_would_send(fake, home):
    seeded(fake)
    env = dict(base_env(home))
    done = subprocess.run([sys.executable, str(WRITER), *replace_args(b"new\n", home, fake, mode="--dry-run")], env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert [r["method"] for r in out["requests"]] == ["GET", "POST", "PUT"] and out["requests"][1]["if_match"] == fake.etag(fake.items[fod.FILE_ID])
    assert out["requests"][2]["path"] == "/upload-session" and "uploadUrl" not in done.stdout
    canonical = json.dumps(out["requests"], sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    assert out["would_sha256"] == hashlib.sha256(canonical).hexdigest() and not (home / "state").exists() and fake.requests == []
    created = subprocess.run([sys.executable, str(WRITER), *create_args(TEXT, home, mode="--dry-run")], env=env, capture_output=True, text=True, timeout=60)
    assert created.returncode == 0 and len(json.loads(created.stdout)["requests"]) == 2


def test_the_requests_a_confirmed_run_sent_are_those_its_dry_run_printed(fake, home):
    dry = json.loads(run(create_args(TEXT, home, mode="--dry-run"), fake, home).stdout)["requests"]
    assert run(create_args(TEXT, home), fake, home).returncode == 0
    assert [(r["method"], r["raw_path"][len("/v1.0"):], r["query"]) for r in fake.requests] == [(r["method"], r["path"], r["query"]) for r in dry]


# --- limits L57 and L58 --------------------------------------------------------------------------------------------------------------


def test_limit_58_the_request_function_refuses_every_method_and_path_outside_its_allow_list():
    m = module()
    session = m.Session(m.msgraph.GraphClient(m.PROFILE, "http://127.0.0.1:1", "token", True), (), True)
    refused = [("DELETE", "/me/drive/items/x"), ("DELETE", "/drives/d/items/i/children"), ("DELETE", "/drives/d/items/i/content"), ("DELETE", "/me/drive/special/recyclebin"),
               ("POST", "/drives/d/items/i/permanentDelete"), ("DELETE", "/drives/d/items/i/permanentDelete"), ("PATCH", "/me/drive/items/x"), ("PATCH", "/drives/d/items/i"),
               ("POST", "/me/drive/items/x/copy"), ("POST", "/me/drive/items/x/createLink"), ("POST", "/me/drive/items/x/invite"),
               ("POST", "/drives/d/items/i/restore"), ("PUT", "/me/drive/items/x/content"), ("PUT", "/me/drive/items/x:/y"), ("GET", "/me/drive/items/.."),
               ("GET", "/me/drive/root:/../x"), ("GET", "/me/drive/items/a/b"), ("GET", "/me/messages"), ("GET", "/me/drive/recent"),
               ("POST", "/me/sendMail"), ("PUT", "/upload/x"), ("POST", "/drives/d/items/i/createUploadSession/x"), ("GET", "/me/drive/special/recyclebin"),
               ("PUT", "/me/drive/root:/a:b:/content"), ("POST", "/token")]
    for method, path in refused:
        with pytest.raises(m.WriterError, match="allow-list"):
            m.send(session, {"method": method, "path": path, "query": {}})


DEL_SEG = r"(?!(?:\.|%2[eE])+(?:/|$))[A-Za-z0-9_%.~=-]{1,600}"      # an id segment of the one DELETE: percent-encoded, no `/`, `:` or `?`, never only dots or %2E


@pytest.mark.parametrize("path", ["/drives/d/items/..", "/drives/../items/i", "/drives/d/items/%2E%2E", "/drives/%2e%2E/items/i", "/drives/d/items/.", "/drives/d/items/root:",
                                  "/drives/d/items/root:/x", "/drives/d/items/i?permanent=true", "/drives/d/items/i/", "/drives/d/items/", "/drives//items/i", "/drives/d/items/i/children",
                                  "/drives/d/items/i/permanentDelete", "/drives/d/items/a b", "/drives/d/items/i%2Fj/x", "/me/drive/items/i"])
def test_limit_58_the_one_delete_refuses_a_traversal_a_root_path_an_encoded_dot_and_a_query_at_the_guard(path):
    m = module()
    with pytest.raises(m.common.WriterError, match="allow-list"):
        m.common.guarded(m.ALLOWED, "DELETE", path)


def test_the_one_delete_accepts_the_item_the_writer_encodes_and_nothing_a_sibling_pattern_would_not():
    m = module()
    m.common.guarded(m.ALLOWED, "DELETE", f"/drives/{m.enc(fod.DRIVE)}/items/{m.enc(fod.FILE_ID)}")
    m.common.guarded(m.ALLOWED, "DELETE", "/drives/b%21Drive_1/items/01FILE.000001%21102")
    assert r"/drives/" + DEL_SEG + r"/items/" + DEL_SEG == m.REMOVE[1]


def test_limit_57_the_writer_holds_one_delete_of_an_item_that_goes_to_the_recycle_bin_no_move_and_no_permanent_removal():
    """R2-A: the one DELETE is `/drives/{drive}/items/{item}` (Graph moves the item to the recycle bin); the permanent call is not here."""
    m = module()
    assert {method for method, _ in m.ALLOWED} == {"GET", "PUT", "POST", "DELETE"}
    assert [pair for pair in m.ALLOWED if pair[0] == "DELETE"] == [("DELETE", r"/drives/" + DEL_SEG + r"/items/" + DEL_SEG)]
    source = WRITER.read_text(encoding="utf-8")
    for word in ("permanentDelete", "batchDelete", "emptyTrash", "'DELETE'", '"PATCH"', "recycleBin", "restore"):
        assert word not in source, word
    assert source.count('"DELETE"') == 1, "the word is spelled once, in the allow-list pair"
    assert "conflictBehavior" in source and '"fail"' in source


def test_limit_58_every_request_the_fake_saw_is_on_the_allow_list(fake, home):
    seeded(fake)
    run(create_args(TEXT, home), fake, home)
    run(replace_args(b"new\n", home, fake, key=OTHER_KEY), fake, home)
    m = module()
    for r in fake.requests:
        m.common.guarded(m.ALLOWED, r["method"], r["raw_path"][len("/v1.0"):])
    assert fake.violations == [] and fake.requests and len(fake.uploads) == 1


# --- review of #480: the account, the owner, and a lost answer is told from the person's edit by the content hash -----------------------------------


def test_a_token_of_another_account_reads_and_writes_nothing(fake, home):
    seeded(fake)
    for build in (lambda: create_args(TEXT, home), lambda: ["file-meta", "--id", ITEM], lambda: replace_args(b"new\n", home, fake)):
        args = build()
        done = run([*args, "--account", "someone.else@mail.example"], fake, home)
        assert done.returncode == 1 and "another account" in done.stderr, args
    assert fake.requests == [] and fake.token_forms == []
    assert run([*create_args(TEXT, home), "--account", "not an address"], fake, home).returncode == 2


def test_file_meta_says_whether_the_item_is_in_the_accounts_own_drive_and_what_hash_graph_reports(fake, home):
    item = seeded(fake)
    out = json.loads(run(["file-meta", "--id", ITEM], fake, home).stdout)
    assert out["owned"] is True and out["sha1"] == hashlib.sha1(OLD).hexdigest() and out["sha256"] is None
    item["drive"] = "b!SomeoneElsesDrive"
    assert json.loads(run(["file-meta", "--id", ITEM], fake, home).stdout)["owned"] is False
    fake.hashes = "sha256"
    item["drive"] = fod.DRIVE
    assert json.loads(run(["file-meta", "--id", ITEM], fake, home).stdout)["sha256"] == hashlib.sha256(OLD).hexdigest()
    assert [m for m, _, _ in fake.listing() if m != "GET"] == []


def lost_upload(fake, home, edit, hashes):
    """An upload that does not land and whose answer is lost; then the person edits the file to bytes of the same size; then the same approval again."""
    item = seeded(fake)
    new = b"NEW CONTENT 1\n"
    args = replace_args(new, home, fake)
    fake.hashes = hashes
    fake.upload = lambda token, entry: (200, {})
    fake.lose_answer = "UPLOAD"
    assert run(args, fake, home).returncode == 4
    item["content"], item["n"], item["modified"] = edit, item["n"] + 1, fake.tick()
    assert len(edit) == len(new)
    fake.lose_answer = None
    return run(args, fake, home), item, args


def test_a_lost_upload_followed_by_the_persons_own_edit_of_the_same_size_is_never_taken_for_our_write(fake, home):
    done, item, _ = lost_upload(fake, home, b"PERSON EDIT 2\n", "sha1")
    assert done.returncode == 1 and done.stderr.startswith("error: changed:"), done.stderr
    assert item["content"] == b"PERSON EDIT 2\n" and len(fake.uploads) == 1
    done, item, _ = lost_upload(fake, home, b"PERSON EDIT 3\n", "sha256")
    assert done.returncode == 1 and "changed:" in done.stderr


def test_when_graph_reports_no_hash_to_compare_the_outcome_stays_unknown_and_nothing_is_called_replayed(fake, home):
    done, item, args = lost_upload(fake, home, b"PERSON EDIT 2\n", "quickxor")
    assert done.returncode == 4 and "cannot be compared" in done.stderr and item["content"] == b"PERSON EDIT 2\n"
    again = run(args, fake, home)
    assert again.returncode == 4, "the key is still pending"


def test_a_create_whose_answer_was_lost_is_found_only_by_the_bytes_the_person_approved(fake, home):
    new = b"approved text 1\n"
    for hashes, edit, code in (("sha1", b"person's own 16\n", 1), ("quickxor", b"person's own 16\n", 4)):
        fake.hashes = hashes
        name = f"Notes {hashes}.md"
        args = create_args(new, home, name=name, key="files-" + ("c" if hashes == "sha1" else "d") * 32)
        real = fake.create
        fake.create = lambda entry: (201, {})
        fake.lose_answer = "PUT"
        assert run(args, fake, home).returncode == 4
        fake.create, fake.lose_answer = real, None
        other = fake.add_file(f"01PERSON{code}!300", name.lower(), edit)       # the person's own file: the name differs in case, the size is the same
        other["created"] = other["modified"] = fake.tick()
        done = run(args, fake, home)
        assert done.returncode == code and "replayed" not in done.stdout, (hashes, done.stderr)
        assert other["content"] == edit
        if code == 1:
            assert done.stderr.startswith("error: taken:")
    fake.hashes = "sha1"
    lost = create_args(new, home, name="Mine.md", key="files-" + "e" * 32)
    fake.lose_answer = "PUT"
    assert run(lost, fake, home).returncode == 4
    fake.lose_answer = None
    done = run(lost, fake, home)
    assert done.returncode == 0 and json.loads(done.stdout)["replayed"] is True, done.stderr


def test_a_replace_whose_upload_landed_and_whose_answer_was_lost_is_replayed_on_the_hash(fake, home):
    item = seeded(fake)
    args = replace_args(b"new text\n", home, fake)
    fake.lose_answer = "UPLOAD"
    assert run(args, fake, home).returncode == 4 and item["content"] == b"new text\n"
    fake.lose_answer = None
    done = run(args, fake, home)
    assert done.returncode == 0 and json.loads(done.stdout)["replayed"] is True


# --- trash (slice R2-A): a file of the account's own drive goes to the recycle bin, never for good ---------------------------------------------------


def trash_args(fake, ident=ITEM, key=KEY, mode="--confirmed", etag=None, ctag=None, size=None, parent=None):
    item = fake.items[fod.FILE_ID]
    return ["trash", "--id", ident, "--base-etag", etag or fake.etag(item), "--base-ctag", ctag or fake.ctag(item), "--base-size", str(len(item["content"]) if size is None else size),
            "--base-parent", parent or item["parent"], "--idempotency-key", key, mode]


def test_a_trash_dry_run_prints_the_exact_requests_and_touches_nothing(fake, home):
    seeded(fake)
    done = run(trash_args(fake, mode="--dry-run"), fake, home)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    etag = fake.etag(fake.items[fod.FILE_ID])
    path = f"/drives/{urllib.parse.quote(fod.DRIVE, safe='')}/items/{urllib.parse.quote(fod.FILE_ID, safe='')}"
    assert out["requests"] == [{"method": "GET", "path": path, "query": {"$select": ITEM_FIELDS}, "body": None},
                               {"method": "DELETE", "path": path, "query": {}, "if_match": etag, "body": None}]
    assert fake.requests == [] and fod.FILE_ID in fake.items


def test_a_confirmed_trash_reads_the_item_and_sends_one_delete_with_if_match_and_the_item_is_in_the_bin_not_gone(fake, home):
    seeded(fake)
    etag = fake.etag(fake.items[fod.FILE_ID])
    done = run(trash_args(fake), fake, home)
    assert done.returncode == 0, done.stderr
    assert [(m, p) for m, p, _ in fake.listing()] == [("GET", f"/v1.0/drives/{fod.DRIVE}/items/{fod.FILE_ID}"), ("GET", "/v1.0/me/drive"),
                                                      ("DELETE", f"/v1.0/drives/{fod.DRIVE}/items/{fod.FILE_ID}")]
    assert fake.requests[2]["if_match"] == etag and fake.violations == []
    assert fod.FILE_ID not in fake.items and fake.bin[fod.FILE_ID]["content"] == OLD, "in the recycle bin with its content"
    out = json.loads(done.stdout)
    assert out["written"] is True and out["replayed"] is False and out["moved_to_trash"] is True and out["id"] == ITEM


def test_vacuity_a_trash_that_skipped_the_comparison_would_trash_the_moved_file(fake, home):
    seeded(fake)
    for field, value in (("etag", '"{x},9"'), ("ctag", '"c:{x},9"'), ("size", 99), ("parent", "01OTHER00000!999")):
        done = run(trash_args(fake, **{field: value}), fake, home)
        assert done.returncode == 1 and "changed:" in done.stderr and "nothing was changed" in done.stderr, field
    assert "DELETE" not in {r["method"] for r in fake.requests} and fod.FILE_ID in fake.items


def test_a_trash_refuses_a_folder_and_an_item_that_is_not_in_the_accounts_own_drive(fake, home):
    seeded(fake)
    fake.add_folder("01SUB0000000!150", "sub", fod.FOLDER_ID)
    item = fake.items["01SUB0000000!150"]
    done = run(["trash", "--id", f"{fod.DRIVE}/01SUB0000000!150", "--base-etag", fake.etag(item), "--base-ctag", fake.ctag(item), "--base-size", "0",
                "--base-parent", fod.FOLDER_ID, "--idempotency-key", KEY, "--confirmed"], fake, home)
    assert done.returncode == 1 and "changed:" in done.stderr and "DELETE" not in {r["method"] for r in fake.requests}
    fake.requests.clear()
    other = run(trash_args(fake, ident=f"OTHERDRIVE0001/{fod.FILE_ID}"), fake, home)
    assert other.returncode == 1 and "DELETE" not in {r["method"] for r in fake.requests}


def test_a_precondition_failure_412_is_changed_and_nothing_is_gone(fake, home):
    seeded(fake)
    item = fake.items[fod.FILE_ID]

    def edit():
        item["n"] += 1
    fake.edit_during = edit
    done = run(trash_args(fake), fake, home)
    assert done.returncode == 1 and "changed:" in done.stderr and fod.FILE_ID in fake.items


def test_a_trash_whose_answer_was_lost_is_unknown_and_approving_again_finds_the_item_gone_and_deletes_nothing_twice(fake, home):
    seeded(fake)
    args = trash_args(fake)
    fake.lose_answer = "DELETE"
    first = run(args, fake, home)
    assert first.returncode == 4 and "unknown" in first.stderr and fod.FILE_ID in fake.bin
    fake.lose_answer = None
    fake.requests.clear()
    again = run(args, fake, home)
    assert again.returncode == 0, again.stderr
    assert json.loads(again.stdout)["replayed"] is True and "DELETE" not in {r["method"] for r in fake.requests}


def test_a_done_trash_is_answered_again_from_the_ledger_with_no_request(fake, home):
    seeded(fake)
    args = trash_args(fake)
    assert run(args, fake, home).returncode == 0
    fake.requests.clear()
    again = run(args, fake, home)
    assert again.returncode == 0 and json.loads(again.stdout)["replayed"] is True and fake.requests == []


def test_a_missing_item_with_a_new_key_is_a_refusal_not_a_replay(fake, home):
    seeded(fake)
    args = trash_args(fake)
    fake.items.pop(fod.FILE_ID)
    done = run(args, fake, home)
    assert done.returncode == 1 and "replayed" not in done.stdout


def test_a_trash_needs_the_base_the_runtime_read(fake, home):
    seeded(fake)
    done = run(["trash", "--id", ITEM, "--idempotency-key", KEY, "--confirmed"], fake, home)
    assert done.returncode == 2 and fake.requests == []
