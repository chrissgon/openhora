"""Tests of the `children` verb of the Drive and OneDrive documents providers (slice S8: the runtime lists the configured folders to find a file by its name),
against the stand-in services (fake_drive.py, fake_graph.py): no network but loopback, no real account, no real credential. The verb lists the DIRECT contents of one
folder, by one GET, and reads no file; a folder id is checked before any request is made.

Run: uv run --with pytest==9.1.1 pytest providers/documents/tests/test_documents_children.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
import fake_drive  # noqa: E402
import fake_graph  # noqa: E402

FOLDER, OTHER = "1FolderAaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "1FolderBbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def run(script, fake, *argv, clean):
    base = {k: v for k, v in os.environ.items() if not any(k.startswith(p) for p in clean)}
    done = subprocess.run([sys.executable, str(REPO / "providers" / "documents" / script), *argv], capture_output=True, text=True, timeout=120, env={**base, **fake.env()})
    try:
        out = json.loads(done.stdout) if done.stdout.strip() else None
    except ValueError:
        out = None
    return done.returncode, out, done.stdout + done.stderr


def gdrive(fake, *argv):
    return run("gdrive.py", fake, *argv, clean=("GDRIVE_", "INTEGRATION_DOCUMENTS_GDRIVE"))


def onedrive(fake, *argv):
    return run("onedrive.py", fake, *argv, clean=("ONEDRIVE_", "INTEGRATION_DOCUMENTS_ONEDRIVE"))


@pytest.fixture
def drive():
    fake = fake_drive.FakeDrive()
    fake.add("1DocAaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "Weekly notes", fake_drive.DOC, exports={"text/markdown": b"# n"}, parent=FOLDER)
    fake.add("1PdfBbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "report.pdf", "application/pdf", content=b"%PDF-1.4\n", parent=FOLDER)
    fake.add("1SubCcccccccccccccccccccccccccccccccccccccc", "Archive", fake_drive.FOLDER, parent=FOLDER)
    fake.add("1FormDdddddddddddddddddddddddddddddddddddd", "Survey form", "application/vnd.google-apps.form", parent=FOLDER)
    fake.add("1GoneEeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee", "Old notes", fake_drive.DOC, trashed=True, parent=FOLDER)
    fake.add("1ElsewhereFffffffffffffffffffffffffffffffff", "Elsewhere", fake_drive.DOC, parent=OTHER)
    yield fake
    fake.close()


def test_drive_children_lists_the_direct_contents_of_one_folder_by_name_with_one_get(drive):
    code, out, said = gdrive(drive, "children", "--id", FOLDER)
    assert code == 0, said
    assert [(i["name"], i["kind"], i["supported"]) for i in out["items"]] == [("Archive", "folder", False), ("Survey form", "file", False), ("Weekly notes", "file", True),
                                                                              ("report.pdf", "file", True)]
    assert out["count"] == 4 and out["truncated"] is False and out["items"][3]["size"] == 9
    listing = [r for r in drive.api_requests() if r[1] == "/drive/v3/files"]
    assert len(listing) == 1 and listing[0][2]["q"] == f"'{FOLDER}' in parents and trashed = false"
    assert set(drive.methods) == {"GET"}
    assert "Elsewhere" not in said and "Old notes" not in said


def test_drive_children_says_when_the_list_is_cut_at_top(drive):
    code, out, _ = gdrive(drive, "children", "--id", FOLDER, "--top", "2")
    assert code == 0 and out["count"] == 2 and out["truncated"] is True


@pytest.mark.parametrize("argv", [["children"], ["children", "--id", "short"], ["children", "--id", "a'b" + "x" * 12], ["children", "--id", FOLDER, "--top", "0"],
                                   ["children", "--id", FOLDER, "--top", "201"], ["children", "--id", FOLDER + "' or '1'='1"]])
def test_drive_children_refuses_a_bad_folder_id_or_top_before_any_request(drive, argv):
    code, _, said = gdrive(drive, *argv)
    assert code == 2, said
    assert [r for r in drive.api_requests() if r[1] == "/drive/v3/files"] == []


def test_vacuity_another_folder_gives_another_list(drive):
    code, out, _ = gdrive(drive, "children", "--id", OTHER)
    assert code == 0 and [i["name"] for i in out["items"]] == ["Elsewhere"]


@pytest.fixture
def graph():
    fake = fake_graph.FakeGraph()
    fake.add_file(fake_graph.DRIVE, "DOCX1!101", "Weekly notes.docx", b"PK\x03\x04 a note", folder_path="/Documentos")
    fake.add_file(fake_graph.DRIVE, "PDF1!102", "Other.pdf", b"%PDF-1.4\n", folder_path="/Particular")
    fake.name_folder("FOLDER1!900", "/Documentos")
    yield fake
    fake.close()


def test_onedrive_children_by_folder_id_lists_the_same_items_as_by_path(graph):
    by_id = onedrive(graph, "children", "--folder-id", "FOLDER1!900")
    by_path = onedrive(graph, "children", "--path", "/Documentos")
    assert by_id[0] == 0 and by_id[1] == by_path[1]
    assert [i["name"] for i in by_id[1]["items"]] == ["Weekly notes.docx"]
    assert [r["path"] for r in graph.api_requests()] == ["/v1.0/me/drive/items/FOLDER1!900/children", "/v1.0/me/drive/root:/Documentos:/children"]


@pytest.mark.parametrize("argv", [["--folder-id", "../x"], ["--folder-id", "a/b"], ["--folder-id", ".."], ["--folder-id", "x" * 201], ["--folder-id", "A!1", "--path", "/Documentos"]])
def test_onedrive_children_refuses_a_bad_folder_id_or_both_flags_before_any_request(graph, argv):
    code, _, said = onedrive(graph, "children", *argv)
    assert code == 2, said
    assert graph.requests == []


def test_vacuity_onedrive_folder_id_of_another_folder_gives_another_list(graph):
    graph.name_folder("FOLDER2!901", "/Particular")
    code, out, _ = onedrive(graph, "children", "--folder-id", "FOLDER2!901")
    assert code == 0 and [i["name"] for i in out["items"]] == ["Other.pdf"]
