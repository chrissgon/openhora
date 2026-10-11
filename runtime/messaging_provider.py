# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The messaging bridge's access to a messenger provider (class messenger:<platform>, providers/messenger/README.md):
the four verbs as methods, started through providers/resolve.py, the one function that resolves a class and runs a
provider's verb. The bridge names no implementation: the class, and the platform as a parameter, choose it.

The neutral message is handed to the provider in a file of mode 0600 that is removed afterwards. The provider reads its
own credential; nothing here sees or passes one.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CAPABILITY_KEYS = {"max_text": int, "buttons": bool, "max_buttons": int, "max_button_label": int, "lists": bool,
                   "max_list_rows": int, "url_buttons": bool, "reply_context": bool, "documents": bool}
SEND_SECONDS = 60


class MessengerError(Exception):
    """A provider verb failed. `kind` is the resolver's word (usage, not-configured, failed, timeout)."""

    def __init__(self, kind: str, reason: str):
        super().__init__(f"{kind}: {reason}")
        self.kind, self.reason = kind, reason


def resolver(root: str = ROOT):
    path = os.path.join(root, "providers", "resolve.py")
    name = "workbench_messaging_resolve"
    module = sys.modules.get(name)
    if module is None or getattr(module, "__file__", None) != path:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


class Messenger:
    def __init__(self, platform: str, root: str = ROOT, implementation=None):
        self.platform, self.root, self.implementation = platform, root, implementation
        self.module = resolver(root)
        self._caps = None

    def _call(self, verb: str, args: list, timeout: int = SEND_SECONDS) -> dict:
        try:
            return self.module.call(f"messenger:{self.platform}", verb, ["--platform", self.platform, *args], root=self.root,
                                    implementation=self.implementation, timeout=timeout)
        except self.module.ProviderCallError as e:
            raise MessengerError(e.kind, e.stderr_tail or e.reason) from None

    def capabilities(self) -> dict:
        """The provider's capabilities, read once and checked: every key present with the right type."""
        if self._caps is None:
            found = self._call("capabilities", [])
            for key, kind in CAPABILITY_KEYS.items():
                if type(found.get(key)) is not kind:
                    raise MessengerError("failed", f"capabilities lacks {key}")
            self._caps = {key: found[key] for key in CAPABILITY_KEYS}
        return self._caps

    def receive(self, offset: int, timeout: int) -> dict:
        found = self._call("receive", ["--offset", str(int(offset)), "--timeout", str(int(timeout))], timeout=int(timeout) + 60)
        if not isinstance(found.get("updates"), list) or type(found.get("next_offset")) is not int:
            raise MessengerError("failed", "receive did not return updates and next_offset")
        return found

    def send(self, chat: str, message: dict) -> str:
        fd, path = tempfile.mkstemp(prefix="messenger-message-", suffix=".json")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(message, f)
            found = self._call("send", ["--chat", str(chat), "--message-file", path])
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        if not isinstance(found.get("message_id"), str):
            raise MessengerError("failed", "send did not return a message_id")
        return found["message_id"]

    def ack(self, action_ref: str) -> None:
        self._call("ack", ["--action-ref", str(action_ref)])
