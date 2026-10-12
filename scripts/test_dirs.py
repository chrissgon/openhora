#!/usr/bin/env python3
"""Print the folders that hold the repository's own tests, one per line, for pytest.

Usage:
  python3 scripts/test_dirs.py            # every test folder
  uv run --with pytest pytest -q $(python3 scripts/test_dirs.py)

A test folder is `tests/` directly under scripts/, evals/, runtime/, shared/scripts/, a provider class, an adapter
or a skill's scripts/ folder, holding at least one test_*.py. Folders named tests inside eval fixtures are not ours.
CI runs this list, so a new test folder is picked up without editing the workflow.
"""
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATTERNS = ("scripts/tests", "evals/tests", "runtime/tests", "shared/scripts/tests", "providers/*/tests",
            "adapters/*/tests", "skills/*/scripts/tests")


def test_dirs(root=ROOT):
    found = []
    for pattern in PATTERNS:
        for path in sorted(glob.glob(os.path.join(root, pattern))):
            if glob.glob(os.path.join(path, "test_*.py")):
                found.append(os.path.relpath(path, root))
    return found


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(__doc__.strip())
        sys.exit(0 if sys.argv[1] in ("-h", "--help") else 2)
    print("\n".join(test_dirs()))
