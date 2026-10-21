"""lab.account_text (package ACCT-C; SPEC-ACCT-ROUTE sections 2.4 and 7): one call of a model on the maintainer's own account through the adapter's text
runner, with the once-per-process preflight, the credential that reaches the runner's environment alone, and a failure that is a code and nothing else.
The runner is a stand-in (`run` of account_text): no process, no model, no secret store, no network. The credential is a made-up string that a stand-in
lookup puts in the environment, as the store's lookup does. Every expected value is this file's own literal; each invariant has a vacuity case.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_lab_account_text.py
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import standin_tree as st

lab = st.load("lab")

REPO = Path(__file__).resolve().parents[2]
TOKEN_NAME = "CLAUDE_CODE_OAUTH_TOKEN"
TOKEN = "fictional-account-token-0001"  # security-scan: allow secret-assignment -- a made-up value that no service knows, to follow through the stand-in lookup
OTHER_KEY = "WB_RUNTIME_KEY_OPENROUTER_API_KEY"
SYSTEM_CANARY = "SYSTEM-CANARY-5d2e91b0"
USER_CANARY = "USER-CANARY-b81c44f7 with ünicode and a \"quote\"\nand a second line"
SONNET = next(r for r in json.loads((REPO / "runtime" / "interpreter_routes.json").read_text(encoding="utf-8"))["routes"] if r["id"] == "acct-claude-sonnet-5.5")
HAIKU = next(r for r in json.loads((REPO / "runtime" / "interpreter_routes.json").read_text(encoding="utf-8"))["routes"] if r["id"] == "acct-claude-haiku-4.5")
ENV_ALLOWED = {"PATH", "LANG", "HOME", "TMPDIR", TOKEN_NAME}      # the names the runner may be given, written out here
RUNNER_REPLY = {"v": 1, "text": "the reply", "finish": "stop", "usage": {"input": 11, "output": 7, "cache_read": 3, "cache_write": 5}, "latency_ms": 321,
                "runner_version": SONNET["runner_version"]}


def probe_reply(row=SONNET, **over):
    out = {"runner_version": row["runner_version"], "runner_sha256": row["runner_sha256"], "envelope_sha256": row["envelope_sha256"],
           "system_verbatim": True, "user_verbatim": True, "messages_requests": 1}
    out.update(over)
    return out


class Runner:
    """The stand-in for the process start of account_text: it records every start and answers the probe and the call."""

    def __init__(self, probe=None, reply=None, code=0, stderr="", delay=0.0, probe_code=0):
        self.starts, self.probe, self.reply, self.code, self.stderr, self.delay, self.probe_code = [], probe or {}, reply, code, stderr, delay, probe_code
        self.lock = threading.Lock()

    def __call__(self, argv, stdin, env, timeout):
        with self.lock:
            self.starts.append({"argv": list(argv), "stdin": stdin, "env": dict(env), "timeout": timeout})
        if "--probe" in argv:
            time.sleep(self.delay)
            body = self.probe if isinstance(self.probe, str) else json.dumps(self.probe if self.probe else probe_reply())
            return subprocess.CompletedProcess(argv, self.probe_code, body, "")
        if isinstance(self.reply, BaseException):
            raise self.reply
        body = self.reply if isinstance(self.reply, str) else json.dumps(RUNNER_REPLY if self.reply is None else self.reply)
        return subprocess.CompletedProcess(argv, self.code, "" if self.code else body, self.stderr)

    def probes(self):
        return [s for s in self.starts if "--probe" in s["argv"]]

    def calls(self):
        return [s for s in self.starts if "--probe" not in s["argv"]]


class Store:
    """The lab's own lookup in place of the OS secret store: like it, it puts the credential in the environment."""

    def __init__(self, value=TOKEN):
        self.value, self.lookups = value, 0

    def install(self, monkeypatch):
        real = lab._lab_call

        def lookup(function, *args, **kwargs):
            if getattr(function, "__name__", "") == "resolve_pass_env":
                self.lookups += 1
                if self.value:
                    for name in args[0]:
                        os.environ.setdefault(name, self.value)
                return []
            return real(function, *args, **kwargs)
        monkeypatch.setattr(lab, "_lab_call", lookup)
        return self


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    lab.reset_account_text()
    for name in (TOKEN_NAME, OTHER_KEY):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "home").mkdir()
    (tmp_path / "tmp").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.chdir(tmp_path)
    yield
    lab.reset_account_text()


@pytest.fixture
def store(monkeypatch):
    return Store().install(monkeypatch)


def call(runner, row=SONNET, system=SYSTEM_CANARY, user=USER_CANARY):
    return lab.account_text(row, system, user, run=runner)


# --- the preflight ---------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("key", ["runner_version", "runner_sha256", "envelope_sha256"])
def test_a_difference_in_the_preflight_is_e_route_with_one_start_the_probe_and_no_credential_looked_up(store, key):
    runner = Runner(probe=probe_reply(**{key: "run-text/1 cli/9.9.9" if key == "runner_version" else "f" * 64}))
    assert call(runner) == {"ok": False, "code": "E_ROUTE"}
    assert len(runner.starts) == 1 and len(runner.probes()) == 1 and runner.calls() == []
    assert store.lookups == 0 and TOKEN_NAME not in os.environ


def test_vacuity_the_same_probe_without_a_difference_goes_on_to_the_call(store):
    runner = Runner()
    got = call(runner)
    assert got["ok"] is True and len(runner.probes()) == 1 and len(runner.calls()) == 1 and store.lookups == 1


def test_the_probe_is_the_runners_with_the_rows_model_and_settings_and_no_credential(store):
    runner = Runner()
    call(runner)
    (probe,) = runner.probes()
    assert probe["argv"][0] == "bash" and probe["argv"][1].endswith(os.path.join("adapters", "claude-code", "run-text.sh"))
    assert probe["argv"][2:] == ["--probe", "--model", "claude-sonnet-5-5", "--max-tokens", "2000", "--reasoning", "low"]
    assert TOKEN_NAME not in probe["env"] and TOKEN not in json.dumps(probe) and probe["stdin"] == ""
    runner = Runner(probe=probe_reply(HAIKU))
    lab.reset_account_text()
    call(runner, row=HAIKU)
    assert runner.probes()[0]["argv"][2:] == ["--probe", "--model", "claude-haiku-4-5", "--max-tokens", "300", "--reasoning", "off"]


def test_the_preflight_runs_once_per_process_for_a_row_a_mismatch_included(store):
    runner = Runner()
    for _ in range(5):
        assert call(runner)["ok"] is True
    assert len(runner.probes()) == 1 and len(runner.calls()) == 5
    bad = Runner(probe=probe_reply(envelope_sha256="e" * 64))
    lab.reset_account_text()
    for _ in range(3):
        assert call(bad) == {"ok": False, "code": "E_ROUTE"}
    assert len(bad.probes()) == 1 and bad.calls() == []


def test_jobs_in_parallel_wait_for_the_one_preflight(store):
    runner = Runner(delay=0.15)
    results = []

    def work():
        results.append(call(runner)["ok"])
    threads = [threading.Thread(target=work) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert results == [True] * 6 and len(runner.probes()) == 1 and len(runner.calls()) == 6 and store.lookups == 1


def test_each_row_has_its_own_preflight(store):
    runner = Runner()
    call(runner)
    haiku_runner = Runner(probe=probe_reply(HAIKU))
    call(haiku_runner, row=HAIKU)
    assert len(runner.probes()) == 1 and len(haiku_runner.probes()) == 1


def test_a_probe_that_fails_or_is_not_json_is_e_route(store):
    failing = Runner(probe_code=3)
    assert call(failing) == {"ok": False, "code": "E_ROUTE"} and failing.calls() == []
    lab.reset_account_text()
    for body in ("not json", "[1]", "null"):
        assert call(Runner(probe=body)) == {"ok": False, "code": "E_ROUTE"}, body


def test_a_model_whose_adapter_declares_no_text_runner_is_e_route(store):
    deepseek = dict(copy.deepcopy(SONNET), lab_model="openrouter/deepseek/deepseek-v4.1-flash")
    runner = Runner()
    assert call(runner, row=deepseek) == {"ok": False, "code": "E_ROUTE"} and runner.starts == [] and store.lookups == 0


def test_a_lab_model_the_gate_file_does_not_list_is_e_route(store):
    runner = Runner()
    assert call(runner, row=dict(copy.deepcopy(SONNET), lab_model="model-the-gate-does-not-list")) == {"ok": False, "code": "E_ROUTE"} and runner.starts == []


# --- the credential ----------------------------------------------------------------------------------------------------------------

def test_the_credential_is_looked_up_once_and_reaches_the_call_environment_only(store, monkeypatch):
    monkeypatch.setenv(OTHER_KEY, "sk-or-v1-fictional-other-key")
    runner = Runner()
    call(runner)
    call(runner)
    assert store.lookups == 1
    (first, second) = runner.calls()
    for start in (first, second):
        assert start["env"][TOKEN_NAME] == TOKEN and set(start["env"]) <= ENV_ALLOWED and OTHER_KEY not in start["env"]
    assert TOKEN_NAME not in runner.probes()[0]["env"] and set(runner.probes()[0]["env"]) <= ENV_ALLOWED


def test_the_environment_of_the_process_is_put_back_whether_it_held_the_token_or_not(store, monkeypatch):
    call(Runner())
    assert TOKEN_NAME not in os.environ
    lab.reset_account_text()
    monkeypatch.setenv(TOKEN_NAME, "the-value-it-held-before")
    runner = Runner()
    call(runner)
    assert os.environ[TOKEN_NAME] == "the-value-it-held-before" and runner.calls()[0]["env"][TOKEN_NAME] == "the-value-it-held-before"


def test_a_lookup_that_overwrites_a_held_value_is_undone_too(monkeypatch):
    """The environment is restored whatever the lookup did to it: a lookup that replaces a value the process held leaves that value back."""
    real = lab._lab_call

    def overwriting(function, *args, **kwargs):
        if getattr(function, "__name__", "") == "resolve_pass_env":
            os.environ[TOKEN_NAME] = TOKEN
            return []
        return real(function, *args, **kwargs)
    monkeypatch.setattr(lab, "_lab_call", overwriting)
    monkeypatch.setenv(TOKEN_NAME, "the-value-it-held-before")
    runner = Runner()
    call(runner)
    assert runner.calls()[0]["env"][TOKEN_NAME] == TOKEN and os.environ[TOKEN_NAME] == "the-value-it-held-before"


def test_a_credential_that_is_not_found_is_e_key_after_the_probe_and_the_call_is_never_started():
    lab.reset_account_text()
    store = Store(value=None)
    mp = pytest.MonkeyPatch()
    try:
        store.install(mp)
        runner = Runner()
        assert call(runner) == {"ok": False, "code": "E_KEY"}
        assert len(runner.probes()) == 1 and runner.calls() == [] and store.lookups == 1 and TOKEN_NAME not in os.environ
    finally:
        mp.undo()


# --- the call ----------------------------------------------------------------------------------------------------------------------

def test_the_request_the_runner_reads_is_the_row_and_the_texts_and_nothing_is_in_the_arguments_or_the_environment(store):
    runner = Runner()
    got = call(runner)
    (start,) = runner.calls()
    assert json.loads(start["stdin"]) == {"v": 1, "system": SYSTEM_CANARY, "user": USER_CANARY, "max_tokens": 2000, "reasoning": "low", "deadline_ms": 60000}
    assert start["argv"][0] == "bash" and start["argv"][2:] == ["--model", "claude-sonnet-5-5"]
    assert start["timeout"] == 65.0
    flat = json.dumps(start["argv"]) + json.dumps(start["env"], sort_keys=True)
    assert SYSTEM_CANARY not in flat and "USER-CANARY" not in flat
    assert got == {"ok": True, "text": "the reply", "finish": "stop", "usage": {"input": 11, "output": 7, "cache_read": 3, "cache_write": 5}, "latency_ms": 321}


def test_the_haiku_row_asks_for_its_own_model_and_settings(store):
    runner = Runner(probe=probe_reply(HAIKU), reply=dict(RUNNER_REPLY, runner_version=HAIKU["runner_version"]))
    assert call(runner, row=HAIKU)["ok"] is True
    assert json.loads(runner.calls()[0]["stdin"])["max_tokens"] == 300 and json.loads(runner.calls()[0]["stdin"])["reasoning"] == "off"
    assert runner.calls()[0]["argv"][2:] == ["--model", "claude-haiku-4-5"]
    assert TOKEN_NAME in runner.calls()[0]["env"], "the Haiku row uses the credential of its lab_model, claude-sonnet-5-5"


@pytest.mark.parametrize("code", ["E_USAGE", "E_KEY", "E_ROUTE", "E_TIMEOUT", "E_RATE", "E_NETWORK", "E_UPSTREAM", "E_RESPONSE", "E_INTERNAL"])
def test_a_runner_failure_is_its_code_from_the_last_stderr_line_and_nothing_else(store, code):
    runner = Runner(code=1, stderr=f"run-text: {code}\n")
    assert call(runner) == {"ok": False, "code": code}


@pytest.mark.parametrize("stderr", ["", "run-text: E_BOGUS\n", f"trace: {USER_CANARY}\n", f"run-text: E_RATE and {USER_CANARY}\n", "E_RATE\n", "run-text: e_rate\n"])
def test_a_stderr_that_is_not_exactly_a_code_is_e_internal_and_none_of_it_is_returned(store, stderr):
    got = call(Runner(code=1, stderr=stderr))
    assert got == {"ok": False, "code": "E_INTERNAL"} and "CANARY" not in json.dumps(got)


def test_a_code_on_the_last_line_counts_when_earlier_lines_come_first(store):
    assert call(Runner(code=1, stderr="warning one\nrun-text: E_TIMEOUT\n")) == {"ok": False, "code": "E_TIMEOUT"}


def test_a_runner_that_runs_past_its_time_is_e_timeout(store):
    assert call(Runner(reply=subprocess.TimeoutExpired(["bash"], 65))) == {"ok": False, "code": "E_TIMEOUT"}


def test_a_runner_that_cannot_start_is_e_internal(store):
    assert call(Runner(reply=OSError("no bash"))) == {"ok": False, "code": "E_INTERNAL"}


@pytest.mark.parametrize("reply", ["not json", "[]", json.dumps({"v": 2, "text": "x", "finish": "stop", "usage": {}}),
                                   json.dumps({"v": 1, "text": 5, "finish": "stop", "usage": {}}), json.dumps({"v": 1, "text": "x", "finish": "done", "usage": {}}),
                                   json.dumps({"v": 1, "text": "x", "finish": "stop", "usage": "many"}), json.dumps({"v": 1, "finish": "stop", "usage": {}})],
                         ids=["text", "list", "version", "text-type", "finish", "usage", "no-text"])
def test_a_reply_that_is_not_the_contracts_is_e_response(store, reply):
    assert call(Runner(reply=reply)) == {"ok": False, "code": "E_RESPONSE"}


def test_a_runner_whose_version_changed_between_the_probe_and_the_call_is_e_route(store):
    assert call(Runner(reply=dict(RUNNER_REPLY, runner_version="run-text/1 cli/2.1.284"))) == {"ok": False, "code": "E_ROUTE"}


def test_the_usage_has_the_four_keys_and_only_those(store):
    got = call(Runner(reply=dict(RUNNER_REPLY, usage={"input": 1, "debug": "SECRET"})))
    assert got["usage"] == {"input": 1, "output": None, "cache_read": None, "cache_write": None}


def test_nothing_of_a_request_or_a_reply_is_written_or_printed_here(store, tmp_path, capsys):
    call(Runner())
    call(Runner(code=1, stderr=f"trace: {USER_CANARY}\n"))
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""
    hits = []
    for root, _dirs, files in os.walk(tmp_path):
        for name in files:
            data = (Path(root) / name).read_bytes()
            if b"USER-CANARY" in data or b"SYSTEM-CANARY" in data:
                hits.append(os.path.join(root, name))
    assert hits == []
    (tmp_path / "tmp" / "planted.txt").write_text(USER_CANARY)      # vacuity: the same walk finds a planted copy
    assert any(name == "planted.txt" for _root, _d, files in os.walk(tmp_path) for name in files if b"USER-CANARY" in (Path(_root) / name).read_bytes())


# --- the manifest -------------------------------------------------------------------------------------------------------------------

def test_the_lab_is_a_reader_of_the_account_token_in_the_manifest():
    manifest = json.loads((REPO / "adapters" / "claude-code" / "adapter.json").read_text(encoding="utf-8"))
    secret = next(s for s in manifest["secrets"] if s["name"] == TOKEN_NAME)
    assert "runtime/lab.py" in secret["readers"] and manifest["text_runner"] == "run-text.sh"
    assert manifest["text_files"] == ["run-text.sh", "run_text.py", "text_probe_stub.py"]


def test_the_text_runner_of_the_gate_models_adapter_is_the_script_the_manifest_names():
    path, names = lab._text_runner("claude-sonnet-5-5")
    assert path == str(REPO / "adapters" / "claude-code" / "run-text.sh") and names == [TOKEN_NAME] and os.path.isfile(path)
    with pytest.raises(lab.LabError):
        lab._text_runner("openrouter/deepseek/deepseek-v4.1-flash")
