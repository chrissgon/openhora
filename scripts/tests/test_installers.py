"""Tests for installer and build hygiene: packs are validated, installers delete only what they made,
the shared references land beside the skills, and a pack change leaves nothing of the earlier pack.

Run: uv run --with pytest pytest scripts/tests

Every run targets a temporary folder (--project, HOME and the skills directory variable point there).
The tests that change packs, rename a skill or build the plugin run the real installers inside a small
copy of the workbench (`workbench`), with invented skills, so that no test writes into this checkout's
build folder or depends on the real skill list.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = ROOT / "adapters/agents-dir/install.sh"
BUILD = ROOT / "adapters/claude-code/build.py"
BASH = shutil.which("bash")
# The shell macOS ships is bash 3.2, where an empty array under `set -u` is an error; where it exists
# beside another bash, both are exercised.
SHELLS = sorted({s for s in (BASH, "/bin/bash") if s and os.path.exists(s)})
MARK = ".installed-by-openhora"
LEGACY_MARK = ".installed-by-ai-workbench"  # T23: what the installer wrote before the rename
LINK = "openhora"
LEGACY_LINK = "ai-workbench"  # T23: the plugin link of the installer before the rename
SECURITY = "shared/references/security.md"


def default_pack() -> list[str]:
    r = subprocess.run([sys.executable, str(ROOT / "scripts/select_skills.py"), "--pack", "default", "--lines"],
                       capture_output=True, text=True, check=True)
    return r.stdout.split()


def install(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "HOME": str(tmp_path / "home")}
    return subprocess.run([BASH, str(AGENTS_DIR), "--project", str(tmp_path / "proj"), *args], env=env,
                          capture_output=True, text=True, timeout=120)


def skill(root: Path, name: str, area: str) -> None:
    folder = root / "skills" / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: An invented skill of the installer tests.\nmetadata:\n  area: {area}\n"
        "  kind: capability\n---\n\n# Demo\n\nRead `../../shared/references/security.md`.\n", encoding="utf-8")


@pytest.fixture
def workbench(tmp_path):
    """A small workbench: the real installers, scaffold and selection scripts, three invented skills."""
    wb = tmp_path / "wb"
    for rel in ("adapters/agents-dir/install.sh", "adapters/claude-code/install.sh", "adapters/claude-code/build.py",
                "adapters/claude-code/listing_budget.py", "adapters/claude-code/plugin.json",
                "scripts/select_skills.py", "scripts/validate.py",
                "scripts/new-skill.sh", SECURITY):
        (wb / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, wb / rel)
    shutil.copytree(ROOT / "templates", wb / "templates")
    shutil.copytree(ROOT / "adapters/claude-code/overrides", wb / "adapters/claude-code/overrides")
    (wb / "agents").mkdir()
    (wb / "agents" / "helper.md").write_text("---\nname: helper\ndescription: An invented agent.\n---\n\n# Helper\n",
                                             encoding="utf-8")
    for name, area in (("eng-alpha", "engineering"), ("eng-beta", "engineering"), ("mkt-gamma", "marketing")):
        skill(wb, name, area)
    (wb / "packs").mkdir()
    (wb / "packs" / "default.txt").write_text("*\n", encoding="utf-8")
    (wb / "packs" / "engonly.txt").write_text("eng-*\n", encoding="utf-8")
    (wb / "packs" / "empty.txt").write_text("asst-*\n", encoding="utf-8")
    return wb


def run(script: Path, *args: str, home: Path, shell: str = BASH, **env: str) -> subprocess.CompletedProcess:
    home.mkdir(parents=True, exist_ok=True)
    return subprocess.run([shell, str(script), *args], env={"PATH": os.environ["PATH"], "HOME": str(home), **env},
                          capture_output=True, text=True, timeout=120)


def agents_dir(wb: Path, tmp_path: Path, *args: str, shell: str = BASH) -> subprocess.CompletedProcess:
    return run(wb / "adapters/agents-dir/install.sh", "--project", str(tmp_path / "proj"), *args,
               home=tmp_path / "home", shell=shell)


def plugin(wb: Path, tmp_path: Path, *args: str, shell: str = BASH) -> subprocess.CompletedProcess:
    return run(wb / "adapters/claude-code/install.sh", *args, home=tmp_path / "home", shell=shell,
               CLAUDE_SKILLS_DIR=str(tmp_path / "cc" / "skills"))


def entries(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def test_pack_names_are_validated(tmp_path):
    for pack in ("../../x", "/etc/passwd", "Default", "nope"):
        r = subprocess.run([sys.executable, str(ROOT / "scripts/select_skills.py"), "--pack", pack],
                           capture_output=True, text=True)
        assert r.returncode == 2 and "not found" in r.stderr, pack
        b = subprocess.run([sys.executable, str(BUILD), "--pack", pack, "--dry-run"], capture_output=True, text=True)
        assert b.returncode == 2, pack
        assert install(tmp_path, "--pack", pack).returncode == 2, pack
    assert not (tmp_path / "proj").exists()


def test_symlink_install_skips_and_keeps_a_folder_it_did_not_make(tmp_path):
    names = default_pack()
    skills = tmp_path / "proj" / ".agents" / "skills"
    mine = skills / names[0]
    mine.mkdir(parents=True)
    (mine / "notes.md").write_text("mine\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (skills / names[1]).symlink_to(elsewhere)

    r = install(tmp_path)
    assert r.returncode == 1 and "Skipped" in r.stderr
    out = json.loads(r.stdout)
    assert set(out["skipped"]) == set(names[:2])
    assert out["installed"] == len(names) - 2
    assert (skills / names[2]).is_symlink()
    assert (skills / ".." / SECURITY).is_file(), "the real pack gets the real shared references"

    r = install(tmp_path, "--uninstall")
    assert r.returncode == 1
    assert (mine / "notes.md").read_text(encoding="utf-8") == "mine\n"
    assert (skills / names[1]).is_symlink() and os.readlink(skills / names[1]) == str(elsewhere)
    assert not (skills / names[2]).exists()
    assert not (skills.parent / "shared").exists()


def test_copy_install_replaces_and_removes_only_its_copies(tmp_path):
    names = default_pack()
    skills = tmp_path / "proj" / ".agents" / "skills"
    assert install(tmp_path, "--copy").returncode == 0
    assert (skills / names[0] / "SKILL.md").is_file()
    assert install(tmp_path, "--copy").returncode == 0, "a second run replaces its own copies"
    r = install(tmp_path, "--uninstall")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["removed"] == len(names)
    assert list(skills.iterdir()) == []


def test_plugin_uninstall_keeps_a_link_it_did_not_make(tmp_path):
    plugin_installer = BUILD.parent / "install.sh"
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (skills_dir / LINK).symlink_to(elsewhere)
    env = {**os.environ, "HOME": str(tmp_path / "home"), "CLAUDE_SKILLS_DIR": str(skills_dir)}
    r = subprocess.run([BASH, str(plugin_installer), "--uninstall"], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and "not created by this installer" in r.stderr
    assert os.readlink(skills_dir / LINK) == str(elsewhere)


# --- the shared references, beside the skills after each kind of install ---------------------------

@pytest.mark.parametrize("mode", [[], ["--copy"]])
def test_agents_dir_install_puts_the_shared_references_beside_the_skills(workbench, tmp_path, mode):
    r = agents_dir(workbench, tmp_path, *mode)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["installed"] == 3 and out["shared"] == "installed" and out["skipped"] == []
    skills = tmp_path / "proj" / ".agents" / "skills"
    assert (skills / ".." / SECURITY).is_file()
    # by the installed path, as a model follows the link a skill writes
    assert Path(os.path.normpath(skills / "eng-alpha" / "../.." / SECURITY)).is_file()
    shared = skills.parent / "shared"
    assert (shared / MARK).is_file() and not shared.is_symlink()
    assert (shared / "references").is_symlink() == (mode == [])

    assert agents_dir(workbench, tmp_path, *mode).returncode == 0, "a second run replaces its own shared folder"
    r = agents_dir(workbench, tmp_path, "--uninstall")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["shared"] == "removed"
    assert not shared.exists() and entries(skills) == []
    assert (workbench / SECURITY).is_file(), "removing a link never removes what it points to"


def test_agents_dir_install_leaves_a_shared_folder_it_did_not_make(workbench, tmp_path):
    theirs = tmp_path / "proj" / ".agents" / "shared"
    theirs.mkdir(parents=True)
    (theirs / "notes.md").write_text("another tool's\n", encoding="utf-8")
    r = agents_dir(workbench, tmp_path)
    assert r.returncode == 1 and "shared references were not installed" in r.stderr
    out = json.loads(r.stdout)
    assert out["shared"] == "skipped" and out["skipped"] == ["shared"] and out["installed"] == 3
    r = agents_dir(workbench, tmp_path, "--uninstall")
    assert r.returncode == 1
    assert entries(theirs) == ["notes.md"]


def test_plugin_install_puts_the_shared_references_in_the_build(workbench, tmp_path):
    r = plugin(workbench, tmp_path)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    link = tmp_path / "cc" / "skills" / LINK
    build = workbench / "adapters/claude-code/build/default"
    assert out["linked"] == str(link) and os.readlink(link) == str(build)
    assert out["fallback"].endswith(f"--plugin-dir {build}")
    assert entries(link / "skills") == ["eng-alpha", "eng-beta", "mkt-gamma"]
    assert (link / "skills" / ".." / SECURITY).is_file()
    assert Path(os.path.normpath(link / "skills" / "eng-alpha" / "../.." / SECURITY)).is_file()
    assert (link / "agents" / "helper.md").is_file()
    manifest = json.loads((link / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    # With an `agents` path the CLI refused the whole folder as an invalid manifest; agents/ is found by default.
    assert manifest["name"] == "openhora" and "agents" not in manifest


# --- the compatibility stage of the rename: the old plugin link and the old marker (T23) ------------

def legacy_link(workbench, tmp_path, target=None) -> Path:
    """The link the installer made before the rename: under the old name, into this checkout's build folder."""
    skills = tmp_path / "cc" / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    link = skills / LEGACY_LINK
    link.symlink_to(target or workbench / "adapters/claude-code/build/default")
    return link


def test_plugin_install_removes_the_old_link_into_its_own_build_and_says_so(workbench, tmp_path):
    old = legacy_link(workbench, tmp_path)
    r = plugin(workbench, tmp_path)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    link = tmp_path / "cc" / "skills" / LINK
    assert out["linked"] == str(link) and out["legacy_removed"] == str(old)
    assert link.is_symlink() and not old.is_symlink() and not old.exists()
    assert "Removed the old plugin link" in r.stderr and LEGACY_LINK in r.stderr, "the person is told that the old link went"
    assert "openhora@skills-dir" in out["next"]
    again = plugin(workbench, tmp_path)
    assert again.returncode == 0 and "legacy_removed" not in json.loads(again.stdout), "nothing to remove the second time"


def test_plugin_install_leaves_an_old_link_that_points_elsewhere_or_is_a_folder(workbench, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    old = legacy_link(workbench, tmp_path, target=elsewhere)
    r = plugin(workbench, tmp_path)
    assert r.returncode == 0, r.stderr
    assert "legacy_removed" not in json.loads(r.stdout) and os.readlink(old) == str(elsewhere)
    old.unlink()
    old.mkdir()
    (old / "notes.md").write_text("mine\n", encoding="utf-8")
    assert plugin(workbench, tmp_path).returncode == 0 and entries(old) == ["notes.md"]


def test_plugin_dry_run_reports_the_old_link_it_would_remove_and_removes_nothing(workbench, tmp_path):
    old = legacy_link(workbench, tmp_path)
    r = plugin(workbench, tmp_path, "--dry-run")
    assert r.returncode == 0, r.stderr
    last = json.loads(r.stdout.splitlines()[-1])
    assert last["would_remove_legacy"] == str(old) and old.is_symlink()
    assert not (tmp_path / "cc" / "skills" / LINK).exists()
    u = json.loads(plugin(workbench, tmp_path, "--uninstall", "--dry-run").stdout)
    assert u["would_remove_legacy"] == str(old) and old.is_symlink()


def test_plugin_uninstall_removes_either_link_or_both(workbench, tmp_path):
    skills = tmp_path / "cc" / "skills"
    # only the old one (installed before the rename, never reinstalled)
    old = legacy_link(workbench, tmp_path)
    r = plugin(workbench, tmp_path, "--uninstall")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"removed": None, "legacy_removed": str(old)} and not old.is_symlink()
    # only the new one
    assert plugin(workbench, tmp_path).returncode == 0
    assert json.loads(plugin(workbench, tmp_path, "--uninstall").stdout) == {"removed": str(skills / LINK)}
    # both
    assert plugin(workbench, tmp_path).returncode == 0
    old = legacy_link(workbench, tmp_path)
    out = json.loads(plugin(workbench, tmp_path, "--uninstall").stdout)
    assert out == {"removed": str(skills / LINK), "legacy_removed": str(old)}
    assert entries(skills) == [] and not (workbench / "adapters/claude-code/build").exists()


def test_plugin_uninstall_keeps_an_old_link_it_did_not_make(workbench, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    old = legacy_link(workbench, tmp_path, target=elsewhere)
    assert plugin(workbench, tmp_path).returncode == 0
    r = plugin(workbench, tmp_path, "--uninstall")
    assert r.returncode == 0, r.stderr
    assert os.readlink(old) == str(elsewhere) and not (tmp_path / "cc" / "skills" / LINK).exists()


def test_the_listing_budget_backup_prefix_is_the_new_name(workbench, tmp_path):
    settings = tmp_path / "proj" / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"env": {"KEEP": "1"}}), encoding="utf-8")
    r = plugin(workbench, tmp_path, "--listing-budget", "write", "--project", str(tmp_path / "proj"))
    assert r.returncode == 0, r.stderr
    backups = sorted(p.name for p in settings.parent.glob("settings.json.*.bak"))
    assert len(backups) == 1 and backups[0].startswith("settings.json.openhora-") and "ai-workbench" not in backups[0]


@pytest.mark.parametrize("mode", [[], ["--copy"]])
def test_agents_dir_install_replaces_and_removes_copies_made_under_the_old_marker(workbench, tmp_path, mode):
    skills = tmp_path / "proj" / ".agents" / "skills"
    assert agents_dir(workbench, tmp_path, "--copy").returncode == 0
    # make every copy and the shared folder look like the installer of before the rename made them
    for folder in [*skills.iterdir(), skills.parent / "shared"]:
        (folder / MARK).rename(folder / LEGACY_MARK)
    r = agents_dir(workbench, tmp_path, *mode)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["skipped"] == [], "a copy under the old marker is still the installer's own"
    if mode:
        assert all((f / MARK).is_file() and not (f / LEGACY_MARK).exists() for f in [*skills.iterdir(), skills.parent / "shared"])
    # and an uninstall removes whatever carries either marker
    assert agents_dir(workbench, tmp_path, "--copy").returncode == 0
    (skills / "eng-alpha" / MARK).rename(skills / "eng-alpha" / LEGACY_MARK)
    (skills.parent / "shared" / MARK).rename(skills.parent / "shared" / LEGACY_MARK)
    r = agents_dir(workbench, tmp_path, "--uninstall")
    assert r.returncode == 0, r.stderr
    assert entries(skills) == [] and not (skills.parent / "shared").exists()


# --- a pack change and an uninstall remove what an earlier pack installed --------------------------

@pytest.mark.parametrize("mode", [[], ["--copy"]])
def test_agents_dir_pack_change_and_uninstall_leave_nothing_behind(workbench, tmp_path, mode):
    skills = tmp_path / "proj" / ".agents" / "skills"
    mine = skills / "my-own-skill"
    mine.mkdir(parents=True)
    assert agents_dir(workbench, tmp_path, *mode).returncode == 0
    assert entries(skills) == ["eng-alpha", "eng-beta", "mkt-gamma", "my-own-skill"]

    r = agents_dir(workbench, tmp_path, "--pack", "engonly", *mode)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["installed"] == 2 and out["stale_removed"] == 1
    assert entries(skills) == ["eng-alpha", "eng-beta", "my-own-skill"]

    # A skill renamed in the workbench: its link dangles (or its copy is stale) until the next install.
    (workbench / "skills" / "eng-beta").rename(workbench / "skills" / "eng-delta")
    assert agents_dir(workbench, tmp_path, "--pack", "engonly", *mode).returncode == 0
    assert entries(skills) == ["eng-alpha", "eng-delta", "my-own-skill"]

    # Uninstalling with another pack still removes everything the installer made.
    assert agents_dir(workbench, tmp_path, "--pack", "default", *mode).returncode == 0
    r = agents_dir(workbench, tmp_path, "--pack", "engonly", "--uninstall")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["removed"] == 3
    assert entries(skills) == ["my-own-skill"] and mine.is_dir()
    assert sorted(p.name for p in (workbench / "skills").iterdir()) == ["eng-alpha", "eng-delta", "mkt-gamma"]


def test_plugin_pack_change_and_uninstall_remove_the_old_builds(workbench, tmp_path):
    builds = workbench / "adapters/claude-code/build"
    link = tmp_path / "cc" / "skills" / LINK
    assert plugin(workbench, tmp_path).returncode == 0
    assert entries(builds) == ["default"]
    r = plugin(workbench, tmp_path, "--pack", "engonly")
    assert r.returncode == 0, r.stderr
    assert entries(builds) == ["engonly"] and os.readlink(link) == str(builds / "engonly")
    assert entries(link / "skills") == ["eng-alpha", "eng-beta"]

    (workbench / "skills" / "eng-beta").rename(workbench / "skills" / "eng-delta")
    assert plugin(workbench, tmp_path, "--pack", "engonly").returncode == 0
    assert entries(link / "skills") == ["eng-alpha", "eng-delta"]

    r = plugin(workbench, tmp_path, "--uninstall")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["removed"] == str(link)
    assert not link.is_symlink() and not builds.exists()
    assert sorted(p.name for p in (workbench / "skills").iterdir()) == ["eng-alpha", "eng-delta", "mkt-gamma"]


def test_plugin_install_refuses_a_target_it_did_not_make_and_builds_nothing(workbench, tmp_path):
    link = tmp_path / "cc" / "skills" / LINK
    link.mkdir(parents=True)
    (link / "notes.md").write_text("mine\n", encoding="utf-8")
    r = plugin(workbench, tmp_path)
    assert r.returncode == 1 and "not created by this installer" in r.stderr
    assert entries(link) == ["notes.md"] and not (workbench / "adapters/claude-code/build").exists()


# --- a pack that selects nothing; usage errors; the JSON line ---------------------------------------

@pytest.mark.parametrize("shell", SHELLS)
def test_a_pack_that_selects_nothing_is_reported_and_exits_0(workbench, tmp_path, shell):
    assert agents_dir(workbench, tmp_path, "--pack", "engonly", shell=shell).returncode == 0
    skills = tmp_path / "proj" / ".agents" / "skills"
    for args in (["--pack", "empty"], ["--pack", "empty", "--copy"]):
        r = agents_dir(workbench, tmp_path, *args, shell=shell)
        assert r.returncode == 0, r.stderr
        assert "selects no skill" in r.stderr and "unbound variable" not in r.stderr
        assert json.loads(r.stdout)["installed"] == 0
    assert entries(skills) == ["eng-alpha", "eng-beta"], "an empty pack changes nothing"
    r = agents_dir(workbench, tmp_path, "--pack", "empty", "--dry-run", shell=shell)
    assert r.returncode == 0 and json.loads(r.stdout)["skills"] == []
    r = agents_dir(workbench, tmp_path, "--pack", "empty", "--uninstall", shell=shell)
    assert r.returncode == 0, r.stderr
    assert entries(skills) == [] and json.loads(r.stdout)["removed"] == 2

    r = plugin(workbench, tmp_path, "--pack", "empty", shell=shell)
    assert r.returncode == 0 and "selects no skill" in r.stderr
    assert json.loads(r.stdout) == {"pack": "empty", "linked": None, "skills": 0}
    assert not (tmp_path / "cc").exists() and not (workbench / "adapters/claude-code/build").exists()


USAGE = [
    ("adapters/agents-dir/install.sh", ["--pack"]), ("adapters/agents-dir/install.sh", ["--copy", "--project"]),
    ("adapters/claude-code/install.sh", ["--pack"]), ("adapters/claude-code/install.sh", ["--dry-run", "--pack"]),
    ("adapters/claude-code/install.sh", ["--listing-budget"]), ("adapters/claude-code/install.sh", ["--project"]),
    ("adapters/claude-code/install.sh", ["--settings-scope"]),
    ("adapters/claude-code/run-agent.sh", ["--model"]), ("adapters/claude-code/run-agent.sh", ["--out", "x", "--skill-dir"]),
    ("adapters/claude-code/run-agent.sh", ["--max-cost-usd"]), ("adapters/claude-code/run-agent.sh", ["--timeout-seconds"]),
    ("scripts/new-skill.sh", ["--name"]), ("scripts/new-skill.sh", ["--name", "biz-demo-x", "--area"]),
]


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("script,args", USAGE)
def test_a_flag_given_last_without_its_value_exits_2_with_a_message(tmp_path, shell, script, args):
    r = run(ROOT / script, *args, home=tmp_path / "home", shell=shell, CLAUDE_SKILLS_DIR=str(tmp_path / "cc"))
    assert r.returncode == 2, r.stderr
    assert r.stderr.strip() == f"Error: {args[-1]} needs a value. See --help."
    assert r.stdout == "" and not (tmp_path / "cc").exists()


def test_build_refuses_an_unknown_option_and_a_pack_without_a_value(workbench):
    build = workbench / "adapters/claude-code/build.py"
    for args in (["--pak", "default"], ["--pack"]):
        r = subprocess.run([sys.executable, str(build), *args], capture_output=True, text=True)
        assert r.returncode == 2 and r.stderr.startswith("Error:"), args
    assert not (workbench / "adapters/claude-code/build").exists()


def test_the_json_the_installers_print_is_valid_for_a_path_with_a_quote_and_a_space(workbench, tmp_path):
    odd = tmp_path / 'my "quoted" project'
    home = tmp_path / "home"
    for extra in (["--dry-run"], [], ["--uninstall"]):
        r = run(workbench / "adapters/agents-dir/install.sh", "--project", str(odd), *extra, home=home)
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout)["target"] == str(odd / ".agents" / "skills")
    skills_dir = str(odd / "cc skills")
    link = str(Path(skills_dir) / LINK)
    script = workbench / "adapters/claude-code/install.sh"
    lines = run(script, "--dry-run", home=home, CLAUDE_SKILLS_DIR=skills_dir).stdout.splitlines()
    assert json.loads(lines[0])["skills"] == 3 and json.loads(lines[1])["would_link"] == link
    assert json.loads(run(script, home=home, CLAUDE_SKILLS_DIR=skills_dir).stdout)["linked"] == link
    assert json.loads(run(script, "--uninstall", "--dry-run", home=home, CLAUDE_SKILLS_DIR=skills_dir).stdout) == {
        "would_remove": link}
    assert json.loads(run(script, "--uninstall", home=home, CLAUDE_SKILLS_DIR=skills_dir).stdout) == {"removed": link}
    assert json.loads(run(script, "--uninstall", home=home, CLAUDE_SKILLS_DIR=skills_dir).stdout) == {"removed": None}


def test_the_help_of_each_script_is_its_whole_header(tmp_path):
    for script in ("adapters/agents-dir/install.sh", "adapters/claude-code/install.sh", "scripts/new-skill.sh"):
        r = run(ROOT / script, "--help", home=tmp_path / "home")
        header = []
        for line in (ROOT / script).read_text(encoding="utf-8").splitlines()[1:]:
            if not line.startswith("#"):
                break
            header.append(line[2:] if line.startswith("# ") else line[1:])
        assert r.returncode == 0 and r.stdout.splitlines() == header, script


def test_packs_readme_names_only_options_the_installers_have():
    text = (ROOT / "packs" / "README.md").read_text(encoding="utf-8")
    for script in ("adapters/agents-dir/install.sh", "adapters/claude-code/install.sh", "adapters/claude-code/build.py"):
        assert "--areas" not in (ROOT / script).read_text(encoding="utf-8")
    assert "--areas" not in text and "--pack <name>" in text
