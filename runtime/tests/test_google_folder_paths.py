"""A Google folder given as a path in `accounts.google.folders` (slice S11, runtime/project_config.py, runtime/ops_google_folders.py, runtime/ops_config.py `accept_config`).

The file may hold "/Documentos" or "/Clientes/2026" where a Google folder id went; accepting the file resolves each path to the folder's id through the Drive provider's
`resolve-path` verb (here a stand-in `call`, so no network and no account), shows the id beside the path, and keeps it; an ambiguous or missing folder refuses the
acceptance and names the path; the id form is unchanged and asks the provider nothing. Every expectation is a literal of this file; the vacuity tests plant a wrong result.
Every address and id is fictional.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_google_folder_paths.py
"""
from __future__ import annotations

import json
import os
import stat

import pytest

import standin_tree as st

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
project_config = st.load("project_config")
ops_google_folders = st.load("ops_google_folders")

DOCS, YEAR, MOVED = "1DocumentosAaaaaaaaaaaaaaaaaaaaaaaaaaa", "1Year2026Bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "1MovedCccccccccccccccccccccccccccccc"
RAW = "Folder_ID_01"


@pytest.fixture
def world(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    calls, answers = [], {"/Documentos": DOCS, "/Clientes/2026": YEAR}

    def call(cls, verb, args, **kw):
        calls.append((cls, verb, list(args)))
        found = answers[args[1]]
        if isinstance(found, Exception):
            raise found
        return {"id": found, "path": args[1], "levels": args[1].count("/")}

    monkeypatch.setattr(ops_google_folders, "provider_call", call)
    return {**built, "path": str(built["project"]), "calls": calls, "answers": answers}


def configure(world, folders) -> str:
    file = project_config.path(world["path"])
    raw = json.loads(open(file, encoding="utf-8").read())
    raw["accounts"] = {"google": {"address": "ana@mail.example", "folders": folders}}
    open(file, "w", encoding="utf-8").write(json.dumps(raw))
    return world["path"]


def accept(world):
    """Accept the file as the person does: `config` for the hash and the widening list, then `accept-config`; when the widening list changes because the ids are resolved,
    the refusal's own command (the second try) is what the person types."""
    shown = ops.config(world["path"])
    try:
        return ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])
    except ops_core.OpsError as e:
        again = str(e).rsplit("--widen ", 1)[-1].strip().split()[0]
        return ops.accept_config(world["path"], shown["sha256"], widen=again)


def data_file(world):
    return os.path.join(ops.config(world["path"])["data_dir"], "google-folders.json")


def test_a_path_is_resolved_when_the_file_is_accepted_and_the_id_is_shown_beside_it(world):
    configure(world, {"default": "/Documentos", "clients": "/Clientes/2026", "raw": RAW})
    assert ops.config(world["path"])["google_folders"] == {"default": {"path": "/Documentos", "id": None}, "clients": {"path": "/Clientes/2026", "id": None}}, \
        "before the acceptance: the paths, with no id"
    done = accept(world)
    assert done["google_folders"] == {"default": {"path": "/Documentos", "id": DOCS}, "clients": {"path": "/Clientes/2026", "id": YEAR}}
    assert ops.config(world["path"])["google_folders"] == done["google_folders"], "the config output shows the id beside the path"
    # two paths, tried twice: the first try is refused because the widening list now holds the ids (the person types the refusal's own hash, nothing was kept)
    assert sorted(world["calls"], key=lambda c: c[2][1]) == [("integration:documents", "resolve-path", ["--path", "/Clientes/2026"])] * 2 + \
        [("integration:documents", "resolve-path", ["--path", "/Documentos"])] * 2


def test_the_loaded_file_and_every_target_use_the_id_and_the_id_form_is_untouched(world):
    configure(world, {"default": "/Documentos", "clients": "/Clientes/2026", "raw": RAW})
    accept(world)
    cfg = project_config.load(world["path"])
    assert cfg["accounts"]["google"]["folders"] == {"default": DOCS, "clients": YEAR, "raw": RAW}
    assert project_config.account_target(cfg, "google", "folders", "default") == (DOCS, None)
    assert project_config.account_target(cfg, "google", "folders", "clients") == (YEAR, None)
    assert project_config.account_target(cfg, "google", "folders", "raw") == (RAW, None)
    assert project_config.account_target(cfg, "google", "folders", "default") != (YEAR, None), "vacuity: the oracle tells one id from another"


def test_a_path_never_resolved_is_refused_as_a_target_and_the_record_is_private(world):
    configure(world, {"default": "/Documentos"})
    cfg = project_config.load(world["path"])
    target, why = project_config.account_target(cfg, "google", "folders", "default")
    assert target is None and why == ("the Google folder /Documentos has not been resolved to its id: accept the configuration again, which resolves it through your Google account")
    accept(world)
    assert stat.S_IMODE(os.stat(data_file(world)).st_mode) == 0o600
    assert json.loads(open(data_file(world)).read()) == {"v": 1, "folders": {"/Documentos": DOCS}}


def test_a_missing_folder_refuses_the_acceptance_names_the_path_and_keeps_nothing(world):
    configure(world, {"default": "/Documentos", "clients": "/Clientes/2026"})
    world["answers"]["/Clientes/2026"] = Exception("the Drive provider said: no folder /Clientes/2026 in My Drive")
    shown = ops.config(world["path"])
    with pytest.raises(ops_core.OpsError) as raised:
        ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])
    assert str(raised.value) == ("the configuration was not accepted: the Google folder /Clientes/2026 could not be resolved: the Drive provider said: no folder /Clientes/2026 in My Drive")
    assert ops.config(world["path"])["accepted"] is False and not os.path.exists(data_file(world))


def test_an_ambiguous_folder_refuses_the_acceptance_and_names_the_path(world):
    configure(world, {"default": "/Documentos"})
    world["answers"]["/Documentos"] = Exception("2 folders in My Drive are named /Documentos: the path does not say which")
    shown = ops.config(world["path"])
    with pytest.raises(ops_core.OpsError) as raised:
        ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])
    assert str(raised.value).startswith("the configuration was not accepted: the Google folder /Documentos could not be resolved: ")
    assert "2 folders in My Drive are named /Documentos" in str(raised.value) and ops.config(world["path"])["accepted"] is False


def test_an_answer_the_runtime_does_not_read_is_refused(world):
    configure(world, {"default": "/Documentos"})
    world["answers"]["/Documentos"] = "../not an id"
    shown = ops.config(world["path"])
    with pytest.raises(ops_core.OpsError) as raised:
        ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])
    assert "the Google folder /Documentos could not be resolved" in str(raised.value) and not os.path.exists(data_file(world))


def test_the_id_form_asks_the_provider_nothing_and_adds_nothing_to_the_answers(world):
    configure(world, {"default": RAW})
    done = accept(world)
    assert world["calls"] == [] and "google_folders" not in done and "google_folders" not in ops.config(world["path"])
    assert not os.path.exists(data_file(world))
    assert project_config.load(world["path"])["accounts"]["google"]["folders"] == {"default": RAW}


def test_accepting_again_follows_a_folder_that_moved_only_with_the_widening_hash(world):
    configure(world, {"default": "/Documentos"})
    accept(world)
    world["answers"]["/Documentos"] = MOVED          # the folder behind the path is another one now
    shown = ops.config(world["path"])
    with pytest.raises(ops_core.OpsError) as raised:
        ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])
    assert "the file widens what" in str(raised.value) and f"accounts:google:folder:default={MOVED}: " in str(raised.value), "the list shows the new id behind the name"
    assert project_config.load(world["path"])["accounts"]["google"]["folders"] == {"default": DOCS}, "a refused acceptance changes nothing the runtime uses"
    done = accept(world)
    assert done["google_folders"] == {"default": {"path": "/Documentos", "id": MOVED}}
    assert project_config.load(world["path"])["accounts"]["google"]["folders"] == {"default": MOVED}


def test_a_file_without_a_path_removes_an_older_record(world):
    configure(world, {"default": "/Documentos"})
    accept(world)
    assert os.path.exists(data_file(world))
    configure(world, {"default": RAW})
    accept(world)
    assert not os.path.exists(data_file(world))


def test_a_record_that_is_not_ours_is_ignored(world):
    configure(world, {"default": "/Documentos"})
    accept(world)
    with open(data_file(world), "w") as f:
        f.write(json.dumps({"v": 1, "folders": {"/Documentos": "../escape", "/Other": DOCS}}))
    assert project_config.load(world["path"])["accounts"]["google"]["folders"] == {"default": "/Documentos"}
    with open(data_file(world), "w") as f:
        f.write("not json")
    assert project_config.load(world["path"])["google_folders"] == {"default": {"path": "/Documentos", "id": None}}
