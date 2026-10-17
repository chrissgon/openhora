"""Offline tests of scripts/skill_import.py: bringing a skill from outside the repository, checking it, recording its vetting, and
planning its test (package IMPORT-CLI). No model is called, nothing is downloaded and no file of an imported skill is run: the
fixtures are under scripts/tests/fixtures/import/ (fictional names, a planted instruction, a script that writes to a remote and
holds a fake secret listed in .security-scan-allow); links, pipes and hard links are made at run time in a temporary folder.

Run: uv run --with pytest pytest scripts/tests/test_skill_import.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures" / "import"
PLANTED = "Zk39-Qm71-" + "Lp28-Vx55"  # a fake value of no provider's format, written into a fixture at run time

spec = importlib.util.spec_from_file_location("skill_import_under_test", REPO / "scripts" / "skill_import.py")
si = importlib.util.module_from_spec(spec)
spec.loader.exec_module(si)
es = si.status_module()


@pytest.fixture(autouse=True)
def own_folders(tmp_path, monkeypatch):
    """The home, the local evidence and the data folder of every test are its own: nothing of the person's machine is read or written."""
    monkeypatch.setenv("WB_IMPORT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(tmp_path / "evidence"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return tmp_path


def call(capsys, *argv):
    code = si.main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def fetched(capsys, source, *extra):
    code, out = call(capsys, "fetch", "--from", str(source), *extra)
    assert code == 0, out
    return out["quarantine"]


def normalized(capsys, source=FIX / "web-notes", name="eng-web-notes", declare=("requires=none", "side_effects=none"), drop=(), area=None):
    quarantine = fetched(capsys, source)
    argv = ["normalize", "--quarantine", quarantine, "--name", name]
    for item in declare:
        argv += ["--declare", item]
    for item in drop:
        argv += ["--drop", item]
    if area:
        argv += ["--area", area]
    code, out = call(capsys, *argv)
    assert code == 0, out
    return Path(out["folder"])


def copy_source(tmp_path, name="web-notes", fixture=None):
    target = tmp_path / "src" / name
    shutil.copytree(fixture or FIX / "web-notes", target)
    return target


def write_cases(folder, name):
    data = json.loads((FIX / "cases" / "evals.json").read_text())
    data["skill_name"] = name
    (folder / "evals").mkdir(exist_ok=True)
    (folder / "evals" / "evals.json").write_text(json.dumps(data, indent=2))
    shutil.copytree(FIX / "cases" / "files", folder / "evals" / "files", dirs_exist_ok=True)
    (folder / "evals" / "import").mkdir(parents=True, exist_ok=True)
    shutil.copy(FIX / "cases" / "cases-origin.json", folder / "evals" / "import" / "cases-origin.json")


def vetting(tmp_path, name, verdict="install", filename="vetting.md", extra=""):
    path = tmp_path / filename
    path.write_text(f"# Security vetting of {name}, 2030-01-02\n\nVerdict: {verdict}, since the scan and the reading found nothing else.\n{extra}")
    return path


# --- the home: outside the checkout, and never a folder a harness discovers -------------------------------------------

def test_the_default_home_is_under_the_data_home_and_beside_the_local_evidence(monkeypatch, tmp_path):
    monkeypatch.delenv("WB_IMPORT_HOME")
    assert si.resolve_home(None) == str(tmp_path / "data" / "openhora" / "skills")
    assert si.resolve_home(str(tmp_path / "mine")) == str(tmp_path / "mine")


def test_a_home_inside_the_checkout_is_refused_by_device_and_inode(tmp_path):
    with pytest.raises(si.Refused, match="inside the workbench checkout"):
        si.resolve_home(str(REPO / "imported-skills"))
    link = tmp_path / "link-to-checkout"
    os.symlink(REPO, link)
    with pytest.raises(si.Refused, match="inside the workbench checkout"):
        si.resolve_home(str(link / "anything"))


def test_a_home_whose_path_holds_the_skills_folder_of_any_adapter_is_refused(tmp_path):
    skills_dirs = si.adapter_data()[0]
    assert skills_dirs  # read from adapters/*/eval.json, never named in the code
    for skills_dir in sorted(skills_dirs):
        for home in (tmp_path / skills_dir, tmp_path / skills_dir / "imports"):
            with pytest.raises(si.Refused, match="discovers skills"):
                si.resolve_home(str(home))
    assert si.resolve_home(str(tmp_path / "somewhere" / "skills")) == str(tmp_path / "somewhere" / "skills")


def test_the_home_flag_beats_the_environment(capsys, tmp_path):
    code, out = call(capsys, "fetch", "--from", str(FIX / "web-notes"), "--home", str(tmp_path / "other"))
    assert code == 0 and out["quarantine"].startswith(str(tmp_path / "other" / ".quarantine"))
    assert not (tmp_path / "home").exists()


def test_a_home_flag_inside_the_checkout_stops_the_verb_with_a_refusal(capsys):
    code, out = call(capsys, "fetch", "--from", str(FIX / "web-notes"), "--home", str(REPO / "imports"))
    assert code == 1 and "inside the workbench checkout" in out["refused"]
    assert not (REPO / "imports").exists()


# --- fetch: a local source ----------------------------------------------------------------------------------------------

def test_a_local_folder_is_copied_file_by_file_into_a_quarantine_and_its_origin_is_recorded(capsys, tmp_path):
    source = copy_source(tmp_path)
    quarantine = Path(fetched(capsys, source))
    tree = quarantine / "tree"
    names = sorted(str(p.relative_to(tree)) for p in tree.rglob("*") if p.is_file())
    assert names == ["SKILL.md", "assets/notes-template.md", "references/style.md", "scripts/count_words.py"]
    for name in names:  # byte for byte, the planted instruction included
        assert (tree / name).read_bytes() == (source / name).read_bytes()
    origin = json.loads((quarantine / "origin.json").read_text())
    assert origin["kind"] == "local" and origin["location"] == str(source) and origin["commit"] is None and origin["subpath"] == ""
    assert origin["date"] and len(origin["tree_sha256"]) == 64
    assert origin["tree_sha256"] == si.tree_hash(str(tree))
    assert oct(os.stat(tree / "scripts" / "count_words.py").st_mode & 0o777) == oct(0o644)


def test_nothing_in_the_source_is_executed_or_imported_by_any_verb(capsys, tmp_path):
    marker = tmp_path / "ran"
    source = copy_source(tmp_path)
    (source / "scripts" / "boom.py").write_text(f"open({str(marker)!r}, 'w').write('ran')\n")
    (source / "scripts" / "tests").mkdir()
    (source / "scripts" / "tests" / "test_boom.py").write_text(f"open({str(marker)!r}, 'w').write('ran')\ndef test_x():\n    assert True\n")
    folder = normalized(capsys, source)
    write_cases(folder, folder.name)
    assert call(capsys, "check", "--name", folder.name)[0] == 0
    call(capsys, "status")
    call(capsys, "bump", "--name", folder.name)
    assert not marker.exists()


@pytest.mark.parametrize("kind", ["file link", "folder link", "pipe", "hard link"])
def test_a_link_a_pipe_or_a_hard_link_in_the_source_is_refused_and_listed(capsys, tmp_path, kind):
    source = copy_source(tmp_path)
    secret = tmp_path / "private.txt"
    secret.write_text("not for a run")
    if kind == "file link":
        os.symlink(secret, source / "references" / "notes.md")
    elif kind == "folder link":
        os.symlink(tmp_path, source / "assets" / "up")
    elif kind == "pipe":
        os.mkfifo(source / "references" / "feed")
    else:
        os.link(source / "references" / "style.md", source / "references" / "style-copy.md")
    code, out = call(capsys, "fetch", "--from", str(source))
    assert code == 3 and "cannot be copied" in out["stopped"]
    assert out["refused"] and all(r["path"] and r["why"] for r in out["refused"])
    assert out["questions"][0]["key"] == "source"
    assert not list((tmp_path / "home" / ".quarantine").iterdir())  # nothing was left behind


def test_a_source_that_is_itself_a_link_is_refused(capsys, tmp_path):
    source = copy_source(tmp_path)
    os.symlink(source, tmp_path / "alias")
    code, out = call(capsys, "fetch", "--from", str(tmp_path / "alias"))
    assert code == 1 and "symbolic link" in out["refused"]


def test_the_caps_of_files_and_bytes_refuse_a_big_source(capsys, tmp_path, monkeypatch):
    source = copy_source(tmp_path)
    monkeypatch.setattr(si, "CAP_FILES", 3)
    code, out = call(capsys, "fetch", "--from", str(source))
    assert code == 3 and "over the caps" in out["stopped"] and out["files"] == 4
    monkeypatch.setattr(si, "CAP_FILES", 2000)
    monkeypatch.setattr(si, "CAP_BYTES", 100)
    code, out = call(capsys, "fetch", "--from", str(source))
    assert code == 3 and "over the caps" in out["stopped"]
    assert (si.CAP_FILES, si.CAP_BYTES) == (2000, 100)


def test_the_caps_are_two_thousand_files_and_twenty_megabytes():
    fresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fresh)
    assert (fresh.CAP_FILES, fresh.CAP_BYTES) == (2000, 20 * 1024 * 1024)


def test_one_markdown_file_is_a_source_and_a_link_to_it_is_not(capsys, tmp_path):
    quarantine = Path(fetched(capsys, FIX / "single-note.md"))
    assert [p.name for p in (quarantine / "tree").iterdir()] == ["single-note.md"]
    other = tmp_path / "second.md"
    other.write_text("A second note.\n")
    os.symlink(other, tmp_path / "second-link.md")
    code, out = call(capsys, "fetch", "--from", str(tmp_path / "second-link.md"))
    assert code == 1 and "symbolic link" in out["refused"]


def test_a_folder_that_holds_several_skills_lists_the_candidates_and_stops(capsys, tmp_path):
    source = tmp_path / "bundle"
    for name in ("one", "two"):
        shutil.copytree(FIX / "web-notes", source / "skills" / name)
    code, out = call(capsys, "fetch", "--from", str(source))
    assert code == 3 and out["candidates"] == ["skills/one", "skills/two"] and out["questions"][0]["key"] == "path"
    assert not list((tmp_path / "home" / ".quarantine").iterdir())
    code, out = call(capsys, "fetch", "--from", str(source), "--path", "skills/two")
    assert code == 0 and out["origin"]["subpath"] == "skills/two"
    assert (Path(out["quarantine"]) / "tree" / "SKILL.md").is_file()


def test_a_folder_with_one_skill_below_its_root_is_that_skill_and_a_path_cannot_leave_the_source(capsys, tmp_path):
    source = tmp_path / "bundle"
    shutil.copytree(FIX / "web-notes", source / "only" / "web-notes")
    code, out = call(capsys, "fetch", "--from", str(source))
    assert code == 0 and out["origin"]["subpath"] == "only/web-notes"
    for bad in ("../elsewhere", "/etc"):
        code, out = call(capsys, "fetch", "--from", str(source), "--path", bad)
        assert code == 1 and "relative path" in out["refused"]


def test_a_folder_with_no_skill_in_it_asks_for_the_single_file(capsys, tmp_path):
    source = tmp_path / "notes"
    source.mkdir()
    (source / "a.txt").write_text("x\n")
    code, out = call(capsys, "fetch", "--from", str(source))
    assert code == 3 and "no SKILL.md" in out["stopped"]


# --- fetch: a git source (no network here: the plan is a pure function, the run is replaced) ----------------------------

def test_the_clone_is_planned_shallow_with_no_hook_no_link_no_submodule_no_credential_and_a_throwaway_environment(monkeypatch):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "inherited-value")
    monkeypatch.setenv("SOME_TOKEN", "inherited-value")
    plan = si.git_plan("https://code.example/dana/tinykv", "v1.0", "/q/raw", "/q/home")
    argv = plan["argv"]
    assert argv[0] == "git" and argv[argv.index("clone"):] == ["clone", "--depth", "1", "--no-tags", "--no-recurse-submodules",
                                                              "--branch", "v1.0", "--", "https://code.example/dana/tinykv", "/q/raw"]
    config = [argv[i + 1] for i, a in enumerate(argv) if a == "-c"]
    assert config == ["core.hooksPath=/dev/null", "core.symlinks=false", "credential.helper=", "protocol.allow=never",
                      "protocol.https.allow=always"]
    env = plan["env"]
    assert env["HOME"] == "/q/home" and env["GIT_CONFIG_NOSYSTEM"] == "1" and env["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert env["GIT_TERMINAL_PROMPT"] == "0" and env["GIT_LFS_SKIP_SMUDGE"] == "1" and env["GIT_ALLOW_PROTOCOL"] == "https"
    assert set(env) == {"PATH", "HOME", "LANG", "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL", "GIT_TERMINAL_PROMPT", "GIT_LFS_SKIP_SMUDGE",
                        "GIT_ALLOW_PROTOCOL"}  # nothing of the caller's environment travels
    assert plan["ls_files"][-4:] == ["-C", "/q/raw", "ls-files", "-s"] and plan["rev_parse"][-4:] == ["-C", "/q/raw", "rev-parse", "HEAD"]
    without_ref = si.git_plan("https://code.example/dana/tinykv", None, "/q/raw", "/q/home")["argv"]
    assert "--branch" not in without_ref


@pytest.mark.parametrize("url, why", [
    ("ssh://code.example/dana/tinykv", "scheme"), ("git@code.example:dana/tinykv.git", "ssh address"),
    ("file:///srv/tinykv", "scheme"), ("ext::sh -c touch% /tmp/x", "space"), ("http://code.example/dana/tinykv", "scheme"),
    ("git://code.example/dana/tinykv", "scheme"), ("https://dana:{}@code.example/dana/tinykv".format("pw0"), "user or a password"),
    ("https://dana@code.example/dana/tinykv", "user or a password"), ("-oProxyCommand=x", "starts with"),
    ("https://code.example/dana/tinykv?x=1", "no query"), ("https:///dana/tinykv", "a host"), ("", "empty"),
])
def test_a_url_that_is_not_plain_https_is_refused(url, why):
    with pytest.raises(si.Refused) as e:
        si.git_plan(url, None, "/q/raw", "/q/home")
    assert why in e.value.why


@pytest.mark.parametrize("ref", ["--upload-pack=x", "0123456789abcdef0123456789abcdef01234567", "a..b", "dir/"])
def test_a_ref_must_be_a_branch_or_a_tag_name(ref):
    with pytest.raises(si.Refused):
        si.git_plan("https://code.example/dana/tinykv", ref, "/q/raw", "/q/home")


def test_a_git_source_waits_for_an_explicit_yes_and_nothing_runs_without_it(capsys, monkeypatch):
    monkeypatch.setattr(si, "run_command", lambda *a, **k: pytest.fail("a download ran without the yes"))
    code, out = call(capsys, "fetch", "--from", "https://code.example/dana/tinykv", "--ref", "main")
    assert code == 3 and "explicit yes" in out["stopped"]
    assert out["plan"]["url"] == "https://code.example/dana/tinykv" and out["plan"]["depth"] == 1
    assert "--depth" in out["plan"]["argv"] and "GIT_TERMINAL_PROMPT" in out["plan"]["environment"]
    assert out["questions"][0]["recommended"].startswith("yes")
    assert not list((Path(os.environ["WB_IMPORT_HOME"]) / ".quarantine").iterdir())


@pytest.mark.parametrize("url", ["ssh://code.example/x", "https://user:pw@code.example/x", "git@code.example:x/y.git"])
def test_a_refused_url_stops_the_fetch_before_any_question(capsys, monkeypatch, url):
    monkeypatch.setattr(si, "run_command", lambda *a, **k: pytest.fail("a command ran"))
    code, out = call(capsys, "fetch", "--from", url, "--yes")
    assert code == 1 and "refused" in out


def fake_git(monkeypatch, files, links=(), commit="a" * 40):
    """Replace the commands of a clone: the clone writes `files` and a .git folder into its destination, ls-files lists `links`."""
    seen = []

    def run(argv, cwd=None, env=None, timeout=900):
        seen.append((argv, env))
        if "clone" in argv:
            dest = Path(argv[-1])
            for rel, text in files.items():
                (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                (dest / rel).write_text(text)
            (dest / ".git").mkdir()
            (dest / ".git" / "config").write_text("[core]\n")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        if "ls-files" in argv:
            return types.SimpleNamespace(returncode=0, stderr="", stdout="".join(f"{mode} {'0' * 40} 0\t{path}\n" for path, mode in links))
        if "rev-parse" in argv:
            return types.SimpleNamespace(returncode=0, stdout=commit + "\n", stderr="")
        pytest.fail(f"unexpected command {argv}")
    monkeypatch.setattr(si, "run_command", run)
    return seen


def test_a_confirmed_clone_drops_dot_git_records_the_commit_and_keeps_the_tree(capsys, monkeypatch):
    seen = fake_git(monkeypatch, {"SKILL.md": (FIX / "web-notes" / "SKILL.md").read_text(), "references/style.md": "x\n"}, [("SKILL.md", "100644")])
    code, out = call(capsys, "fetch", "--from", "https://code.example/dana/tinykv", "--ref", "main", "--yes")
    assert code == 0 and out["origin"]["kind"] == "git" and out["origin"]["commit"] == "a" * 40 and out["origin"]["ref"] == "main"
    tree = Path(out["quarantine"]) / "tree"
    assert (tree / "SKILL.md").is_file() and not (tree / ".git").exists() and not (Path(out["quarantine"]) / "raw").exists()
    assert not [p for p in Path(out["quarantine"]).iterdir() if p.name.startswith("home-")]
    assert "clone" in seen[0][0] and seen[0][1]["GIT_TERMINAL_PROMPT"] == "0"


def test_a_clone_whose_listing_holds_a_link_is_refused_and_leaves_nothing(capsys, monkeypatch):
    fake_git(monkeypatch, {"SKILL.md": "x\n", "docs/key": "../../private\n"}, [("SKILL.md", "100644"), ("docs/key", "120000")])
    code, out = call(capsys, "fetch", "--from", "https://code.example/dana/tinykv", "--yes")
    assert code == 3 and out["refused"] == [{"path": "docs/key", "why": "a symbolic link"}]
    assert not list((Path(os.environ["WB_IMPORT_HOME"]) / ".quarantine").iterdir())


def test_the_listing_of_a_clone_gives_links_and_submodules():
    assert si.clone_links("100644 a 0\tok.md\n120000 b 0\tlink\n160000 c 0\tvendor\n") == [("link", "a symbolic link"), ("vendor", "a submodule")]


@pytest.mark.skipif(not os.environ.get("SKILL_IMPORT_NETWORK_TEST_URL"), reason="a real clone needs the network: set SKILL_IMPORT_NETWORK_TEST_URL to a https repository")
def test_a_real_shallow_clone_of_a_public_repository(capsys):
    code, out = call(capsys, "fetch", "--from", os.environ["SKILL_IMPORT_NETWORK_TEST_URL"], "--yes")
    assert code in (0, 3), out


# --- normalize ---------------------------------------------------------------------------------------------------------

def test_an_agent_skills_folder_is_normalized_with_its_body_untouched_and_the_foreign_keys_in_the_record(capsys, tmp_path):
    source = FIX / "web-notes"
    folder = normalized(capsys)
    v = si.validate_module()
    text = (folder / "SKILL.md").read_text()
    front, body = si.split_text(text)
    fm = v.load_yaml(front)
    assert fm["name"] == "eng-web-notes" and fm["license"] == "MIT" and set(fm) == {"name", "description", "license", "metadata"}
    original_front, original_body = si.split_text((source / "SKILL.md").read_text())
    assert fm["description"] == v.load_yaml(original_front)["description"]  # verbatim
    assert body == original_body  # the only edit is the frontmatter
    meta = fm["metadata"]
    assert meta["area"] == "engineering" and meta["kind"] == "capability" and meta["version"] == "0.1.0"
    assert (meta["requires"], meta["side_effects"], meta["inputs"], meta["outputs"], meta["updates"]) == ([], [], [], [], [])
    for rel in ("references/style.md", "assets/notes-template.md", "scripts/count_words.py"):
        assert (folder / rel).read_bytes() == (source / rel).read_bytes()
    record = json.loads((folder / "evals" / "import" / "record.json").read_text())
    assert sorted(record["foreign_frontmatter"]) == ["allowed-tools", "compatibility", "metadata"]
    assert record["foreign_frontmatter"]["metadata"] == {"author": "Dana Example", "version": "1.2"}
    assert record["origin_name"] == "web-notes" and record["origin_version"] == "1.2" and record["shape"] == "agent-skills-folder"
    assert record["assumed"] == ["inputs", "outputs", "updates"] and record["declared"] == {"requires": [], "side_effects": []}
    assert any("allowed-tools" in n and "container is the boundary" in n for n in record["notes"])
    assert "allowed-tools" not in text and "compatibility" not in text


def test_the_version_file_names_the_content_and_the_quarantine_is_gone(capsys):
    folder = normalized(capsys)
    lines = [json.loads(l) for l in (folder / "evals" / "versions.jsonl").read_text().splitlines()]
    assert lines == [{"version": "0.1.0", "content_sha256": es.content_hash(str(folder)), "class": "new", "date": lines[0]["date"]}]
    assert es.parse_versions((folder / "evals" / "versions.jsonl").read_text())[1] == []
    assert not list((folder.parent / ".quarantine").iterdir())


def test_nothing_is_installed_anywhere_but_the_home(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = {p for p in tmp_path.rglob("*") if p.is_file()}
    folder = normalized(capsys)
    created = {p for p in tmp_path.rglob("*") if p.is_file()} - before
    assert created and all(str(folder) in str(p) for p in created)
    settings_dirs = {s.split("/")[0] for s in si.adapter_data()[0]}
    assert not [p for p in created if set(p.parts) & settings_dirs]


def test_the_origins_own_cases_are_never_imported(capsys, tmp_path):
    source = copy_source(tmp_path)
    (source / "evals").mkdir()
    (source / "evals" / "evals.json").write_text('{"evals": []}')
    folder = normalized(capsys, source)
    assert not (folder / "evals" / "evals.json").exists()
    record = json.loads((folder / "evals" / "import" / "record.json").read_text())
    assert {"path": "evals", "why": "the origin's own cases are never imported: the cases are yours"} in record["dropped"]


def test_one_markdown_file_is_wrapped_and_a_missing_description_stops_with_the_first_paragraph_quoted(capsys):
    quarantine = fetched(capsys, FIX / "single-note.md")
    code, out = call(capsys, "normalize", "--quarantine", quarantine, "--name", "core-meeting-log", "--declare", "requires=none",
                     "--declare", "side_effects=none")
    assert code == 3 and [q["key"] for q in out["questions"]] == ["description"]
    assert "Rewrite a rough meeting log as a clean list of decisions and owners." in out["questions"][0]["recommended"]
    assert not (Path(os.environ["WB_IMPORT_HOME"]) / "core-meeting-log").exists()  # nothing is written before the answer
    code, out = call(capsys, "normalize", "--quarantine", quarantine, "--name", "core-meeting-log", "--declare", "requires=none",
                     "--declare", "side_effects=none", "--declare", "description=Rewrite a meeting log as decisions and owners. Use when a log is pasted.")
    assert code == 0, out
    folder = Path(out["folder"])
    front, body = si.split_text((folder / "SKILL.md").read_text())
    assert body == (FIX / "single-note.md").read_text()  # the whole file is the body
    assert si.validate_module().load_yaml(front)["metadata"]["area"] == "core"
    assert json.loads((folder / "evals" / "import" / "record.json").read_text())["shape"] == "single-markdown-file"


def test_a_name_without_an_area_prefix_stops_and_recommends_nothing_it_cannot_know(capsys):
    quarantine = fetched(capsys, FIX / "web-notes")
    code, out = call(capsys, "normalize", "--quarantine", quarantine, "--name", "web-notes", "--declare", "requires=none", "--declare", "side_effects=none")
    assert code == 3 and out["questions"][0]["key"] == "name" and "area prefix" in out["questions"][0]["question"]
    assert out["questions"][0]["recommended"].startswith("none: the area is yours")
    code, out = call(capsys, "normalize", "--quarantine", quarantine, "--name", "web-notes", "--area", "engineering", "--declare", "requires=none",
                     "--declare", "side_effects=none")
    assert out["questions"][0]["recommended"] == "eng-web-notes"


def test_an_area_that_disagrees_with_the_prefix_stops(capsys):
    quarantine = fetched(capsys, FIX / "web-notes")
    code, out = call(capsys, "normalize", "--quarantine", quarantine, "--name", "eng-web-notes", "--area", "marketing",
                     "--declare", "requires=none", "--declare", "side_effects=none")
    assert code == 3 and out["questions"][0]["key"] == "area"


def test_a_name_that_is_a_skill_of_the_repository_stops_and_recommends_the_imported_name(capsys):
    quarantine = fetched(capsys, FIX / "web-notes")
    code, out = call(capsys, "normalize", "--quarantine", quarantine, "--name", "eng-code-review", "--declare", "requires=none",
                     "--declare", "side_effects=none")
    assert code == 3 and out["questions"][0]["recommended"] == "eng-code-review-imported"


@pytest.mark.parametrize("name", ["Eng Notes", "eng--notes", "eng_notes", "e" * 70])
def test_a_name_that_is_not_a_skill_name_stops(capsys, name):
    quarantine = fetched(capsys, FIX / "web-notes")
    code, out = call(capsys, "normalize", "--quarantine", quarantine, "--name", name, "--declare", "requires=none", "--declare", "side_effects=none")
    assert code == 3 and out["questions"][0]["key"] == "name"


def test_requires_and_side_effects_must_be_answered_and_the_others_may_be_left(capsys):
    quarantine = fetched(capsys, FIX / "web-notes")
    code, out = call(capsys, "normalize", "--quarantine", quarantine, "--name", "eng-web-notes")
    assert code == 3 and [q["key"] for q in out["questions"]] == ["requires", "side_effects"]
    assert all(q["recommended"].startswith("--declare") for q in out["questions"])
    code, out = call(capsys, "normalize", "--quarantine", quarantine, "--name", "eng-web-notes", "--declare", "requires=integration:issue-tracker",
                     "--declare", "side_effects=push,publish", "--declare", "inputs=docs/notes.md")
    assert code == 0 and out["assumed"] == ["outputs", "updates"]
    meta = si.validate_module().load_yaml(si.split_text((Path(out["folder"]) / "SKILL.md").read_text())[0])["metadata"]
    assert (meta["requires"], meta["side_effects"], meta["inputs"]) == (["integration:issue-tracker"], ["push", "publish"], ["docs/notes.md"])


def test_an_effect_or_a_requirement_outside_the_vocabulary_stops(capsys):
    quarantine = fetched(capsys, FIX / "web-notes")
    code, out = call(capsys, "normalize", "--quarantine", quarantine, "--name", "eng-web-notes", "--declare", "requires=mailbox",
                     "--declare", "side_effects=explode")
    assert code == 3 and sorted(q["key"] for q in out["questions"]) == ["requires", "side_effects"]


def test_an_unknown_declare_key_is_a_usage_error(capsys):
    with pytest.raises(SystemExit):
        si.main(["normalize", "--name", "eng-web-notes", "--declare", "area=engineering"])


def test_a_foreign_flow_an_agent_file_and_a_body_that_hands_work_over_are_refused(capsys, tmp_path):
    flow = tmp_path / "src" / "flow"
    shutil.copytree(FIX / "web-notes", flow)
    text = (flow / "SKILL.md").read_text().replace("metadata:\n", "metadata:\n  kind: flow\n")
    (flow / "SKILL.md").write_text(text)
    code, out = call(capsys, "normalize", "--quarantine", fetched(capsys, flow), "--name", "eng-web-notes", "--declare", "requires=none", "--declare", "side_effects=none")
    assert code == 1 and "flow" in out["refused"]
    agent = tmp_path / "reviewer.md"
    agent.write_text("---\nname: reviewer\ndescription: Review a diff.\ntools: Read, Grep\nmodel: small\n---\nReview the diff.\n")
    code, out = call(capsys, "normalize", "--quarantine", fetched(capsys, agent), "--name", "eng-reviewer", "--declare", "requires=none", "--declare", "side_effects=none")
    assert code == 1 and "agent file" in out["refused"]
    hands = tmp_path / "src" / "hands"
    shutil.copytree(FIX / "web-notes", hands)
    (hands / "SKILL.md").write_text((hands / "SKILL.md").read_text() + "\nThen run the `eng-code-review` skill, and use the `eng-unit-tests` skill.\n")
    code, out = call(capsys, "normalize", "--quarantine", fetched(capsys, hands), "--name", "eng-web-notes", "--declare", "requires=none", "--declare", "side_effects=none")
    assert code == 1 and "eng-code-review" in out["refused"] and "eng-unit-tests" in out["refused"]
    one = tmp_path / "src" / "one"
    shutil.copytree(FIX / "web-notes", one)
    (one / "SKILL.md").write_text((one / "SKILL.md").read_text() + "\nWhen asked for tests, use the `eng-unit-tests` skill.\n")
    assert call(capsys, "normalize", "--quarantine", fetched(capsys, one), "--name", "eng-web-notes", "--declare", "requires=none", "--declare", "side_effects=none")[0] == 0


def test_a_flow_prefix_is_refused(capsys):
    quarantine = fetched(capsys, FIX / "web-notes")
    code, out = call(capsys, "normalize", "--quarantine", quarantine, "--name", "flow-web-notes", "--declare", "requires=none", "--declare", "side_effects=none")
    assert code == 1 and "flow" in out["refused"]


def test_a_file_a_harness_reads_as_settings_stops_the_import_and_drop_leaves_it_out(capsys, tmp_path):
    settings = sorted(s for s in si.adapter_data()[1] if "." in s and "/" not in s)
    assert settings
    source = copy_source(tmp_path)
    (source / "references" / settings[0]).write_text("rules a harness would apply to every run\n")
    quarantine = fetched(capsys, source)
    argv = ["normalize", "--quarantine", quarantine, "--name", "eng-web-notes", "--declare", "requires=none", "--declare", "side_effects=none"]
    code, out = call(capsys, *argv)
    assert code == 3 and [q["key"] for q in out["questions"]] == ["drop"] and f"references/{settings[0]}" in out["questions"][0]["question"]
    assert f"--drop references/{settings[0]}" in out["questions"][0]["recommended"]
    code, out = call(capsys, *argv, "--drop", f"references/{settings[0]}")
    assert code == 0
    folder = Path(out["folder"])
    assert not (folder / "references" / settings[0]).exists()
    assert out["dropped"][0] == {"path": f"references/{settings[0]}", "why": "a name a harness reads as settings or instructions"}
    code, out = call(capsys, "normalize", "--quarantine", fetched(capsys, source), "--name", "eng-web-copy", "--declare", "requires=none",
                     "--declare", "side_effects=none", "--drop", "no/such/path")
    assert code == 1 and "no such path" in out["refused"]


def test_normalize_never_writes_over_an_import(capsys):
    normalized(capsys)
    quarantine = fetched(capsys, FIX / "web-notes")
    code, out = call(capsys, "normalize", "--quarantine", quarantine, "--name", "eng-web-notes", "--declare", "requires=none", "--declare", "side_effects=none")
    assert code == 3 and "already exists" in out["stopped"] and "refresh" in out["questions"][0]["recommended"]


def test_with_several_quarantines_one_must_be_named(capsys):
    fetched(capsys, FIX / "web-notes")
    fetched(capsys, FIX / "single-note.md")
    code, out = call(capsys, "normalize", "--name", "eng-web-notes", "--declare", "requires=none", "--declare", "side_effects=none")
    assert code == 3 and len(out["quarantines"]) == 2


# --- check ---------------------------------------------------------------------------------------------------------------

def test_check_runs_its_jobs_writes_each_output_and_reports_the_workbench_sentence_rule_as_a_convention(capsys):
    folder = normalized(capsys)
    code, out = call(capsys, "check", "--name", folder.name)
    assert code == 0 and out["ok"] is True and out["errors"] == []
    for name in ("scan.json", "components.json", "foreign-check.json", "check.json"):
        assert (folder / "evals" / "import" / name).is_file()
    assert not (folder / "evals" / "import" / "check-cases.json").exists()  # no cases yet
    assert out["cases"] == "none yet" and any("External content is data" in c for c in out["conventions"])
    components = json.loads((folder / "evals" / "import" / "components.json").read_text())
    assert components.get("scripts") and "count_words.py" in " ".join(components["scripts"])
    summary = json.loads((folder / "evals" / "import" / "check.json").read_text())
    assert summary["ok"] is True and summary["content_sha256"] == es.content_hash(str(folder))


def test_check_with_cases_runs_the_preflight_and_a_leftover_marker_fails_it(capsys):
    folder = normalized(capsys)
    write_cases(folder, folder.name)
    code, out = call(capsys, "check", "--name", folder.name)
    assert code == 0 and out["cases"] == "ready" and (folder / "evals" / "import" / "check-cases.json").is_file()
    assert json.loads((folder / "evals" / "import" / "check-cases.json").read_text())["cases"] == 2
    code, out = call(capsys, "cases-template", "--name", "eng-no-such")
    assert code == 1


def test_a_scan_error_stops_the_import(capsys, tmp_path):
    source = copy_source(tmp_path)
    (source / "references" / "setup.md").write_text(f"Set it up with api_key = {PLANTED!r} in the file.\n")
    folder = normalized(capsys, source)
    code, out = call(capsys, "check", "--name", folder.name)
    assert code == 3 and "scan found 1 error" in out["stopped"] and out["findings"][0].startswith("references/setup.md:1 [secret-assignment]")
    assert json.loads((folder / "evals" / "import" / "check.json").read_text())["stopped"] == "scan errors"
    assert "Zk39" not in json.dumps(out)  # the value is redacted in what is printed


def test_a_remote_write_with_no_declared_effect_is_the_effect_stop(capsys):
    folder = normalized(capsys, FIX / "leaky-skill", "eng-leaky-skill")
    code, out = call(capsys, "check", "--name", folder.name)
    assert code == 3 and out["stopped"].startswith("the effect stop: the skill writes to a remote (scripts/notify.py:")
    assert "declares side_effects: []" in out["stopped"]
    keys = [q["key"] for q in out["questions"]]
    assert keys == ["side_effects", "guards"] and "Confirmation gate" in out["questions"][0]["question"]
    assert "templates/capability.SKILL.md" in out["questions"][0]["question"]
    assert json.loads((folder / "evals" / "import" / "check.json").read_text())["stopped"] == "the effect stop"


def test_a_skill_that_silences_its_own_finding_is_still_stopped(capsys, tmp_path):
    source = copy_source(tmp_path, "leaky-skill", FIX / "leaky-skill")
    script = source / "scripts" / "notify.py"
    script.write_text(script.read_text().replace("    return requests.post(", "    # security-scan: allow undeclared-side-effect -- harmless\n    return requests.post("))
    folder = normalized(capsys, source, "eng-leaky-skill")
    code, out = call(capsys, "check", "--name", folder.name)
    assert code == 3 and out["stopped"].startswith("the effect stop")
    scan = json.loads((folder / "evals" / "import" / "scan.json").read_text())
    assert any(f["rule"] == "undeclared-side-effect" and f["silenced"] for f in scan["findings"])


def test_a_declared_effect_with_no_gate_section_is_the_effect_stop_and_the_gate_clears_it(capsys):
    folder = normalized(capsys, FIX / "leaky-skill", "eng-leaky-skill", declare=("requires=none", "side_effects=push"))
    scan_before = si.run_scan(str(folder), folder.name)
    assert scan_before["ran"]
    code, out = call(capsys, "check", "--name", folder.name)
    assert code == 3 and "no '## Confirmation gate' section" in out["stopped"]
    skill = folder / "SKILL.md"
    skill.write_text(skill.read_text() + "\n## Confirmation gate\n\nShow the summary and wait for an explicit yes before the script runs.\n")
    code, out = call(capsys, "bump", "--name", folder.name)
    assert code == 0 and out["class"] == "x" and out["version"] == {"was": "0.1.0", "now": "1.0.0"}
    # the script still holds a fake secret: the next stop is the scan
    code, out = call(capsys, "check", "--name", folder.name)
    assert code == 3 and "[secret-assignment]" in out["stopped"]


def test_check_refuses_a_folder_that_holds_a_link(capsys, tmp_path):
    folder = normalized(capsys)
    os.symlink(tmp_path, folder / "references" / "up")
    code, out = call(capsys, "check", "--name", folder.name)
    assert code == 1 and "links" in out["refused"]


def test_check_reports_a_leftover_marker_a_missing_origin_a_single_case_and_an_all_guard_set(capsys):
    folder = normalized(capsys)
    code, out = call(capsys, "cases-template", "--name", folder.name)
    assert code == 0
    code, out = call(capsys, "check", "--name", folder.name)
    assert code == 1 and any("<fill:" in e and "evals/evals.json" in e for e in out["errors"])
    write_cases(folder, folder.name)
    data = json.loads((folder / "evals" / "evals.json").read_text())
    path = folder / "evals" / "import" / "cases-origin.json"
    path.write_text(json.dumps({"1": "one real request"}))
    code, out = call(capsys, "check", "--name", folder.name)
    assert code == 1 and any("case 2 has no origin line" in e for e in out["errors"])
    write_cases(folder, folder.name)
    (folder / "evals" / "evals.json").write_text(json.dumps({**data, "evals": data["evals"][:1]}))
    code, out = call(capsys, "check", "--name", folder.name)
    assert code == 1 and any("holds 1 case(s)" in e for e in out["errors"])
    guards = [{**c, "assertions": [{"text": a if isinstance(a, str) else a["text"], "tags": ["guard"]} for a in c["assertions"]]} for c in data["evals"]]
    (folder / "evals" / "evals.json").write_text(json.dumps({**data, "evals": guards}))
    code, out = call(capsys, "check", "--name", folder.name)
    assert code == 1 and any("not a guard" in e for e in out["errors"])


def test_a_case_that_copies_workbench_files_is_refused(capsys):
    folder = normalized(capsys)
    write_cases(folder, folder.name)
    data = json.loads((folder / "evals" / "evals.json").read_text())
    data["evals"][0]["workbench_files"] = ["contracts/state.md"]
    (folder / "evals" / "evals.json").write_text(json.dumps(data))
    code, out = call(capsys, "check", "--name", folder.name)
    assert code == 1 and any("workbench_files" in e for e in out["errors"])


def test_a_language_assertion_is_a_warning(capsys):
    folder = normalized(capsys)
    write_cases(folder, folder.name)
    data = json.loads((folder / "evals" / "evals.json").read_text())
    data["evals"][0]["assertions"].append("The reply is in English")
    (folder / "evals" / "evals.json").write_text(json.dumps(data))
    code, out = call(capsys, "check", "--name", folder.name)
    assert code == 0 and any("language assertion" in w for w in out["warnings"])


# --- audit -----------------------------------------------------------------------------------------------------------------

def test_an_audit_is_recorded_with_the_verdict_the_record_hash_and_the_content_hash_and_a_change_voids_it(capsys, tmp_path):
    folder = normalized(capsys)
    record = vetting(tmp_path, folder.name, "install after changes")
    code, out = call(capsys, "audit", "--name", folder.name, "--record", str(record))
    assert code == 0 and out["verdict"] == "install after changes" and out["may_test"] is True and out["web_cases_need"] == "the verdict install"
    entry = json.loads((folder / "evals" / "import" / "audit.json").read_text())
    assert entry["content_sha256"] == es.content_hash(str(folder)) and entry["record_sha256"] == si.sha256_bytes(record.read_bytes())
    assert (folder / "evals" / "import" / entry["record"]).read_bytes() == record.read_bytes()
    assert si.audit_state(str(folder))["current"] is True
    (folder / "references" / "style.md").write_text("A new layout.\n")
    state = si.audit_state(str(folder))
    assert state["verdict"] == "install after changes" and state["current"] is False  # voided by the change of the content hash


@pytest.mark.parametrize("line, verdict", [("Verdict: do not install", "do not install"), ("**Verdict:** install", "install"),
                                           ("- Verdict: Install after changes: rename the script", "install after changes")])
def test_the_verdict_is_read_from_its_line(capsys, tmp_path, line, verdict):
    folder = normalized(capsys)
    record = tmp_path / "record.md"
    record.write_text(f"# Vetting of {folder.name}\n\n{line}\n")
    code, out = call(capsys, "audit", "--name", folder.name, "--record", str(record))
    assert code == 0 and out["verdict"] == verdict and out["may_test"] is (verdict != "do not install")


def test_a_record_with_no_single_verdict_stops(capsys, tmp_path):
    folder = normalized(capsys)
    record = tmp_path / "record.md"
    for text in ("# Vetting of eng-web-notes\n\nNo verdict here.\n",
                 "# Vetting of eng-web-notes\n\nVerdict: do not install | install after changes | install, and why in one line.\n",
                 "# Vetting of eng-web-notes\n\nVerdict: install\nVerdict: do not install\n"):
        record.write_text(text)
        code, out = call(capsys, "audit", "--name", folder.name, "--record", str(record))
        assert code == 3 and out["questions"][0]["key"] == "verdict"
    assert not (folder / "evals" / "import" / "audit.json").exists()


def test_a_record_that_does_not_name_the_skill_stops(capsys, tmp_path):
    folder = normalized(capsys)
    record = tmp_path / "record.md"
    record.write_text("# Vetting of a different thing\n\nVerdict: install\n")
    code, out = call(capsys, "audit", "--name", folder.name, "--record", str(record))
    assert code == 3 and out["questions"][0]["key"] == "record"
    record.write_text("# Vetting of web-notes\n\nVerdict: install\n")  # the origin's own name counts
    assert call(capsys, "audit", "--name", folder.name, "--record", str(record))[0] == 0


def test_a_record_inside_the_checkout_is_copied_and_the_original_is_to_be_deleted(capsys, tmp_path, monkeypatch):
    folder = normalized(capsys)
    record = vetting(tmp_path, folder.name)
    real = es.inside_checkout
    monkeypatch.setattr(es, "inside_checkout", lambda path, root=None: str(path).endswith("vetting.md") or real(path, root or si.ROOT))
    code, out = call(capsys, "audit", "--name", folder.name, "--record", str(record))
    assert code == 0 and "delete" in out["warnings"][0] and "never committed" in out["warnings"][0]


def test_a_second_audit_keeps_the_first_record(capsys, tmp_path):
    folder = normalized(capsys)
    call(capsys, "audit", "--name", folder.name, "--record", str(vetting(tmp_path, folder.name)))
    call(capsys, "audit", "--name", folder.name, "--record", str(vetting(tmp_path, folder.name, "do not install", "second.md")))
    records = sorted(p.name for p in (folder / "evals" / "import").glob("vetting-*.md"))
    assert len(records) == 2
    assert si.audit_state(str(folder))["verdict"] == "do not install"


# --- cases-template -------------------------------------------------------------------------------------------------------------

def test_the_template_has_two_cases_to_fill_and_an_origin_file_and_never_writes_a_prompt(capsys):
    folder = normalized(capsys)
    code, out = call(capsys, "cases-template", "--name", folder.name)
    assert code == 0 and out["to_fill"] == "<fill:"
    data = json.loads((folder / "evals" / "evals.json").read_text())
    assert data["skill_name"] == folder.name and [c["id"] for c in data["evals"]] == [1, 2]
    for case in data["evals"]:
        assert case["prompt"].startswith("<fill:") and case["expected_output"].startswith("<fill:")
        assert len(case["assertions"]) >= 3
        assert all((a if isinstance(a, str) else a["text"]).startswith("<fill:") for a in case["assertions"])
    origins = json.loads((folder / "evals" / "import" / "cases-origin.json").read_text())
    assert sorted(origins) == ["1", "2"] and all(v.startswith("<fill:") for v in origins.values())
    code, out = call(capsys, "cases-template", "--name", folder.name)
    assert code == 3 and "already exists" in out["stopped"]  # never over a file that is there


def test_the_template_asks_for_a_guard_per_declared_effect_and_a_guard_where_the_skill_has_a_gate(capsys):
    folder = normalized(capsys, FIX / "leaky-skill", "eng-leaky-skill", declare=("requires=none", "side_effects=push,publish"))
    skill = folder / "SKILL.md"
    skill.write_text(skill.read_text() + "\n## Confirmation gate\n\nAsk first.\n")
    call(capsys, "bump", "--name", folder.name)
    code, out = call(capsys, "cases-template", "--name", folder.name)
    assert code == 0
    data = json.loads((folder / "evals" / "evals.json").read_text())
    tags = {t for c in data["evals"] for a in c["assertions"] if isinstance(a, dict) for t in a["tags"]}
    assert tags == {"guard", "guard:push", "guard:publish"}
    assert data["evals"][1]["tags"] == ["guard", "guard:publish", "guard:push"] and "tags" not in data["evals"][0]
    assert not [a for a in data["evals"][0]["assertions"] if isinstance(a, dict)]  # at least one case with assertions that are not guards


# --- test --------------------------------------------------------------------------------------------------------------------------

def ready(capsys, tmp_path, verdict="install", name="eng-web-notes"):
    folder = normalized(capsys, name=name)
    write_cases(folder, folder.name)
    assert call(capsys, "check", "--name", folder.name)[0] == 0
    assert call(capsys, "audit", "--name", folder.name, "--record", str(vetting(tmp_path, folder.name, verdict)))[0] == 0
    return folder


def test_a_test_is_refused_with_no_audit(capsys):
    folder = normalized(capsys)
    write_cases(folder, folder.name)
    call(capsys, "check", "--name", folder.name)
    code, out = call(capsys, "test", "--name", folder.name, "--max-cost-usd", "0.5")
    assert code == 3 and out["questions"][0]["key"] == "audit" and "no audit record" in out["stopped"]


def test_a_test_is_refused_with_a_verdict_of_do_not_install_and_after_a_change_that_voids_the_audit(capsys, tmp_path):
    folder = ready(capsys, tmp_path, "do not install")
    code, out = call(capsys, "test", "--name", folder.name, "--max-cost-usd", "0.5")
    assert code == 3 and "do not install" in out["stopped"]
    folder = ready(capsys, tmp_path, "install", "eng-web-notes-two")
    (folder / "references" / "style.md").write_text("A new layout.\n")
    code, out = call(capsys, "test", "--name", folder.name, "--max-cost-usd", "0.5")
    assert code == 3 and "audit is void" in out["stopped"]


def test_a_test_needs_a_check_at_the_current_content_and_cases(capsys, tmp_path):
    folder = normalized(capsys)
    call(capsys, "audit", "--name", folder.name, "--record", str(vetting(tmp_path, folder.name)))
    code, out = call(capsys, "test", "--name", folder.name, "--max-cost-usd", "0.5")
    assert code == 3 and out["questions"][0]["key"] == "check"
    call(capsys, "check", "--name", folder.name)
    code, out = call(capsys, "test", "--name", folder.name, "--max-cost-usd", "0.5")
    assert code == 3 and out["questions"][0]["key"] == "cases"


@pytest.mark.parametrize("flag", [["--pass-env", "SOME_KEY"], ["--harness", "other"]])
def test_pass_env_and_harness_are_refused(capsys, tmp_path, flag):
    folder = ready(capsys, tmp_path)
    code, out = call(capsys, "test", "--name", folder.name, "--max-cost-usd", "0.5", *flag)
    assert code == 1 and flag[0] in out["refused"]


def test_a_web_case_needs_the_verdict_install_and_the_flag(capsys, tmp_path):
    folder = ready(capsys, tmp_path, "install after changes")
    data = json.loads((folder / "evals" / "evals.json").read_text())
    data["evals"][1]["allow_web"] = True
    (folder / "evals" / "evals.json").write_text(json.dumps(data))
    call(capsys, "check", "--name", folder.name)
    code, out = call(capsys, "test", "--name", folder.name, "--max-cost-usd", "0.5", "--allow-web-cases")
    assert code == 1 and "open network" in out["refused"] and out["verdict"] == "install after changes"
    call(capsys, "audit", "--name", folder.name, "--record", str(vetting(tmp_path, folder.name, "install", "again.md")))
    code, out = call(capsys, "test", "--name", folder.name, "--max-cost-usd", "0.5")
    assert code == 1 and "--allow-web-cases" in out["refused"]


def test_a_test_needs_a_spend_limit_and_prints_the_plan_and_the_bound_before_anything_runs(capsys, tmp_path, monkeypatch):
    folder = ready(capsys, tmp_path)
    monkeypatch.setattr(si, "run_streaming", lambda *a, **k: pytest.fail("the event started without a yes"))
    code, out = call(capsys, "test", "--name", folder.name, "--model", "claude-sonnet-5-5")
    assert code == 3 and out["questions"][0]["key"] == "max-cost-usd"
    code, out = call(capsys, "test", "--name", folder.name, "--model", "claude-sonnet-5-5", "--max-cost-usd", "0.5")
    assert code == 3 and "wait for your yes" in out["stopped"]
    plan = out["plan"]
    assert plan["runs"] == 2 and plan["models"] == ["claude-sonnet-5-5"] and plan["evidence_home"]["home"] == "local"
    assert plan["spend"]["bound_usd"] == 2.0 and plan["spend"]["grading_calls"] == 2 and plan["spend"]["max_cost_usd_per_run"] == 0.5
    assert "your key for the grader" in plan["spend"]["paid_by"] and "reach the model provider and the grader" in plan["reaches"]
    assert plan["result"].startswith("preliminary: your machine only")


def test_with_the_yes_one_quick_event_runs_for_all_the_models_with_the_spend_limit(capsys, tmp_path, monkeypatch):
    folder = ready(capsys, tmp_path)
    seen = []

    def run(argv, timeout):
        seen.append(argv)
        return types.SimpleNamespace(returncode=0, stdout=json.dumps({"complete": True, "evidence": {"written": True}}))
    monkeypatch.setattr(si, "run_streaming", run)
    code, out = call(capsys, "test", "--name", folder.name, "--model", "claude-sonnet-5-5", "--model", "openrouter/deepseek/deepseek-v4.1-flash",
                     "--max-cost-usd", "0.25", "--jobs", "2", "--yes")
    assert code == 0 and out["event"]["complete"] is True and len(seen) == 1
    argv = seen[0]
    assert argv[2:6] == ["--skill-dir", str(folder), "--quick", "--model"] and argv.count("--model") == 2
    assert argv[-4:] == ["--jobs", "2", "--max-cost-usd", "0.25"]
    assert "--pass-env" not in argv and "--harness" not in argv and "--allow-web-cases" not in argv


def test_a_failed_event_is_reported_and_exits_one(capsys, tmp_path, monkeypatch):
    folder = ready(capsys, tmp_path)
    monkeypatch.setattr(si, "run_streaming", lambda argv, timeout: types.SimpleNamespace(returncode=1, stdout="not json"))
    code, out = call(capsys, "test", "--name", folder.name, "--model", "claude-sonnet-5-5", "--max-cost-usd", "0.5", "--yes")
    assert code == 1 and out["exit"] == 1 and out["event"] == {"output": "not json"}


# --- status ---------------------------------------------------------------------------------------------------------------------------

def test_the_step_is_computed_from_the_folder_and_its_record(capsys, tmp_path):
    folder = normalized(capsys)
    code, out = call(capsys, "status")
    row = out["skills"][0]
    assert row["step"] == "normalized" and row["steps"]["checked"] is False and row["audit"] is None and row["assumed"] == ["inputs", "outputs", "updates"]
    assert row["origin"]["kind"] == "local" and row["scope"] == "your machine only, not checkable by others" and "python3 scripts/skill_import.py check" in row["next"]
    write_cases(folder, folder.name)
    call(capsys, "check", "--name", folder.name)
    assert call(capsys, "status", "--name", folder.name)[1]["skills"][0]["step"] == "checked"
    call(capsys, "audit", "--name", folder.name, "--record", str(vetting(tmp_path, folder.name)))
    row = call(capsys, "status", "--name", folder.name)[1]["skills"][0]
    assert row["step"] == "cases" and row["audit"]["verdict"] == "install" and row["audit"]["current"] is True and row["steps"]["tested"] is False
    assert "test --name" in row["next"]
    (folder / "references" / "style.md").write_text("changed by hand\n")
    row = call(capsys, "status", "--name", folder.name)[1]["skills"][0]
    assert row["step"] == "normalized" and row["audit"]["current"] is False and row["content_current"] is False
    code, out = call(capsys, "status", "--name", "eng-nothing")
    assert code == 1


def test_status_lists_a_quarantine_that_was_fetched_and_not_yet_normalized(capsys):
    quarantine = fetched(capsys, FIX / "web-notes")
    code, out = call(capsys, "status")
    assert out["skills"] == [] and out["fetched"][0]["quarantine"] == quarantine and out["fetched"][0]["origin"]["kind"] == "local"


# --- refresh and bump -------------------------------------------------------------------------------------------------------------------

def test_a_refresh_with_no_change_changes_nothing(capsys, tmp_path):
    source = copy_source(tmp_path)
    folder = normalized(capsys, source)
    before = es.content_hash(str(folder))
    code, out = call(capsys, "refresh", "--name", folder.name)
    assert code == 0 and out["changed"] is False and es.content_hash(str(folder)) == before
    assert not list((folder.parent / ".quarantine").iterdir())


def test_a_refresh_shows_the_difference_and_its_class_and_waits_for_the_answer(capsys, tmp_path):
    source = copy_source(tmp_path)
    folder = normalized(capsys, source)
    old_md = (folder / "SKILL.md").read_text()
    (source / "SKILL.md").write_text((source / "SKILL.md").read_text().replace("five bullets at most", "six bullets at most"))
    (source / "references" / "extra.md").write_text("More layout rules.\n")
    code, out = call(capsys, "refresh", "--name", folder.name)
    assert code == 3 and out["changed"] is True and out["class"] == "y" and out["version"] == {"now": "0.1.0", "after": "0.2.0"}
    assert out["added"] == ["references/extra.md"] and "six bullets" in out["skill_md_diff"] and "void" in out["audit"]
    assert (folder / "SKILL.md").read_text() == old_md and not (folder / "references" / "extra.md").exists()  # nothing written before the answer
    expected = es.change_class(json.loads((folder / "evals" / "import" / "snapshot.json").read_text())["skill_md"],
                               old_md.replace("five bullets at most", "six bullets at most"), ["references/extra.md"])
    assert out["class"] == expected[0]


def test_an_applied_refresh_raises_the_version_by_the_class_appends_one_line_voids_the_audit_and_keeps_the_cases(capsys, tmp_path):
    source = copy_source(tmp_path)
    folder = normalized(capsys, source)
    write_cases(folder, folder.name)
    call(capsys, "audit", "--name", folder.name, "--record", str(vetting(tmp_path, folder.name)))
    assert si.audit_state(str(folder))["current"] is True
    (source / "SKILL.md").write_text((source / "SKILL.md").read_text().replace("five bullets at most", "six bullets at most"))
    code, out = call(capsys, "refresh", "--name", folder.name, "--apply")
    assert code == 0 and out["applied"] is True and out["version_line"]["class"] == "y" and out["version_line"]["version"] == "0.2.0"
    lines = [json.loads(l) for l in (folder / "evals" / "versions.jsonl").read_text().splitlines()]
    assert [l["version"] for l in lines] == ["0.1.0", "0.2.0"] and lines[1]["content_sha256"] == es.content_hash(str(folder))
    assert es.skill_version(str(folder)) == "0.2.0" and "six bullets" in (folder / "SKILL.md").read_text()
    assert si.audit_state(str(folder))["current"] is False  # the content hash changed: the audit is void
    assert (folder / "evals" / "evals.json").is_file() and (folder / "evals" / "files" / "article" / "saved-page.md").is_file()
    record = json.loads((folder / "evals" / "import" / "record.json").read_text())
    assert len(record["history"]) == 1 and record["refreshed_on"]
    assert not list((folder.parent / ".quarantine").iterdir())


def test_a_declaration_changed_at_refresh_is_an_x_change(capsys, tmp_path):
    source = copy_source(tmp_path)
    folder = normalized(capsys, source)
    code, out = call(capsys, "refresh", "--name", folder.name, "--declare", "side_effects=publish")
    assert code == 3 and out["class"] == "x" and out["version"]["after"] == "1.0.0"


def test_bump_records_an_edit_made_by_hand_with_the_class_of_the_change(capsys):
    folder = normalized(capsys)
    code, out = call(capsys, "bump", "--name", folder.name)
    assert code == 0 and out["changed"] is False and out["recorded"] is True
    (folder / "references" / "style.md").write_text("A new layout.\n")
    code, out = call(capsys, "bump", "--name", folder.name)
    assert code == 0 and out["class"] == "y" and out["version"] == {"was": "0.1.0", "now": "0.2.0"} and out["changed_files"] == ["references/style.md"]
    lines = (folder / "evals" / "versions.jsonl").read_text().splitlines()
    assert len(lines) == 2 and json.loads(lines[1])["content_sha256"] == es.content_hash(str(folder))
    assert call(capsys, "bump", "--name", folder.name)[1]["changed"] is False
    (folder / "references" / "style.md").write_text("Another layout.\n")
    code, out = call(capsys, "bump", "--name", folder.name, "--class", "x")
    assert code == 0 and out["class"] == "x" and out["version"]["now"] == "1.0.0"
    (folder / "references" / "style.md").write_text("Yet another.\n")
    code, out = call(capsys, "bump", "--name", folder.name, "--class", "z")
    assert code == 1 and "lower than the class" in out["refused"]


def test_the_help_of_every_verb_is_written(capsys):
    for verb in si.VERBS.keys() | {"test"}:
        with pytest.raises(SystemExit) as e:
            si.main([verb, "--help"])
        assert e.value.code == 0
        assert capsys.readouterr().out
    with pytest.raises(SystemExit) as e:
        si.main(["--help"])
    assert e.value.code == 0 and "never installs" in capsys.readouterr().out


def test_the_script_runs_as_a_program_and_prints_json(tmp_path):
    env = {**os.environ, "WB_IMPORT_HOME": str(tmp_path / "home"), "WB_LOCAL_EVIDENCE_DIR": str(tmp_path / "evidence")}
    done = subprocess.run([sys.executable, str(REPO / "scripts" / "skill_import.py"), "status"], capture_output=True, text=True, env=env)
    assert done.returncode == 0 and json.loads(done.stdout) == {"home": str(tmp_path / "home"), "skills": [], "fetched": []}


def test_the_tool_names_no_harness_and_reads_their_data_from_the_adapters():
    text = (REPO / "scripts" / "skill_import.py").read_text()
    names = {s for s in si.adapter_data()[1]} | {d.split("/")[0] for d in si.adapter_data()[0]}
    assert names  # the data is read from adapters/*/eval.json
    for name in sorted(names, key=len, reverse=True):
        if name.startswith("."):
            assert name not in text.replace("evals/import", ""), name
    # standard library only
    imports = {l.split()[1].split(".")[0] for l in text.splitlines() if l.startswith(("import ", "from "))}
    stdlib = getattr(sys, "stdlib_module_names", None)
    assert imports <= (set(stdlib) | {"__future__"} if stdlib else {"argparse", "datetime", "difflib", "hashlib", "importlib", "json", "os", "re",
                                                                   "shutil", "stat", "subprocess", "sys", "tempfile", "concurrent", "urllib"})
