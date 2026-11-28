"""Tests of scripts/rename_move.py, the one-time move of the old data and cache folders (T47).

Run: uv run --with pytest==9.1.1 pytest scripts/tests/test_rename_move.py

Offline and safe: every folder is under tmp_path (HOME, XDG_* and SCHEDULER_* point there), the scheduler's agent and unit
folders are temporary, and a PATH of failing launchctl and systemctl stubs proves the script never runs either. Nothing
here touches a real data folder, keychain or scheduled job.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "rename_move.py"
OLD, NEW = "ai-workbench", "openhora"


def load_module():
    spec = importlib.util.spec_from_file_location("rename_move_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class World:
    """A machine under tmp_path: the folders the script reads, and a way to run it with them."""

    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        self.data_base = tmp_path / "data"
        self.cache_base = tmp_path / "cache"
        self.agents = tmp_path / "agents"
        self.units = tmp_path / "units"
        self.stubs = tmp_path / "stubs"
        self.stub_calls = tmp_path / "stub-calls.txt"
        for folder in (self.home, self.data_base, self.cache_base, self.agents, self.units, self.stubs):
            folder.mkdir()
        for name in ("launchctl", "systemctl"):
            stub = self.stubs / name
            stub.write_text(f'#!/bin/sh\necho "{name} $@" >> "{self.stub_calls}"\nexit 1\n')
            stub.chmod(0o755)
        self.env = {
            "PATH": f"{self.stubs}{os.pathsep}{os.environ['PATH']}", "HOME": str(self.home),
            "XDG_DATA_HOME": str(self.data_base), "XDG_CACHE_HOME": str(self.cache_base),
            "SCHEDULER_AGENTS_DIR": str(self.agents), "SCHEDULER_UNITS_DIR": str(self.units),
        }

    @property
    def old_data(self) -> Path:
        return self.data_base / OLD

    @property
    def new_data(self) -> Path:
        return self.data_base / NEW

    @property
    def old_cache(self) -> Path:
        return self.cache_base / OLD

    @property
    def new_cache(self) -> Path:
        return self.cache_base / NEW

    def run(self, *argv):
        done = subprocess.run([sys.executable, str(SCRIPT), "--platform", "other", *argv], capture_output=True, text=True,
                              timeout=60, env=self.env)
        try:
            out = json.loads(done.stdout)
        except ValueError:
            out = None
        return done.returncode, out, done.stderr

    def put(self, path: Path, text: str = "x") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def tree(self, root: Path) -> dict:
        if not root.exists():
            return {}
        return {str(p.relative_to(root)): (p.read_text() if p.is_file() else None) for p in sorted(root.rglob("*"))}

    def snapshot(self) -> dict:
        return {"data": self.tree(self.data_base), "cache": self.tree(self.cache_base)}


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def ledger(entries: dict) -> str:
    """A Notion ledger file as the providers write it: {"version", "entries": {key: {"status", ...}}}."""
    return json.dumps({"version": 1, "entries": {k: {"status": v, "started_at": "2026-01-01T00:00:00Z"} for k, v in entries.items()}})


def runtime_project(world: World, name: str = "p1", folder: str = "p1", key: str = "data_dir") -> Path:
    """An old project data folder, and a project folder whose runtime.json names it by its NEW path (already updated, as the fix of
    B7 says: a project that still names the old path is blocked by B7 until it is)."""
    world.put(world.old_data / "runtime" / folder / "store.db", "db")
    project = world.tmp / f"project-{name}"
    world.put(project / "docs" / "workbench" / "runtime.json", json.dumps({key: str(world.new_data / "runtime" / folder)}))
    return project


def plant(world: World) -> None:
    world.put(world.old_data / "scheduler" / "job-1" / "job.json", json.dumps({"status": "done"}))
    world.put(world.old_data / "scheduler" / "job-1" / "files" / "post.txt", "hello")
    world.put(world.old_data / "vcs-github.json", "{}")
    world.put(world.old_data / "documents-notion.json", ledger({"a": "done"}))
    world.put(world.old_cache / "thumbs" / "a.bin", "cache")


def test_it_lists_and_changes_nothing_without_yes(world):
    plant(world)
    before = world.snapshot()
    code, out, said = world.run()
    assert code == 0 and out["mode"] == "list" and "done" not in out and out["blockers"] == []
    assert world.snapshot() == before
    kinds = {f["kind"]: f for f in out["folders"]}
    assert kinds["data"]["from"] == str(world.old_data) and kinds["data"]["to"] == str(world.new_data) and kinds["data"]["exists"]
    assert kinds["cache"]["from"] == str(world.old_cache) and kinds["cache"]["to"] == str(world.new_cache)
    assert {m["from"] for m in out["move"]} >= {str(world.old_data / "scheduler"), str(world.old_data / "vcs-github.json"),
                                                  str(world.old_cache / "thumbs")}
    assert out["delete"] == [{"path": str(world.old_data / "documents-notion.json"),
                              "why": "the old Notion test ledger holds no pending key (decision 13)"}]
    assert out["ledgers"] == [{"path": str(world.old_data / "documents-notion.json"), "done": 1, "pending": 0, "other": 0, "action": "delete"}]
    assert len(out["next"]) == 3 and "accept again" in out["next"][0] and "schedule each job" in out["next"][1]
    assert "run this command again" in out["next"][2]
    assert "run again with --yes" in said


def test_yes_moves_data_and_cache_and_removes_the_empty_old_folders(world):
    plant(world)
    code, out, _ = world.run("--yes")
    assert code == 0 and out["mode"] == "moved"
    assert not world.old_data.exists() and not world.old_cache.exists()
    assert (world.new_data / "scheduler" / "job-1" / "files" / "post.txt").read_text() == "hello"
    assert (world.new_data / "vcs-github.json").read_text() == "{}"
    assert (world.new_cache / "thumbs" / "a.bin").read_text() == "cache"
    assert not (world.new_data / "documents-notion.json").exists()
    steps = {d["step"] for d in out["done"]}
    assert steps == {"move", "delete", "rmdir"}
    again_code, again, _ = world.run("--yes")
    assert again_code == 0 and again["move"] == [] and again["delete"] == []


def test_it_merges_an_existing_empty_new_runtime_folder(world):
    project = runtime_project(world)
    (world.new_data / "runtime").mkdir(parents=True)
    code, out, _ = world.run("--project", str(project), "--yes")
    assert code == 0, out
    assert (world.new_data / "runtime" / "p1" / "store.db").read_text() == "db"
    assert not world.old_data.exists()


def test_a_notion_ledger_with_no_pending_key_is_deleted_with_its_locks_and_nothing_else(world):
    for name in ("documents-notion.json.lock", "documents-notion.json.abc.lock", "issue-tracker-notion.json.lock"):
        world.put(world.old_data / name)
    world.put(world.old_data / "documents-notion.json", ledger({"a": "done", "b": "done"}))
    world.put(world.old_data / "issue-tracker-notion.json", json.dumps({"version": 1, "entries": {}}))
    world.put(world.old_data / "documents-notion-notes.txt", "keep")
    world.put(world.old_data / "other.json", "keep")
    code, out, _ = world.run("--yes")
    assert code == 0 and len(out["delete"]) == 5
    assert sorted(p.name for p in world.new_data.iterdir()) == ["documents-notion-notes.txt", "other.json"]


def test_a_notion_ledger_with_a_pending_key_is_moved_not_deleted_and_the_plan_says_so_without_its_content(world):
    world.put(world.old_data / "documents-notion.json", ledger({"page-1": "pending", "page-2": "done", "page-3": "failed"}))
    world.put(world.old_data / "documents-notion.json.lock", "")
    code, out, said = world.run()
    assert code == 0 and out["delete"] == []
    (row,) = out["ledgers"]
    assert row == {"path": str(world.old_data / "documents-notion.json"), "done": 1, "pending": 1, "other": 1, "action": "move"}
    assert any("pending" in note and "documents-notion.json" in note for note in out["notes"])
    assert "page-1" not in json.dumps(out) and "page-1" not in said
    code, out, _ = world.run("--yes")
    assert code == 0
    assert json.loads((world.new_data / "documents-notion.json").read_text())["entries"]["page-1"]["status"] == "pending"
    assert (world.new_data / "documents-notion.json.lock").exists(), "the lock of a moved ledger moves with it"


@pytest.mark.parametrize("text", ["{not json", "[]", json.dumps({"entries": []}), json.dumps({"version": 1})])
def test_an_unreadable_or_unshaped_notion_ledger_is_moved(world, text):
    world.put(world.old_data / "issue-tracker-notion.json", text)
    code, out, _ = world.run()
    assert code == 0 and out["delete"] == []
    assert out["ledgers"] == [{"path": str(world.old_data / "issue-tracker-notion.json"), "unreadable": True, "action": "move"}]
    assert world.run("--yes")[0] == 0 and (world.new_data / "issue-tracker-notion.json").read_text() == text


def test_a_cache_ledger_with_no_data_copy_goes_to_the_new_data_folder(world):
    world.put(world.old_cache / "vcs-github.json", "cache copy")
    world.put(world.old_cache / "vcs-github.json.lock", "")
    world.put(world.old_cache / "publisher-linkedin.json", "post copy")
    code, out, _ = world.run("--yes")
    assert code == 0
    assert (world.new_data / "vcs-github.json").read_text() == "cache copy"
    assert (world.new_data / "vcs-github.json.lock").exists()
    assert (world.new_data / "publisher-linkedin.json").read_text() == "post copy"
    assert not world.new_cache.exists() or not list(world.new_cache.iterdir())


def test_a_cache_ledger_with_a_data_copy_goes_to_the_new_cache_folder(world):
    world.put(world.old_data / "vcs-github.json", "data copy")
    world.put(world.old_cache / "vcs-github.json", "stale cache copy")
    world.put(world.new_data / "publisher-linkedin.json", "already moved")
    world.put(world.old_cache / "publisher-linkedin.json", "stale post copy")
    code, out, _ = world.run("--yes")
    assert code == 0
    assert (world.new_data / "vcs-github.json").read_text() == "data copy"
    assert (world.new_cache / "vcs-github.json").read_text() == "stale cache copy"
    assert (world.new_data / "publisher-linkedin.json").read_text() == "already moved"
    assert (world.new_cache / "publisher-linkedin.json").read_text() == "stale post copy"


def blocked(world: World, *argv):
    before = world.snapshot()
    code, out, said = world.run(*argv)
    assert code == 1 and out is not None and out["blockers"], said
    assert world.snapshot() == before and "done" not in out
    code_yes, out_yes, _ = world.run(*argv, "--yes")
    assert code_yes == 1 and world.snapshot() == before and not out_yes.get("done")
    return out["blockers"]


def test_b1_a_job_still_scheduled_under_the_old_name_blocks(world):
    plant(world)
    plist = world.put(world.agents / "dev.ai-workbench.scheduler.post-1.plist")
    (blocker,) = blocked(world)
    assert blocker["path"] == str(plist) and blocker["why"] == "a job is still scheduled under the old name"
    assert "launchd.py cancel --id post-1" in blocker["fix"] and "launchctl bootout gui/<uid>/dev.ai-workbench.scheduler.post-1" in blocker["fix"]


def test_b1_a_systemd_unit_under_the_old_name_blocks_with_its_own_fix(world):
    plant(world)
    world.put(world.units / "dev.ai-workbench.scheduler.tick.timer")
    (blocker,) = blocked(world)
    assert "systemctl --user disable --now dev.ai-workbench.scheduler.tick.timer" in blocker["fix"]
    assert "daemon-reload" in blocker["fix"]


def test_b1_a_new_name_does_not_block(world):
    plant(world)
    world.put(world.agents / "dev.openhora.scheduler.post-1.plist")
    assert world.run()[0] == 0


@pytest.mark.parametrize("status", ["scheduled", "running"])
def test_b2_an_unfinished_job_record_in_the_old_home_blocks(world, status):
    world.put(world.old_data / "scheduler" / "job-9" / "job.json", json.dumps({"status": status}))
    (blocker,) = blocked(world)
    assert blocker["why"] == "a job record in the old home is not finished"
    assert blocker["path"].endswith("job-9/job.json") and "scheduler of a checkout before this change" in blocker["fix"]


def test_b2_a_finished_job_record_does_not_block(world):
    world.put(world.old_data / "scheduler" / "job-9" / "job.json", json.dumps({"status": "failed"}))
    assert world.run()[0] == 0


LOCK_WORKER = (
    "import fcntl, sys\n"
    "fd = open(sys.argv[1], 'a')\n"
    "fcntl.flock(fd, fcntl.LOCK_EX)\n"
    "print('ready', flush=True)\n"
    "sys.stdin.readline()\n"
)


def hold_lock(path: Path):
    child = subprocess.Popen([sys.executable, "-c", LOCK_WORKER, str(path)], stdout=subprocess.PIPE, stdin=subprocess.PIPE,
                             text=True)
    assert child.stdout.readline().strip() == "ready"
    return child


def release(child) -> None:
    child.stdin.write("\n")
    child.stdin.flush()
    child.wait(timeout=30)


@pytest.mark.parametrize("where", ["data-top", "cache-top", "job-run-lock"])
def test_b3_a_lock_held_by_a_process_blocks(world, where):
    plant(world)
    path = {"data-top": world.old_data / "vcs-github.json.lock", "cache-top": world.old_cache / "publisher-linkedin.json.lock",
            "job-run-lock": world.old_data / "scheduler" / "job-1" / "run.lock"}[where]
    world.put(path, "")
    child = hold_lock(path)
    try:
        (blocker,) = blocked(world)
        assert blocker["path"] == str(path) and blocker["why"] == "a process holds this lock"
        assert "stop the service" in blocker["fix"]
    finally:
        release(child)
    assert world.run()[0] == 0   # the same lock, released: nothing blocks, and the script created no lock of its own


def test_b3_the_script_never_creates_a_lock_file(world):
    plant(world)
    world.run()
    assert not list(world.tmp.rglob("run.lock"))


def test_b4_a_file_in_both_folders_blocks(world):
    world.put(world.old_data / "scheduler" / "job-1" / "job.json", json.dumps({"status": "done"}))
    world.put(world.new_data / "scheduler" / "job-1" / "job.json", json.dumps({"status": "done"}))
    world.put(world.old_data / "same.txt", "old")
    world.put(world.new_data / "same.txt", "new")
    blockers = blocked(world)
    assert {b["path"] for b in blockers} == {str(world.new_data / "same.txt"),
                                             str(world.new_data / "scheduler" / "job-1" / "job.json")}
    assert all(b["why"] == "both folders hold this file" for b in blockers)


def test_b5_folders_on_different_devices_block(world, monkeypatch, capsys):
    plant(world)
    module = load_module()
    for key, value in world.env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(module, "device_of", lambda path: 2 if str(path).endswith(NEW) else 1)
    assert module.main(["--platform", "other", "--yes"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert {b["why"] for b in out["blockers"]} == {"a rename cannot cross devices"}
    assert world.old_data.exists() and not world.new_data.exists()


def test_b6_project_data_folders_with_no_project_given_block(world):
    world.put(world.old_data / "runtime" / "p1" / "store.db", "db")
    (blocker,) = blocked(world)
    assert blocker["path"] == str(world.old_data / "runtime" / "p1")
    assert blocker["why"] == "the old folder holds a project data folder that no --project names"
    assert "--project <dir>" in blocker["fix"]


def test_b6_an_empty_runtime_folder_does_not_block(world):
    (world.old_data / "runtime").mkdir(parents=True)
    assert world.run()[0] == 0


def test_b6_a_project_with_no_readable_runtime_json_blocks_and_does_not_count(world):
    world.put(world.old_data / "runtime" / "p1" / "store.db", "db")
    for case, make in (("missing folder", lambda: world.tmp / "nowhere"),
                       ("no runtime.json", lambda: (world.tmp / "empty").mkdir() or world.tmp / "empty"),
                       ("broken runtime.json", lambda: world.put(world.tmp / "broken" / "docs" / "workbench" / "runtime.json", "{no").parents[2])):
        project = make()
        blockers = blocked(world, "--project", str(project))
        whys = {b["why"] for b in blockers}
        assert "this project has no readable docs/workbench/runtime.json" in whys or "this project's runtime.json cannot be read" in whys, case
        assert "the old folder holds a project data folder that no --project names" in whys, case


def test_b6_every_project_folder_under_the_old_runtime_must_be_named_by_a_project(world):
    named = runtime_project(world, "a", "p1")
    world.put(world.old_data / "runtime" / "p2" / "store.db", "db")
    (blocker,) = blocked(world, "--project", str(named))
    assert blocker["path"] == str(world.old_data / "runtime" / "p2") and "no --project names" in blocker["why"]
    second = runtime_project(world, "b", "p2")
    assert world.run("--project", str(named), "--project", str(second))[0] == 0


def test_b6_a_project_naming_the_whole_old_runtime_folder_names_every_folder_in_it(world):
    world.put(world.old_data / "runtime" / "p1" / "store.db", "db")
    world.put(world.old_data / "runtime" / "p2" / "store.db", "db")
    project = world.tmp / "project"
    world.put(project / "docs" / "workbench" / "runtime.json", json.dumps({"root": str(world.old_data / "runtime")}))
    assert blocked(world, "--project", str(project))[0]["why"].endswith("points into the old folder")
    assert all("no --project names" not in b["why"] for b in world.run("--project", str(project))[1]["blockers"])


def test_b7_a_project_pointing_into_the_old_folder_blocks_and_names_the_new_path(world):
    project = runtime_project(world)
    inside = str(world.old_data / "runtime" / "p1")
    world.put(project / "docs" / "workbench" / "runtime.json",
              json.dumps({"data_dir": inside, "store_db": f"{inside}/store.db", "note": "Acme Example", "port": 8000,
                          "elsewhere": str(world.tmp / "other")}))
    blockers = blocked(world, "--project", str(project))
    assert {b["path"] for b in blockers} == {inside, f"{inside}/store.db"}
    by_key = {b["why"].split(" ")[0]: b for b in blockers}
    assert set(by_key) == {"data_dir", "store_db"}
    assert str(world.new_data / "runtime" / "p1") in by_key["data_dir"]["fix"]
    assert str(world.new_data / "runtime" / "p1" / "store.db") in by_key["store_db"]["fix"]
    assert "accept the configuration again" in by_key["data_dir"]["fix"]


def test_b7_a_project_pointing_elsewhere_does_not_block(world):
    project = runtime_project(world)
    world.put(project / "docs" / "workbench" / "runtime.json", json.dumps({"data_dir": str(world.tmp / "elsewhere")}))
    blockers = world.run("--project", str(project))[1]["blockers"]
    assert not any(b["why"].endswith("points into the old folder") for b in blockers)


def test_b7_nested_values_relative_paths_tilde_and_home_are_read(world):
    world.put(world.old_data / "runtime" / "p1" / "store.db", "db")
    project = world.tmp / "project"
    old = world.old_data
    rel = os.path.relpath(old / "runtime" / "p1", project)
    world.put(project / "docs" / "workbench" / "runtime.json", json.dumps({
        "store": {"db": str(old / "runtime" / "p1" / "store.db"), "list": ["/elsewhere", {"deep": str(old / "x")}]},
        "relative": rel, "tilde": "~/../data/ai-workbench/runtime/p1", "dollar": "$HOME/../data/ai-workbench/runtime/p1"}))
    blockers = world.run("--project", str(project))[1]["blockers"]
    keys = {b["why"].split(" ")[0] for b in blockers if b["why"].endswith("points into the old folder")}
    assert keys == {"store.db", "store.list[1].deep", "relative", "tilde", "dollar"}, keys


def test_an_error_in_the_middle_prints_what_was_done_and_a_rerun_finishes(world, monkeypatch, capsys):
    for name in ("a.txt", "b.txt", "c.txt"):
        world.put(world.old_data / name, name)
    module = load_module()
    for key, value in world.env.items():
        monkeypatch.setenv(key, value)
    real = os.rename
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError(28, "No space left on device")
        return real(src, dst)

    monkeypatch.setattr(module.os, "rename", flaky)
    assert module.main(["--platform", "other", "--yes"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["error"] == "[Errno 28] No space left on device" and len(out["done"]) == 1
    assert (world.new_data / "a.txt").exists() and (world.old_data / "b.txt").exists()
    monkeypatch.setattr(module.os, "rename", real)
    assert module.main(["--platform", "other", "--yes"]) == 0
    capsys.readouterr()
    assert sorted(p.name for p in world.new_data.iterdir()) == ["a.txt", "b.txt", "c.txt"] and not world.old_data.exists()


def test_it_never_runs_launchctl_or_systemctl(world):
    plant(world)
    world.put(world.agents / "dev.openhora.scheduler.x.plist")
    world.run()
    world.run("--yes")
    assert not world.stub_calls.exists()


def test_it_writes_nothing_outside_the_six_folders(world):
    plant(world)
    world.run("--yes")
    assert list(world.agents.iterdir()) == [] and list(world.units.iterdir()) == []
    assert list(world.home.iterdir()) == []


def test_the_darwin_data_folder_is_under_library_application_support(world):
    root = world.home / "Library" / "Application Support"
    world.put(root / OLD / "x.txt", "x")
    done = subprocess.run([sys.executable, str(SCRIPT), "--platform", "darwin", "--yes"], capture_output=True, text=True,
                          timeout=60, env=world.env)
    assert done.returncode == 0, done.stderr
    assert (root / NEW / "x.txt").read_text() == "x" and not (root / OLD).exists()


def test_help_names_the_flags_and_exit_codes():
    done = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0
    for word in ("--project", "--yes", "--platform", "Exit 0", "never runs launchctl"):
        assert word in done.stdout
    assert subprocess.run([sys.executable, str(SCRIPT), "--platform", "plan9"], capture_output=True, timeout=60).returncode == 2


def test_a_cache_ledger_never_overwrites_a_file_already_in_the_new_data_folder(world):
    world.put(world.old_cache / "vcs-github.json", "cache copy")
    world.put(world.old_cache / "vcs-github.json.lock", "")
    world.put(world.new_data / "vcs-github.json.lock", "already here")
    (blocker,) = blocked(world)
    assert blocker["path"] == str(world.new_data / "vcs-github.json.lock") and blocker["why"] == "both folders hold this file"
    assert (world.new_data / "vcs-github.json.lock").read_text() == "already here"


@pytest.mark.parametrize("which", ["data", "cache"])
def test_an_old_folder_that_is_a_symbolic_link_is_a_blocker_with_its_own_sentence(world, which):
    target = world.tmp / "elsewhere"
    target.mkdir()
    link = world.old_data if which == "data" else world.old_cache
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)
    (blocker,) = blocked(world)
    assert blocker["path"] == str(link) and blocker["why"] == "the old folder is a symbolic link"
    assert "real folder" in blocker["fix"]


def test_a_lock_taken_between_the_plan_and_the_renames_stops_the_move(world, monkeypatch, capsys):
    plant(world)
    lock = world.put(world.old_data / "vcs-github.json.lock", "")
    module = load_module()
    for key, value in world.env.items():
        monkeypatch.setenv(key, value)
    held = {"now": False}
    monkeypatch.setattr(module, "lock_held", lambda path: held["now"] and Path(path) == lock)
    real_build = module.Plan.build

    def build_then_take_the_lock(self):
        plan = real_build(self)
        held["now"] = True       # the plan saw no lock; one is held when the renames are about to start
        return plan

    monkeypatch.setattr(module.Plan, "build", build_then_take_the_lock)
    assert module.main(["--platform", "other", "--yes"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] != "moved" and not out.get("done")
    assert [b["why"] for b in out["blockers"]] == ["a process holds this lock"]
    assert world.old_data.exists() and not world.new_data.exists()


def test_mode_is_moved_only_when_there_is_no_error(world, monkeypatch, capsys):
    for name in ("a.txt", "b.txt"):
        world.put(world.old_data / name, name)
    module = load_module()
    for key, value in world.env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(module.os, "rename", lambda src, dst: (_ for _ in ()).throw(OSError(18, "Invalid cross-device link")))
    assert module.main(["--platform", "other", "--yes"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "error" and "error" in out and out["done"] == []


def test_an_unreadable_folder_in_the_plan_is_a_blocker_not_a_traceback(world):
    world.put(world.old_data / "sub" / "a.txt", "a")
    (world.new_data / "sub").mkdir(parents=True)      # present in both, so the plan has to read it
    (world.old_data / "sub").chmod(0)
    try:
        code, out, said = world.run()
    finally:
        (world.old_data / "sub").chmod(0o700)
    assert code == 1 and out is not None and "Traceback" not in said
    assert any(b["why"] == "this folder cannot be read" and b["path"].endswith("sub") for b in out["blockers"])
