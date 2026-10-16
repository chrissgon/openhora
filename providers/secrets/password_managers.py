#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The password managers the secret resolver can read through (package S16): the fourth place a secret is looked up, after the
environment, the credentials directory and the OS secret store. Adopted, not built (principle 14): each backend calls the vendor's own
command-line tool and nothing else. 1Password (`op`) is the first; a second manager is one more class in BACKENDS and a word of the
mapping file's "backend", and neither the resolver's chain nor its callers change.

What every backend promises (the hard limit L39, contracts/runtime.md):
  - the tool is called only here, on the host, as a list of arguments (no shell), with stdin on /dev/null and a deadline;
  - it never signs in, adds an account or unlocks anything, and never touches the terminal: the person signs in (the desktop app's
    unlock, or a service account's token provided before the call);
  - it is never called inside an eval container (`WB_EVAL_CONTAINER` set): there the answer is "unavailable", with no call;
  - its environment is the minimum below, plus the backend's own token only when the resolver found it;
  - what the tool prints to stderr is read for fixed markers and then dropped: never shown, logged or put in an exception. stdout is
    the value and is at most 64 KiB; it is never printed here.

A backend has: `name`, `label`, `executable`, `token_name`, `token_store_username`, `reference_problem(ref)` / `reference_ok(ref)`,
`classify(returncode, stderr)`, `read(ref, env, timeout)`, `probe(env, timeout)` and `sentence(kind)`. `read` and `probe` return a
Result whose state is "found", "missing", "locked" or "unavailable".

Standard library only. Python 3.9 syntax.
"""
from __future__ import annotations

import os
import re
import subprocess
from collections import namedtuple

STDOUT_MAX = 64 * 1024
DEFAULT_TIMEOUT = 15
PROBE_TIMEOUT = 5
TIMEOUT_RANGE = (1, 60)
CONTAINER_VARIABLE = "WB_EVAL_CONTAINER"   # what the eval image sets; any non-empty value is read as "inside a run"
ENV_KEEP = ("PATH", "HOME", "USER", "LANG", "TMPDIR", "XDG_CONFIG_HOME", "XDG_RUNTIME_DIR")   # the minimum environment of a call

Result = namedtuple("Result", "state value")   # state: found | missing | locked | unavailable; value only when found


def in_container(environ=None) -> bool:
    """True when this process (or the environment it was given) is inside an eval container: a run never reaches a password manager."""
    return any((env.get(CONTAINER_VARIABLE) or "").strip() for env in (os.environ, environ or {}))


def minimum_environment(environ, token_name: str = "", token: str = "") -> dict:
    """The environment of a call: ENV_KEEP when set, and the backend's token only when one is given (the resolver found it itself)."""
    out = {k: environ[k] for k in ENV_KEEP if environ.get(k)}
    if token_name and token:
        out[token_name] = token
    return out


def _run(argv, env, timeout):
    """(returncode, stdout bytes, stderr bytes) of one call without a shell and without a terminal; or the strings "timeout" /
    "absent" / "refused" in place of the returncode when it did not run to the end. Nothing of the tool's text leaves this function
    except what the caller reads for markers."""
    if in_container():
        return "refused", b"", b""
    try:
        done = subprocess.run(argv, shell=False, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return "timeout", b"", b""
    except (OSError, ValueError):
        return "absent", b"", b""
    return done.returncode, done.stdout, done.stderr


class OnePassword:
    """1Password through its CLI, `op` (version 2). Sign-in is the person's: the desktop app integration (the app asks for the unlock),
    or a service account token provided as OP_SERVICE_ACCOUNT_TOKEN. Not supported: `op signin` sessions and a Connect server."""

    name = "1password"
    label = "1Password"
    executable = "op"
    token_name = "OP_SERVICE_ACCOUNT_TOKEN"
    token_store_username = "password-manager-1password"
    # The texts of `op` read for the state (lowercase, searched in the lowercase stderr). Only a marker of the first list is "missing":
    # anything the lists do not recognise is "unavailable", never "missing" (a failure that is not understood must not read as
    # an absent secret, finding I3). Checked against the vendor's documentation or a public report: see docs/architecture/platform/
    # unattended.md, "Use with 1Password". Most of these texts are TO VERIFY against a real `op` before the first use on a machine.
    MISSING_MARKERS = ("isn't an item in the", "isn't a vault in this account", "isn't a field", "does not have a field")
    LOCKED_MARKERS = ("not signed in", "not currently signed in", "sign in", "authorization prompt dismissed", "authorization timeout",
                      "authorization denied", "couldn't connect to the 1password desktop app", "is locked",
                      "session expired", "service account token", "unauthorized")
    NAME_PART = re.compile(r"[A-Za-z0-9._ -]+")   # what the vendor allows in a name; anything else must be written as the item's ID
    REFERENCE_MAX = 256

    def __init__(self, account: str = ""):
        self.account = account or ""

    # -- the reference ---------------------------------------------------------------------------------------------------------

    @classmethod
    def reference_problem(cls, ref) -> str:
        """Why `ref` is not a reference `op read` may be given, or "": op://<vault>/<item>[/<section>]/<field>, each part non-empty and
        made of letters, digits, spaces, hyphens, underscores and periods (the vendor's documented set; a name with other characters is
        written as its ID), no query (`?`), no variable, nothing before `op://`, so that nothing can read as an option."""
        if not isinstance(ref, str) or not ref:
            return "is empty"
        if len(ref) > cls.REFERENCE_MAX:
            return f"is longer than {cls.REFERENCE_MAX} characters"
        if not ref.startswith("op://"):
            return "does not start with op://"
        parts = ref[len("op://"):].split("/")
        if len(parts) not in (3, 4):
            return "is not op://<vault>/<item>/<field> or op://<vault>/<item>/<section>/<field>"
        for part in parts:
            if not part or part != part.strip():
                return "has an empty part, or a part that starts or ends with a space"
            if not cls.NAME_PART.fullmatch(part):
                return "has a character the vendor allows only through an ID (use letters, digits, spaces, - _ .; no ?, $ or control character)"
        return ""

    @classmethod
    def reference_ok(cls, ref) -> bool:
        return cls.reference_problem(ref) == ""

    @staticmethod
    def account_problem(account) -> str:
        """Why `account` (a sign-in address or shorthand) cannot follow --account, or ""."""
        if not isinstance(account, str) or not account:
            return "must be a non-empty text"
        if len(account) > 255 or account.startswith("-") or any(ord(c) < 32 or ord(c) == 127 or c.isspace() for c in account):
            return "must be at most 255 characters, not start with a hyphen and hold no space or control character"
        return ""

    # -- the calls -------------------------------------------------------------------------------------------------------------

    def classify(self, returncode, stderr) -> str:
        """The state a failed call means: "missing" (the item or field does not exist), "locked" (not signed in, locked, the prompt
        dismissed) or "unavailable" (anything else). `stderr` is read here and nowhere else."""
        text = stderr.decode("utf-8", errors="replace").lower() if isinstance(stderr, (bytes, bytearray)) else str(stderr or "").lower()
        if any(m in text for m in self.MISSING_MARKERS):
            return "missing"
        if any(m in text for m in self.LOCKED_MARKERS):
            return "locked"
        return "unavailable"

    def _executable(self, env) -> str:
        """The tool on the PATH of the minimum environment, as an absolute path, or "". A relative entry of the PATH (an empty one, ".")
        is skipped, so a file named like the tool in the working folder is never started."""
        for folder in (env.get("PATH") or "").split(os.pathsep):
            if not folder or not os.path.isabs(folder):
                continue
            candidate = os.path.join(folder, self.executable)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        return ""

    def argv(self, exe: str, *words: str) -> list:
        return [exe, *words] + (["--account", self.account] if self.account else [])

    def read(self, reference: str, env: dict, timeout: float = DEFAULT_TIMEOUT) -> Result:
        """`op read <reference> [--account <a>]`. found (the value, stripped), missing, locked or unavailable. The reference is checked
        again here, so that a caller that skipped the check still cannot pass an option."""
        if not self.reference_ok(reference):
            return Result("unavailable", "")
        exe = self._executable(env)
        if not exe:
            return Result("unavailable", "")
        code, out, err = _run(self.argv(exe, "read", reference), env, timeout)
        if code == "timeout":
            return Result("locked", "")   # the unlock prompt was left unanswered
        if code in ("absent", "refused"):
            return Result("unavailable", "")
        if code != 0:
            return Result(self.classify(code, err), "")
        if len(out) > STDOUT_MAX:
            return Result("unavailable", "")
        value = out.decode("utf-8", errors="replace").strip()
        return Result("found", value) if value else Result("missing", "")

    def probe(self, env: dict, timeout: float = PROBE_TIMEOUT) -> Result:
        """`op whoami`: whether the tool is installed and signed in. No secret is read. found (value "") | locked | unavailable."""
        exe = self._executable(env)
        if not exe:
            return Result("unavailable", "")
        code, _, err = _run(self.argv(exe, "whoami"), env, timeout)
        if code == "timeout":
            return Result("locked", "")
        if code in ("absent", "refused"):
            return Result("unavailable", "")
        if code == 0:
            return Result("found", "")
        kind = self.classify(code, err)
        return Result("unavailable" if kind == "missing" else kind, "")

    def sentence(self, kind: str) -> str:
        """The sentence a message shows for a failing manager: its name and the fix. Never a text of the tool."""
        if kind == "locked":
            return (f"the password manager ({self.label}) is locked or not signed in: unlock the app, or on a headless machine provide "
                    f"{self.token_name} in the credentials directory (docs/architecture/platform/unattended.md). The secret may be stored; "
                    "it cannot be read now")
        return (f"the password manager ({self.label}) cannot be used: its tool `{self.executable}` is not installed or not on the PATH, or "
                "it failed in a way this check does not recognise (docs/architecture/platform/unattended.md). The secret may be stored; "
                "it cannot be read now")


BACKENDS = {OnePassword.name: OnePassword}


if __name__ == "__main__":
    print(__doc__)
