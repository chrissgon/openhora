"""A `- Language: <tag>` header line changes nothing check_design.py reports.

Run: uv run --python 3.11 --with pytest==9.1.1 pytest -q skills/eng-architecture/scripts/tests

Offline; every product, feature and requirement below is fictional. Each case runs the script on a copy of the
trace-check fixture without the line and with it (`pt-BR`, `en-US`) in the design (after `- Owner:`), in the
ADR (after `- Status:`, its first header line) and in the specification (after `- Owner:`), and compares the
return code and the printed result (findings, counts and warnings).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

CHECK = Path(__file__).resolve().parents[1] / "check_design.py"
FIXTURE = Path(__file__).resolve().parents[2] / "evals" / "files" / "trace-check"
TAGS = ("pt-BR", "en-US")

SPEC = "docs/product/specs/expense-export.md"
DESIGN = "docs/engineering/designs/expense-export.md"
ADR_DIR = "docs/engineering/adr"
ADR = ADR_DIR + "/0001-export-file-format.md"


def project(tmp_path: Path) -> Path:
    shutil.copytree(FIXTURE, tmp_path, dirs_exist_ok=True)
    return tmp_path


def fix(root: Path) -> None:
    """The correct fix of the fixture: a component for REQ-2, a row for AC-2, and a second option in the ADR."""
    design = root / DESIGN
    t = design.read_text(encoding="utf-8")
    t = t.replace("| ExportRoute | Reads", "| CsvSerializer | Turns expenses into sorted rows | src/server/export/csv.ts "
                  "| expenses | CSV text | REQ-2 |\n| ExportRoute | Reads")
    t = t.replace("| AC-3 | Export a month", "| AC-2 | Serialize three expenses out of order | unit | test/csv.test.ts |\n"
                  "| AC-3 | Export a month")
    design.write_text(t, encoding="utf-8")
    adr = root / ADR
    adr.write_text(adr.read_text(encoding="utf-8").replace(
        "## Decision", "### Option B: spreadsheet file\n- Consequences: needs a library.\n\n## Decision"),
        encoding="utf-8")


def add_language(path: Path, after: str, tag: str) -> None:
    """Insert the line right after the first line that starts with `after`."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    at = next(i for i, ln in enumerate(lines) if ln.startswith(after))
    lines.insert(at + 1, f"- Language: {tag}\n")
    path.write_text("".join(lines), encoding="utf-8")


def check(root: Path) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(CHECK), "--spec", SPEC, "--design", DESIGN, "--adr-dir", ADR_DIR],
                       cwd=root, capture_output=True, text=True, timeout=60)
    assert r.stderr == ""
    return r.returncode, r.stdout


def with_and_without(tmp_path: Path, fixed: bool) -> None:
    base = project(tmp_path / "base")
    if fixed:
        fix(base)
    expected = check(base)
    for tag in TAGS:
        for files in ([(DESIGN, "- Owner:")],
                      [(DESIGN, "- Owner:"), (ADR, "- Status:"), (SPEC, "- Owner:")]):
            root = project(tmp_path / f"{tag}-{len(files)}")
            if fixed:
                fix(root)
            for rel, after in files:
                add_language(root / rel, after, tag)
                assert f"- Language: {tag}" in (root / rel).read_text(encoding="utf-8")
            assert check(root) == expected


def test_a_passing_design_still_passes_with_a_language_line(tmp_path):
    base = project(tmp_path / "pass")
    fix(base)
    code, out = check(base)
    assert code == 0 and json.loads(out)["ok"] is True and json.loads(out)["errors"] == []
    with_and_without(tmp_path / "cases", fixed=True)


def test_a_failing_design_reports_the_same_findings_with_a_language_line(tmp_path):
    base = project(tmp_path / "fail")
    code, out = check(base)
    assert code == 1
    assert json.loads(out)["errors"] == [
        "ids from the spec not mentioned in the design: ['AC-2', 'REQ-2']",
        "acceptance criteria without a row in the verification plan: ['AC-2']",
        "0001-export-file-format.md: only 1 option(s)",
    ]
    with_and_without(tmp_path / "cases", fixed=False)
