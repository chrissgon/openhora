"""A FAKE `op` for the tests of the password-manager backend (package S16). Not a test file, and never the real tool: an executable the
test writes into a temporary folder, with a `#!<this interpreter>` line, that records each call (argv, environment, whether stdin is a
terminal) in a file beside it and answers from a fixture file beside it. No real 1Password, no real secret: the values are SENTINEL.

  fake = FakeOp(tmp_path / "bin")
  fake.answer("op://Example Vault/github-read/credential", stdout=SENTINEL)        # rc 0 and a value
  fake.answer("op://Example Vault/github-read/credential", rc=1, stderr="...")      # a failure
  fake.answer("whoami", stdout="")                                                 # the probe
  fake.answer("*", ...)                                                            # any other reference
  fake.calls()  ->  [{"argv": [...], "env": {...}, "tty": False}, ...]
"""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

SCRIPT = '''#!{python}
import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "record.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps({{"argv": sys.argv, "env": dict(os.environ), "tty": sys.stdin.isatty()}}) + "\\n")
with open(os.path.join(here, "answers.json"), encoding="utf-8") as f:
    answers = json.load(f)
key = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "read" else sys.argv[1]
answer = answers.get(key) or answers.get("*") or {{"rc": 1, "stderr": "[ERROR] something this check does not recognise"}}
time.sleep(answer.get("sleep", 0))
sys.stderr.write(answer.get("stderr", ""))
sys.stdout.write(answer.get("stdout", ""))
sys.exit(answer.get("rc", 0))
'''


class FakeOp:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path = self.folder / "op"
        self.path.write_text(SCRIPT.format(python=sys.executable), encoding="utf-8")
        self.path.chmod(self.path.stat().st_mode | stat.S_IXUSR)
        self.answers = {}
        self._save()

    def _save(self):
        (self.folder / "answers.json").write_text(json.dumps(self.answers), encoding="utf-8")

    def answer(self, key, *, rc=0, stdout="", stderr="", sleep=0):
        self.answers[key] = {"rc": rc, "stdout": stdout, "stderr": stderr, "sleep": sleep}
        self._save()

    def calls(self):
        record = self.folder / "record.jsonl"
        if not record.exists():
            return []
        return [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines() if line]
