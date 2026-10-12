"""Tests for the skill-listing budget of the Claude Code installer (install.sh and listing_budget.py).

Offline, no model and no harness. The budget of the real packs is computed from this checkout, which writes
nothing. Every install runs in a small copy of the workbench under the test's temporary folder, with HOME, the
skills directory and the project there too: no test writes into this checkout, a real project or a real home.

Run: uv run --with pytest pytest adapters/claude-code/tests
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "adapters/claude-code/listing_budget.py"
VAR = "SLASH_COMMAND_TOOL_CHAR_BUDGET"
sys.path.insert(0, str(ROOT / "scripts"))
from select_skills import resolve  # noqa: E402
from validate import load_yaml, split_frontmatter  # noqa: E402


def compute(pack: str, root: Path = ROOT) -> dict:
    r = subprocess.run([sys.executable, str(root / "adapters/claude-code/listing_budget.py"), "compute", "--pack", pack],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def listed(names: list[str], root: Path) -> int:
    """The characters of the lines `- openhora:<name>: <description>`, read independently of the script."""
    total = 0
    for name in names:
        fm, _ = split_frontmatter(str(root / "skills" / name / "SKILL.md"))
        description = str(load_yaml(fm)["description"]).strip()
        total += len(f"- openhora:{name}: {description}\n")
    return total


@pytest.mark.parametrize("pack", ["default", "all"])
def test_the_budget_of_a_real_pack_is_its_listing_plus_a_bounded_margin(pack):
    out = compute(pack)
    names = resolve(pack=pack)
    chars = listed(names, ROOT)
    assert out["skills"] == len(names) > 0
    assert out["characters"] == chars
    assert out["budget"] % 1000 == 0 and out["budget"] == chars + out["margin"]
    # At least a quarter of the pack and at least 10000 above it; never more than the next 1000 beyond that.
    floor = chars + max(10000, math.ceil(chars * 0.25))
    assert floor <= out["budget"] < floor + 1000
    # Far under the eval adapter's 200000: the budget follows the pack, it is not a fixed huge number.
    assert out["budget"] < 100000


def test_a_pack_that_selects_nothing_needs_no_budget():
    assert compute("assistant") == {"pack": "assistant", "skills": 0, "characters": 0, "margin": 0, "budget": 0}


# --- the installer, in a small copy of the workbench --------------------------------------------------

def skill(root: Path, name: str, description: str) -> None:
    folder = root / "skills" / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: >\n  {description}\nmetadata:\n  area: engineering\n"
                                     "  kind: capability\n---\n\n# Demo\n", encoding="utf-8")


@pytest.fixture
def wb(tmp_path):
    wb = tmp_path / "wb"
    for rel in ("adapters/claude-code/install.sh", "adapters/claude-code/build.py",
                "adapters/claude-code/listing_budget.py", "adapters/claude-code/plugin.json",
                "scripts/select_skills.py", "scripts/validate.py", "shared/references/security.md"):
        (wb / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, wb / rel)
    (wb / "adapters/claude-code/overrides").mkdir()
    (wb / "agents").mkdir()
    skill(wb, "eng-alpha", "An invented skill of the listing tests, used when alpha work is asked for.")
    skill(wb, "eng-beta", "A second invented skill, used when beta work is asked for.")
    (wb / "packs").mkdir()
    (wb / "packs" / "default.txt").write_text("*\n", encoding="utf-8")
    (wb / "packs" / "one.txt").write_text("eng-alpha\n", encoding="utf-8")
    (tmp_path / "home").mkdir()
    (tmp_path / "proj").mkdir()
    return wb


def install(wb: Path, *args: str) -> subprocess.CompletedProcess:
    tmp = wb.parent
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp / "home"), "CLAUDE_SKILLS_DIR": str(tmp / "cc" / "skills")}
    return subprocess.run(["bash", str(wb / "adapters/claude-code/install.sh"), *args], env=env,
                          capture_output=True, text=True, timeout=120)


def files(folder: Path) -> list[str]:
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*")) if folder.exists() else []


def backups(folder: Path) -> list[Path]:
    return sorted(folder.glob("*.openhora-*.bak"))


def test_the_fixture_budget_is_exact(wb):
    chars = listed(["eng-alpha", "eng-beta"], wb)
    assert compute("default", wb) == {"pack": "default", "skills": 2, "characters": chars, "margin": 11000 - chars,
                                      "budget": 11000}


def test_by_default_the_line_and_its_file_are_printed_and_nothing_is_written(wb, tmp_path):
    r = install(wb, "--project", str(tmp_path / "proj"))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)["listing_budget"]
    settings = tmp_path / "proj" / ".claude" / "settings.json"
    assert out["budget"] == 11000 and out["setting"] == VAR and out["written"] is False
    assert out["line"] == f'"env": {{"{VAR}": "11000"}}'
    assert out["file"] == str(settings)
    assert out["apply"].endswith(f"--listing-budget write --project {tmp_path / 'proj'}")
    assert out["line"] in r.stderr and str(settings) in r.stderr and "Nothing was written" in r.stderr
    assert files(tmp_path / "proj") == [] and files(tmp_path / "home") == []
    assert not (wb / "adapters/claude-code/installed").exists()


def test_without_a_project_the_printed_file_is_a_placeholder(wb):
    r = install(wb)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["listing_budget"]["file"] == "<project>/.claude/settings.json"


def test_skip_leaves_the_budget_out(wb):
    r = install(wb, "--listing-budget", "skip")
    assert r.returncode == 0 and "listing_budget" not in json.loads(r.stdout)
    assert VAR not in r.stderr


def test_write_merges_keeps_every_key_backs_up_and_uninstall_puts_it_back(wb, tmp_path):
    folder = tmp_path / "proj" / ".claude"
    folder.mkdir()
    settings = folder / "settings.json"
    original = '{"permissions": {"allow": ["Bash(ls)"]}, "env": {"OTHER": "1"}, "model": "x"}\n'
    settings.write_text(original, encoding="utf-8")

    r = install(wb, "--listing-budget", "write", "--project", str(tmp_path / "proj"))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)["listing_budget"]
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data == {"permissions": {"allow": ["Bash(ls)"]}, "env": {"OTHER": "1", VAR: "11000"}, "model": "x"}
    assert out["written"] is True and out["file"] == str(settings)
    [backup] = backups(folder)
    assert out["backup"] == str(backup) and backup.read_text(encoding="utf-8") == original
    assert (tmp_path / "cc" / "skills" / "openhora").is_symlink(), "the plugin is installed as well"
    assert files(tmp_path / "home") == [], "the project scope never writes into the home"

    r = install(wb, "--uninstall")
    assert r.returncode == 0, r.stderr
    undone = json.loads(r.stdout)["listing_budget"]["undone"]
    assert undone[0]["file"] == str(settings) and undone[0]["restored"] is None
    assert json.loads(settings.read_text(encoding="utf-8")) == json.loads(original)
    assert not (wb / "adapters/claude-code/installed").exists()


def test_write_into_no_file_creates_it_and_uninstall_removes_it(wb, tmp_path):
    proj = tmp_path / "proj"
    r = install(wb, "--listing-budget", "write", "--project", str(proj))
    assert r.returncode == 0, r.stderr
    assert json.loads((proj / ".claude" / "settings.json").read_text(encoding="utf-8")) == {"env": {VAR: "11000"}}
    assert json.loads(r.stdout)["listing_budget"]["backup"] is None
    assert install(wb, "--uninstall").returncode == 0
    assert files(proj) == []


def test_a_broken_settings_file_is_refused_and_nothing_changes(wb, tmp_path):
    folder = tmp_path / "proj" / ".claude"
    folder.mkdir()
    for text in ('{"env": {', '["a list"]', '{"env": "not an object"}'):
        (folder / "settings.json").write_text(text, encoding="utf-8")
        r = install(wb, "--listing-budget", "write", "--project", str(tmp_path / "proj"))
        assert r.returncode == 1 and r.stderr.startswith("Error:") and "nothing was written" in r.stderr, text
        assert r.stdout == ""
        assert (folder / "settings.json").read_text(encoding="utf-8") == text
        assert backups(folder) == []
        assert not (tmp_path / "cc").exists() and not (wb / "adapters/claude-code/build").exists()


def test_a_larger_value_the_person_set_is_kept(wb, tmp_path):
    folder = tmp_path / "proj" / ".claude"
    folder.mkdir()
    text = json.dumps({"env": {VAR: "300000"}})
    (folder / "settings.local.json").write_text(text, encoding="utf-8")
    r = install(wb, "--listing-budget", "write", "--settings-scope", "local", "--project", str(tmp_path / "proj"))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["listing_budget"]["kept"] == "300000" and "left as it is" in r.stderr
    assert (folder / "settings.local.json").read_text(encoding="utf-8") == text and backups(folder) == []
    assert not (wb / "adapters/claude-code/installed").exists()


def test_a_smaller_value_is_raised_and_put_back_on_uninstall(wb, tmp_path):
    folder = tmp_path / "proj" / ".claude"
    folder.mkdir()
    (folder / "settings.json").write_text(json.dumps({"env": {VAR: "5000"}}), encoding="utf-8")
    assert install(wb, "--listing-budget", "write", "--project", str(tmp_path / "proj")).returncode == 0
    assert json.loads((folder / "settings.json").read_text())["env"][VAR] == "11000"
    assert install(wb, "--uninstall").returncode == 0
    assert json.loads((folder / "settings.json").read_text()) == {"env": {VAR: "5000"}}


def test_uninstall_leaves_a_value_changed_since(wb, tmp_path):
    proj = tmp_path / "proj"
    assert install(wb, "--listing-budget", "write", "--project", str(proj)).returncode == 0
    settings = proj / ".claude" / "settings.json"
    settings.write_text(json.dumps({"env": {VAR: "77000"}}), encoding="utf-8")
    r = install(wb, "--uninstall")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["listing_budget"]["left"][0]["file"] == str(settings)
    assert json.loads(settings.read_text()) == {"env": {VAR: "77000"}}
    assert not (wb / "adapters/claude-code/installed").exists(), "a value that is not ours is not ours to track"


def test_a_pack_change_rewrites_its_own_value_and_keeps_what_was_there_first(wb, tmp_path):
    skill(wb, "eng-gamma", "A long invented skill. " * 100)
    proj = tmp_path / "proj"
    settings = proj / ".claude" / "settings.json"
    assert install(wb, "--listing-budget", "write", "--project", str(proj)).returncode == 0
    assert json.loads(settings.read_text())["env"][VAR] == "13000"
    r = install(wb, "--pack", "one", "--listing-budget", "write", "--project", str(proj))
    assert r.returncode == 0, r.stderr
    assert json.loads(settings.read_text())["env"][VAR] == str(compute("one", wb)["budget"]) == "11000"
    assert install(wb, "--uninstall").returncode == 0
    assert files(proj) == [], "the file the first write created is removed, not kept as a backup's leftover"


def test_the_user_scope_is_written_only_when_named(wb, tmp_path):
    home_settings = tmp_path / "home" / ".claude" / "settings.json"
    r = install(wb, "--listing-budget", "write", "--settings-scope", "user")
    assert r.returncode == 0, r.stderr
    assert json.loads(home_settings.read_text()) == {"env": {VAR: "11000"}}
    assert files(tmp_path / "proj") == []
    assert install(wb, "--uninstall").returncode == 0
    assert not home_settings.exists()


def test_write_needs_a_project_and_a_dry_run_writes_nothing(wb, tmp_path):
    r = install(wb, "--listing-budget", "write")
    assert r.returncode == 2 and "--project" in r.stderr and r.stdout == ""
    for args in (["--listing-budget", "maybe"], ["--settings-scope", "global"]):
        r = install(wb, *args)
        assert r.returncode == 2 and r.stderr.startswith("Error:"), args
    r = install(wb, "--dry-run", "--listing-budget", "write", "--project", str(tmp_path / "proj"))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout.splitlines()[1])["listing_budget"]["would_write"] == "11000"
    assert files(tmp_path / "proj") == [] and files(tmp_path / "home") == []
    assert not (tmp_path / "cc").exists() and not (wb / "adapters/claude-code/installed").exists()


def test_the_script_refuses_usage_errors_without_a_traceback():
    for args in (["apply", "--mode"], ["nope"], ["apply", "--mode", "write"], ["compute", "--pack", "../x"]):
        r = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
        assert r.returncode == 2 and r.stderr.startswith("Error:") and "Traceback" not in r.stderr, args
        assert r.stdout == ""
    r = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and VAR in r.stdout
