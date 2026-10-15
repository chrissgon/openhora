"""The numbered limits of the sources folder, L21 to L27 (contracts/runtime.md, "The limits"), each with the test named after it,
and the refusals the platform plan lists: a symbolic link out, the home folder, the root, a folder that contains the project, a
folder shared with data_dir or store_db, a mode other than 0700, a non-regular file coming back from a container, and a file
changed outside the runtime. Offline: the converter is a stand-in; nothing is run in a container; no real service is called.

  L21  the folder is dedicated (empty or marked as the runtime's at acceptance) with mode 0700
  L22  it is disjoint from data_dir, store_db, the workbench checkout and the local evidence folder, by device and inode
  L23  the runtime writes only inside it, never follows a symbolic link out; the home folder, the root and a folder that
       contains the project are refused
  L24  what a container writes comes back only as regular files (lstat, O_NOFOLLOW), under a byte cap and naming rules
  L25  a file changed outside the runtime is detected by its hash, sniffed, converted and scanned again, labelled as the
       person's, and never used unattended
  L26  the work copy excludes the folder, even inside a tracked tree
  L27  the catalog is built only from converted output, never by parsing a raw file on the host

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_sources_limits.py
"""
from __future__ import annotations

import ast
import json
import os
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import standin_tree as st
from sources_fixture import make_pdf, standin_convert, with_sources

ops = st.load("ops")
ops_core = st.load("ops_core")
sources = st.load("sources")
project_config = st.load("project_config")
workcopy = st.load("workcopy")
lab = st.load("lab")
REPO = st.REPO
GIT = ["git", "-c", "user.name=Demo", "-c", "user.email=demo@example.test", "-c", "commit.gpgsign=false"]
CSV = "name,price\napple,1.20\npear,3.10\n"


def write_config(tmp_path, **overrides) -> str:
    """A project with a runtime.json (workbench, data_dir, store_db, sources_dir, and what overrides replace; a key set to None is
    left out). Returns the project's path."""
    project = tmp_path / "project"
    (project / "docs" / "workbench").mkdir(parents=True, exist_ok=True)
    config = {"workbench": str(REPO), "data_dir": str(tmp_path / "data"), "store_db": str(tmp_path / "store" / "tasks.sqlite"),
              "sources_dir": str(tmp_path / "sources")}
    config.update(overrides)
    config = {k: v for k, v in config.items() if v is not None}
    (project / "docs" / "workbench" / "runtime.json").write_text(json.dumps(config), encoding="utf-8")
    return str(project)


@pytest.fixture(autouse=True)
def isolated_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(tmp_path / "evidence"))


@pytest.fixture
def case(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    ops.accept_config(path, project_config.load(path)["sha256"])
    ctx = ops_core.context(path)
    monkeypatch.setattr(sources, "provider_convert", lambda cfg, call=None: standin_convert)
    files = tmp_path / "files"
    files.mkdir()

    def drop(name, data):
        target = files / name
        target.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return str(target)
    return SimpleNamespace(path=path, ctx=ctx, cfg=ctx["cfg"], folder=Path(ctx["cfg"]["sources_dir"]), tmp=tmp_path, drop=drop)


def source_row(case, source_id="survey", name="survey.csv"):
    return sources.register(case.ctx, source_id, "file", name)


def refused(function, *args, **kwargs):
    with pytest.raises((sources.SourcesError, project_config.ConfigError, ops_core.OpsError)) as caught:
        function(*args, **kwargs)
    return str(caught.value)


# --- L21 ---------------------------------------------------------------------------------------------------------------------------


def test_limit_21_the_sources_folder_is_dedicated_and_private_empty_or_marked_as_the_runtimes_with_mode_0700(tmp_path):
    # missing: created 0700 and marked
    made = tmp_path / "made"
    done = sources.accept_folder(str(made))
    assert done["created"] and done["marked"] and stat.S_IMODE(made.stat().st_mode) == 0o700 and (made / sources.MARKER).is_file()
    assert json.loads((made / sources.MARKER).read_text())["kind"] == "openhora-sources"
    # empty and 0700: marked
    empty = tmp_path / "empty"
    empty.mkdir(mode=0o700)
    assert sources.accept_folder(str(empty)) == {"path": str(empty), "created": False, "marked": True}
    # marked: kept as it is, with its content, and not marked again
    (empty / "survey").mkdir()
    assert sources.accept_folder(str(empty))["marked"] is False
    # not empty and not marked: not dedicated
    other = tmp_path / "other"
    other.mkdir(mode=0o700)
    (other / "holiday-photos").mkdir()
    assert "not dedicated" in refused(sources.accept_folder, str(other)) and not (other / sources.MARKER).exists()
    # the marker must be a real marker: a link, a folder or text that is not the runtime's is no mark
    forged = tmp_path / "forged"
    forged.mkdir(mode=0o700)
    (forged / sources.MARKER).write_text("hello\n")
    (forged / "x").write_text("x")
    assert "not dedicated" in refused(sources.accept_folder, str(forged))
    # at use, the same: the mark and the mode are checked again by every operation
    case_path = write_config(tmp_path, sources_dir=str(tmp_path / "sources2"))
    ops.accept_config(case_path, project_config.load(case_path)["sha256"])
    cfg = ops_core.context(case_path)["cfg"]
    sources.check_folder(cfg)
    os.unlink(Path(cfg["sources_dir"]) / sources.MARKER)
    assert "no marker" in refused(sources.check_folder, cfg)


@pytest.mark.parametrize("mode", [0o755, 0o750, 0o770, 0o777, 0o600, 0o500, 0o701])
def test_a_mode_other_than_0700_is_refused_at_acceptance_and_at_every_use(tmp_path, mode):
    folder = tmp_path / "sources"
    folder.mkdir()
    os.chmod(folder, mode)
    assert "0700" in refused(sources.accept_folder, str(folder))
    path = write_config(tmp_path)
    message = refused(ops.accept_config, path, project_config.load(path)["sha256"])
    assert "sources folder is refused" in message and "0700" in message
    ctx = ops_core.context(path, check_config=False)
    assert ctx["store"].cursor_get(ctx["conn"], project_config.ACCEPTED) is None, "nothing was accepted"
    os.chmod(folder, 0o700)
    ops.accept_config(path, project_config.load(path)["sha256"])
    cfg = ops_core.context(path)["cfg"]
    os.chmod(folder, mode)
    assert "0700" in refused(sources.check_folder, cfg)
    assert "0700" in refused(sources.import_version, ops_core.context(path, check_config=False) | {"cfg": cfg},
                             {"id": "x", "type": "file", "origin": "x"}, b"abc", convert=standin_convert)


def test_a_folder_that_belongs_to_someone_else_or_is_a_file_is_not_a_sources_folder(tmp_path):
    plain = tmp_path / "plain"
    plain.write_text("a file")
    assert refused(sources.accept_folder, str(plain))
    assert "parent" in refused(sources.accept_folder, str(tmp_path / "nowhere" / "deep" / "sources"))


# --- L22 ---------------------------------------------------------------------------------------------------------------------------


def test_limit_22_the_sources_folder_is_disjoint_from_the_data_folder_the_store_the_checkout_and_the_local_evidence(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    data, store_db, evidence = tmp_path / "data", tmp_path / "store" / "tasks.sqlite", tmp_path / "evidence"
    for folder in (data, store_db.parent, evidence):
        folder.mkdir(parents=True, exist_ok=True)
    store_db.write_text("")

    def problems(folder, **over):
        return sources.path_problems(str(folder), project=str(project), data_dir=str(data), store_db=str(store_db),
                                     workbench=str(REPO), evidence_base=str(evidence), **over)
    assert problems(tmp_path / "fresh") == [] and problems(project / "vault") == [], "a folder of its own is fine, also inside the project"
    for folder, what in ((data, "data_dir"), (data / "sub", "data_dir"), (tmp_path, "data_dir"), (store_db.parent, "the store"),
                         (REPO, "the workbench checkout"), (REPO / "runtime", "the workbench checkout"),
                         (REPO.parent, "the workbench checkout"), (evidence, "the local evidence folder"),
                         (evidence / "core-orchestrator", "the local evidence folder")):
        found = problems(folder)
        assert any(f"and {what} are not disjoint" in p for p in found), (str(folder), found)
    # the store's file itself; a sibling folder of it holds none of it, so it is a folder of its own
    assert any("the store" in p for p in problems(store_db))
    assert problems(store_db.parent / "sub") == []


def test_a_folder_shared_with_data_dir_or_store_db_is_refused_when_the_configuration_is_read_and_when_it_is_accepted(tmp_path):
    for field, value in (("sources_dir", str(tmp_path / "data")), ("sources_dir", str(tmp_path / "data" / "sources")),
                         ("sources_dir", str(tmp_path / "store"))):
        path = write_config(tmp_path, **{field: value})
        message = refused(project_config.load, path)
        assert "not disjoint" in message, value
    path = write_config(tmp_path, sources_dir=str(REPO / "sources-here"))
    assert "workbench checkout" in refused(project_config.load, path)
    path = write_config(tmp_path, sources_dir=str(tmp_path / "evidence" / "sources"))   # the local evidence folder is asked at acceptance
    assert project_config.load(path)["sources_dir"]
    message = refused(ops.accept_config, path, project_config.load(path)["sha256"])
    assert "local evidence folder" in message
    # the key is mandatory: a project without it does not run
    path = write_config(tmp_path, sources_dir=None)
    assert "needs sources_dir" in refused(project_config.load, path)


def test_disjointness_is_by_device_and_inode_not_by_spelling(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    alias = tmp_path / "alias"
    os.symlink(data, alias)   # a folder reached by another name
    found = sources.path_problems(str(alias / "sources"), project=str(project), data_dir=str(data), store_db=str(tmp_path / "s.sqlite"),
                                  workbench=str(REPO))
    assert any("data_dir" in p for p in found)
    if (tmp_path / "DATA").exists():   # a case-insensitive file system: the same folder spelled in another case
        found = sources.path_problems(str(tmp_path / "DATA" / "sources"), project=str(project), data_dir=str(data),
                                      store_db=str(tmp_path / "s.sqlite"), workbench=str(REPO))
        assert any("data_dir" in p for p in found)
    assert sources._inside(str(alias), str(data)) and sources.related(str(data), str(alias / "x"))
    assert not sources.related(str(project), str(data))


# --- L23 ---------------------------------------------------------------------------------------------------------------------------


def test_limit_23_the_runtime_writes_only_inside_the_sources_folder_and_never_follows_a_symbolic_link_out(case):
    outside = case.tmp / "outside"
    outside.mkdir()
    source = source_row(case)
    # the folder of a source is a link to somewhere else: nothing is written there
    os.symlink(outside, case.folder / "survey")
    assert refused(sources.import_version, case.ctx, source, case.drop("survey.csv", CSV), convert=standin_convert)
    assert list(outside.iterdir()) == [], "nothing went out through the link"
    os.unlink(case.folder / "survey")
    # the staging folder is a link
    os.rename(case.folder / ".incoming", case.folder / ".incoming.real") if (case.folder / ".incoming").exists() else None
    os.symlink(outside, case.folder / ".incoming")
    assert refused(sources.import_version, case.ctx, source, case.drop("survey.csv", CSV), convert=standin_convert)
    assert list(outside.iterdir()) == []
    os.unlink(case.folder / ".incoming")
    # a version folder that is a link is never read through
    done = sources.import_version(case.ctx, source, case.drop("survey.csv", CSV), convert=standin_convert)
    assert done["imported"]
    (outside / "converted.csv").write_text("stolen,data\n1,2\n")
    real = case.folder / "survey" / "1"
    os.rename(real, case.folder / "survey" / "1.moved")
    os.symlink(outside, real)
    folder = sources.Folder(case.cfg)
    try:
        assert refused(folder.read, ["survey", "1", "converted.csv"], 1000) and folder.sha256_of(["survey", "1", "converted.csv"]) is None
    finally:
        folder.close()
    # the folder itself as a link: refused before anything is opened
    link = case.tmp / "link-to-sources"
    os.symlink(case.folder, link)
    other = write_config(case.tmp, sources_dir=str(link))
    assert "symbolic link" in refused(project_config.load, other)
    cfg = dict(case.cfg, sources_dir=str(link))
    assert refused(sources.check_folder, cfg)


def test_the_home_folder_the_root_and_a_folder_that_contains_the_project_are_refused(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    path = write_config(tmp_path, sources_dir=str(home))
    assert "home folder" in refused(project_config.load, path)
    path = write_config(tmp_path, sources_dir="/")
    assert "filesystem root" in refused(project_config.load, path)
    path = write_config(tmp_path, sources_dir=str(tmp_path))   # contains the project (and the data folder)
    assert "contains the project" in refused(project_config.load, path)
    path = write_config(tmp_path, sources_dir=str(tmp_path.parent))
    assert "contains the project" in refused(project_config.load, path)
    project = tmp_path / "project"
    assert "contains the project" in refused(project_config.load, write_config(tmp_path, sources_dir=str(project)))
    ok = write_config(tmp_path, sources_dir=str(home / "sources"))
    assert project_config.load(ok)["sources_dir"] == str((home / "sources").resolve())
    # a symbolic link at the folder's own name
    real = tmp_path / "real"
    real.mkdir()
    os.symlink(real, tmp_path / "linked")
    assert "symbolic link" in refused(project_config.load, write_config(tmp_path, sources_dir=str(tmp_path / "linked")))


def test_a_name_that_is_not_plain_is_never_a_path_inside_the_folder(case):
    for bad in ("..", ".", "a/b", "", "a\\b", "x\x00y"):
        assert refused(sources._plain, bad)
    folder = sources.Folder(case.cfg)
    try:
        assert refused(folder.read, ["..", "data", "x"], 10)
        assert refused(folder.subdir, ["a/b"])
    finally:
        folder.close()


# --- L24 ---------------------------------------------------------------------------------------------------------------------------


def outputs_dir(tmp_path, name="out"):
    folder = tmp_path / name
    folder.mkdir(mode=0o700)
    return folder


def test_limit_24_what_a_container_writes_comes_back_only_as_regular_files_under_a_byte_cap_and_with_names_from_a_closed_list(tmp_path):
    good = outputs_dir(tmp_path, "good")
    (good / "converted.md").write_text("# text\n")
    (good / "info.json").write_text("{}")
    assert sources.collect_outputs(str(good)) == {"converted.md": b"# text\n", "info.json": b"{}"}
    # a link (to a file that exists, and to one that does not)
    link = outputs_dir(tmp_path, "link")
    (tmp_path / "secret.txt").write_text("secret")
    os.symlink(tmp_path / "secret.txt", link / "converted.md")
    assert "not a regular file" in refused(sources.collect_outputs, str(link))
    dangling = outputs_dir(tmp_path, "dangling")
    os.symlink(tmp_path / "nowhere", dangling / "converted.md")
    assert "not a regular file" in refused(sources.collect_outputs, str(dangling))
    # a folder, a pipe, a hard link, a name that is not on the list, too many entries, a file over the cap
    folder = outputs_dir(tmp_path, "folder")
    (folder / "converted.md").mkdir()
    assert "not a regular file" in refused(sources.collect_outputs, str(folder))
    pipe = outputs_dir(tmp_path, "pipe")
    os.mkfifo(pipe / "converted.md")
    assert "not a regular file" in refused(sources.collect_outputs, str(pipe))
    hard = outputs_dir(tmp_path, "hard")
    (hard / "converted.md").write_text("x")
    os.link(hard / "converted.md", tmp_path / "second-name")
    assert "more than one link" in refused(sources.collect_outputs, str(hard))
    named = outputs_dir(tmp_path, "named")
    (named / "converted.md").write_text("x")
    (named / ".hidden").write_text("x")
    assert "not one of its outputs" in refused(sources.collect_outputs, str(named))
    many = outputs_dir(tmp_path, "many")
    for n in ("converted.md", "converted.csv", "info.json"):
        (many / n).write_text("x")
    (many / "extra").write_text("x")
    assert "entries" in refused(sources.collect_outputs, str(many))
    big = outputs_dir(tmp_path, "big")
    (big / "converted.md").write_bytes(b"x" * (sources.CONVERTED_CAP + 1))
    assert "over the" in refused(sources.collect_outputs, str(big))
    (big / "converted.md").write_bytes(b"x" * sources.CONVERTED_CAP)
    assert len(sources.collect_outputs(str(big))["converted.md"]) == sources.CONVERTED_CAP
    info = outputs_dir(tmp_path, "info")
    (info / "converted.md").write_text("x")
    (info / "info.json").write_bytes(b"x" * (sources.INFO_CAP + 1))
    assert "over the" in refused(sources.collect_outputs, str(info))
    assert "cannot be listed" in refused(sources.collect_outputs, str(tmp_path / "missing"))


def test_a_non_regular_file_coming_back_from_a_container_refuses_the_import_and_keeps_nothing(case):
    source = source_row(case)

    def link_out(input_path, subtype, out_dir):
        os.symlink("/etc/hosts", os.path.join(out_dir, "converted.md"))
        return {}

    def fifo_out(input_path, subtype, out_dir):
        os.mkfifo(os.path.join(out_dir, "converted.csv"))
        return {}

    def folder_out(input_path, subtype, out_dir):
        os.mkdir(os.path.join(out_dir, "converted.md"))
        return {}
    for convert in (link_out, fifo_out, folder_out):
        message = refused(sources.import_version, case.ctx, source, case.drop("survey.csv", CSV), convert=convert)
        assert "not a regular file" in message
    assert not any((case.folder / ".incoming").iterdir() if (case.folder / ".incoming").exists() else []) and not (case.folder / "survey").exists()
    assert case.ctx["store"].source_latest(case.ctx["conn"], "survey") is None


# --- L25 ---------------------------------------------------------------------------------------------------------------------------


def test_limit_25_a_file_changed_outside_the_runtime_is_detected_by_its_hash_sniffed_converted_and_scanned_again_labelled_as_the_persons_and_never_used_unattended(case):
    source = source_row(case)
    done = sources.import_version(case.ctx, source, case.drop("survey.csv", CSV), convert=standin_convert)
    assert done["version"] == 1
    folder = sources.Folder(case.cfg)
    try:
        latest = case.ctx["store"].source_latest(case.ctx["conn"], "survey")
        assert sources.verify_version(folder, latest) == {"ok": True, "original": True, "converted": True}
        original = case.folder / "survey" / "1" / "original.csv"
        os.chmod(original, 0o600)
        original.write_text(CSV + "fig,9.00\n")   # the person edits the file in the folder
        assert sources.verify_version(folder, latest) == {"ok": False, "original": False, "converted": True}
    finally:
        folder.close()
    # nothing hands it over as recorded: a task that asks for it is refused, attended or not
    for unattended in (True, False):
        assert "changed outside the runtime" in refused(sources.task_copies, case.ctx, {"sources": ["survey"]},
                                                       str(case.tmp / "prepared"), unattended=unattended)
    # it is sniffed (the bytes are checked as any upload), converted and scanned again, and it is a version of the person's
    again = sources.recheck(case.ctx, source, convert=standin_convert)
    assert again["changed"] and again["version"] == 2 and again["by"] == "person" and again["label"] == "changed-by-person"
    assert again["kind"] == "csv" and (case.folder / "survey" / "2" / "converted.csv").read_text().endswith("fig,9.00\n")
    # never used unattended; used when the person starts the task
    assert "starts on its own" in refused(sources.task_copies, case.ctx, {"sources": ["survey"]}, str(case.tmp / "prepared"), unattended=True)
    attended = sources.task_copies(case.ctx, {"sources": ["survey"]}, str(case.tmp / "prepared"), unattended=False)
    assert attended["records"][0]["version"] == 2
    # the sniff and the scan are made again: a changed file that is not a document, or that holds a key, is refused
    original = case.folder / "survey" / "2" / "original.csv"
    os.chmod(original, 0o600)
    original.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    assert refused(sources.recheck, case.ctx, source, convert=standin_convert)
    assert case.ctx["store"].source_latest(case.ctx["conn"], "survey")["version"] == 2, "a refused change adds no version"


def test_a_planted_key_in_a_changed_pdf_is_found_after_the_conversion(case):
    source = source_row(case, "brief", "brief.pdf")
    sources.import_version(case.ctx, source, case.drop("brief.pdf", make_pdf("A harmless brief")), convert=standin_convert)
    original = case.folder / "brief" / "1" / "original.pdf"
    os.chmod(original, 0o600)
    key = "sk-" + "ant-" + "api03-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"
    original.write_bytes(make_pdf(f"now it holds {key}"))
    assert workcopy.scan(original.read_bytes()) is None
    assert "credential" in refused(sources.recheck, case.ctx, source, convert=standin_convert)


# --- L26 ---------------------------------------------------------------------------------------------------------------------------


def test_limit_26_the_work_copy_excludes_the_sources_folder_even_when_it_sits_inside_a_tracked_tree(tmp_path, monkeypatch):
    project = tmp_path / "project"
    (project / "docs" / "workbench").mkdir(parents=True)
    path = write_config(tmp_path, sources_dir=str(project / "vault"))
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    (project / ".gitignore").write_text(".workbench-local/\n")
    ops.accept_config(path, project_config.load(path)["sha256"])
    ctx = ops_core.context(path)
    monkeypatch.setattr(sources, "provider_convert", lambda cfg, call=None: standin_convert)
    row = sources.register(ctx, "survey", "file", "survey.csv")
    (tmp_path / "survey.csv").write_text(CSV)
    sources.import_version(ctx, row, str(tmp_path / "survey.csv"), convert=standin_convert)
    (project / "note.txt").write_text("a tracked file\n")
    (project / "docs" / "business").mkdir(parents=True)
    (project / "docs" / "business" / "market.md").write_text("# Market\n")
    os.symlink(project / "vault" / "survey" / "1" / "converted.csv", project / "docs" / "business" / "link.md")
    subprocess.run(GIT + ["-C", str(project), "add", "-A"], check=True)
    subprocess.run(GIT + ["-C", str(project), "commit", "-q", "-m", "everything"], check=True)
    tracked = subprocess.run(["git", "-C", str(project), "ls-files"], capture_output=True, text=True, check=True).stdout.split()
    assert "vault/survey/1/converted.csv" in tracked, "the folder is in the tracked tree"
    cfg = ctx["cfg"]
    meta = {"inputs": ["docs/business/market.md"], "outputs": [], "updates": [], "area": "business", "web": False}
    entered = workcopy.entering(str(project), meta, web=False, cfg=cfg, settings_names=[], prepared_dir=str(tmp_path / "prepared"))
    rels = [rel for _s, rel in entered["files"]]
    assert "note.txt" in rels and "docs/business/market.md" in rels, "the rest of the tracked tree enters"
    assert not any(rel.startswith("vault") or rel.endswith("link.md") for rel in rels)
    assert entered["left_out"].count({"path": "vault/", "reason": "the sources folder never enters a run: only the copies its plan chose do"}) == 1
    # a run with the web sees only the artifacts the skill declares: the folder is not among them either
    web = workcopy.entering(str(project), dict(meta, web=True), web=True, cfg=cfg, settings_names=[], prepared_dir=str(tmp_path / "p2"))
    assert not any(rel.startswith("vault") for _s, rel in web["files"])
    # a copy the plan chose enters at its own path, and nothing but that
    made = sources.task_copies(ctx, {"sources": ["survey"]}, str(tmp_path / "p3"), unattended=False)
    with_copy = workcopy.entering(str(project), meta, web=False, cfg=cfg, settings_names=[], prepared_dir=str(tmp_path / "p4"),
                                  sourced=made["files"])
    assert ".workbench-local/sources/survey/converted.csv" in [rel for _s, rel in with_copy["files"]]
    assert not any(rel.startswith("vault") for _s, rel in with_copy["files"])
    with pytest.raises(workcopy.CopyError):
        workcopy.entering(str(project), meta, web=False, cfg=cfg, settings_names=[], prepared_dir=str(tmp_path / "p5"),
                          sourced=[(made["files"][0][0], "docs/business/market.md")])
    assert sources.inside(cfg, str(project / "vault")) and sources.inside(cfg, str(project / "vault" / "survey"))
    assert not sources.inside(cfg, str(project / "note.txt")) and not sources.inside({}, str(project))


def test_limit_26_nothing_a_run_leaves_is_written_into_the_sources_folder_even_when_it_sits_inside_the_project(tmp_path, monkeypatch):
    """The return direction: a run's result that names a path inside the folder (docs/sources/...) is kept, with a reason, and
    nothing is written there; a path beside it still comes back; a change set that touches the folder is protected."""
    project = tmp_path / "project"
    path = write_config(tmp_path, sources_dir=str(project / "sources"))
    ops.accept_config(path, project_config.load(path)["sha256"])
    ctx = ops_core.context(path)
    monkeypatch.setattr(sources, "provider_convert", lambda cfg, call=None: standin_convert)
    row = sources.register(ctx, "survey", "file", "survey.csv")
    (tmp_path / "survey.csv").write_text(CSV)
    sources.import_version(ctx, row, str(tmp_path / "survey.csv"), convert=standin_convert)
    folder = project / "sources"
    before = sorted(str(p.relative_to(folder)) for p in folder.rglob("*"))
    cwd = tmp_path / "copy"
    left = {"sources/survey/1/planted.md": "planted\n", "sources/survey/9/converted.md": "# a version nobody imported\n",
            "sources/.openhora-sources": "{}\n", "docs/business/note.md": "# A note\n"}
    for rel, text in left.items():
        (cwd / rel).parent.mkdir(parents=True, exist_ok=True)
        (cwd / rel).write_text(text)
    result = {"cwd": str(cwd), "staged": [], "changes": {"created": sorted(left), "modified": [], "deleted": [], "unchanged": []}}
    returned, kept, _ = workcopy.returning(path, result, {}, None, "demo-writes", cfg=ctx["cfg"])
    assert [item["path"] for item in returned] == ["docs/business/note.md"], "the file beside the folder comes back"
    assert sorted(item["path"] for item in kept) == sorted(rel for rel in left if rel.startswith("sources/"))
    assert all(item["reason"] == workcopy.SOURCES_KEPT for item in kept)
    assert sorted(str(p.relative_to(folder)) for p in folder.rglob("*")) == before, "nothing was written into the folder"
    assert not (folder / "survey" / "9").exists() and not (folder / "survey" / "1" / "planted.md").exists()
    # defence in depth: whatever the path rule calls the path (here a document of docs/), the folder is never written
    docs = {"cwd": str(cwd), "staged": [], "changes": {"created": ["docs/sources/survey/1/note.md"], "modified": [], "deleted": [], "unchanged": []}}
    (cwd / "docs" / "sources" / "survey" / "1").mkdir(parents=True)
    (cwd / "docs" / "sources" / "survey" / "1" / "note.md").write_text("planted\n")
    inside_docs = {"sources_dir": str(project / "docs" / "sources")}
    returned, kept, _ = workcopy.returning(path, docs, {}, None, "demo-writes", cfg=inside_docs)
    assert returned == [] and [(k["class"], k["reason"]) for k in kept] == [("document", workcopy.SOURCES_KEPT)]
    assert not (project / "docs" / "sources").exists(), "nothing was written there"
    # a change set that touches the folder is refused whoever wrote it: the folder is a protected path of the project
    protected = sources.protected_paths(ctx["cfg"])
    changeset = st.load("changeset")
    for inside in ("sources/survey/1/planted.md", "Sources/survey/1/planted.md", "SOURCES/x", "sOuRcEs/a/b/c.md"):
        assert changeset.matches(inside, protected), inside   # whatever the case a disk keeps
    for beside in ("docs/business/note.md", "sourcesx/a.md", "src/sources.md", "docs/sources.md"):
        assert not changeset.matches(beside, protected), beside
    assert sources.protected_paths({"protected_paths": ["x/*"], "project": path, "sources_dir": str(tmp_path / "elsewhere")}) == ["x/*"]


# --- L27 ---------------------------------------------------------------------------------------------------------------------------


def test_limit_27_the_catalog_is_built_only_from_converted_output_and_no_raw_file_is_parsed_on_the_host(case):
    source = source_row(case, "survey", "survey.xlsx")

    def converter_that_disagrees_with_the_raw_file(input_path, subtype, out_dir):
        # whatever the raw file holds, the catalog is made of what the converter wrote
        Path(out_dir, "converted.csv").write_text("alpha,beta\n1,2\n3,4\n")
        Path(out_dir, "info.json").write_text(json.dumps({"converter": "stand-in", "kind": "csv"}))
        return {}
    raw = b"RAWONLYHEADER,OTHER\nx,y\n"
    done = sources.import_version(case.ctx, source, case.drop("survey.xlsx", raw), convert=converter_that_disagrees_with_the_raw_file)
    columns = [c["name"] for c in done["catalog"]["sheets"][0]["columns"]]
    assert columns == ["alpha", "beta"] and "RAWONLYHEADER" not in json.dumps(done["catalog"])
    # the catalog is read from the registry: the raw file can be gone
    os.chmod(case.folder / "survey" / "1" / "original.csv", 0o600)
    os.unlink(case.folder / "survey" / "1" / "original.csv")
    rows = sources.list_catalog(case.ctx, hashes=False)
    assert rows[0]["catalog"]["sheets"][0]["columns"][0]["name"] == "alpha" and rows[0]["status"] == "unchecked"
    assert sources.list_catalog(case.ctx)[0]["status"] == "changed", "and the missing file is seen by its hash, not parsed"
    # the builder takes the converted bytes and nothing else
    import inspect
    parameters = inspect.signature(sources.catalog_entry).parameters
    assert "converted" in parameters and not any(p in parameters for p in ("original", "raw", "path", "data"))
    # the host module parses no document format: no archive, markup or workbook reader is imported, and the file-type readers are
    # the converter's (the tools in the container)
    tree = ast.parse(Path(sources.__file__).read_text(encoding="utf-8"))
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not imported & {"zipfile", "xml", "html", "openpyxl", "pdfminer", "docx", "subprocess", "pypdf", "PyPDF2", "bs4", "lxml"}


def test_the_sources_modules_import_nothing_of_the_operations_layer():
    for name in ("sources.py",):
        tree = ast.parse((st.RUNTIME / name).read_text(encoding="utf-8"))
        names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        names |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert not {n for n in names if n == "ops" or n.startswith("ops_")}, name


def test_limit_26_returning_cannot_be_called_without_the_sources_configuration():
    """The return check cannot be left out by a caller: cfg is a required keyword with no default."""
    import inspect
    parameter = inspect.signature(workcopy.returning).parameters["cfg"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY and parameter.default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        workcopy.returning("/nowhere", {"cwd": "/x", "staged": [], "changes": {"created": [], "modified": [], "deleted": []}}, {}, None, "demo")


def test_limit_23_a_sources_folder_inside_the_project_s_local_work_folder_is_refused(tmp_path):
    """The file drop, the copies of the sources a task receives and the work data live under .workbench-local/, and the runtime writes
    there by path: the sources folder is never that folder or inside it. It may be elsewhere inside the project."""
    project = tmp_path / "project"
    for name in (".workbench-local", ".workbench-local/drop", ".workbench-local/sources", ".workbench-local/deeper/still"):
        path = write_config(tmp_path, sources_dir=str(project / name))
        text = refused(project_config.load, path)
        assert ".workbench-local/" in text and "sources_dir" in text, name
    # nothing was made there, and an acceptance cannot get round the check
    assert not (project / ".workbench-local").exists()
    path = write_config(tmp_path, sources_dir=str(project / "sources"))
    ops.accept_config(path, project_config.load(path)["sha256"])
    assert (project / "sources" / sources.MARKER).is_file()
    problems = sources.path_problems(str(project / ".workbench-local" / "drop"), project=path, data_dir=str(tmp_path / "data"),
                                     store_db=str(tmp_path / "store" / "tasks.sqlite"), workbench=str(REPO))
    assert any(".workbench-local/" in p for p in problems)


def test_limit_23_a_sources_folder_inside_the_project_s_docs_folder_is_refused(tmp_path):
    """The documents mirror writes under docs/ by path: the sources folder is never docs/ or inside it."""
    project = tmp_path / "project"
    for name in ("docs", "docs/sources", "docs/workbench/vault", "docs/a/b/c"):
        path = write_config(tmp_path, sources_dir=str(project / name))
        text = refused(project_config.load, path)
        assert "docs/" in text and "sources_dir" in text, name
    # a neighbour whose name only starts the same way is fine
    for name in ("docs-archive", "docsx/sources", "sources"):
        path = write_config(tmp_path, sources_dir=str(project / name))
        assert project_config.load(path)["sources_dir"] == str(project / name)


# --- the folder, after review: leftovers, pipes, links with a closing slash, the marker's project, the staging folder ---------------


def import_text(case, text, label="import", name="survey.csv", source_id="survey"):
    row = sources.register(case.ctx, source_id, "file", name) if not case.ctx["store"].sources_list(case.ctx["conn"]) else \
        case.ctx["store"].source_get(case.ctx["conn"], source_id)
    return sources.import_version(case.ctx, row, case.drop(name, text), convert=standin_convert, label=label)


def orphans(case):
    return sorted(p.name for p in (case.folder / ".incoming").iterdir() if p.name.endswith("-orphan"))


def test_a_numbered_folder_with_no_record_never_blocks_the_next_import_it_is_moved_aside(case):
    assert import_text(case, CSV)["version"] == 1
    (case.folder / "survey" / "2").mkdir()
    (case.folder / "survey" / "2" / "planted.md").write_text("planted")
    long_ago = __import__("time").time() - 5 * 86400
    os.utime(case.folder / "survey" / "2", (long_ago, long_ago))   # a leftover of an older backup: its own date is old
    second = import_text(case, CSV + "fig,9.00\n", label="refresh")
    assert second["version"] == 2, "the number after the recorded ones, not after the folders"
    assert (case.folder / "survey" / "2" / "manifest.json").is_file() and not (case.folder / "survey" / "2" / "planted.md").exists()
    [aside] = orphans(case)
    assert (case.folder / ".incoming" / aside / "planted.md").read_text() == "planted", "moved aside, not lost"
    assert __import__("time").time() - (case.folder / ".incoming" / aside).stat().st_mtime < 600, "the sweep counts its 24 hours from the move"
    # a stray file and a link at the next numbers are leftovers too; nothing goes out through the link
    outside = case.tmp / "outside"
    outside.mkdir()
    (case.folder / "survey" / "3").write_text("a stray file")
    third = import_text(case, CSV + "fig,9.00\nkiwi,4.00\n", label="refresh")
    assert third["version"] == 3 and (case.folder / "survey" / "3" / "manifest.json").is_file()
    os.symlink(outside, case.folder / "survey" / "4")
    fourth = import_text(case, CSV + "kiwi,4.00\n", label="refresh")
    assert fourth["version"] == 4 and not (case.folder / "survey" / "4").is_symlink() and list(outside.iterdir()) == []
    assert case.ctx["store"].source_version_count(case.ctx["conn"], "survey") == 4


def test_a_crash_after_the_rename_and_before_the_row_leaves_nothing_that_blocks_the_next_import(case, monkeypatch):
    import_text(case, CSV)
    store = case.ctx["store"]
    real = store.source_version_add

    def power_cut(conn, **kwargs):
        raise RuntimeError("power cut between the rename and the row")
    monkeypatch.setattr(store, "source_version_add", power_cut)
    with pytest.raises(RuntimeError):
        import_text(case, CSV + "fig,9.00\n", label="refresh")
    assert (case.folder / "survey" / "2").is_dir(), "the crash left the folder without a row"
    assert store.source_version_count(case.ctx["conn"], "survey") == 1
    monkeypatch.setattr(store, "source_version_add", real)
    again = import_text(case, CSV + "fig,9.00\n", label="refresh")
    assert again["version"] == 2 and store.source_version_count(case.ctx["conn"], "survey") == 2
    assert sources.verify_version(sources.Folder(case.cfg), store.source_latest(case.ctx["conn"], "survey"))["ok"]
    assert len(orphans(case)) == 1


class Hang(Exception):
    pass


def guarded(seconds=20):
    """A read that waits for a writer on a pipe would hang the test: an alarm turns the hang into a failure."""
    import signal

    class Guard:
        def __enter__(self):
            signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(Hang("a read waited on a pipe")))
            signal.alarm(seconds)

        def __exit__(self, *exc):
            signal.alarm(0)
    return Guard()


def test_a_pipe_where_a_file_should_be_is_refused_and_never_hangs_a_read_or_the_catalog(case):
    import_text(case, CSV)
    version = case.folder / "survey" / "1"
    for name in ("converted.csv", "original.csv"):
        os.chmod(version / name, 0o600)
        (version / name).unlink()
        os.mkfifo(version / name)
    folder = sources.Folder(case.cfg)
    try:
        with guarded():
            assert folder.sha256_of(["survey", "1", "converted.csv"]) is None
            assert "not a regular file" in refused(folder.read, ["survey", "1", "converted.csv"], 1000)
            assert "not a regular file" in refused(folder.open_for_read, ["survey", "1", "original.csv"])
            [row] = sources.list_catalog(case.ctx)
            assert row["status"] == "changed"
            source = case.ctx["store"].source_get(case.ctx["conn"], "survey")
            assert sources.recheck(case.ctx, source, convert=standin_convert)["changed"] is True
    finally:
        folder.close()
    with guarded():
        with pytest.raises(sources.SourcesError) as stopped:
            sources.task_copies(case.ctx, {"sources": ["survey"]}, str(case.tmp / "prepared"), unattended=False)
    assert stopped.value.code == "integrity"


def test_a_link_named_with_a_closing_slash_is_still_a_link(tmp_path):
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    link = tmp_path / "link"
    os.symlink(real, link)
    path = write_config(tmp_path, sources_dir=str(link) + "/")
    assert "symbolic link" in refused(project_config.load, path)
    problems = sources.path_problems(str(link) + "/", project=path, data_dir=str(tmp_path / "data"),
                                     store_db=str(tmp_path / "store" / "tasks.sqlite"), workbench=str(REPO))
    assert any("symbolic link" in p for p in problems)
    for spelling in (str(link) + "/.", str(link) + "/./", str(link) + "//"):
        assert "symbolic link" in refused(project_config.load, write_config(tmp_path, sources_dir=spelling)), spelling
    assert not any("symbolic link" in p for p in sources.path_problems(str(real) + "/.", project=path, data_dir=str(tmp_path / "data"),
                                                                       store_db=str(tmp_path / "store" / "tasks.sqlite"), workbench=str(REPO)))
    # a link higher up (as /tmp and /var are on macOS) is not refused for that: the folder's own name decides
    above = tmp_path / "above"
    os.symlink(tmp_path / "real", above)
    assert not any("symbolic link" in p for p in sources.path_problems(str(above / "inner"), project=path, data_dir=str(tmp_path / "data"),
                                                                       store_db=str(tmp_path / "store" / "tasks.sqlite"), workbench=str(REPO)))
    assert not any("symbolic link" in p for p in sources.path_problems(
        str(real) + "/", project=path, data_dir=str(tmp_path / "data"), store_db=str(tmp_path / "store" / "tasks.sqlite"),
        workbench=str(REPO)))


def test_a_folder_marked_by_one_project_is_refused_to_another_and_a_marker_that_names_no_project_is_no_ones(tmp_path):
    shared = str(tmp_path / "shared")
    a, b, c = write_config(tmp_path / "a", sources_dir=shared), write_config(tmp_path / "b", sources_dir=shared), None
    ops.accept_config(a, project_config.load(a)["sha256"])
    marker = json.loads((Path(shared) / sources.MARKER).read_text())
    assert marker["project"] == sources.project_key(a) and marker["project"] != sources.project_key(b)
    assert marker["project"] == f"{os.stat(a).st_dev}:{os.stat(a).st_ino}" and marker["project_path"] == os.path.realpath(a)
    refusal = refused(ops.accept_config, b, project_config.load(b)["sha256"])
    assert "another project" in refusal and "separate folder for each project" in refusal and "sources_dir" in refusal
    assert marker["project"] in refusal and sources.project_key(b) in refusal, "the old and the new identity are shown"
    assert "--adopt-sources" in refusal and "accept-config" in refusal
    assert "another project" in refused(sources.check_folder, project_config.load(b))
    sources.check_folder(project_config.load(a))   # the first project still uses it
    unbound = str(tmp_path / "unbound")
    sources.accept_folder(unbound)   # a marker that names no project
    c = write_config(tmp_path / "c", sources_dir=unbound)
    assert "another project" in refused(ops.accept_config, c, project_config.load(c)["sha256"])


def test_the_marker_names_the_project_folder_not_its_spelling(tmp_path, monkeypatch):
    """On a case-insensitive disk (macOS) the same project is opened as .../A/PROJECT and as .../a/project: the key is what the file
    system calls the folder, so the spelling cannot change it."""
    a = write_config(tmp_path / "a", sources_dir=str(tmp_path / "shared"))
    before = sources.project_key(a)
    monkeypatch.setattr(os.path, "realpath", lambda path, **kw: "/Some/Other/SPELLING")   # a spelling is never what the key is made of
    assert sources.project_key(a) == before
    monkeypatch.undo()
    assert sources.project_key(a + "/.") == before and sources.project_key(a + "/../project") == before
    link = tmp_path / "alias"
    os.symlink(a, link)
    assert sources.project_key(str(link)) == before
    upper = a[:-len("project")] + "PROJECT"
    if os.path.isdir(upper):   # a case-insensitive disk: the real thing
        assert sources.project_key(upper) == before
        ops.accept_config(a, project_config.load(a)["sha256"])
        sources.check_folder(dict(project_config.load(a), project=upper))


def test_a_folder_marked_for_another_project_is_taken_over_only_by_accept_config_in_the_terminal_with_its_flag(tmp_path):
    shared = str(tmp_path / "shared")
    a, b = write_config(tmp_path / "a", sources_dir=shared), write_config(tmp_path / "b", sources_dir=shared)
    ops.accept_config(a, project_config.load(a)["sha256"])
    sha_b = project_config.load(b)["sha256"]
    # the page, the conversation and the other channels cannot: the operation is a terminal verb, and no other call takes the flag
    operations = st.load("operations")
    [row] = [r for r in operations.OPERATIONS if r["name"] == "accept-config"]
    assert row["channels"] == ("terminal",) and [x["name"] for x in row["args"]] == ["sha256", "adopt_sources"]
    import inspect
    for name in ("set_mode", "give_consent", "set_model"):
        if hasattr(ops, name):
            assert "adopt_sources" not in inspect.signature(getattr(ops, name)).parameters, name
    # without the flag: refused, nothing changes
    assert "--adopt-sources" in refused(ops.accept_config, b, sha_b)
    assert json.loads((Path(shared) / sources.MARKER).read_text())["project"] == sources.project_key(a)
    # the use of the folder by b is refused too, and says what to do
    assert "--adopt-sources" in refused(sources.check_folder, project_config.load(b))
    # with the flag: taken over, and the old and the new identity are in the answer
    done = ops.accept_config(b, sha_b, adopt_sources=True)
    assert done["sources_folder_adopted"] == {"from": {"id": sources.project_key(a), "path": os.path.realpath(a)},
                                              "to": {"id": sources.project_key(b), "path": os.path.realpath(b)}}
    marker = json.loads((Path(shared) / sources.MARKER).read_text())
    assert marker["project"] == sources.project_key(b) and marker["project_path"] == os.path.realpath(b)
    assert stat.S_IMODE((Path(shared) / sources.MARKER).stat().st_mode) == 0o600 and not (Path(shared) / (sources.MARKER + ".new")).exists()
    sources.check_folder(project_config.load(b))
    assert "another project" in refused(sources.check_folder, project_config.load(a)), "the first project no longer holds it"
    # the flag changes nothing for a folder that is not foreign, and an acceptance without it never adopts
    again = ops.accept_config(b, sha_b, adopt_sources=True)
    assert "sources_folder_adopted" not in again


def test_the_staging_folder_of_an_import_is_opened_without_following_a_link_and_is_private(case):
    outside = case.tmp / "outside-staging"
    outside.mkdir()
    staging = Path(case.cfg["data_dir"]) / sources.STAGING
    if staging.is_dir():
        staging.rmdir() if not any(staging.iterdir()) else None
    os.symlink(outside, staging)
    source = source_row(case)
    assert refused(sources.import_version, case.ctx, source, case.drop("survey.csv", CSV), convert=standin_convert)
    assert list(outside.iterdir()) == [], "nothing went out through the link"
    assert sources_list_empty(case)
    os.unlink(staging)
    staging.mkdir(mode=0o755)   # a folder of ours with a wide mode is set back to 0700, not followed anywhere
    done = sources.import_version(case.ctx, source, case.drop("survey.csv", CSV), convert=standin_convert)
    assert done["imported"] and stat.S_IMODE(staging.stat().st_mode) == 0o700 and list(staging.iterdir()) == []


def sources_list_empty(case):
    return case.ctx["store"].source_version_count(case.ctx["conn"], "survey") == 0
