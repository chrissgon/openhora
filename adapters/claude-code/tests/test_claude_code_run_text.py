"""Tests for run-text.sh, the text contract of this adapter, with a stand-in `claude` on PATH. No model is called, no credential is
read: the token is a made-up string, and the probe talks to the loopback stub only. The stand-in is a Python script whose mode is
a file beside it (the runner passes it no variable of ours), and it records what the runner gave it.

Every invariant is checked by an oracle that reads the raw input with this file's own literal lists, never the runner's tables,
and each oracle has a vacuity case: a planted fault it must catch.

Run: uv run --with pytest pytest adapters/claude-code/tests/test_claude_code_run_text.py
"""
from __future__ import annotations

import errno
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

ADAPTER = Path(__file__).resolve().parents[1]
REPO = ADAPTER.parents[1]
SCRIPT = ADAPTER / "run-text.sh"
TOKEN = "fake-token-for-the-text-runner-0001"
SYSTEM_CANARY = "SYSTEM-CANARY-41f0c2a9"
USER_CANARY = "USER-CANARY-7d3be855 with ünicode and a quote \" and a newline\nsecond line"

# What the CLI may be given (the spec's closed list), written out here and not read from the runner.
ENV_NAMES = {"PATH", "HOME", "LANG", "TMPDIR", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_MAX_OUTPUT_TOKENS",
             "DISABLE_AUTOUPDATER", "DISABLE_TELEMETRY", "DISABLE_ERROR_REPORTING", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
             "ENABLE_CLAUDEAI_MCP_SERVERS"}
PROBE_ENV_NAMES = {"ANTHROPIC_BASE_URL", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"}
INTERPRETER_NAMES = {"__CF_USER_TEXT_ENCODING", "LC_CTYPE"}   # a Python stand-in may gain these from the system itself
DECOYS = ("WB_RUNTIME_KEY_OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY")
# The probe texts, written out here and not read from the runner: a change of the runner's texts must fail this file.
# Each probe puts a fresh 16-hex-digit nonce where {nonce} stands.
SYSTEM_TEMPLATE_T = "probe system text alpha {nonce}\nsecond line: a\u00e7\u00e3o \u2014 \u00fcn\u00ef\u00e7ode\n  indented third line  \n"
USER_TEMPLATE_T = ("\n  \r\n/x first line  \r\n!bang\n#hash\n@bia ana.lima@mail.example said \"hi\"\n"
                   "cafe\u0301 a\u00e7\u00e3o \u65e5\u672c\u8a9e probe-user-{nonce}\n\n  last line, trailing spaces   \n\n")
NONCE_T = "0123456789abcdef"
PROBE_SYSTEM_TEXT = SYSTEM_TEMPLATE_T.replace("{nonce}", NONCE_T)
PROBE_USER_TEXT = USER_TEMPLATE_T.replace("{nonce}", NONCE_T)


def nonce_of(user_text):
    found = re.search(r"probe-user-([0-9a-f]{16})\n", user_text)
    assert found, "no nonce in the user text"
    return found.group(1)
NEVER_IN_ARGV = ["--dangerously-skip-permissions", "--add-dir", "--append-system-prompt", "--resume", "--continue", "--bare"]
FAKE = r"""#!%(python)s
import json, os, stat, subprocess, sys, time, urllib.request
D = %(dir)r
args = sys.argv[1:]
conf = json.load(open(D + "/mode.json")) if os.path.exists(D + "/mode.json") else {}
mode = conf.get("mode", "answer")
if args == ["--version"]:
    time.sleep(conf.get("version_sleep", 0))
    print("2.1.283 (Claude Code)")
    sys.exit(0)
stdin = sys.stdin.read()
cfg = os.environ.get("CLAUDE_CONFIG_DIR", "")
with open(D + "/calls.jsonl", "a") as f:
    f.write(json.dumps({"pid": os.getpid(), "argv": args, "env": sorted(os.environ), "token": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"),
                        "values": {k: v for k, v in os.environ.items() if k in conf.get("show", [])}, "stdin": stdin,
                        "cwd": os.getcwd(), "cfg": cfg, "cfg_mode": stat.S_IMODE(os.stat(cfg).st_mode) if cfg else None,
                        "cwd_mode": stat.S_IMODE(os.stat(".").st_mode), "cwd_listing": sorted(os.listdir(".")),
                        "cfg_listing": sorted(os.listdir(cfg)) if cfg else None}) + "\n")

def reply(text="the reply", stop="end_turn", out=7, error=False, extra=None, usage=None):
    usage = usage or {"input_tokens": 11, "output_tokens": out, "cache_read_input_tokens": 3, "cache_creation_input_tokens": 5}
    obj = {"type": "result", "subtype": "success", "is_error": error, "result": text, "usage": usage}
    if stop is not None:
        obj["stop_reason"] = stop
    obj.update(extra or {})
    print(json.dumps(obj))

if mode == "answer":
    reply(conf.get("text", "the reply"), conf.get("stop", "end_turn"), conf.get("out", 7))
elif mode == "events":
    print(json.dumps([{"type": "system"}, {"type": "result", "result": "from a list", "usage": {"input_tokens": 1, "output_tokens": 2},
                                           "stop_reason": "end_turn"}]))
elif mode == "leak":
    open(os.path.join(os.environ["HOME"], "leak.txt"), "w").write(stdin)
    reply()
elif mode == "stderr_canary":
    sys.stderr.write("trace: " + stdin + " | " + " ".join(args) + "\n")
    sys.exit(1)
elif mode == "limit":
    print(json.dumps({"type": "result", "subtype": "success", "is_error": True, "api_error_status": 429, "result": ""}))
    sys.exit(1)
elif mode == "limit_text":
    sys.stdout.write("You've hit your weekly limit · resets Oct 9\n")
    sys.exit(1)
elif mode == "limit_reply":
    reply("You've hit your limit is a phrase a user quoted", out=9)
elif mode == "auth":
    sys.stderr.write("Invalid API key · Please run /login\n")
    sys.exit(1)
elif mode == "network":
    sys.stderr.write("fetch failed: ECONNREFUSED\n")
    sys.exit(1)
elif mode == "upstream":
    print(json.dumps({"type": "result", "is_error": True, "api_error_status": 529, "result": "overloaded_error"}))
    sys.exit(1)
elif mode == "badjson":
    print("this is not json")
elif mode == "noresult":
    print(json.dumps({"type": "result", "is_error": False, "usage": {"input_tokens": 1, "output_tokens": 1}}))
elif mode == "empty":
    reply("   ")
elif mode == "nousage":
    print(json.dumps({"type": "result", "is_error": False, "result": "x"}))
elif mode == "crash":
    sys.exit(3)
elif mode == "hang":
    child = subprocess.Popen(["sleep", "60"])
    open(D + "/child.pid", "w").write(str(child.pid))
    time.sleep(60)
elif mode == "escaper":
    code = "import os,time; open(%%r,'w').write(str(os.getpid())); os.setsid(); time.sleep(40)" %% (D + "/escaper.pid")
    subprocess.Popen([sys.executable, "-c", code])   # leaves the group and keeps this process's stdout and stderr
    time.sleep(120)
elif mode == "leave":
    child = subprocess.Popen(["sleep", "60"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    open(D + "/child.pid", "w").write(str(child.pid))
    reply()
elif mode == "http":
    base = os.environ["ANTHROPIC_BASE_URL"]
    model = args[args.index("--model") + 1]
    system = args[args.index("--system-prompt") + 1]
    blocks = [{"type": "text", "text": system}]
    if conf.get("extra_system"):
        blocks.insert(0, {"type": "text", "text": "x" * conf["extra_system"]})
    if conf.get("trim_user"):
        stdin = stdin.strip()
    if conf.get("crlf_user"):
        stdin = stdin.replace("\r\n", "\n")
    if conf.get("nfc_user"):
        import unicodedata
        stdin = unicodedata.normalize("NFC", stdin)
    user = [{"type": "text", "text": stdin}]
    if conf.get("inject"):
        import random
        user.append({"type": "text", "text": "cwd: %%s Today's date is 2026-%%02d-%%02d. at 2026-05-%%02dT07:08:09Z" %%
                     (os.getcwd(), random.randint(1, 12), random.randint(1, 28), random.randint(1, 28))})
    if conf.get("outside_path"):
        open(conf["outside_path"], "w").write(stdin)
    if conf.get("outside_escaped"):
        open(conf["outside_escaped"], "w").write(json.dumps({"text": stdin}))
    if conf.get("outside_unrelated"):
        open(conf["outside_unrelated"], "w").write(conf.get("outside_text", "another session's log"))
    if conf.get("outside_unreadable"):
        open(conf["outside_unreadable"], "w").write("something")
        os.chmod(conf["outside_unreadable"], 0)
    if conf.get("deep_under"):
        deep = os.path.join(conf["deep_under"], "l1", "l2", "l3", "l4", "l5")
        os.makedirs(deep)
        open(os.path.join(deep, "leaf.txt"), "w").write("x")
    if conf.get("echo"):
        import re as _re
        user.append({"type": "text", "text": "you said " + _re.search(r"probe-user-[0-9a-f]{16}", stdin).group(0) + " and more"})
    if conf.get("slug_under"):
        import re
        slug_dir = os.path.join(conf["slug_under"], re.sub(r"[^A-Za-z0-9]", "-", os.getcwd()))
        os.makedirs(slug_dir)
        open(slug_dir + "/session.jsonl", "w").write("{}")
    if conf.get("extra_user"):
        user.append({"type": "text", "text": "r" * conf["extra_user"]})
    if conf.get("merge_user"):
        user = [{"type": "text", "text": stdin + "\n<reminder>"}]
    body = {"model": model, "max_tokens": int(os.environ["CLAUDE_CODE_MAX_OUTPUT_TOKENS"]), "system": blocks,
            "messages": [{"role": "user", "content": user}], "stream": True, "metadata": {"user_id": "user_" + str(os.getpid())},
            "thinking": {"type": "disabled"} if os.environ.get("MAX_THINKING_TOKENS") == "0" else {"type": "enabled", "budget_tokens": 1024}}
    if "--effort" in args:
        body["output_config"] = {"effort": args[args.index("--effort") + 1]}
    if conf.get("unstable"):
        body["nonce"] = str(time.time())
    for _ in range(conf.get("requests", 1)):
        req = urllib.request.Request(base + "/v1/messages?beta=true", data=json.dumps(body).encode(), method="POST",
                                     headers={"content-type": "application/json", "anthropic-beta": "beta-b, beta-a",
                                              "authorization": "Bearer " + conf.get("credential", os.environ["CLAUDE_CODE_OAUTH_TOKEN"])})
        urllib.request.urlopen(req, timeout=20).read()
    if conf.get("other_path"):
        urllib.request.urlopen(base + "/api/hello", timeout=20).read()
    stub_usage = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    if conf.get("noresult"):
        print(json.dumps({"type": "result", "is_error": False, "answer": "probe-ok", "usage": stub_usage}))
    else:
        reply(conf.get("text", "probe-ok"), "end_turn", usage=conf.get("usage", stub_usage))
else:
    sys.exit(9)
"""


@pytest.fixture
def e(tmp_path):
    bin_dir, fake_dir = tmp_path / "bin", tmp_path / "fake"
    for d in (bin_dir, fake_dir, tmp_path / "home", tmp_path / "tmp"):
        d.mkdir()
    (bin_dir / "claude").write_text(FAKE % {"python": sys.executable, "dir": str(fake_dir)})
    (bin_dir / "claude").chmod(0o755)
    tools = os.pathsep.join(dict.fromkeys(str(Path(shutil.which(t)).parent) for t in ("python3", "bash", "sleep")))
    if shutil.which("claude", path=tools):
        pytest.skip("a real claude CLI sits next to python3; this test must not be able to reach it")
    for d in ("base", "outside"):
        (tmp_path / d).mkdir()
    env = {"PATH": f"{bin_dir}{os.pathsep}{tools}{os.pathsep}/usr/bin{os.pathsep}/bin", "HOME": str(tmp_path / "home"),
           "TMPDIR": str(tmp_path / "tmp"), "LANG": "en_US.UTF-8", "CLAUDE_CODE_OAUTH_TOKEN": TOKEN,
           "ANTHROPIC_BASE_URL": "http://decoy.example:1", "HTTPS_PROXY": "http://decoy.example:2", "RUN_TEXT_TEST": "1",
           "RUN_TEXT_BASE": str(tmp_path / "base"), "RUN_TEXT_OUTSIDE": str(tmp_path / "outside")}
    for name in DECOYS:   # variables of the caller's, none of which may reach the CLI
        env[name] = "decoy-value-of-" + name.lower()
    assert shutil.which("claude", path=env["PATH"]) == str(bin_dir / "claude")
    return {"tmp": tmp_path, "fake": fake_dir, "env": env}


def base_of(e):
    return e["tmp"] / "base"


def mode(e, name="answer", **more):
    (e["fake"] / "mode.json").write_text(json.dumps({"mode": name, **more}))


def request(**over):
    req = {"v": 1, "system": "You read one line.", "user": "hello there", "max_tokens": 300, "reasoning": "off", "deadline_ms": 20000}
    req.update(over)
    return req


def run(e, req=None, *args, env=None, raw=None, timeout=90):
    cmd = ["bash", str(SCRIPT), *(args or ["--model", "model-a"])]
    data = raw if raw is not None else json.dumps(req if req is not None else request())
    return subprocess.run(cmd, input=data, capture_output=True, text=True, env={**e["env"], **(env or {})}, timeout=timeout)


def calls(e):
    path = e["fake"] / "calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def find_text(roots, needle):
    """Every file under the roots that holds the needle (utf-8 bytes), the oracle for 'written nowhere'."""
    hits, raw = [], needle.encode("utf-8")
    for root in roots:
        for here, _dirs, files in os.walk(root):
            for name in files:
                try:
                    if raw in Path(here, name).read_bytes():
                        hits.append(str(Path(here, name)))
                except OSError:
                    pass
    return hits


def argv_problems(argv, reasoning):
    """What is wrong with the CLI's argv, by the spec's literal list."""
    bad = []
    for need in ("-p", "--system-prompt", "--tools", "--no-session-persistence", "--disable-slash-commands", "--strict-mcp-config",
                 "--setting-sources"):
        if need not in argv:
            bad.append("missing " + need)
    if "--tools" in argv and argv[argv.index("--tools") + 1] != "":
        bad.append("--tools is not followed by the empty string")
    if "--setting-sources" in argv and argv[argv.index("--setting-sources") + 1] != "project,local":
        bad.append("setting sources")
    if ("--effort" in argv) != (reasoning != "off") or ("--effort" in argv and argv[argv.index("--effort") + 1] != reasoning):
        bad.append("effort")
    bad += ["forbidden " + f for f in NEVER_IN_ARGV if f in argv]
    return bad


# ----------------------------------------------------------------------------------------------------------- the command

@pytest.mark.parametrize("reasoning", ["off", "low", "high"])
def test_the_command_has_the_listed_flags_and_none_of_the_forbidden_ones(e, reasoning):
    res = run(e, request(reasoning=reasoning))
    assert res.returncode == 0, res.stderr
    (call,) = calls(e)
    assert argv_problems(call["argv"], reasoning) == []
    assert call["argv"][call["argv"].index("--model") + 1] == "model-a"
    assert call["argv"][call["argv"].index("--system-prompt") + 1] == "You read one line."
    assert call["argv"][call["argv"].index("--output-format") + 1] == "json"
    assert call["stdin"] == "hello there"


def test_the_oracle_of_the_command_catches_a_planted_fault():
    good = ["claude", "-p", "--system-prompt", "s", "--tools", "", "--no-session-persistence", "--disable-slash-commands",
            "--strict-mcp-config", "--setting-sources", "project,local"]
    assert argv_problems(good, "off") == []
    assert argv_problems(good + ["--append-system-prompt", "x"], "off") == ["forbidden --append-system-prompt"]
    assert argv_problems(good, "low") == ["effort"]
    assert argv_problems(good + ["--effort", "low"], "off") == ["effort"]
    assert "--tools is not followed by the empty string" in argv_problems(
        [a if a != "" else "Read" for a in good], "off")


def test_the_environment_of_the_cli_is_the_closed_list_and_carries_nothing_of_the_callers(e):
    res = run(e, request(max_tokens=1234, reasoning="off"))
    assert res.returncode == 0, res.stderr
    (call,) = calls(e)
    names = set(call["env"]) - INTERPRETER_NAMES
    assert names == ENV_NAMES | {"MAX_THINKING_TOKENS"}
    assert call["token"] == TOKEN
    res = run(e, request(max_tokens=1234, reasoning="low"))
    names = set(calls(e)[-1]["env"]) - INTERPRETER_NAMES
    assert names == ENV_NAMES
    mode(e, show=["MAX_THINKING_TOKENS", "CLAUDE_CODE_MAX_OUTPUT_TOKENS", "ENABLE_CLAUDEAI_MCP_SERVERS", "DISABLE_TELEMETRY", "HOME",
                  "TMPDIR", "LANG"])
    run(e, request(max_tokens=1234, reasoning="off"))
    got = calls(e)[-1]
    home, tmpdir = got["values"].pop("HOME"), got["values"].pop("TMPDIR")
    assert got["values"] == {"MAX_THINKING_TOKENS": "0", "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "1234", "LANG": "en_US.UTF-8",
                             "ENABLE_CLAUDEAI_MCP_SERVERS": "false", "DISABLE_TELEMETRY": "1"}
    # HOME and TMPDIR are folders of the temporary root, not the caller's: a file the CLI writes there goes with the root
    assert Path(home).parent == Path(got["cwd"]).parent == Path(tmpdir).parent
    assert Path(home) != e["tmp"] / "home" and Path(tmpdir) != e["tmp"] / "tmp"


def test_the_cli_runs_in_a_fresh_working_folder_and_configuration_folder(e):
    run(e)
    (call,) = calls(e)
    assert call["cwd_listing"] == [] and call["cfg_listing"] == []
    assert call["cfg_mode"] == 0o700 and call["cwd_mode"] == 0o700
    assert Path(call["cfg"]).parent == Path(call["cwd"]).parent
    assert Path(call["cfg"]).parent.parent.resolve() == base_of(e).resolve()   # the fixed base, not the caller's TMPDIR
    assert not Path(call["cfg"]).exists() and not Path(call["cwd"]).exists()
    assert list(base_of(e).iterdir()) == [] and list((e["tmp"] / "tmp").iterdir()) == []


# -------------------------------------------------------------------------------------------------------- the disk canary

def test_nothing_of_the_system_the_line_or_the_reply_is_written_and_the_line_is_exact_on_stdin(e):
    mode(e, text="reply with " + USER_CANARY)
    res = run(e, request(system=SYSTEM_CANARY, user=USER_CANARY), env={"RUN_TEXT_KEEP_TMP": "1"})
    assert res.returncode == 0, res.stderr
    (call,) = calls(e)
    assert call["stdin"] == USER_CANARY                                   # byte-exact
    assert USER_CANARY.encode("utf-8") not in " ".join(call["argv"]).encode("utf-8")
    assert "CANARY-7d3be855" not in " ".join(call["argv"])
    assert SYSTEM_CANARY in call["argv"]                                  # the system text is in argv, by design
    kept = [p for p in base_of(e).iterdir() if p.name.startswith("run-text-")]
    assert len(kept) == 1 and stat.S_IMODE(kept[0].stat().st_mode) == 0o700   # the kept root exists, so the scan below is not empty
    roots = [e["tmp"] / "home", e["tmp"] / "tmp", kept[0]]
    assert find_text(roots, "CANARY-7d3be855") == [] and find_text(roots, "CANARY-41f0c2a9") == []
    assert json.loads(res.stdout)["text"].startswith("reply with USER-CANARY")
    assert res.stderr == ""


def test_the_disk_oracle_catches_a_planted_leak(e):
    mode(e, "leak")
    run(e, request(user=USER_CANARY), env={"RUN_TEXT_KEEP_TMP": "1"})
    hits = find_text([e["tmp"] / "home", e["tmp"] / "tmp", base_of(e)], "CANARY-7d3be855")   # the CLI's home is a folder of the kept root
    assert len(hits) == 1 and hits[0].startswith(str(base_of(e) / "run-text-")) and hits[0].endswith("/home/leak.txt")


def test_without_the_keep_flag_nothing_stays_and_the_flag_is_ignored_outside_a_test(e, monkeypatch):
    run(e, env={"RUN_TEXT_KEEP_TMP": "1"})
    assert len(list(base_of(e).iterdir())) == 1
    shutil.rmtree(base_of(e))
    base_of(e).mkdir()
    assert run(e).returncode == 0 and list(base_of(e).iterdir()) == []
    runner = load_runner()                                                  # outside a test the keep flag does nothing
    folder = e["tmp"] / "would-be-kept"
    folder.mkdir()
    monkeypatch.delenv("RUN_TEXT_TEST", raising=False)
    monkeypatch.setenv("RUN_TEXT_KEEP_TMP", "1")
    runner.remove_root(str(folder))
    assert not folder.exists()


def test_the_clis_stderr_is_never_forwarded(e):
    mode(e, "stderr_canary")
    res = run(e, request(system=SYSTEM_CANARY, user=USER_CANARY))
    assert res.returncode == 1 and res.stdout == ""
    assert res.stderr == "run-text: E_INTERNAL\n"
    assert "CANARY" not in res.stderr + res.stdout


# ------------------------------------------------------------------------------------------------------------- the reply

def test_a_reply_has_exactly_the_keys_of_the_contract_and_its_figures_come_from_the_cli(e):
    res = run(e, request(max_tokens=300))
    assert res.returncode == 0 and res.stderr == ""
    out = json.loads(res.stdout)
    assert set(out) == {"v", "text", "finish", "usage", "latency_ms", "runner_version"}
    assert out["v"] == 1 and out["text"] == "the reply" and out["finish"] == "stop"
    assert out["usage"] == {"input": 11, "output": 7, "cache_read": 3, "cache_write": 5}
    assert type(out["latency_ms"]) is int and 0 <= out["latency_ms"] < 60000
    assert out["runner_version"] == "run-text/1 cli/2.1.283"
    assert res.stdout.count("\n") == 1 and res.stdout.endswith("\n")


@pytest.mark.parametrize("conf,expected", [
    ({"stop": "end_turn"}, "stop"), ({"stop": "stop_sequence"}, "stop"), ({"stop": "max_tokens"}, "length"),
    ({"stop": "refusal"}, "other"), ({"stop": None, "out": 10}, "other"), ({"stop": None, "out": 300}, "length"),
])
def test_finish_is_read_from_the_stop_reason_and_else_from_the_tokens(e, conf, expected):
    mode(e, **conf)
    assert json.loads(run(e, request(max_tokens=300)).stdout)["finish"] == expected


def test_a_list_of_events_is_read_by_its_result_event(e):
    mode(e, "events")
    out = json.loads(run(e).stdout)
    assert out["text"] == "from a list" and out["usage"]["input"] == 1 and out["usage"]["cache_read"] == 0


@pytest.mark.parametrize("name,code,exit_code", [
    ("limit", "E_RATE", 1), ("limit_text", "E_RATE", 1), ("auth", "E_KEY", 3), ("network", "E_NETWORK", 1),
    ("upstream", "E_UPSTREAM", 1), ("badjson", "E_RESPONSE", 1), ("noresult", "E_RESPONSE", 1), ("empty", "E_RESPONSE", 1),
    ("nousage", "E_RESPONSE", 1), ("crash", "E_INTERNAL", 1),
])
def test_a_failure_is_one_code_on_stderr_and_nothing_else(e, name, code, exit_code):
    mode(e, name)
    res = run(e)
    assert (res.returncode, res.stdout, res.stderr) == (exit_code, "", "run-text: %s\n" % code)


def test_a_reply_that_quotes_a_limit_phrase_is_a_reply(e):
    mode(e, "limit_reply")
    res = run(e)
    assert res.returncode == 0 and json.loads(res.stdout)["text"].startswith("You've hit your limit")


@pytest.mark.parametrize("marker", ["limit reached", "hit your session limit", "Credit balance is too low", "out of usage credits"])
def test_every_account_limit_word_of_the_adapter_gives_e_rate(e, marker):
    eval_words = json.loads((ADAPTER / "eval.json").read_text())["account_limit"]
    assert marker in eval_words                                           # the literal is one of the adapter's own words
    (e["fake"] / "mode.json").write_text(json.dumps({"mode": "limit_text"}))
    fake = (e["tmp"] / "bin" / "claude")
    fake.write_text(fake.read_text().replace("You've hit your weekly limit · resets Oct 9", marker))
    res = run(e)
    assert (res.returncode, res.stderr) == (1, "run-text: E_RATE\n")


def test_every_code_the_runner_prints_is_one_the_interpreter_evidence_knows():
    text = (REPO / "evals" / "evidence_lines.py").read_text(encoding="utf-8")
    known = set(re.search(r"IX_ERRORS = \((.*?)\)", text, re.S).group(1).replace('"', "").replace("\n", " ").replace(" ", "").split(","))
    runner = (ADAPTER / "run_text.py").read_text(encoding="utf-8")
    used = set(re.findall(r'"(E_[A-Z]+)"', runner))
    assert used and used <= known and "E_HTTP" not in used


# ---------------------------------------------------------------------------------------------------------- the stop rules

def test_a_call_without_the_token_is_e_key_before_anything_starts(e):
    env = {k: v for k, v in e["env"].items() if k != "CLAUDE_CODE_OAUTH_TOKEN"}
    res = subprocess.run(["bash", str(SCRIPT), "--model", "m"], input=json.dumps(request()), capture_output=True, text=True,
                         env=env, timeout=60)
    assert (res.returncode, res.stdout, res.stderr) == (3, "", "run-text: E_KEY\n") and calls(e) == []


@pytest.mark.parametrize("bad", [
    {"v": 2}, {"system": ""}, {"system": 5}, {"user": "   "}, {"user": "a\x00b"}, {"max_tokens": 0}, {"max_tokens": True},
    {"max_tokens": 64001}, {"max_tokens": "300"}, {"reasoning": "extreme"}, {"deadline_ms": 0}, {"deadline_ms": 600001},
    {"deadline_ms": 1.5}, {"system": "x" * 100001}, {"extra": 1},
])
def test_a_bad_request_is_e_usage_and_the_cli_never_starts(e, bad):
    res = run(e, {**request(), **bad})
    assert (res.returncode, res.stdout, res.stderr) == (2, "", "run-text: E_USAGE\n") and calls(e) == []


def test_a_missing_key_a_non_object_and_bad_options_are_e_usage(e):
    missing = request()
    del missing["reasoning"]
    for res in (run(e, missing), run(e, raw="not json"), run(e, raw="[1]"), run(e, raw=""),
                run(e, request(), "--model", "-bad"), run(e, request(), "--model", "m", "--extra"),
                run(e, request(), "--model", "m", "--max-tokens", "5"), run(e, request(), "--model", "m", "--repeat", "3"),
                run(e, request(), "--model", "bad model"), run(e, request(), "--probe")):
        assert (res.returncode, res.stderr) == (2, "run-text: E_USAGE\n"), res.args
    assert calls(e) == []


def test_a_cli_that_sleeps_gives_e_timeout_and_its_child_is_gone(e):
    mode(e, "hang")
    started = time.monotonic()
    res = run(e, request(deadline_ms=700))
    assert (res.returncode, res.stdout, res.stderr) == (1, "", "run-text: E_TIMEOUT\n")
    assert time.monotonic() - started < 20
    pid = int((e["fake"] / "child.pid").read_text())
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        os.kill(pid, 9)
        pytest.fail("the child of the CLI outlived the call")
    assert list(base_of(e).iterdir()) == []


def test_what_the_cli_leaves_running_ends_when_it_returns(e):
    mode(e, "leave")
    assert run(e).returncode == 0
    pid = int((e["fake"] / "child.pid").read_text())
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    os.kill(pid, 9)
    pytest.fail("a process the CLI left running outlived the call")


# ---------------------------------------------------------------------------------------------------------------- the probe

PROBE = ["--probe", "--model", "model-a", "--max-tokens", "2000", "--reasoning", "low"]
PROBE_KEYS = {"runner_version", "runner_sha256", "envelope_sha256", "system_verbatim", "user_verbatim", "messages_requests", "paths",
              "extras", "sent", "stable", "overhead_ms", "replaced", "reply_ok", "credential_ok", "files_outside_root",
              "outside_scan_complete", "outside_ok", "outside_other_count", "outside_unread_count",
              "outside_depth_limited_count", "outside_protected_count"}


def probe(e, *extra, **conf):
    mode(e, "http", show=["CLAUDE_CODE_OAUTH_TOKEN"], **conf)
    env = {k: v for k, v in e["env"].items() if k not in ("ANTHROPIC_BASE_URL", "HTTPS_PROXY")}
    res = subprocess.run(["bash", str(SCRIPT), *PROBE, *extra], capture_output=True, text=True, env=env, timeout=120)
    return res, (json.loads(res.stdout) if res.returncode == 0 else None)


def test_the_probe_runs_against_the_loopback_stub_with_a_placeholder_and_reports_the_listed_keys(e):
    res, out = probe(e, "--repeat", "3")
    assert res.returncode == 0 and res.stderr == "", res.stderr
    assert set(out) == PROBE_KEYS
    assert out["system_verbatim"] is True and out["user_verbatim"] is True and out["messages_requests"] == 1
    assert out["paths"] == {"/v1/messages": 1} and out["extras"] == [] and out["stable"] is True
    assert out["reply_ok"] is True and out["credential_ok"] is True and out["replaced"] == {"root": 0, "date": 0, "nonce": 0}
    assert out["files_outside_root"] == [] and out["outside_scan_complete"] is True and out["outside_ok"] is True
    assert out["sent"] == {"max_tokens": 2000, "temperature": None, "thinking": {"type": "enabled", "budget_tokens": 1024}, "effort": "low"}
    assert set(out["overhead_ms"]) == {"p50", "p95"} and 0 <= out["overhead_ms"]["p50"] <= out["overhead_ms"]["p95"]
    assert out["runner_version"] == "run-text/1 cli/2.1.283"
    assert len(out["envelope_sha256"]) == 64 and len(out["runner_sha256"]) == 64
    runs = calls(e)
    assert len(runs) == 3
    for call in runs:
        assert call["token"] == "placeholder" and TOKEN not in json.dumps(call)
        assert set(call["env"]) - INTERPRETER_NAMES == ENV_NAMES | PROBE_ENV_NAMES
        nonce = nonce_of(call["stdin"])
        assert call["stdin"] == USER_TEMPLATE_T.replace("{nonce}", nonce)
        assert call["argv"][call["argv"].index("--system-prompt") + 1] == SYSTEM_TEMPLATE_T.replace("{nonce}", nonce)
        assert argv_problems(call["argv"], "low") == []
    assert len({nonce_of(c["stdin"]) for c in runs}) == 1                  # one nonce for the repeats of a probe
    assert "decoy" not in json.dumps(runs)


def test_the_probe_needs_no_credential_and_leaves_no_file(e):
    env = {k: v for k, v in e["env"].items() if k != "CLAUDE_CODE_OAUTH_TOKEN"}
    mode(e, "http")
    res = subprocess.run(["bash", str(SCRIPT), *PROBE], capture_output=True, text=True, env=env, timeout=120)
    assert res.returncode == 0, res.stderr
    roots = [e["tmp"] / "home", e["tmp"] / "tmp", base_of(e)]
    assert find_text(roots, "probe-user-") == [] and find_text(roots, "probe system text alpha") == []


def test_extra_text_the_cli_adds_is_listed_by_place_and_size(e):
    res, out = probe(e, extra_system=37, extra_user=12)
    assert out["system_verbatim"] is True and out["user_verbatim"] is True
    assert out["extras"] == [{"where": "system[0]", "chars": 37}, {"where": "messages[0].content[1]", "chars": 12}]


def test_a_user_text_merged_into_another_block_is_not_verbatim(e):
    res, out = probe(e, merge_user=True)
    assert out["system_verbatim"] is True and out["user_verbatim"] is False
    assert out["extras"] == [{"where": "messages[0].content[0]", "chars": len("\n<reminder>")}]


def test_a_second_messages_request_and_other_paths_are_counted(e):
    res, out = probe(e, requests=2, other_path=True)
    assert out["messages_requests"] == 2 and out["paths"] == {"/v1/messages": 2, "/api/hello": 1}


def test_an_envelope_that_changes_between_runs_is_reported_unstable(e):
    res, out = probe(e, "--repeat", "2", unstable=True)
    assert out["stable"] is False


def test_the_envelope_changes_with_what_is_sent_and_not_with_the_session(e):
    _, a = probe(e)
    _, b = probe(e)
    assert a["envelope_sha256"] == b["envelope_sha256"]                    # metadata.user_id differs per process and is dropped
    mode(e, "http")
    env = {k: v for k, v in e["env"].items() if k not in ("ANTHROPIC_BASE_URL", "HTTPS_PROXY")}
    other = subprocess.run(["bash", str(SCRIPT), "--probe", "--model", "model-a", "--max-tokens", "300", "--reasoning", "off"],
                           capture_output=True, text=True, env=env, timeout=120)
    assert json.loads(other.stdout)["envelope_sha256"] != a["envelope_sha256"]   # vacuity: a different request is a different hash
    assert json.loads(other.stdout)["sent"]["thinking"] == {"type": "disabled"}


def test_the_probe_options_are_checked(e):
    for args in (["--probe", "--model", "m"], ["--probe", "--model", "m", "--max-tokens", "0", "--reasoning", "low"],
                 ["--probe", "--model", "m", "--max-tokens", "5", "--reasoning", "weird"],
                 ["--probe", "--model", "m", "--max-tokens", "5", "--reasoning", "low", "--repeat", "0"]):
        res = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=e["env"], timeout=60)
        assert (res.returncode, res.stderr) == (2, "run-text: E_USAGE\n"), args


# --------------------------------------------------------------------------------------------- the normaliser and the hash

def load_runner():
    spec = importlib.util.spec_from_file_location("run_text_under_test", ADAPTER / "run_text.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CAPTURED = {"model": "model-a", "max_tokens": 2000, "stream": True,
            "metadata": {"user_id": "user_abc_session_1"},
            "system": [{"type": "text", "text": "identity line"}, {"type": "text", "text": PROBE_SYSTEM_TEXT}],
            "messages": [{"role": "user", "content": [{"type": "text", "text": PROBE_USER_TEXT}]}],
            "thinking": {"type": "enabled", "budget_tokens": 1024}}
HEADERS = {"Anthropic-Beta": "zeta-1, alpha-2", "Content-Type": "application/json"}
# The normalised envelope, written out by hand: the probe texts replaced, metadata.user_id dropped, the sorted beta values added.
EXPECTED_ENVELOPE = ('{"beta":["alpha-2","zeta-1"],"body":{"max_tokens":2000,"messages":[{"content":[{"text":"<USER>",'
                     '"type":"text"}],"role":"user"}],"metadata":{},"model":"model-a","stream":true,"system":[{"text":"identity line",'
                     '"type":"text"},{"text":"<SYSTEM>","type":"text"}],"thinking":{"budget_tokens":1024,"type":"enabled"}}}')
LITERAL_HASH = "e2f91c206b41e479dd2346440f0c82d5ad16a328c957af2cbc73c1210af09c8e"


def test_the_normaliser_gives_the_envelope_and_the_hash_of_a_literal_body():
    run_text = load_runner()
    texts = (PROBE_SYSTEM_TEXT, PROBE_USER_TEXT, NONCE_T)
    envelope = run_text.normalise(CAPTURED, HEADERS, texts)
    assert json.dumps(envelope, sort_keys=True, separators=(",", ":")) == EXPECTED_ENVELOPE
    assert hashlib.sha256(EXPECTED_ENVELOPE.encode("utf-8")).hexdigest() == LITERAL_HASH
    assert hashlib.sha256(run_text.canonical(envelope)).hexdigest() == LITERAL_HASH
    assert CAPTURED["metadata"] == {"user_id": "user_abc_session_1"}       # the captured body itself is not changed
    changed = dict(CAPTURED, max_tokens=2001)                               # vacuity: a planted difference gives another hash
    assert hashlib.sha256(run_text.canonical(run_text.normalise(changed, HEADERS, texts))).hexdigest() != LITERAL_HASH


def test_the_runner_hash_covers_the_listed_files_and_changes_with_their_bytes(e, tmp_path):
    names = json.loads((ADAPTER / "adapter.json").read_text())["text_files"]
    assert names == ["run-text.sh", "run_text.py", "text_probe_stub.py"] and all((ADAPTER / n).is_file() for n in names)

    def oracle(folder):
        digest = hashlib.sha256()
        for name in sorted(names):
            digest.update(name.encode() + b"\n" + (folder / name).read_bytes() + b"\n")
        return digest.hexdigest()

    _, out = probe(e)
    assert out["runner_sha256"] == oracle(ADAPTER)
    copy = tmp_path / "copy"
    copy.mkdir()
    for name in names + ["adapter.json", "eval.json"]:
        shutil.copy2(ADAPTER / name, copy / name)
    (copy / "text_probe_stub.py").write_text((copy / "text_probe_stub.py").read_text() + "\n# an edit\n")
    mode(e, "http")
    env = {k: v for k, v in e["env"].items() if k not in ("ANTHROPIC_BASE_URL", "HTTPS_PROXY")}
    res = subprocess.run(["bash", str(copy / "run-text.sh"), *PROBE], capture_output=True, text=True, env=env, timeout=120)
    changed = json.loads(res.stdout)["runner_sha256"]
    assert changed == oracle(copy) and changed != out["runner_sha256"]


# ------------------------------------------------------------------------------------------------------- the loopback stub

def test_the_stub_listens_on_loopback_only_answers_a_streamed_reply_and_counts_paths():
    import urllib.request
    spec = importlib.util.spec_from_file_location("text_probe_stub_under_test", ADAPTER / "text_probe_stub.py")
    stub = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stub)
    server = stub.start()
    try:
        host, port = server.server_address
        assert host == "127.0.0.1"
        body = json.dumps({"model": "m", "stream": True, "messages": []}).encode()
        reply = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/v1/messages?beta=true", data=body, method="POST"),
                                       timeout=10).read().decode()
        events = [line[7:] for line in reply.splitlines() if line.startswith("event: ")]
        assert events == ["message_start", "content_block_start", "content_block_delta", "content_block_stop", "message_delta",
                          "message_stop"] and "probe-ok" in reply and "end_turn" in reply
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/other", timeout=10).read()
        seen = server.requests()
        assert [(r["method"], r["path"]) for r in seen] == [("POST", "/v1/messages"), ("GET", "/api/other")]
        assert seen[0]["body"]["model"] == "m"
        server.reset()
        assert server.requests() == []
    finally:
        server.shutdown()
        server.server_close()


# ------------------------------------------------------------------------------------------------------------------ the files

def test_the_manifest_names_the_text_runner_its_files_and_the_new_reader_of_the_token():
    manifest = json.loads((ADAPTER / "adapter.json").read_text())
    assert manifest["text_runner"] == "run-text.sh" and (ADAPTER / manifest["text_runner"]).is_file()
    token = next(s for s in manifest["secrets"] if s["name"] == "CLAUDE_CODE_OAUTH_TOKEN")
    assert "runtime/lab.py" in token["readers"] and (REPO / "runtime" / "lab.py").is_file()
    assert os.access(ADAPTER / "run-text.sh", os.X_OK)


@pytest.mark.skipif(os.environ.get("WB_RUN_TEXT_PROBE") != "1", reason="the real-CLI probe runs only with WB_RUN_TEXT_PROBE=1")
def test_the_real_cli_probe_reports_a_single_verbatim_request():
    """Runs the real CLI against the loopback stub with a placeholder token: no credential, no model. The maintainer's or the
    supervisor's to run; it reports what the pinned CLI adds, so the rows of the routes file can be written."""
    res = subprocess.run(["bash", str(SCRIPT), *PROBE, "--repeat", "2"], capture_output=True, text=True, timeout=300)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    assert out["system_verbatim"] is True and out["user_verbatim"] is True and out["messages_requests"] == 1 and out["stable"] is True


# ------------------------------------------------------------------------------- the deadline, the signals, the stale roots

def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def wait_gone(pid, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not alive(pid):
            return True
        time.sleep(0.1)
    return False


def start_runner(e, req=None):
    """The runner started and left running (a hanging CLI): the Popen and the CLI's pid once it has started."""
    proc = subprocess.Popen(["bash", str(SCRIPT), "--model", "model-a"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=e["env"])
    proc.stdin.write(json.dumps(req or request(deadline_ms=60000)))
    proc.stdin.close()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and not calls(e):
        time.sleep(0.05)
    assert calls(e), "the stand-in CLI never started"
    return proc, calls(e)[0]["pid"]


def test_a_slow_version_check_is_inside_the_deadline_and_is_e_timeout(e):
    mode(e, version_sleep=6)
    started = time.monotonic()
    res = run(e, request(deadline_ms=1500))
    assert (res.returncode, res.stdout, res.stderr) == (1, "", "run-text: E_TIMEOUT\n")
    assert time.monotonic() - started < 1.5 + 3 and calls(e) == []         # the call itself never started
    assert list(base_of(e).iterdir()) == []


def test_the_version_check_and_the_call_share_one_deadline(e):
    mode(e, "hang", version_sleep=1.5)
    started = time.monotonic()
    res = run(e, request(deadline_ms=2000))
    elapsed = time.monotonic() - started
    assert (res.returncode, res.stderr) == (1, "run-text: E_TIMEOUT\n")
    assert elapsed < 3.0          # a deadline of its own for each would give 1.5 + 2.0 and more
    pid = int((e["fake"] / "child.pid").read_text())
    assert wait_gone(pid)


def test_a_grandchild_in_another_session_that_holds_the_pipes_cannot_hold_the_runner(e):
    mode(e, "escaper")
    started = time.monotonic()
    try:
        res = run(e, request(deadline_ms=800))
        elapsed = time.monotonic() - started
        assert (res.returncode, res.stdout, res.stderr) == (1, "", "run-text: E_TIMEOUT\n")
        assert elapsed < 0.8 + 3.0          # the documented bound: deadline_ms + 3 s
        assert list(base_of(e).iterdir()) == []
    finally:
        escapee = e["fake"] / "escaper.pid"
        if escapee.exists():
            try:
                os.kill(int(escapee.read_text()), 9)   # it left the group on purpose: the one process the runner cannot end
            except ProcessLookupError:
                pass


def test_term_ends_the_cli_and_removes_the_root(e):
    mode(e, "hang")
    proc, cli_pid = start_runner(e)
    assert len(list(base_of(e).iterdir())) == 1
    proc.send_signal(15)
    try:
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 143 and wait_gone(cli_pid)
    assert list(base_of(e).iterdir()) == []


def test_kill_9_leaves_the_root_and_the_cli_and_the_next_call_sweeps_the_old_root(e):
    mode(e, "hang")
    proc, cli_pid = start_runner(e)
    roots = list(base_of(e).iterdir())
    assert len(roots) == 1
    proc.kill()
    proc.wait(timeout=10)
    try:
        # what SIGKILL cannot clean, as the contract says: the root stays and the CLI, in a session of its own, runs on
        assert roots[0].exists() and alive(cli_pid)
        fresh = base_of(e) / "run-text-fresh0"
        fresh.mkdir()
        other = base_of(e) / "keep-me"
        other.mkdir()
        outside = e["tmp"] / "outside" / "target"
        outside.mkdir()
        (outside / "file").write_text("x")
        (base_of(e) / "run-text-link0").symlink_to(outside)
        old = time.time() - 700 - 60
        for path in (roots[0], other):
            os.utime(path, (old, old))
        mode(e)
        assert run(e).returncode == 0
        assert not roots[0].exists()                                        # older than the longest deadline plus a minute
        assert fresh.exists() and other.exists()                           # a recent root and a folder of another name stay
        assert (outside / "file").exists() and (base_of(e) / "run-text-link0").is_symlink()   # a link is never followed
    finally:
        try:
            os.kill(cli_pid, 9)
        except ProcessLookupError:
            pass


def test_the_base_is_the_fixed_tmp_folder_and_a_link_or_a_stranger_is_refused(e, monkeypatch, tmp_path):
    monkeypatch.setenv("RUN_TEXT_TEST", "1")
    runner = load_runner()
    link = tmp_path / "linked-base"
    link.symlink_to(tmp_path / "outside")
    monkeypatch.setenv("RUN_TEXT_BASE", str(link))
    with pytest.raises(runner.Fail) as caught:
        runner.root_base()
    assert caught.value.code == "E_INTERNAL"
    monkeypatch.delenv("RUN_TEXT_TEST")                                     # outside a test the override is ignored
    seen = []
    monkeypatch.setattr(runner.os, "makedirs", lambda path, *a, **k: seen.append(path) or (_ for _ in ()).throw(OSError("stop")))
    with pytest.raises(runner.Fail):
        runner.root_base()
    assert seen == ["/tmp/run-text-%d" % os.getuid()]


# ----------------------------------------------------------------------------------- what the probe proves about the reply

def test_the_probe_checks_that_the_reply_reads_as_the_stubs(e):
    assert probe(e)[1]["reply_ok"] is True
    for conf in ({"noresult": True}, {"text": "something else"}, {"usage": {"input_tokens": 2, "output_tokens": 1,
                 "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}):
        res, out = probe(e, **conf)
        assert res.returncode == 0 and out["reply_ok"] is False, conf


def test_the_probe_reports_a_credential_the_stub_should_not_have_seen(e):
    assert probe(e)[1]["credential_ok"] is True
    assert probe(e, credential="some-other-token")[1]["credential_ok"] is False


@pytest.mark.parametrize("conf,why", [({"trim_user": True}, "trimmed"), ({"crlf_user": True}, "CRLF turned into LF"),
                                       ({"nfc_user": True}, "combining mark composed")])
def test_a_harness_that_changes_the_line_in_any_of_these_ways_is_not_verbatim(e, conf, why):
    res, out = probe(e, **conf)
    assert out["user_verbatim"] is False, why
    assert out["system_verbatim"] is True


def test_the_probe_texts_are_the_adversarial_ones_and_arrive_whole(e):
    assert "\r\n" in PROBE_USER_TEXT and PROBE_USER_TEXT.startswith("\n  ") and PROBE_USER_TEXT.endswith("  \n\n")
    assert "cafe\u0301" in PROBE_USER_TEXT and "\n/x " in PROBE_USER_TEXT.replace("\r\n", "\n") and "\n!bang" in PROBE_USER_TEXT
    assert "\n#hash" in PROBE_USER_TEXT and "\n@bia " in PROBE_USER_TEXT and "ana.lima@mail.example" in PROBE_USER_TEXT
    assert PROBE_SYSTEM_TEXT.count("\n") >= 3 and not PROBE_SYSTEM_TEXT.isascii()
    res, out = probe(e)
    assert out["system_verbatim"] is True and out["user_verbatim"] is True
    assert load_runner().probe_texts(NONCE_T) == (PROBE_SYSTEM_TEXT, PROBE_USER_TEXT, NONCE_T)
    fresh = [load_runner().probe_texts()[2] for _ in range(3)]
    assert len(set(fresh)) == 3 and all(re.fullmatch(r"[0-9a-f]{16}", n) for n in fresh)   # a nonce of fixed length, new each time


# --------------------------------------------------------------------------- values that vary from run to run, and files outside

INJECTED = "cwd: <ROOT>/cwd Today's date is <DATE>. at <DATE>"


def test_the_root_and_the_dates_are_replaced_before_the_hash_and_listed(e):
    res, out = probe(e, "--repeat", "3", inject=True)
    assert out["stable"] is True                                            # a different root and date in every run
    assert out["replaced"] == {"root": 1, "date": 2, "nonce": 0}
    assert out["extras"] == [{"where": "messages[0].content[1]", "chars": len(INJECTED)}]   # counted after the replacement
    paths = {c["cwd"] for c in calls(e)}
    assert len(paths) == 3                                                  # vacuity: the runs really differed


def test_the_scrub_replaces_each_form_of_the_root_and_each_date_and_only_with_a_root_given():
    run_text = load_runner()
    root = "/private/var/x/base/run-text-ab12cd34"
    body = {"system": "path " + root + "/cwd and slug -private-var-x-base-run-text-ab12cd34-cwd",
            "messages": [{"content": [{"type": "text", "text": "Today's date is October 21, 2026. noon 2026-10-21T10:11:12.123Z on 2026-10-21"}]}]}
    scrubbed, counts = run_text.scrub_body(body, root)
    assert scrubbed == {"system": "path <ROOT>/cwd and slug -private-var-x-base-<ROOT>-cwd",
                        "messages": [{"content": [{"type": "text", "text": "Today's date is <DATE>. noon <DATE> on <DATE>"}]}]}
    assert counts == {"root": 2, "date": 3}
    assert body["system"].startswith("path /private")                      # the captured body is not changed
    kept, counts = run_text.scrub_body(body, None)                         # vacuity: without a root the root stays
    assert root in kept["system"] and counts["root"] == 0
    other = json.loads(json.dumps(body).replace("ab12cd34", "99ee88dd"))
    headers = {"anthropic-beta": "b"}
    texts = (PROBE_SYSTEM_TEXT, PROBE_USER_TEXT, NONCE_T)
    assert run_text.normalise(body, headers, texts, root) == run_text.normalise(other, headers, texts, root.replace("ab12cd34", "99ee88dd"))
    assert run_text.normalise(body, headers, texts) != run_text.normalise(other, headers, texts)


def test_a_file_the_cli_writes_outside_its_root_is_listed_with_its_time_and_whether_it_holds_the_probe_text(e):
    outside = e["tmp"] / "outside"
    old = outside / "old.txt"
    old.write_text("written before the probe")
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    res, out = probe(e, outside_path=str(outside / "leak.txt"))
    assert out["outside_scan_complete"] is True
    assert [(Path(f["path"]).name, f["probe_text"]) for f in out["files_outside_root"]] == [("leak.txt", True)]
    assert abs(out["files_outside_root"][0]["mtime"] - time.time()) < 120


def test_the_outside_scan_says_when_it_was_not_whole(e, monkeypatch):
    run_text = load_runner()
    folder = e["tmp"] / "outside"
    for i in range(10):
        (folder / ("f%d" % i)).write_text("x")
    monkeypatch.setattr(run_text, "SCAN_LIMIT", 4)
    found, complete, limited, unreadable, protected = run_text.scan_outside([(str(folder), 3)], [], 0)
    assert complete is False and len(found) <= 4
    monkeypatch.setattr(run_text, "SCAN_LIMIT", 1000)
    found, complete, limited, unreadable, protected = run_text.scan_outside([(str(folder), 3)], [], 0)
    assert complete is True and len(found) == 10 and limited == 0
    assert run_text.scan_outside([(str(folder), 3)], [str(folder)], 0) == ({}, True, 0, 0, 0)   # a skipped folder is not entered


def test_the_outside_rule_fails_a_planted_file_with_a_probe_text_and_one_under_the_probes_own_folder_and_passes_an_unrelated_one(e):
    outside = e["tmp"] / "outside"
    # a new, unrelated file (another session's log) is counted, not listed, and does not fail the rule
    res, out = probe(e, outside_unrelated=str(outside / "other-session.jsonl"))
    assert out["files_outside_root"] == [] and out["outside_other_count"] == 1
    assert "other-session" not in res.stdout and str(outside) not in res.stdout       # nothing of its name is published
    assert out["outside_scan_complete"] is True and out["outside_ok"] is True
    (outside / "other-session.jsonl").unlink()
    # a file that holds the line fails it
    res, out = probe(e, outside_path=str(outside / "leak.txt"))
    assert out["outside_ok"] is False and out["files_outside_root"][0]["probe_text"] is True
    (outside / "leak.txt").unlink()
    # so does one that holds it as a JSON string (a log's escaping): the marker inside the text is found
    res, out = probe(e, outside_escaped=str(outside / "log.jsonl"))
    assert out["outside_ok"] is False and out["files_outside_root"][0]["probe_text"] is True
    (outside / "log.jsonl").unlink()
    # a folder the harness derives from the working folder's path fails it, with no probe text in it
    res, out = probe(e, slug_under=str(outside))
    flagged = [f for f in out["files_outside_root"] if f["own_folder"]]
    assert out["outside_ok"] is False and len(flagged) == 2 and all(f["probe_text"] is False for f in flagged)
    assert out["files_outside_root"][0]["own_folder"] is True      # the flagged are printed first


def test_a_file_that_holds_the_runners_source_or_the_templates_is_not_a_probe_file_only_the_nonce_is(e):
    """The log of a session that runs the probe quotes the runner's source: it holds the templates, never the nonce."""
    outside = e["tmp"] / "outside"
    quoted = (ADAPTER / "run_text.py").read_text(encoding="utf-8") + SYSTEM_TEMPLATE_T + USER_TEMPLATE_T + PROBE_USER_TEXT
    res, out = probe(e, outside_unrelated=str(outside / "session-log.jsonl"), outside_text=quoted)
    assert "{nonce}" in quoted and NONCE_T in quoted                                     # the planted file is a real source quote
    assert out["outside_ok"] is True and out["files_outside_root"] == [] and out["outside_other_count"] == 1
    (outside / "session-log.jsonl").unlink()
    # a nonce of an earlier probe is nobody's now, and the next probe has a new one
    first = nonce_of(calls(e)[-1]["stdin"])
    res, out = probe(e, outside_unrelated=str(outside / "session-log.jsonl"), outside_text="x probe-user-" + first)
    assert nonce_of(calls(e)[-1]["stdin"]) != first and out["outside_ok"] is True
    (outside / "session-log.jsonl").unlink()
    # vacuity: the nonce of this probe in the same kind of file fails the rule (the fake writes the line it received)
    res, out = probe(e, outside_path=str(outside / "session-log.jsonl"))
    assert out["outside_ok"] is False and len(out["files_outside_root"]) == 1


# ------------------------------------------------------------------------------ the outside scan reads every file, whole

def report_of(run_text, path, nonce=NONCE_T):
    info = os.lstat(path)
    report, unread = run_text.outside_report({str(path): (str(path), info)}, [], nonce)
    return report[0]["probe_text"], unread


def test_a_nonce_past_one_megabyte_is_found_and_a_file_without_it_is_read_whole_and_clean(e):
    run_text = load_runner()
    big = e["tmp"] / "outside" / "big.log"
    big.write_bytes(b"x" * (1536 * 1024) + NONCE_T.encode() + b"tail")
    assert report_of(run_text, big) == (True, 0)
    big.write_bytes(b"x" * (1536 * 1024) + b"0123456789abcdee" + b"tail")        # vacuity: a near miss is not found
    assert report_of(run_text, big) == (False, 0)


@pytest.mark.parametrize("offset", [0, 55, 60, 63, 64, 100, 127])
def test_a_nonce_across_the_edge_of_two_chunks_is_found(e, monkeypatch, offset):
    run_text = load_runner()
    monkeypatch.setattr(run_text, "READ_CHUNK", 64)
    path = e["tmp"] / "outside" / "edge.bin"
    for name, data in (("ascii", NONCE_T.encode()), ("utf-16-le", NONCE_T.encode("utf-16-le")), ("utf-16-be", NONCE_T.encode("utf-16-be"))):
        path.write_bytes(b"." * offset + data + b"." * 40)
        assert report_of(run_text, path) == (True, 0), (name, offset)
    path.write_bytes(b"." * offset + NONCE_T[:-1].encode() + b"#" + b"." * 40)    # vacuity: one byte wrong
    assert report_of(run_text, path) == (False, 0)


def test_the_nonce_is_found_as_utf_16_in_both_orders_and_a_transformed_copy_is_not(e):
    import base64
    import zlib
    run_text = load_runner()
    path = e["tmp"] / "outside" / "enc.bin"
    for data in (NONCE_T.encode("utf-16-le"), NONCE_T.encode("utf-16-be"), b"\\xff\\xfe" + NONCE_T.encode("utf-16-le")):
        path.write_bytes(b"head" + data + b"tail")
        assert report_of(run_text, path) == (True, 0)
    for data in (base64.b64encode(NONCE_T.encode()), zlib.compress(NONCE_T.encode() * 3)):   # documented: not detected
        path.write_bytes(data)
        assert report_of(run_text, path) == (False, 0)


def test_a_file_that_cannot_be_read_makes_the_scan_incomplete_and_is_counted_not_named(e):
    outside = e["tmp"] / "outside"
    res, out = probe(e, outside_unreadable=str(outside / "locked-6f2a.log"))
    try:
        assert out["outside_unread_count"] == 1 and out["outside_scan_complete"] is False and out["outside_ok"] is False
        assert out["files_outside_root"] == [] and out["outside_other_count"] == 1
        assert "locked-6f2a" not in res.stdout                                        # an unflagged file is never named
    finally:
        (outside / "locked-6f2a.log").chmod(0o600)
    # vacuity: the same probe without an unreadable file is complete
    (outside / "locked-6f2a.log").unlink()
    res, out = probe(e)
    assert out["outside_unread_count"] == 0 and out["outside_scan_complete"] is True and out["outside_ok"] is True


def test_a_budget_that_runs_out_leaves_a_file_unread_never_clean(e, monkeypatch):
    run_text = load_runner()
    path = e["tmp"] / "outside" / "budget.bin"
    path.write_bytes(b"y" * 300)
    monkeypatch.setattr(run_text, "READ_CHUNK", 100)
    monkeypatch.setattr(run_text, "READ_BYTES_BUDGET", 150)
    assert report_of(run_text, path) == (False, 1)
    monkeypatch.setattr(run_text, "READ_BYTES_BUDGET", 10000)
    monkeypatch.setattr(run_text, "READ_SECONDS_BUDGET", -1.0)                     # time already out
    assert report_of(run_text, path) == (False, 1)
    monkeypatch.setattr(run_text, "READ_SECONDS_BUDGET", 120.0)
    assert report_of(run_text, path) == (False, 0)                                 # vacuity: enough of both, and it is clean


def test_a_changed_folder_the_depth_limit_stops_at_makes_the_scan_incomplete_unless_another_location_listed_it(e):
    run_text = load_runner()
    root = e["tmp"] / "outside"
    (root / "a" / "b").mkdir(parents=True)
    (root / "a" / "b" / "c.txt").write_text("x")
    found, complete, limited, unreadable, protected = run_text.scan_outside([(str(root), 1)], [], 0)       # a is at the limit and holds more
    assert (complete, limited) == (False, 1)
    found, complete, limited, unreadable, protected = run_text.scan_outside([(str(root), 3)], [], 0)       # deep enough
    assert (complete, limited) == (True, 0)
    found, complete, limited, unreadable, protected = run_text.scan_outside([(str(root), 1), (str(root / "a"), 3)], [], 0)   # listed by another location
    assert (complete, limited) == (True, 0)
    found, complete, limited, unreadable, protected = run_text.scan_outside([(str(root), 1)], [], time.time() + 3600)         # nothing changed: nothing to fear
    assert (complete, limited) == (True, 0)


def test_the_probe_reports_a_folder_too_deep_to_look_in(e):
    res, out = probe(e, deep_under=str(e["tmp"] / "outside"))
    assert out["outside_depth_limited_count"] >= 1 and out["outside_scan_complete"] is False and out["outside_ok"] is False
    assert "l1" not in res.stdout                                                   # counted, not named


def test_a_nonce_that_stands_alone_is_replaced_and_counted_so_an_echo_has_a_named_cause(e):
    res, out = probe(e, "--repeat", "2", echo=True)
    assert out["replaced"]["nonce"] == 1 and out["stable"] is True
    assert out["system_verbatim"] is True and out["user_verbatim"] is True
    assert out["extras"] == [{"where": "messages[0].content[1]", "chars": len("you said probe-user-" + "0" * 16 + " and more")}]   # the nonce has a fixed length
    again = probe(e, echo=True)[1]
    assert again["envelope_sha256"] == out["envelope_sha256"]                       # another nonce, the same envelope
    run_text = load_runner()
    body = {"messages": [{"role": "user", "content": "echo probe-user-%s end"}]}
    one, two = ("1111111111111111", "2222222222222222")
    texts_one = (SYSTEM_TEMPLATE_T.replace("{nonce}", one), USER_TEMPLATE_T.replace("{nonce}", one), one)
    texts_two = (SYSTEM_TEMPLATE_T.replace("{nonce}", two), USER_TEMPLATE_T.replace("{nonce}", two), two)
    env_one = run_text.normalise({"messages": [{"role": "user", "content": body["messages"][0]["content"] % one}]}, {}, texts_one)
    env_two = run_text.normalise({"messages": [{"role": "user", "content": body["messages"][0]["content"] % two}]}, {}, texts_two)
    assert env_one == env_two and "<NONCE>" in json.dumps(env_one) and one not in json.dumps(env_one)


# ------------------------------------------------------ a folder that cannot be looked into, and the CLI's own places

def test_a_folder_that_lists_its_names_but_not_their_details_is_unread_and_the_scan_is_incomplete(e):
    run_text = load_runner()
    folder = e["tmp"] / "outside" / "closed"
    folder.mkdir()
    (folder / "late.log").write_text("x probe-user-" + NONCE_T)
    folder.chmod(0o400)                                  # names can be listed; nothing inside can be looked at
    try:
        found, complete, limited, unreadable, protected = run_text.scan_outside([(str(e["tmp"] / "outside"), 4)], [], 0)
        assert complete is False and unreadable >= 1 and not any(Path(path).name == "late.log" for path, _ in found.values())
    finally:
        folder.chmod(0o700)
    # vacuity: the same tree with 0700 is complete, and the file is found and flagged
    found, complete, limited, unreadable, protected = run_text.scan_outside([(str(e["tmp"] / "outside"), 4)], [], 0)
    assert (complete, unreadable) == (True, 0)
    report, unread = run_text.outside_report(found, [], NONCE_T)
    assert unread == 0 and [(Path(r["path"]).name, r["probe_text"]) for r in report if Path(r["path"]).name == "late.log"] == [("late.log", True)]


def test_the_probe_counts_a_closed_folder_as_unread_never_named_and_outside_ok_is_false(e):
    outside = e["tmp"] / "outside"
    closed = outside / "closed-77e1"
    closed.mkdir()
    (closed / "late.log").write_text("x")
    closed.chmod(0o400)
    try:
        res, out = probe(e)
        assert out["outside_unread_count"] >= 1 and out["outside_scan_complete"] is False and out["outside_ok"] is False
        assert "closed-77e1" not in res.stdout
    finally:
        closed.chmod(0o700)


def test_the_cli_places_are_walked_without_a_depth_limit_and_the_general_ones_are_not(e):
    run_text = load_runner()
    old = time.time() - 7200
    for place in ("cli", "plain"):
        deep = e["tmp"] / place / "a" / "b" / "c" / "d" / "e" / "f"
        deep.mkdir(parents=True)
        (deep / "new.txt").write_text("probe-user-" + NONCE_T)
        for folder in [e["tmp"] / place / n for n in ("a", "a/b", "a/b/c", "a/b/c/d", "a/b/c/d/e")] + [e["tmp"] / place]:
            os.utime(folder, (old, old))                 # the folders existed before the probe; only the leaf folder and file are new
    since = time.time() - 600
    found, complete, limited, unreadable, protected = run_text.scan_outside([(str(e["tmp"] / "cli"), None)], [], since)
    assert complete is True and [Path(p).name for p, _ in found.values() if Path(p).name == "new.txt"] == ["new.txt"]
    found, complete, limited, unreadable, protected = run_text.scan_outside([(str(e["tmp"] / "plain"), 2)], [], since)
    assert not any(Path(p).name == "new.txt" for p, _ in found.values())
    assert complete is True and limited == 0             # the documented limit: seen by nobody, said by nobody


def test_the_default_places_are_the_cli_ones_without_a_limit_and_the_general_ones_to_depth_two(e, monkeypatch, tmp_path):
    run_text = load_runner()
    home = tmp_path / "fakehome"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude.json").write_text("{}")
    (home / ".other").mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    monkeypatch.delenv("RUN_TEXT_TEST", raising=False)
    places = dict((path, depth) for path, depth in run_text.outside_locations())
    uid = os.getuid()
    assert places["/tmp/claude-%d" % uid] is None and places["/private/tmp/claude-%d" % uid] is None
    assert places[str(home / ".claude")] is None and places[str(home / ".claude.json")] is None and str(home / ".other") not in places
    assert places["/tmp"] == 2 and places["/private/tmp"] == 2 and places[str(tmp_path / "tmp")] == 2


def test_a_spent_limit_of_entries_or_of_time_leaves_the_walk_incomplete(e, monkeypatch):
    run_text = load_runner()
    folder = e["tmp"] / "outside"
    for i in range(6):
        (folder / ("g%d" % i)).write_text("x")
    monkeypatch.setattr(run_text, "SCAN_SECONDS_BUDGET", -1.0)
    assert run_text.scan_outside([(str(folder), None)], [], 0)[1] is False
    monkeypatch.setattr(run_text, "SCAN_SECONDS_BUDGET", 120.0)
    monkeypatch.setattr(run_text, "SCAN_LIMIT", 3)
    assert run_text.scan_outside([(str(folder), None)], [], 0)[1] is False
    monkeypatch.setattr(run_text, "SCAN_LIMIT", 1000)
    assert run_text.scan_outside([(str(folder), None)], [], 0)[1] is True


# ------------------------------------------------ a folder the operating system keeps from this process (EPERM) is not unreadable

def raising_scandir(monkeypatch, run_text, folder, code):
    """os.scandir fails on `folder` alone, with the OSError of errno `code`; every other folder lists as it does."""
    real = os.scandir

    def scandir(path="."):
        if os.path.realpath(path) == os.path.realpath(str(folder)):
            raise PermissionError(code, os.strerror(code))
        return real(path)
    monkeypatch.setattr(run_text.os, "scandir", scandir)


def test_a_folder_the_system_protects_with_eperm_is_counted_not_unreadable_and_the_scan_stays_complete(e, monkeypatch):
    run_text = load_runner()
    protected_folder = e["tmp"] / "outside" / "TemporaryItems"
    protected_folder.mkdir()
    (e["tmp"] / "outside" / "other").mkdir()
    raising_scandir(monkeypatch, run_text, protected_folder, errno.EPERM)
    found, complete, limited, unreadable, protected = run_text.scan_outside([(str(e["tmp"] / "outside"), 4)], [], 0)
    assert (complete, unreadable, protected, limited) == (True, 0, 1, 0)
    # vacuity: the very same failure with EACCES (errno 13) is unreadable, and the scan is incomplete
    raising_scandir(monkeypatch, run_text, protected_folder, errno.EACCES)
    found, complete, limited, unreadable, protected = run_text.scan_outside([(str(e["tmp"] / "outside"), 4)], [], 0)
    assert (complete, unreadable, protected) == (False, 1, 0)
    # and any other error number stays unreadable too
    raising_scandir(monkeypatch, run_text, protected_folder, errno.EIO)
    found, complete, limited, unreadable, protected = run_text.scan_outside([(str(e["tmp"] / "outside"), 4)], [], 0)
    assert (complete, unreadable, protected) == (False, 1, 0)


DRIVER = """import errno, importlib.util, os, sys
spec = importlib.util.spec_from_file_location('rt', sys.argv[1])
rt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rt)
real = os.scandir
def scandir(path='.'):
    if isinstance(path, (str, bytes, os.PathLike)) and os.path.basename(os.fsdecode(path)) == 'TemporaryItems-3c9a':
        raise PermissionError(int(os.environ['DRIVER_ERRNO']), 'refused')
    return real(path)
rt.os.scandir = scandir
sys.exit(rt.main(sys.argv[2:]))
"""


def test_the_probe_reports_outside_protected_count_and_never_names_the_folder(e):
    driver = e["tmp"] / "driver.py"
    driver.write_text(DRIVER)
    (e["tmp"] / "outside" / "TemporaryItems-3c9a").mkdir()
    mode(e, "http", show=["CLAUDE_CODE_OAUTH_TOKEN"])
    env = {k: v for k, v in e["env"].items() if k not in ("ANTHROPIC_BASE_URL", "HTTPS_PROXY")}

    def run_driver(code):
        return subprocess.run([sys.executable, str(driver), str(ADAPTER / "run_text.py"), *PROBE], capture_output=True, text=True,
                              env={**env, "DRIVER_ERRNO": str(code)}, timeout=120)
    res = run_driver(errno.EPERM)
    assert res.returncode == 0 and res.stderr == "", res.stderr
    out = json.loads(res.stdout)
    assert out["outside_protected_count"] == 1 and out["outside_unread_count"] == 0
    assert out["outside_scan_complete"] is True and out["outside_ok"] is True
    assert "TemporaryItems-3c9a" not in res.stdout and "TemporaryItems-3c9a" not in res.stderr
    # vacuity: the same driver with errno 13 says unread 1, incomplete and not ok, and still names nothing
    res = run_driver(errno.EACCES)
    out = json.loads(res.stdout)
    assert out["outside_protected_count"] == 0 and out["outside_unread_count"] == 1
    assert out["outside_scan_complete"] is False and out["outside_ok"] is False
    assert "TemporaryItems-3c9a" not in res.stdout
