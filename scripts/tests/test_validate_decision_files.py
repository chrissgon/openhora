"""Offline tests of the decision-files check in scripts/validate.py: one file per decision entry in docs/decisions/, named
YYYY-MM-DD-<package-id>-<slug>.md, whose first line starts with '## <the same date>: '."""
import importlib.util
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("validate", REPO / "scripts" / "validate.py")
validate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validate)

GOOD = "2030-04-05-pkg-1-a-rule.md"


@pytest.fixture
def root(tmp_path):
    folder = tmp_path / "docs" / "decisions"
    folder.mkdir(parents=True)
    (folder / "README.md").write_text("The rules.\n")
    (folder / GOOD).write_text("## 2030-04-05: A rule (PKG-1)\n\nThe text.\n")
    return tmp_path


def findings(root):
    report = validate.Report()
    validate.check_decision_files(report, root=str(root))
    return [(e["where"], e["message"]) for e in report.errors]


def test_a_well_named_file_with_the_matching_first_line_and_the_readme_are_accepted(root):
    assert findings(root) == []


@pytest.mark.parametrize("name", ["decisions-rule.md", "2030-04-05.md", "2030-04-05-Rule.md", "2030-04-05-a_rule.md", "2030-4-5-rule.md",
                                  "2030-04-05-rule--x.md", "2030-04-05-rule-.md", "2030-04-05-rule.txt", "2030-04-05-r" + chr(0xe9) + "gle.md"])
def test_a_bad_name_is_refused(root, name):
    (root / "docs" / "decisions" / name).write_text("## 2030-04-05: A rule\n")
    got = findings(root)
    assert [w for w, _ in got] == ["docs/decisions/" + name] and "name" in got[0][1]


def test_a_first_line_with_another_date_or_no_heading_is_refused(root):
    folder = root / "docs" / "decisions"
    (folder / GOOD).write_text("## 2030-04-06: A rule\n\nThe text.\n")
    got = findings(root)
    assert [w for w, _ in got] == ["docs/decisions/" + GOOD + ":1"] and "2030-04-05" in got[0][1]
    (folder / GOOD).write_text("# 2030-04-05: A rule\n")
    assert [w for w, _ in findings(root)] == ["docs/decisions/" + GOOD + ":1"]
    (folder / GOOD).write_text("\n## 2030-04-05: a blank line first\n")
    assert [w for w, _ in findings(root)] == ["docs/decisions/" + GOOD + ":1"]
    (folder / GOOD).write_text("## 2030-04-05 A rule without the colon\n")
    assert [w for w, _ in findings(root)] == ["docs/decisions/" + GOOD + ":1"]


def test_vacuity_the_check_is_not_silent_and_a_tree_without_the_folder_passes(root, tmp_path_factory):
    (root / "docs" / "decisions" / "bad.md").write_text("x\n")
    assert len(findings(root)) == 1  # a planted wrong name is found, so the empty list above is not a check that never looks
    assert findings(tmp_path_factory.mktemp("no-folder")) == []


def test_the_real_folder_of_this_repository_passes_and_the_english_only_check_reads_it(tmp_path):
    assert findings(REPO) == []
    scanner = validate.load_scanner()
    listed = {Path(p).relative_to(REPO).as_posix() for p in scanner.list_files(str(REPO), None)}
    assert any(rel.startswith("docs/decisions/") and rel != "docs/decisions/README.md" for rel in listed) or not (REPO / "docs/decisions").is_dir()
    # a planted Portuguese line in a decision file is an english-only error: the check reads the folder
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "docs" / "decisions").mkdir(parents=True)
    (tmp_path / "docs" / "decisions" / GOOD).write_text("## 2030-04-05: A rule\n\nA decis" + chr(0xe3) + "o foi tomada.\n")
    report = validate.Report()
    validate.check_english(report, root=str(tmp_path))
    assert [e["where"] for e in report.errors] == ["docs/decisions/" + GOOD + ":3"]
