"""One process of the cross-process tests of the Microsoft records' lock (test_account_microsoft_lock.py). Not a test file: it is started with
`python3 lock_worker.py '<json config>'` and prints one JSON object.

A worker uses providers/_msgraph.py for real (its lock, its comparison, its write-back) against a file-backed stand-in for the OS secret store,
so that two workers are two processes that really share a record. The stand-in's write is slow on purpose (`delay`) and says when it began
(`events/<name>-writing`), so that a test can act in the window between a process's comparison and its write.

modes:
  rotate     load the record, refresh it against the stand-in token endpoint, say `<name>-refreshed`, wait for `events/go`, then store_rotation.
  forget     msgraph.forget on the stand-in store.
  write      msgraph.write_record of the text in `text` (what a new authorization does with its record).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

config = json.loads(sys.argv[1])
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("msgraph_in_a_worker", HERE.parents[1] / "_msgraph.py")
msgraph = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = msgraph
spec.loader.exec_module(msgraph)
if "lock_timeout" in config:
    msgraph.LOCK_TIMEOUT_SECONDS = config["lock_timeout"]

STORE, EVENTS, NAME = Path(config["store"]), Path(config["events"]), config["name"]
USERNAME = "microsoft-account"
PROFILE = msgraph.account_profile(run_hint="uv run x", env_prefix="ACCOUNT_MICROSOFT", user_agent="openhora-test", not_found="nf", forbidden_hint="fh")


class PasswordDeleteError(Exception):
    pass


class FileStore:
    """A secret store that lives in a file, so that several processes share it; its write is slow and says when it began."""

    def read(self) -> dict:
        try:
            return json.loads(STORE.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}

    def write(self, data: dict) -> None:
        temporary = STORE.with_suffix(".tmp-" + NAME)
        temporary.write_text(json.dumps(data), encoding="utf-8")
        os.replace(temporary, STORE)

    def set_password(self, service, username, value):
        (EVENTS / f"{NAME}-writing").write_text("1")
        time.sleep(config.get("delay", 0))
        data = self.read()
        data[username] = value
        self.write(data)
        with open(EVENTS / "writes.log", "a", encoding="utf-8") as log:
            log.write(f"{NAME} {json.loads(value).get('refresh_token')}\n")

    def delete_password(self, service, username):
        data = self.read()
        if username not in data:
            raise PasswordDeleteError("not found")
        del data[username]
        self.write(data)


class Resolver:
    def resolve(self, name, allow_store=True):
        value = FileStore().read().get(USERNAME)
        return None if value is None else (value, "secret store")


class Provider:
    """What msgraph.forget looks up on a provider."""

    @staticmethod
    def endpoints():
        return "http://127.0.0.1:1", None, (), False

    @staticmethod
    def keyring_module(test_mode):
        return FileStore()


def wait_for(path: Path, seconds: float = 30) -> None:
    deadline = time.monotonic() + seconds
    while not path.exists():
        if time.monotonic() > deadline:
            raise SystemExit(f"{NAME}: timed out waiting for {path.name}")
        time.sleep(0.02)


def main() -> dict:
    mode = config["mode"]
    if mode == "rotate":
        record = msgraph.parse_account_record(PROFILE, FileStore().read()[USERNAME])
        _, rotated = msgraph.refresh_access_token(PROFILE, config["token_url"], record)
        (EVENTS / f"{NAME}-refreshed").write_text("1")
        wait_for(EVENTS / "go")
        outcome = msgraph.store_rotation(PROFILE, record, rotated, "secret store", False, lambda: Resolver(), lambda test_mode: FileStore())
        return {"name": NAME, "outcome": outcome, "rotated": rotated}
    if mode == "forget":
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                code = msgraph.forget(PROFILE, Provider)
            except msgraph.ProviderError as exc:
                return {"name": NAME, "code": exc.code, "error": str(exc)}
        return {"name": NAME, "code": code}
    if mode == "write":
        try:
            msgraph.write_record(PROFILE, FileStore(), config["text"])
        except msgraph.ProviderError as exc:
            return {"name": NAME, "code": exc.code, "error": str(exc)}
        return {"name": NAME, "code": 0}
    raise SystemExit(f"unknown mode {mode}")


print(json.dumps(main()))
