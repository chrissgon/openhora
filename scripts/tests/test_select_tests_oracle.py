"""The import oracle of scripts/select_tests.py on this repository: every test that really imports a changed file within three steps
is selected. It reads the whole tree twice (the selector's graph, and its own parse of every `import`), about 18 s locally and 49 s in
CI, so it is no guard of every commit (docs/decisions.md, the entry of T2b). It runs in the nightly run and every whole-suite run
(.github/workflows/nightly.yml, checks.yml), and whenever the selector or the CI wiring changes (scripts/select_tests.py: rule 5 selects
scripts/tests whole; rule 2 selects this file by its name). The planted-selector tests on a fictional tree stay in test_select_tests.py,
which always runs, so a change to the selector's rules is still caught on every commit; what waits for the night is a miss that only the
real tree shows.

Run: uv run --with pytest==9.1.1 pytest scripts/tests/test_select_tests_oracle.py
"""
from __future__ import annotations

import ast
import importlib.util
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("select_tests_under_oracle", REPO / "scripts" / "select_tests.py")
sel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sel)


@pytest.fixture(scope="module")
def real():
    return sel.Repo(str(REPO))


def real_import_oracle(root, start, depth):
    """The tests that really `import` the file, or a module that imports it, up to `depth` steps: only the `import` statements of the
    Python files, read here with the test's own parser (never the selector's graph), a name resolved by stem within the importer's area first."""
    files = [str(p.relative_to(root)).replace(os.sep, "/") for p in Path(root).rglob("*.py")
             if not any(part in (".git", "node_modules", "__pycache__") for part in p.parts)]
    files = [f for f in files if not f.startswith("skills/") or "/scripts/" in f]
    by_stem = {}
    for f in files:
        by_stem.setdefault(os.path.basename(f)[:-3], []).append(f)
    importers = {}
    for f in files:
        try:
            tree = ast.parse((Path(root) / f).read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[-1] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.update([node.module.split(".")[-1]] if node.module else [])
                names.update(a.name for a in node.names)
        for name in names:
            candidates = by_stem.get(name, [])
            area = f.split("/")[0]
            for target in [c for c in candidates if c.split("/")[0] == area] or candidates:
                if target != f:
                    importers.setdefault(target, set()).add(f)
    seen, frontier = {start}, [start]
    for _ in range(depth):
        frontier = [i for x in frontier for i in importers.get(x, ()) if i not in seen and not seen.add(i)]
    return {f for f in seen if os.path.basename(f).startswith("test_") and "/tests/" in f}


def test_every_test_that_really_imports_a_changed_file_within_three_steps_is_selected(real):
    """The regression the review found: a selection that missed tests importing the changed module through another module."""
    for changed in ("runtime/natural_time.py", "runtime/phrases_pt_br.py", "runtime/ops_core.py", "runtime/tests/test_service.py", "runtime/lease.py"):
        got = set(sel.select(real, [changed]).result())
        covered = lambda t: t in got or any(t.startswith(g + "/") for g in got)
        missed = sorted(t for t in real_import_oracle(REPO, changed, 3) if not covered(t))
        assert missed == [], (changed, missed[:5])
