"""Tests of the Drive documents provider (providers/documents/gdrive.py) against the stand-in service (fake_drive.py): no network
but loopback, no real account, no real credential. The provider reads the files a person picked as sources: `stat` says whether
a file changed (its `version`), `read` writes the bytes (an export of a Google file, or a download) for the converter, and
nothing is ever written to Drive.

Run: uv run --with pytest==9.1.1 pytest providers/documents/tests/test_documents_gdrive.py
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SCRIPT = REPO / "providers" / "documents" / "gdrive.py"
sys.path.insert(0, str(HERE))
import fake_drive  # noqa: E402

SECRETS = (fake_drive.ACCESS_TOKEN, fake_drive.REFRESH_TOKEN, fake_drive.CLIENT_SECRET, fake_drive.API_KEY)
DOC_ID, SHEET_ID, SLIDES_ID, PDF_ID = ("1DocAaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "1ShtBbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                                       "1SldCccccccccccccccccccccccccccccccccccccc", "1PdfDddddddddddddddddddddddddddddddddddddd")
MARKDOWN = b"# Weekly notes\n\nThe clinics asked for shorter forms.\n"
PDF = b"%PDF-1.4\n% a fictional file\n"


class Case:
    def __init__(self, tmp_path: Path):
        self.fake = fake_drive.FakeDrive()
        self.tmp = tmp_path
        self.out = tmp_path / "out"
        self.out.mkdir()

    def run(self, *argv, env=None, record=None):
        base = {k: v for k, v in os.environ.items() if not k.startswith("GDRIVE_") and not k.startswith("INTEGRATION_DOCUMENTS_GDRIVE")}
        merged = {**base, **(self.fake.env() if record is None else self.fake.env(**record)), **(env or {})}
        done = subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True, text=True, timeout=120, env=merged)
        try:
            out = json.loads(done.stdout) if done.stdout.strip() else None
        except ValueError:
            out = None
        return done.returncode, out, done.stdout + done.stderr

    def read(self, ident, *more):
        return self.run("read", "--id", ident, "--as-source", "--out-dir", str(self.out), *more)


@pytest.fixture
def case(tmp_path):
    c = Case(tmp_path)
    c.fake.add(DOC_ID, "Weekly notes", fake_drive.DOC, exports={"text/markdown": MARKDOWN, fake_drive.DOCX: b"PK\x03\x04docx"})
    c.fake.add(SHEET_ID, "Survey results", fake_drive.SHEET, exports={fake_drive.XLSX: b"PK\x03\x04xlsx"})
    c.fake.add(SLIDES_ID, "Kickoff deck", fake_drive.SLIDES, exports={"application/pdf": PDF})
    c.fake.add(PDF_ID, "report.pdf", "application/pdf", content=PDF)
    yield c
    c.fake.close()


def test_stat_says_what_the_file_is_and_a_version_that_moves_when_it_changes(case):
    code, out, said = case.run("stat", "--id", DOC_ID, "--as-source")
    assert code == 0, said
    assert out["id"] == DOC_ID and out["name"] == "Weekly notes" and out["mime_type"] == fake_drive.DOC
    assert out["supported"] is True and out["archived"] is False and out["reason"] == ""
    first = out["version"]
    assert case.run("stat", "--id", DOC_ID, "--as-source")[1]["version"] == first, "asking changes nothing"
    case.fake.edit(DOC_ID, exports={"text/markdown": MARKDOWN + b"More.\n"})
    assert case.run("stat", "--id", DOC_ID, "--as-source")[1]["version"] != first
    case.fake.touch(PDF_ID)
    assert case.run("stat", "--id", PDF_ID, "--as-source")[1]["size"] == len(PDF)


def test_a_google_doc_is_exported_as_markdown_and_written_for_the_converter(case):
    code, out, said = case.read(DOC_ID)
    assert code == 0, said
    assert out["content"] == "markdown" and out["exported_as"] == "text/markdown" and out["as_source"] is True
    assert out["bytes"] == len(MARKDOWN) and out["sha256"] == hashlib.sha256(MARKDOWN).hexdigest() and out["file"] == "content"
    written = case.out / "content"
    assert written.read_bytes() == MARKDOWN and stat.S_IMODE(written.stat().st_mode) == 0o600
    export = [r for r in case.fake.api_requests() if r[1].endswith("/export")]
    assert [r[2]["mimeType"] for r in export] == ["text/markdown"], "one export, in the format asked for first"


def test_a_doc_falls_back_to_the_word_format_only_when_markdown_is_not_offered(case):
    case.fake.files[DOC_ID]["exports"].pop("text/markdown")
    code, out, said = case.read(DOC_ID)
    assert code == 0, said
    assert out["content"] == "file" and out["exported_as"] == fake_drive.DOCX
    assert (case.out / "content").read_bytes() == b"PK\x03\x04docx"
    tried = [r[2]["mimeType"] for r in case.fake.api_requests() if r[1].endswith("/export")]
    assert tried == ["text/markdown", fake_drive.DOCX]


def test_a_sheet_goes_to_xlsx_and_slides_to_pdf(case):
    code, out, said = case.read(SHEET_ID)
    assert code == 0 and out["exported_as"] == fake_drive.XLSX and out["content"] == "file", said
    assert (case.out / "content").read_bytes() == b"PK\x03\x04xlsx"
    (case.out / "content").unlink()
    code, out, said = case.read(SLIDES_ID)
    assert code == 0 and out["exported_as"] == "application/pdf", said
    assert (case.out / "content").read_bytes() == PDF


def test_another_file_is_downloaded_and_checked_against_the_md5_drive_recorded(case):
    code, out, said = case.read(PDF_ID)
    assert code == 0, said
    assert out["content"] == "file" and out["exported_as"] is None and out["bytes"] == len(PDF)
    assert (case.out / "content").read_bytes() == PDF
    case.fake.files[PDF_ID]["md5"] = "0" * 32
    (case.out / "content").unlink()
    code, _, said = case.read(PDF_ID)
    assert code == 1 and "changed while it was being downloaded" in said and not (case.out / "content").exists()


def test_a_file_over_the_cap_is_refused_before_it_is_downloaded(case):
    code, _, said = case.read(PDF_ID, "--max-bytes", "10")
    assert code == 1 and "over the 10" in said
    assert not any(r[2].get("alt") == "media" for r in case.fake.api_requests()), "the bytes were not asked for"
    assert case.run("read", "--id", PDF_ID, "--as-source", "--out-dir", str(case.out), "--max-bytes", "0")[0] == 2


def test_an_export_over_googles_limit_is_named_as_that(case):
    case.fake.files[SHEET_ID]["exports"][fake_drive.XLSX] = b"x" * (fake_drive.EXPORT_LIMIT + 1)
    code, _, said = case.read(SHEET_ID, "--max-bytes", str(40 * 1024 * 1024))
    assert code == 1 and "10 MB limit on exported content" in said


@pytest.mark.parametrize("make,why", [
    (lambda f: f.add("1FoldEeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee", "Reports", fake_drive.FOLDER), "a folder is not a source"),
    (lambda f: f.add("1DrawFffffffffffffffffffffffffffffffffffff", "Logo sketch", fake_drive.DRAWING), "not read as a source"),
    (lambda f: f.add("1TrshGggggggggggggggggggggggggggggggggggg", "Old", "application/pdf", content=PDF, trashed=True), "in the trash"),
])
def test_a_folder_a_drawing_and_a_trashed_file_are_refused_with_the_reason(case, make, why):
    ident = make(case.fake)
    code, out, said = case.run("stat", "--id", ident, "--as-source")
    assert code == 0 and out["supported"] is False and why in out["reason"], "stat describes it and says it is not read"
    code, _, said = case.read(ident)
    assert code == 1 and why in said and not (case.out / "content").exists()


def test_a_file_the_app_was_not_given_is_a_refusal_that_says_to_pick_it_again(case):
    code, _, said = case.run("stat", "--id", "1NopeHhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhh", "--as-source")
    assert code == 1 and "pick it again" in said


def test_the_api_is_only_ever_read_and_every_request_carries_the_token(case):
    case.read(DOC_ID)
    case.run("stat", "--id", PDF_ID, "--as-source")
    assert case.fake.methods and set(case.fake.methods) == {"GET"}, "no write method is ever sent to Drive"
    assert all(authed for *_, authed in case.fake.api_requests())
    assert case.fake.token_forms and all(f["grant_type"] == "refresh_token" for f in case.fake.token_forms)
    assert all("scope" not in f for f in case.fake.token_forms), "a refresh asks for no scope of its own"


def test_the_verbs_that_would_write_are_not_supported_and_call_nothing(case):
    for argv in (["write", "--path", "docs/a.md", "--markdown-file", "x", "--idempotency-key", "k", "--confirmed"],
                 ["notice", "--id", DOC_ID, "--text", "t", "--confirmed"], ["resolve", "--idempotency-key", "k", "--not-created", "--confirmed"],
                 ["comments", "--id", DOC_ID]):
        code, _, said = case.run(*argv)
        assert code == 2 and "not supported" in said, argv
    assert case.fake.requests == [] and case.fake.token_forms == []


def test_the_flags_are_checked_before_anything_is_asked(case):
    assert case.run("stat", "--id", DOC_ID)[0] == 2, "a source read needs --as-source"
    assert case.run("write", "--as-source")[0] == 2
    assert case.run("stat", "--id", "not an id", "--as-source")[0] == 2
    assert case.run("read", "--id", DOC_ID, "--as-source")[0] == 2, "--out-dir is required"
    assert case.run("read", "--id", DOC_ID, "--as-source", "--out-dir", str(case.tmp / "missing"))[0] == 2
    link = case.tmp / "link"
    link.symlink_to(case.out)
    assert case.run("read", "--id", DOC_ID, "--as-source", "--out-dir", str(link))[0] == 2, "a link is not a folder of ours"
    assert case.run()[0] == 2 and case.run("--check", "stat")[0] == 2
    assert case.run("stat", "--id", DOC_ID, "--as-source", "--no-browser")[0] == 2, "--no-browser belongs to pick"
    assert case.run("pick", "--as-source")[0] == 2
    assert case.fake.requests == []


def test_an_existing_content_file_is_never_overwritten(case):
    assert case.read(DOC_ID)[0] == 0
    code, _, said = case.read(DOC_ID)
    assert code == 1 and "cannot be written" in said
    assert (case.out / "content").read_bytes() == MARKDOWN


def test_no_authorization_a_revoked_one_and_a_wider_scope_are_not_configured_and_say_what_to_run(case):
    code, _, said = case.run("stat", "--id", DOC_ID, "--as-source", env={"GDRIVE_SOURCES_TOKEN": ""})
    assert code == 3 and "gdrive_auth.py authorize" in said
    code, _, said = case.run("stat", "--id", DOC_ID, "--as-source", env={"GDRIVE_SOURCES_TOKEN": "not json"})
    assert code == 3 and "unreadable" in said
    case.fake.token_status = 400
    code, _, said = case.run("stat", "--id", DOC_ID, "--as-source")
    assert code == 3 and "expired or was revoked" in said and "gdrive_auth.py authorize" in said
    case.fake.token_status = 200
    case.fake.scope_granted = fake_drive.SCOPE + " https://www.googleapis.com/auth/drive.readonly"
    case.fake.requests.clear()
    code, _, said = case.run("stat", "--id", DOC_ID, "--as-source")
    assert code == 3 and "drive.readonly" in said and case.fake.requests == [], "a token that is wider than drive.file is never used"
    case.fake.scope_granted = "https://www.googleapis.com/auth/drive.readonly"
    assert case.run("--check")[0] == 3


def test_a_rejected_client_is_not_configured(case):
    code, _, said = case.run("stat", "--id", DOC_ID, "--as-source", record={"client_secret": "fake-wrong-secret"})
    assert code == 3 and "rejected the OAuth client" in said and "fake-wrong-secret" not in said


def test_check_proves_the_authorization_with_the_one_token_call_and_names_the_scope(case):
    code, out, said = case.run("--check")
    assert code == 0 and out == {"ok": True, "scope": fake_drive.SCOPE, "obtained_at": "2026-10-15T08:00:00Z"}, said
    assert case.fake.api_requests() == [] and len(case.fake.token_forms) == 1


def test_a_redirect_is_refused_because_the_request_carries_a_credential(case):
    case.fake.redirect_next = True
    code, _, said = case.run("stat", "--id", DOC_ID, "--as-source")
    assert code == 1 and "refusing to follow a 302 redirect" in said


def test_the_test_overrides_must_be_loopback_and_come_together(case):
    code, _, said = case.run("--check", env={"INTEGRATION_DOCUMENTS_GDRIVE_API_BASE": "https://drive.example"})
    assert code == 2 and "loopback" in said
    code, _, said = case.run("--check", env={"INTEGRATION_DOCUMENTS_GDRIVE_TOKEN_URL": ""})
    assert code == 2 and "set together" in said


def test_no_credential_is_ever_printed(case):
    outputs = []
    for argv in (("--check",), ("stat", "--id", DOC_ID, "--as-source"), ("read", "--id", DOC_ID, "--as-source", "--out-dir", str(case.out)),
                 ("stat", "--id", "1NopeHhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhh", "--as-source"), ("--help",)):
        outputs.append(case.run(*argv)[2])
    case.fake.token_status = 400
    outputs.append(case.run("--check")[2])
    for text in outputs:
        for secret in SECRETS:
            assert secret not in text

