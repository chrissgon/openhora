"""Shared test setup for scripts/tests.

Git exports GIT_DIR, GIT_INDEX_FILE and friends to hooks. A test that runs `git init` or
`git commit` in a temporary folder while they are set acts on the workbench repository instead:
it commits there, or turns it bare (from a worktree, `git init <tmp>` with GIT_DIR set rewrote the
shared config with core.bare = true). Every test here uses temporary repositories only, so every
GIT_* variable is removed before any test module is imported, whoever starts pytest.
"""
import os

for name in [n for n in os.environ if n.startswith("GIT_")]:
    os.environ.pop(name, None)

# The password-manager mapping file (S16) is looked for under XDG_CONFIG_HOME, else under the home folder. A file the person wrote there
# must never be read by a test, which would start the real tool: for the whole session the config folder is an empty one. A test that
# needs another sets its own.
import atexit
import shutil
import tempfile

_EMPTY_CONFIG = tempfile.mkdtemp(prefix="wb-no-config-")
os.environ["XDG_CONFIG_HOME"] = _EMPTY_CONFIG
atexit.register(shutil.rmtree, _EMPTY_CONFIG, ignore_errors=True)
