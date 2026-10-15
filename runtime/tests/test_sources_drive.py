"""Tests of the Google Drive sources (P7): a picked file is registered, read through the Drive provider (providers/documents/gdrive.py,
the REAL provider process, against the stand-in service providers/documents/tests/fake_drive.py), converted, versioned and refreshed; a
refresh with no change makes no version and reads no content; a native Google Doc and Sheet go through export; the Picker's picks become
several sources at once; and no credential reaches a run or a file of the sources. Offline: no Google host is reached, the converter is the
stand-in of sources_fixture.py, and the secrets of a test are made-up strings.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_sources_drive.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import standin_tree as st
from sources_fixture import make_docx, make_pdf, make_xlsx, standin_convert, with_sources

REPO = st.REPO
sys.path.insert(0, str(REPO / "providers" / "documents" / "tests"))
import fake_drive  # noqa: E402

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_sources = st.load("ops_sources")
operations = st.load("operations")
cli = st.load("cli")
sources = st.load("sources")
lab = st.load("lab")

_spec = importlib.util.spec_from_file_location("resolve_for_drive_tests", REPO / "providers" / "resolve.py")
resolve = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(resolve)

DOC, SHEET, SLIDES, PDF, FOLDER = ("1DocAaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "1ShtBbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                                   "1SldCccccccccccccccccccccccccccccccccccccc", "1PdfDddddddddddddddddddddddddddddddddddddd",
                                   "1FldEeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee")
NOPE = "1NopeHhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhh"
MARKDOWN = b"# Weekly notes\n\nThe clinics asked for shorter forms.\n"
SECRETS = (fake_drive.ACCESS_TOKEN, fake_drive.REFRESH_TOKEN, fake_drive.CLIENT_SECRET, fake_drive.API_KEY)
SHEET_BYTES = make_xlsx([("Responses", [["clinic", "score"], ["North", "4"], ["South", "5"]])])


class Drive:
    """The stand-in service, a project that accepted its configuration, and the seam that runs the real provider against the service."""

    def __init__(self, tmp_path, monkeypatch):
        self.fake = fake_drive.FakeDrive()
        self.tmp = tmp_path
        monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(tmp_path / "evidence"))
        project = tmp_path / "project"
        (project / "docs" / "workbench").mkdir(parents=True)
        config = with_sources({"workbench": str(REPO), "data_dir": str(tmp_path / "data"), "store_db": str(tmp_path / "store" / "tasks.sqlite")},
                              tmp_path)
        (project / "docs" / "workbench" / "runtime.json").write_text(json.dumps(config), encoding="utf-8")
        self.path = str(project)
        ops.accept_config(self.path, ops.project_config.load(self.path)["sha256"])
        self.ctx = ops_core.context(self.path)
        self.cfg, self.folder = self.ctx["cfg"], Path(self.ctx["cfg"]["sources_dir"])
        monkeypatch.setattr(sources, "provider_convert", lambda cfg, call=None: standin_convert)
        original = sources.drive_call

        def drive_call(cfg, verb, args, *, call=None, timeout=sources.DRIVE_TIMEOUT):
            return original(cfg, verb, args, call=call or self.provider, timeout=timeout)
        monkeypatch.setattr(sources, "drive_call", drive_call)
        self.fake.add(DOC, "Weekly notes", fake_drive.DOC, exports={"text/markdown": MARKDOWN})
        self.fake.add(SHEET, "Survey results", fake_drive.SHEET, exports={fake_drive.XLSX: SHEET_BYTES})
        self.fake.add(SLIDES, "Kickoff deck", fake_drive.SLIDES, exports={"application/pdf": make_pdf("Kickoff goals")})
        self.fake.add(PDF, "Quarterly report", "application/pdf", content=make_pdf("Quarterly numbers"))
        self.fake.add(FOLDER, "Reports", fake_drive.FOLDER)
        self.calls = []

    def provider(self, cls, verb, args, **kwargs):
        """The runtime's call to the provider, run for real as a process of this interpreter against the stand-in service."""
        self.calls.append((cls, verb, list(args), kwargs))
        script = str(REPO / "providers" / "documents" / "gdrive.py")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("GDRIVE_", "INTEGRATION_DOCUMENTS_GDRIVE"))}
        env.update(self.fake.env())
        return resolve.call(cls, verb, args, root=kwargs["root"], implementation=kwargs["implementation"], timeout=kwargs["timeout"], env=env,
                            run=lambda argv: subprocess.run([sys.executable, *argv[argv.index(script):]], capture_output=True, text=True,
                                                            timeout=120, env=env, check=False))

    def reads(self):
        """The requests that asked Drive for content (an export or a download), not for a description."""
        return [r for r in self.fake.api_requests() if r[1].endswith("/export") or r[2].get("alt") == "media"]

    def latest(self, source_id):
        return self.ctx["store"].source_latest(self.ctx["conn"], source_id)


@pytest.fixture
def drive(tmp_path, monkeypatch):
    d = Drive(tmp_path, monkeypatch)
    yield d
    d.fake.close()


def pick(*ids):
    return {"picked": [{"id": i, "name": "", "mime_type": ""} for i in ids], "cancelled": False}


# --- a Drive source in the registry --------------------------------------------------------------------------------------------------


def test_a_drive_source_is_stored_as_a_file_row_and_read_everywhere_as_a_drive_source(drive):
    row = sources.register(drive.ctx, "notes", "drive", DOC, "The weekly notes.")
    assert row["type"] == "drive" and row["origin"] == DOC and row["description"] == "The weekly notes."
    stored = drive.ctx["store"].source_get(drive.ctx["conn"], "notes")
    assert stored["type"] == "file" and stored["origin"] == "drive:" + DOC, "no migration: the registry's type column is unchanged"
    assert sources.public_row(stored) == row and sources.drive_id_of(stored) == DOC
    [listed] = sources.list_catalog(drive.ctx, hashes=False)
    assert listed["type"] == "drive" and listed["origin"] == DOC
    assert ops_sources.sources_catalog(drive.path)["sources"][0]["type"] == "drive"
    assert sources.register(drive.ctx, "plain", "file", "survey.csv")["type"] == "file"


@pytest.mark.parametrize("origin", ["", "short", "has space in it 12345", "../etc/passwd-1234", "https://drive.example/file/d/" + DOC, "x" * 101])
def test_a_drive_origin_that_is_not_a_file_id_is_refused(drive, origin):
    with pytest.raises(sources.SourcesError) as refused:
        sources.register(drive.ctx, "notes", "drive", origin)
    assert refused.value.code == "usage"
    assert sources.list_catalog(drive.ctx, hashes=False) == []


def test_an_ordinary_file_source_cannot_claim_the_prefix_that_marks_a_drive_source(drive):
    for origin in ("drive:" + DOC, "drive:anything"):
        with pytest.raises(sources.SourcesError):
            sources.register(drive.ctx, "plain", "file", origin)
    assert sources.drive_file_id("drive:" + DOC) == DOC and sources.drive_file_id(DOC) == DOC


def test_a_file_cannot_be_imported_into_a_drive_source_and_a_drive_source_is_not_refreshed_from_a_file(drive, tmp_path):
    sources.register(drive.ctx, "notes", "drive", DOC)
    other = tmp_path / "survey.csv"
    other.write_text("a,b\n1,2\n")
    with pytest.raises(ops_core.OpsError) as wrong:
        ops_sources.source_import(drive.path, "notes", file=str(other))
    assert "drive source" in str(wrong.value)
    with pytest.raises(ops_core.OpsError) as refused:
        ops_sources.source_refresh(drive.path, "notes", file=str(other))
    assert "refreshed from Drive" in str(refused.value)


def test_source_ids_are_made_from_the_names_and_never_collide():
    make = sources.drive_source_id
    assert make("Survey results (final)", []) == "survey-results-final"
    assert make("Survey results", ["survey-results"]) == "survey-results-2"
    assert make("Survey results", ["survey-results", "survey-results-2"]) == "survey-results-3"
    assert make("", []) == "drive-file" and make("???", ["drive-file"]) == "drive-file-2"
    assert len(make("x" * 100, [])) <= 36 and len(make("x" * 100, ["x" * 36])) <= 40
    assert sources.SOURCE_ID.fullmatch(make("Ünïcode name", []))


# --- import, convert, version and refresh --------------------------------------------------------------------------------------------


def test_one_picked_file_is_registered_imported_and_converted_and_the_provider_is_asked_for_reads_only(drive):
    done = ops_sources.source_drive(drive.path, file_id=PDF, source_id="quarterly")
    [one] = done["results"]
    assert one["source"] == "quarterly" and one["registered"] is True and one["imported"] is True and one["version"] == 1, one
    assert one["kind"] == "pdf" and "Quarterly numbers" in (drive.folder / "quarterly" / "1" / "converted.md").read_text()
    row = drive.latest("quarterly")
    assert row["origin_version"].startswith("1@") and row["label"] == "import" and row["by"] == "runtime"
    assert row["catalog"]["name"] == "Quarterly report", "the catalog names the file, not its id"
    manifest = json.loads((drive.folder / "quarterly" / "1" / "manifest.json").read_text())
    assert manifest["type"] == "drive" and manifest["origin"] == PDF and manifest["name"] == "Quarterly report"
    assert manifest["origin_version"] == row["origin_version"]
    verbs = [(c[1], c[3]["implementation"]) for c in drive.calls]
    assert verbs == [("stat", "gdrive"), ("read", "gdrive")] and all(c[0] == "integration:documents" for c in drive.calls)
    assert all("--as-source" in c[2] for c in drive.calls)
    assert set(drive.fake.methods) == {"GET"}, "nothing is written to Drive"
    assert not (drive.tmp / "data" / "sources-staging").exists() or not list((drive.tmp / "data" / "sources-staging").iterdir()), "staging is gone"


def test_a_google_doc_arrives_as_markdown_text_and_a_sheet_goes_through_the_converter(drive):
    docs = ops_sources.source_drive(drive.path, file_id=DOC, source_id="weekly")["results"][0]
    assert docs["imported"] and docs["kind"] == "markdown"
    assert (drive.folder / "weekly" / "1" / "converted.md").read_bytes() == MARKDOWN
    assert (drive.folder / "weekly" / "1" / "original.md").read_bytes() == MARKDOWN
    assert json.loads((drive.folder / "weekly" / "1" / "manifest.json").read_text())["converter"]["name"] == "markdown"
    sheet = ops_sources.source_drive(drive.path, file_id=SHEET, source_id="survey")["results"][0]
    assert sheet["imported"] and sheet["kind"] == "xlsx"
    entry = drive.latest("survey")["catalog"]
    assert entry["name"] == "Survey results" and entry["sheets"][0]["rows"] == 2 and [c["name"] for c in entry["sheets"][0]["columns"]] == ["clinic", "score"]
    deck = ops_sources.source_drive(drive.path, file_id=SLIDES, source_id="kickoff")["results"][0]
    assert deck["imported"] and deck["kind"] == "pdf" and "Kickoff goals" in (drive.folder / "kickoff" / "1" / "converted.md").read_text()


def test_a_doc_whose_markdown_export_is_not_offered_is_read_as_word_and_converted(drive):
    drive.fake.files[DOC]["exports"] = {fake_drive.DOCX: make_docx(["Weekly notes", "Shorter forms."])}
    done = ops_sources.source_drive(drive.path, file_id=DOC, source_id="weekly")["results"][0]
    assert done["imported"] and done["kind"] == "docx"
    assert "Shorter forms." in (drive.folder / "weekly" / "1" / "converted.md").read_text()


def test_several_picked_files_become_several_sources_and_one_that_cannot_be_read_stops_itself_alone(drive, monkeypatch):
    drive.fake.add("1DupeFffffffffffffffffffffffffffffffffffff", "Weekly notes", fake_drive.DOC, exports={"text/markdown": b"# Other\n\nText.\n"})
    monkeypatch.setattr(sources, "pick_drive", lambda cfg: pick(DOC, SHEET, FOLDER, NOPE, PDF, "1DupeFffffffffffffffffffffffffffffffffffff"))
    done = ops_sources.source_drive(drive.path)
    assert done["picked"] == 6 and done["cancelled"] is False
    by_file = {r["file"]: r for r in done["results"]}
    assert [by_file[i].get("source") for i in (DOC, SHEET, PDF, "1DupeFffffffffffffffffffffffffffffffffffff")] == [
        "weekly-notes", "survey-results", "quarterly-report", "weekly-notes-2"]
    assert all(by_file[i]["imported"] for i in (DOC, SHEET, PDF))
    assert "folder is not a source" in by_file[FOLDER]["error"] and "source" not in by_file[FOLDER]
    assert "pick it again" in by_file[NOPE]["error"] and "source" not in by_file[NOPE]
    assert [r["id"] for r in sources.list_catalog(drive.ctx, hashes=False)] == ["quarterly-report", "survey-results", "weekly-notes", "weekly-notes-2"]
    assert drive.ctx["store"].source_get(drive.ctx["conn"], "weekly-notes")["description"] == "Weekly notes", "the file's name is the first description"


def test_a_file_picked_again_is_the_source_it_already_is_and_makes_no_new_version(drive, monkeypatch):
    monkeypatch.setattr(sources, "pick_drive", lambda cfg: pick(PDF))
    first = ops_sources.source_drive(drive.path)["results"][0]
    reads = len(drive.reads())
    again = ops_sources.source_drive(drive.path)["results"][0]
    assert len(drive.reads()) == reads, "a file picked again is a refresh: Drive's version is asked and nothing is read when it matches"
    assert first["registered"] is True and again["registered"] is False and again["source"] == first["source"]
    assert again["imported"] is False and again.get("unchanged") is True
    assert drive.ctx["store"].source_version_count(drive.ctx["conn"], first["source"]) == 1
    with pytest.raises(ops_core.OpsError):
        ops_sources.source_drive(drive.path, source_id="orphan")
    with pytest.raises(ops_core.OpsError):
        ops_sources.source_drive(drive.path, file_id=PDF)
    other = ops_sources.source_drive(drive.path, file_id=PDF, source_id="elsewhere")["results"][0]
    assert "already the source quarterly-report" in other["error"]


def test_a_cancelled_picker_makes_nothing(drive, monkeypatch):
    monkeypatch.setattr(sources, "pick_drive", lambda cfg: {"picked": [], "cancelled": True})
    assert ops_sources.source_drive(drive.path) == {"picked": 0, "cancelled": True, "results": []}
    assert sources.list_catalog(drive.ctx, hashes=False) == []


def test_a_refresh_with_no_change_creates_no_version_and_reads_no_content(drive):
    ops_sources.source_drive(drive.path, file_id=DOC, source_id="weekly")
    reads_before = len(drive.reads())
    quiet = ops_sources.source_refresh(drive.path, "weekly")
    assert quiet["refreshed"] is False and quiet["unchanged"] is True and quiet["read"] is False and quiet["version"] == 1
    assert len(drive.reads()) == reads_before, "the version matched: nothing was asked for but the description"
    assert drive.ctx["store"].source_version_count(drive.ctx["conn"], "weekly") == 1


def test_a_change_makes_a_new_version_and_records_the_version_it_read(drive):
    ops_sources.source_drive(drive.path, file_id=DOC, source_id="weekly")
    first = drive.latest("weekly")["origin_version"]
    drive.fake.edit(DOC, exports={"text/markdown": MARKDOWN + b"\nA second paragraph.\n"})
    newer = ops_sources.source_refresh(drive.path, "weekly")
    assert newer["refreshed"] is True and newer["version"] == 2 and newer["label"] == "refresh" and newer["read"] is True
    row = drive.latest("weekly")
    assert row["origin_version"] != first and row["origin_version"].startswith("2@")
    assert (drive.folder / "weekly" / "2" / "converted.md").read_bytes().endswith(b"A second paragraph.\n")
    assert (drive.folder / "weekly" / "1" / "converted.md").read_bytes() == MARKDOWN, "the first version is as it was"
    # the version a task receives is the newest, and the rows say which (decision D29)
    got = sources.task_copies(drive.ctx, {"sources": ["weekly"]}, str(drive.tmp / "prepared"), unattended=True)
    assert [(r["source"], r["version"]) for r in got["records"]] == [("weekly", 2)]


def test_a_version_that_moved_with_the_same_bytes_reads_the_file_and_makes_no_version(drive):
    ops_sources.source_drive(drive.path, file_id=PDF, source_id="quarterly")
    drive.fake.touch(PDF)
    done = ops_sources.source_refresh(drive.path, "quarterly")
    assert done["refreshed"] is False and done["unchanged"] is True and done["read"] is True
    assert drive.ctx["store"].source_version_count(drive.ctx["conn"], "quarterly") == 1


def test_a_file_changed_in_the_folder_is_still_noticed_when_drive_did_not_change(drive):
    ops_sources.source_drive(drive.path, file_id=DOC, source_id="weekly")
    converted = drive.folder / "weekly" / "1" / "converted.md"
    os.chmod(converted, 0o600)
    converted.write_text("# Weekly notes\n\nEdited by hand.\n")
    done = ops_sources.source_refresh(drive.path, "weekly")
    assert done["refreshed"] and done["by"] == "person" and done["read"] is False and done["version"] == 2
    assert len(drive.reads()) == 1, "Drive was not read again"
    with pytest.raises(sources.SourcesError) as unattended:
        sources.task_copies(drive.ctx, {"sources": ["weekly"]}, str(drive.tmp / "prepared"), unattended=True)
    assert unattended.value.code == "unattended"


def test_a_file_that_became_unreadable_is_a_refusal_and_no_version(drive):
    ops_sources.source_drive(drive.path, file_id=PDF, source_id="quarterly")
    drive.fake.files[PDF]["trashed"] = True
    with pytest.raises(ops_core.OpsError) as refused:
        ops_sources.source_refresh(drive.path, "quarterly")
    assert "in the trash" in str(refused.value)
    assert drive.ctx["store"].source_version_count(drive.ctx["conn"], "quarterly") == 1


def test_a_provider_that_fails_names_why_and_leaves_no_row(drive):
    drive.fake.token_status = 400
    [one] = ops_sources.source_drive(drive.path, file_id=PDF, source_id="quarterly")["results"]
    assert "error" in one and "gdrive_auth.py authorize" in one["error"] and "source" not in one
    assert sources.list_catalog(drive.ctx, hashes=False) == []
    for text in (json.dumps(one),):
        assert not any(secret in text for secret in SECRETS)


def test_source_drive_is_a_terminal_operation_only_and_outside_the_group_a_policy_turns_on():
    row = operations.by_name("source-drive")
    assert row["channels"] == ("terminal",) and row["model"] is False and "job" not in row
    assert "source-drive" not in operations.GROUPS["sources"]["operations"]
    assert "source-drive" in operations.terminal_verbs() and "source-drive" in cli.__doc__
    got = cli.build_parser().parse_args(["source-drive", "--project", "/p", "--file-id", DOC, "--source", "notes"])
    assert (got.command, got.f_file_id, got.f_source) == ("source-drive", DOC, "notes")
    for channel in ("page", "mcp", "messaging"):
        assert operations.permitted("source-drive", channel, {channel: ["read", "sources"]}) is False
    assert "drive" in cli.build_parser().parse_args(["source-add", "--project", "/p", "--source", "x", "--type", "drive", "--origin", DOC]).f_type


# --- the Picker's command -------------------------------------------------------------------------------------------------------------


def test_the_picker_is_started_with_the_minimum_environment_and_its_answer_is_read(drive, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "a-key-that-must-not-travel")
    monkeypatch.setenv("NOTION_TOKEN", "a-token-that-must-not-travel")
    monkeypatch.setenv("GDRIVE_SOURCES_TOKEN", "the-one-secret-the-picker-reads")
    seen = {}

    def run(argv, env, timeout):
        seen.update(argv=argv, env=env, timeout=timeout)
        return 0, json.dumps({"picked": [{"id": DOC, "name": "Weekly notes", "mime_type": fake_drive.DOC}], "cancelled": False})

    got = sources.pick_drive(drive.cfg, run=run)
    assert got["picked"][0]["id"] == DOC
    assert seen["argv"] == ["pick"], "the verb of the Drive provider, with no argument"
    assert seen["env"]["GDRIVE_SOURCES_TOKEN"] == "the-one-secret-the-picker-reads"
    assert "OPENROUTER_API_KEY" not in seen["env"] and "NOTION_TOKEN" not in seen["env"]
    assert set(seen["env"]) <= set(resolve.ENV_MINIMUM) | {"GDRIVE_SOURCES_TOKEN", "INTEGRATION_DOCUMENTS_PROVIDER"}
    assert seen["timeout"] == sources.DRIVE_PICK_TIMEOUT
    for bad in ((3, ""), (1, "{}"), (0, "not json"), (0, json.dumps({"picked": "x"}))):
        with pytest.raises(sources.SourcesError) as refused:
            sources.pick_drive(drive.cfg, run=lambda argv, env, timeout, bad=bad: bad)
        assert refused.value.code == "drive"


def test_the_picker_child_is_started_by_the_resolver_its_messages_reach_the_person_and_it_is_ended_when_the_time_is_up(drive, capsys):
    script = ("import sys, time, json\nsys.stderr.write('Open this URL: http://127.0.0.1:1/start\\n'); sys.stderr.flush()\n"
              "mode = sys.argv[1]\nif mode == 'slow':\n    time.sleep(60)\nprint(json.dumps({'picked': [], 'cancelled': True}))\n")

    class Resolver:
        def __init__(self, mode):
            self.mode, self.seen = mode, []

        def start(self, cls, verb, args, **kwargs):
            self.seen.append((cls, verb, list(args), kwargs))
            return subprocess.Popen([sys.executable, "-c", script, self.mode], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, start_new_session=True)

    quick = Resolver("quick")
    code, out = sources._run_pick(quick, drive.cfg, {"PATH": "x"}, 30)
    assert code == 0 and json.loads(out) == {"picked": [], "cancelled": True}
    assert "Open this URL: http://127.0.0.1:1/start" in capsys.readouterr().err, "the address reaches the person as it is printed"
    [(cls, verb, args, kwargs)] = quick.seen
    assert (cls, verb, args) == ("integration:documents", "pick", []) and kwargs["implementation"] == "gdrive" and kwargs["env"] == {"PATH": "x"}
    code, out = sources._run_pick(Resolver("slow"), drive.cfg, {"PATH": "x"}, 1)
    assert code != 0 and out == "", "a Picker that does not answer is ended"

    class Broken:
        def start(self, *args, **kwargs):
            raise OSError("no such program")
    with pytest.raises(sources.SourcesError) as refused:
        sources._run_pick(Broken(), drive.cfg, {}, 5)
    assert refused.value.code == "drive"


# --- a credential never enters a run ---------------------------------------------------------------------------------------------------


def test_the_provider_gets_the_minimum_environment_and_the_one_secret_and_the_converter_gets_neither(drive, monkeypatch):
    for name, value in (("GDRIVE_SOURCES_TOKEN", "t-one"), ("NOTION_SOURCES_TOKEN", "t-two"), ("OPENROUTER_API_KEY", "t-three"),
                        ("VCS_GITHUB_TOKEN", "t-four"), ("INTEGRATION_DOCUMENTS_GDRIVE_API_BASE", "http://127.0.0.1:1")):
        monkeypatch.setenv(name, value)
    for_drive = sources._provider_env(drive.cfg, sources.DRIVE_CLASS, (sources.DRIVE_SECRET,))
    assert for_drive["GDRIVE_SOURCES_TOKEN"] == "t-one"
    assert set(for_drive) <= set(resolve.ENV_MINIMUM) | {"GDRIVE_SOURCES_TOKEN", "INTEGRATION_DOCUMENTS_PROVIDER"}
    assert "INTEGRATION_DOCUMENTS_GDRIVE_API_BASE" not in for_drive, "the test overrides never reach a real provider process"
    for_converter = sources._provider_env(drive.cfg, sources.CONVERTER_CLASS)
    assert not any(k.startswith("GDRIVE") or "TOKEN" in k or "KEY" in k for k in for_converter)
    for_notion = sources._provider_env(drive.cfg, sources.NOTION_CLASS, (sources.NOTION_SECRET,))
    assert "GDRIVE_SOURCES_TOKEN" not in for_notion, "each provider is given its own secret only"


def test_the_environment_of_a_run_holds_no_drive_secret_whatever_the_model_passes(drive, monkeypatch, tmp_path):
    monkeypatch.setenv("GDRIVE_SOURCES_TOKEN", drive.fake.record_json())
    gate = json.loads((REPO / "evals" / "eval-gate.json").read_text(encoding="utf-8"))
    passed = sorted({name for found in gate["models"].values() for name in found.get("pass_env", []) + found.get("web_pass_env", [])})
    assert "GDRIVE_SOURCES_TOKEN" not in passed
    env = lab.LAB.contained_env(str(tmp_path / "run-a"), tuple(passed))
    assert "GDRIVE_SOURCES_TOKEN" not in env and not any(secret in json.dumps(env) for secret in SECRETS)


def test_no_secret_is_in_a_file_of_the_sources_nor_in_what_a_task_receives(drive, monkeypatch):
    monkeypatch.setenv("GDRIVE_SOURCES_TOKEN", drive.fake.record_json())
    for file_id, source_id in ((DOC, "weekly"), (SHEET, "survey"), (PDF, "quarterly")):
        assert ops_sources.source_drive(drive.path, file_id=file_id, source_id=source_id)["results"][0]["imported"]
    got = ops_sources.copies_for(drive.ctx, {"id": 1, "sources": ["weekly", "survey", "quarterly"]}, str(drive.tmp / "prepared"), True)
    held = [Path(root, name) for base in (drive.folder, drive.tmp / "prepared", drive.tmp / "data") for root, _, names in os.walk(base) for name in names]
    assert len(held) >= 9
    for path in held:
        data = path.read_bytes()
        for secret in SECRETS:
            assert secret.encode() not in data, f"{secret[:12]}... is in {path}"
    assert not any(secret in "\n".join(got["lines"]) for secret in SECRETS)


def test_the_provider_message_of_a_failure_carries_no_secret(drive, monkeypatch):
    monkeypatch.setenv("GDRIVE_SOURCES_TOKEN", drive.fake.record_json())
    drive.fake.files.pop(PDF)
    [one] = ops_sources.source_drive(drive.path, file_id=PDF, source_id="quarterly")["results"]
    assert "pick it again" in one["error"] and not any(secret in one["error"] for secret in SECRETS)


# --- the runtime's page and the interface -----------------------------------------------------------------------------------------------


def test_the_picker_page_is_not_part_of_the_interface_and_the_runtime_page_keeps_its_policy():
    interface = REPO / "interface"
    for path in interface.rglob("*"):
        if path.is_file() and path.suffix in (".html", ".js", ".css", ".json", ".mjs"):
            text = path.read_text(encoding="utf-8", errors="replace")
            assert "gapi" not in text and "google.picker" not in text and "apis.google.com" not in text, f"{path} loads the Picker"
    assert not list(interface.rglob("*picker*")), "no file of the interface is the Picker's page"
    assert "default-src 'self'" in (REPO / "runtime" / "service.py").read_text(encoding="utf-8")
    assert "apis.google.com" in (REPO / "providers" / "documents" / "gdrive_picker.py").read_text(encoding="utf-8"), "the page lives with the provider"
