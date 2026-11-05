"""The whole tree holds no security warning: scripts/security_scan.py run on this repository. Hook step 2 and the validate job of
.github/workflows/checks.yml run the same scan with --strict on every commit and every pull request; they are the protection. This test
repeats them inside pytest (about 10 s locally, 18 s in CI), so it runs in the nightly run, the whole-suite runs and whenever the
scanner or the wiring changes (scripts/select_tests.py: rule 2 selects it by its name for a change to security_scan.py; rule 5 selects
scripts/tests for the wiring), never as a guard of every commit (docs/decisions.md, the entry of T2b). That the hook and the job keep
running the scan is checked on every commit by test_security_scan.py.

Run: uv run --with pytest==9.1.1 pytest scripts/tests/test_security_scan_repo.py
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "security_scan.py"
spec = importlib.util.spec_from_file_location("security_scan_whole_tree", SCRIPT)
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)


def test_this_repository_has_no_security_warning():
    _, active, _ = scanner.scan(str(SCRIPT.parents[1]))
    assert [(f["path"], f["line"], f["rule"]) for f in active] == []
