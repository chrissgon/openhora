"""The `resolve-path` verb of the Drive documents provider (slice S11): a folder named by its path from My Drive (`/Clientes/2026`) becomes the folder's id, one GET of the
files list for each name, against the stand-in service (fake_drive.py): no network but loopback, no real account, no real credential. Every expectation is a literal of this
file (the ids, the paths, the number of requests), read from what the stand-in was sent; the vacuity tests plant a wrong result to show each oracle can fail.

Run: uv run --with pytest==9.1.1 pytest providers/documents/tests/test_documents_gdrive_resolve_path.py
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

CLIENTS, YEAR, DOCS = "1ClientsAaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "1Year2026Bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "1DocumentosCcccccccccccccccccccccccccc"
OTHER_YEAR, DOUBLE_A, DOUBLE_B = "1Year2026Zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz", "1TwinAaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "1TwinBbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def gdrive(fake, *argv):
    base = {k: v for k, v in os.environ.items() if not any(k.startswith(p) for p in ("GDRIVE_", "INTEGRATION_DOCUMENTS_GDRIVE"))}
    done = subprocess.run([sys.executable, str(REPO / "providers" / "documents" / "gdrive.py"), *argv], capture_output=True, text=True, timeout=120, env={**base, **fake.env()})
    try:
        out = json.loads(done.stdout) if done.stdout.strip() else None
    except ValueError:
        out = None
    return done.returncode, out, done.stdout + done.stderr


def listings(fake):
    return [r for r in fake.api_requests() if r[1] == "/drive/v3/files"]


@pytest.fixture
def drive():
    fake = fake_drive.FakeDrive()
    fake.add(DOCS, "Documentos", fake_drive.FOLDER, parent="root")
    fake.add(CLIENTS, "Clientes", fake_drive.FOLDER, parent="root")
    fake.add(YEAR, "2026", fake_drive.FOLDER, parent=CLIENTS)
    fake.add(OTHER_YEAR, "2026", fake_drive.FOLDER, parent=DOCS)          # the same name under another folder: not the one under /Clientes
    fake.add("1TrashedDddddddddddddddddddddddddddddd", "Arquivo", fake_drive.FOLDER, parent="root", trashed=True)
    fake.add("1FileEeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee", "Notas", fake_drive.DOC, parent="root")          # a file, not a folder
    fake.add(DOUBLE_A, "Gêmeas", fake_drive.FOLDER, parent="root")          # validate: allow english-only -- the Portuguese line or sentence under test
    fake.add(DOUBLE_B, "Gêmeas", fake_drive.FOLDER, parent="root")          # validate: allow english-only -- the Portuguese line or sentence under test
    fake.add("1QuoteFffffffffffffffffffffffffffffffff", "Joao's files", fake_drive.FOLDER, parent="root")
    yield fake
    fake.close()


def test_one_name_is_one_get_and_gives_the_id_of_that_folder(drive):
    code, out, said = gdrive(drive, "resolve-path", "--path", "/Documentos")
    assert code == 0, said
    assert out == {"id": DOCS, "path": "/Documentos", "levels": 1}
    assert [r[2]["q"] for r in listings(drive)] == ["'root' in parents and name = 'Documentos' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"]
    assert set(drive.methods) == {"GET"}


def test_two_names_are_two_gets_the_second_under_the_id_the_first_gave(drive):
    code, out, said = gdrive(drive, "resolve-path", "--path", "/Clientes/2026")
    assert code == 0, said
    assert out == {"id": YEAR, "path": "/Clientes/2026", "levels": 2}
    assert [r[2]["q"].split(" and name")[0] for r in listings(drive)] == ["'root' in parents", f"'{CLIENTS}' in parents"]
    assert len(listings(drive)) == 2 and {r[1] for r in drive.api_requests() if r[1].startswith("/drive")} == {"/drive/v3/files"}


def test_vacuity_the_same_last_name_under_another_folder_is_another_id(drive):
    code, out, _ = gdrive(drive, "resolve-path", "--path", "/Documentos/2026")
    assert code == 0 and out["id"] == OTHER_YEAR and out["id"] != YEAR


def test_a_name_with_a_quote_is_escaped_in_the_query_and_found(drive):
    code, out, said = gdrive(drive, "resolve-path", "--path", "/Joao's files")
    assert code == 0, said
    assert out["id"] == "1QuoteFffffffffffffffffffffffffffffffff"
    assert listings(drive)[0][2]["q"] == "'root' in parents and name = 'Joao\\'s files' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"


@pytest.mark.parametrize("path, said_part", [("/Inexistente", "no folder /Inexistente in My Drive"), ("/Clientes/2025", "no folder /Clientes/2025 in My Drive"),
                                              ("/Arquivo", "no folder /Arquivo in My Drive"), ("/Notas", "no folder /Notas in My Drive")])
def test_a_missing_folder_a_trashed_one_or_a_file_is_refused_with_the_path_read_so_far(drive, path, said_part):
    code, out, said = gdrive(drive, "resolve-path", "--path", path)
    assert code == 1 and out is None and said_part in said, said


def test_two_folders_with_the_name_are_refused_and_none_is_picked(drive):
    code, out, said = gdrive(drive, "resolve-path", "--path", "/Gêmeas")      # validate: allow english-only -- the Portuguese line or sentence under test
    assert code == 1 and out is None
    assert "2 folders in My Drive are named /Gêmeas" in said and DOUBLE_A not in said and DOUBLE_B not in said      # validate: allow english-only -- the Portuguese line or sentence under test


def test_a_missing_middle_name_stops_the_walk(drive):
    code, _, said = gdrive(drive, "resolve-path", "--path", "/Nada/2026")
    assert code == 1 and "no folder /Nada in My Drive" in said
    assert len(listings(drive)) == 1, "the walk stops at the first name that fails"


@pytest.mark.parametrize("path", [None, "Documentos", "/", "//x", "/a//b", "/a/./b", "/a/../b", "/ a", "/a ", "/x\ny", "/" + "n" * 101, "/" + "/".join("n" for _ in range(9))])
def test_a_bad_path_is_refused_before_any_request(drive, path):
    argv = ["resolve-path"] + (["--path", path] if path is not None else [])
    code, _, said = gdrive(drive, *argv)
    assert code == 2, said
    assert listings(drive) == []


def test_the_verb_takes_no_as_source_flag_and_writes_nothing(drive):
    code, _, said = gdrive(drive, "resolve-path", "--path", "/Documentos", "--as-source")
    assert code == 2, said
    assert gdrive(drive, "resolve-path", "--path", "/Documentos")[0] == 0
    assert set(drive.methods) == {"GET"}


def test_vacuity_the_oracle_of_the_requests_fails_for_a_wrong_count(drive):
    gdrive(drive, "resolve-path", "--path", "/Documentos")
    assert len(listings(drive)) != 2
