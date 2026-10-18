"""What a second implementation of the class reader:email does to the choice of one (package M1): `"mailbox": "auto"` in a project's runtime.json
falls to "the only implementation shipped" (providers/resolve.py, rule 3), so with `gmail.py` and `outlook.py` both in providers/mailbox/ it no
longer resolves. The resolution exits 3 and its sentence names MAILBOX_PROVIDER; `"mailbox": "gmail"` (an implementation named by the project
configuration) keeps working. Nothing in the runtime changed to make this so, and these tests pin it, against the real providers/ folder of this
checkout: the maintainer sets `"mailbox": "gmail"` in the live social handler's runtime.json before this reaches main (providers/mailbox/README.md).

Run: uv run --with pytest==9.1.1 pytest providers/mailbox/tests/test_mailbox_resolution.py
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
RESOLVE = REPO / "providers" / "resolve.py"


def load(path: Path, name: str, monkeypatch):
    monkeypatch.syspath_prepend(str(path.parent))   # the handler and the tick load their neighbours by name
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def resolve():
    spec = importlib.util.spec_from_file_location("resolve_for_the_mailbox_tests", RESOLVE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def clean_env():
    return {k: v for k, v in os.environ.items() if not k.endswith("_PROVIDER")}


def test_both_readers_are_implementations_and_their_helpers_are_not(resolve):
    assert resolve.implementations("reader:email", root=REPO, env={}) == ["gmail", "outlook"]
    assert "outlook" in resolve.implementations("integration:calendar", root=REPO, env={})
    assert "outlook" not in resolve.implementations("integration:documents", root=REPO, env={}), "the OneDrive provider is not the calendar's"
    for helper in ("outlook_auth", "_msgraph", "auth"):
        assert helper not in resolve.implementations("reader:email", root=REPO, env={})


def test_auto_with_two_readers_exits_3_and_names_the_variable_to_set(resolve):
    with pytest.raises(resolve.Unresolved) as refused:
        resolve.resolve("reader:email", root=REPO, env={})
    message = str(refused.value)
    assert "MAILBOX_PROVIDER" in message and "gmail" in message and "outlook" in message and "none is selected" in message
    assert resolve.Unresolved.code == 3
    done = subprocess.run([sys.executable, str(RESOLVE), "--class", "reader:email", "--root", str(REPO)], capture_output=True, text=True,
                          timeout=60, env=clean_env())
    assert done.returncode == 3 and "MAILBOX_PROVIDER" in done.stderr and done.stdout == ""


def test_naming_the_implementation_keeps_working_whatever_the_environment_says(resolve):
    for name in ("gmail", "outlook"):
        found = resolve.resolve("reader:email", root=REPO, env={}, implementation=name)
        assert found["implementation"] == name and found["source"] == "configuration" and Path(found["path"]) == REPO / "providers" / "mailbox" / f"{name}.py"
    found = resolve.resolve("reader:email", root=REPO, env={"MAILBOX_PROVIDER": "gmail"})
    assert found["implementation"] == "gmail" and found["source"] == "environment"
    assert resolve.resolve("reader:email", root=REPO, env={"MAILBOX_PROVIDER": "outlook"}, implementation="gmail")["implementation"] == "gmail"


def test_the_social_tick_of_a_project_with_auto_fails_and_with_gmail_resolves(monkeypatch):
    for name in [n for n in os.environ if n.endswith("_PROVIDER")]:
        monkeypatch.delenv(name)
    for label, path in (("scripts_runtime_for_the_mailbox_tests", REPO / "scripts" / "runtime.py"),
                        ("social_handler_for_the_mailbox_tests", REPO / "runtime" / "handlers" / "social.py")):
        module = load(path, label, monkeypatch)
        providers = module.Providers(REPO)
        with pytest.raises(module.Fail) as refused:
            providers.path("reader:email", None)   # what `"mailbox": "auto"` asks
        assert refused.value.code == 3 and "MAILBOX_PROVIDER" in str(refused.value), label
        assert providers.path("reader:email", "gmail") == REPO / "providers" / "mailbox" / "gmail.py", label   # what `"mailbox": "gmail"` asks
        monkeypatch.setenv("MAILBOX_PROVIDER", "gmail")
        assert providers.path("reader:email", None) == REPO / "providers" / "mailbox" / "gmail.py", label
        monkeypatch.delenv("MAILBOX_PROVIDER")


def test_the_documents_that_tell_the_maintainer_say_what_to_set():
    readme = (REPO / "providers" / "mailbox" / "README.md").read_text(encoding="utf-8")
    assert '"mailbox": "gmail"' in readme and "MAILBOX_PROVIDER" in readme and "auto" in readme
    handler = (REPO / "runtime" / "handlers" / "social.py").read_text(encoding="utf-8")
    assert '"mailbox": "auto | none | <implementation>"' in handler, "the handler's own documentation of the key is unchanged"
