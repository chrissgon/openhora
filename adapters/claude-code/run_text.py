#!/usr/bin/env python3
"""The text contract of this adapter (contracts/runtime.md, "The text contract"): one system text and one user text in, one reply out.

  run-text.sh --model <id>                      reads one JSON object on stdin, prints one JSON object on stdout
  run-text.sh --probe --model <id> --max-tokens <n> --reasoning <r> [--repeat N]
                                                measures what reaches the model, with no credential and no model call
  run-text.sh --help

Request (stdin): {"v": 1, "system", "user", "max_tokens", "reasoning", "deadline_ms"}, exactly these keys; reasoning is
off, low, medium, high, xhigh or max.
Reply (stdout, one line): {"v": 1, "text", "finish": "stop"|"length"|"other", "usage": {"input", "output", "cache_read",
"cache_write"}, "latency_ms", "runner_version"}.
A failure prints one line on stderr, `run-text: E_<CODE>`, and nothing else: E_USAGE (exit 2); E_KEY, E_ROUTE (exit 3);
E_TIMEOUT, E_RATE, E_NETWORK, E_UPSTREAM, E_RESPONSE, E_INTERNAL (exit 1). The CLI's stdout and stderr are read in memory
and never forwarded or written; the system text, the user text and the reply are written nowhere (the CLI keeps no session,
and the working folder and the configuration folder it uses are removed when the call ends, however it ends).

The call runs the CLI in a fresh working folder and a fresh configuration folder (one temporary root, mode 700), in its own
process group, with an environment of a closed list of names. The credential is CLAUDE_CODE_OAUTH_TOKEN, read from this
process's environment (the caller puts it there; nothing here reads the OS secret store). Tests only: RUN_TEXT_TEST=1 with
RUN_TEXT_KEEP_TMP=1 keeps the temporary root so that a test can look for what must not be there.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import text_probe_stub as stub  # noqa: E402  (the loopback stub of --probe; stdlib only)

RUNNER_VERSION = "run-text/1"
EXIT = {"E_USAGE": 2, "E_KEY": 3, "E_ROUTE": 3, "E_TIMEOUT": 1, "E_RATE": 1, "E_NETWORK": 1, "E_UPSTREAM": 1,
        "E_RESPONSE": 1, "E_INTERNAL": 1}
REASONING = ("off", "low", "medium", "high", "xhigh", "max")
REQUEST_KEYS = ("v", "system", "user", "max_tokens", "reasoning", "deadline_ms")
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\[\]-]{0,63}")
MAX_STDIN = 4 * 1024 * 1024
MAX_SYSTEM_BYTES = 100000      # the system text travels in argv; one argument is 128 KiB at most on Linux
MAX_TOKENS_LIMIT = 64000
MAX_DEADLINE_MS = 600000
KILL_GRACE_S = 2.0
TOKEN_NAME = "CLAUDE_CODE_OAUTH_TOKEN"
PASS_THROUGH = ("PATH", "LANG")   # HOME is the temporary root's own
FIXED_ENV = {"DISABLE_AUTOUPDATER": "1", "DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1",
             "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "ENABLE_CLAUDEAI_MCP_SERVERS": "false"}
PROBE_SYSTEM = "probe system text alpha 7f3a"
PROBE_USER = "probe user text beta 91c2"
PROBE_TOKEN = "placeholder"
PROBE_DEADLINE_MS = 60000
STOP_REASONS = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length"}
AUTH_MARKERS = ("invalid api key", "please run /login", "authentication_error", "oauth token has expired",
                "\"api_error_status\":401", "invalid bearer token", "failed to authenticate")
NETWORK_MARKERS = ("econnrefused", "enotfound", "eai_again", "econnreset", "fetch failed", "unable to connect",
                   "getaddrinfo", "network error", "socket hang up")
UPSTREAM_MARKERS = ("overloaded_error", "internal server error", "\"api_error_status\":500", "\"api_error_status\":502",
                    "\"api_error_status\":503", "\"api_error_status\":504", "\"api_error_status\":529", "api_error")


class Fail(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def tidy(text):
    """Lower case, with the space after a colon of a JSON key taken out, so that one marker matches both spellings."""
    return re.sub(r'":\s+', '":', text).lower()


# ---------------------------------------------------------------------------------------------------------------- request

def read_request(stream):
    raw = stream.read(MAX_STDIN + 1)
    if len(raw) > MAX_STDIN:
        raise Fail("E_USAGE")
    try:
        req = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise Fail("E_USAGE")
    if not isinstance(req, dict) or set(req) != set(REQUEST_KEYS):
        raise Fail("E_USAGE")
    for key in ("v", "max_tokens", "deadline_ms"):
        if type(req[key]) is not int:
            raise Fail("E_USAGE")
    if req["v"] != 1 or not 1 <= req["max_tokens"] <= MAX_TOKENS_LIMIT or not 1 <= req["deadline_ms"] <= MAX_DEADLINE_MS:
        raise Fail("E_USAGE")
    if req["reasoning"] not in REASONING:
        raise Fail("E_USAGE")
    for key in ("system", "user"):
        if not isinstance(req[key], str) or not req[key].strip() or "\x00" in req[key]:
            raise Fail("E_USAGE")
    if len(req["system"].encode("utf-8")) > MAX_SYSTEM_BYTES:
        raise Fail("E_USAGE")
    return req


def check_model(model):
    if not isinstance(model, str) or not MODEL_RE.fullmatch(model):
        raise Fail("E_USAGE")
    return model


# ------------------------------------------------------------------------------------------------------------------ the CLI

def build_argv(model, system, reasoning):
    argv = ["claude", "-p", "--model", model, "--system-prompt", system, "--tools", "", "--no-session-persistence",
            "--disable-slash-commands", "--strict-mcp-config", "--setting-sources", "project,local",
            "--output-format", "json"]
    if reasoning != "off":
        argv += ["--effort", reasoning]
    return argv


def build_env(root, token, max_tokens, reasoning, extra=None):
    """Only the names of the closed list; the caller's other variables never reach the CLI."""
    env = {k: os.environ[k] for k in PASS_THROUGH if k != "HOME" and os.environ.get(k)}
    env["HOME"] = str(Path(root) / "home")   # the person's own home is never the CLI's: whatever it writes there goes with the root
    env["TMPDIR"] = str(Path(root) / "tmp")
    env["CLAUDE_CONFIG_DIR"] = str(Path(root) / "config")
    env[TOKEN_NAME] = token
    env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(max_tokens)
    env.update(FIXED_ENV)
    if reasoning == "off":
        env["MAX_THINKING_TOKENS"] = "0"
    env.update(extra or {})
    return env


def make_root():
    """One temporary root (mode 700) with the working folder, the configuration folder and a temp folder of the CLI."""
    root = tempfile.mkdtemp(prefix="run-text-")
    os.chmod(root, 0o700)
    for name in ("cwd", "config", "tmp", "home"):
        os.mkdir(os.path.join(root, name), 0o700)
    return root


def remove_root(root):
    if os.environ.get("RUN_TEXT_TEST") == "1" and os.environ.get("RUN_TEXT_KEEP_TMP") == "1":
        return
    shutil.rmtree(root, ignore_errors=True)


def end_group(proc):
    """TERM, then KILL KILL_GRACE_S later, to the CLI's whole process group: whatever it started ends with it."""
    for sig, grace in ((signal.SIGTERM, KILL_GRACE_S), (signal.SIGKILL, 0.0)):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            return
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            try:
                os.killpg(proc.pid, 0)
            except (ProcessLookupError, PermissionError):
                return
            time.sleep(0.05)


def run_cli(argv, env, cwd, stdin_text, deadline_s):
    """(returncode, stdout, stderr, wall_ms). The output is read in memory; nothing is forwarded or written."""
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                                cwd=cwd, start_new_session=True)
    except OSError:
        raise Fail("E_INTERNAL")
    started = time.monotonic()
    try:
        out, err = proc.communicate(stdin_text.encode("utf-8"), timeout=deadline_s)
    except subprocess.TimeoutExpired:
        end_group(proc)
        proc.communicate()
        raise Fail("E_TIMEOUT")
    except BaseException:
        end_group(proc)
        raise
    wall_ms = int((time.monotonic() - started) * 1000)
    end_group(proc)   # the CLI returned: anything it left running in its group ends now
    return proc.returncode, out.decode("utf-8", errors="replace"), err.decode("utf-8", errors="replace"), wall_ms


def cli_version(env):
    """The CLI's own version, from `claude --version` (no network, no model). Part of runner_version."""
    try:
        res = subprocess.run(["claude", "--version"], stdin=subprocess.DEVNULL, capture_output=True, env=env, timeout=30,
                             cwd=env["TMPDIR"])
    except (OSError, subprocess.TimeoutExpired):
        raise Fail("E_INTERNAL")
    found = re.search(r"\d+\.\d+\.\d+", res.stdout.decode("utf-8", errors="replace"))
    if res.returncode != 0 or not found:
        raise Fail("E_INTERNAL")
    return found.group(0)


def runner_version(version):
    return "%s cli/%s" % (RUNNER_VERSION, version)


# --------------------------------------------------------------------------------------------------------------- the answer

def limit_markers():
    """The account-limit words of this adapter's eval.json: read, never changed."""
    try:
        data = json.loads((HERE / "eval.json").read_text(encoding="utf-8"))
        markers = [m for m in data["account_limit"] if isinstance(m, str) and m]
    except (OSError, ValueError, KeyError, TypeError):
        raise Fail("E_INTERNAL")
    return [tidy(m) for m in markers]


def result_object(out):
    """The CLI's JSON result as a dict (the `result` event when it prints a list of events), or None."""
    try:
        data = json.loads(out)
    except ValueError:
        return None
    if isinstance(data, list):
        data = next((x for x in data if isinstance(x, dict) and x.get("type") == "result"), None)
    return data if isinstance(data, dict) else None


def int_of(value):
    return value if type(value) is int and value >= 0 else 0


def usage_of(obj):
    usage = obj.get("usage")
    if not isinstance(usage, dict):
        raise Fail("E_RESPONSE")
    return {"input": int_of(usage.get("input_tokens")), "output": int_of(usage.get("output_tokens")),
            "cache_read": int_of(usage.get("cache_read_input_tokens")),
            "cache_write": int_of(usage.get("cache_creation_input_tokens"))}


def stop_reason_of(obj):
    reason = obj.get("stop_reason")
    if reason is None and isinstance(obj.get("message"), dict):
        reason = obj["message"].get("stop_reason")
    return reason if isinstance(reason, str) else None


def finish_of(obj, usage, max_tokens):
    reason = stop_reason_of(obj)
    if reason is not None:
        return STOP_REASONS.get(reason, "other")
    return "length" if usage["output"] >= max_tokens else "other"


def classify(rc, out, err, obj, markers):
    """The code for a call that did not produce a reply (None when it did), from the CLI's own words, held in memory only.

    The account-limit words are looked for in the CLI's stderr always, and in its stdout when the call failed or its reply
    wrote no token: a model's reply that quotes them is a reply."""
    failed = rc != 0 or obj is None or obj.get("is_error") is True
    usage = obj.get("usage") if isinstance(obj, dict) else None
    wrote_nothing = isinstance(obj, dict) and not int_of(usage.get("output_tokens") if isinstance(usage, dict) else 0)
    haystack = tidy(err + ("\n" + out if failed or wrote_nothing else ""))
    if any(m in haystack for m in markers):
        return "E_RATE"
    if not failed:
        return None
    if any(m in haystack for m in AUTH_MARKERS):
        return "E_KEY"
    if any(m in haystack for m in NETWORK_MARKERS):
        return "E_NETWORK"
    if any(m in haystack for m in UPSTREAM_MARKERS) or (obj is not None and rc == 0):
        return "E_UPSTREAM"
    return "E_INTERNAL"


def answer(rc, out, err, wall_ms, max_tokens, version):
    obj = result_object(out)
    code = classify(rc, out, err, obj, limit_markers())
    if code:
        raise Fail(code)
    if obj is None:
        raise Fail("E_RESPONSE")
    text = obj.get("result")
    if not isinstance(text, str) or not text.strip():
        raise Fail("E_RESPONSE")
    usage = usage_of(obj)
    return {"v": 1, "text": text, "finish": finish_of(obj, usage, max_tokens), "usage": usage, "latency_ms": wall_ms,
            "runner_version": runner_version(version)}


def call(model, req):
    token = os.environ.get(TOKEN_NAME, "")
    if not token:
        raise Fail("E_KEY")
    if not shutil.which("claude", path=os.environ.get("PATH", "")):
        raise Fail("E_INTERNAL")
    root = make_root()
    try:
        env = build_env(root, token, req["max_tokens"], req["reasoning"])
        version = cli_version(env)
        rc, out, err, wall_ms = run_cli(build_argv(model, req["system"], req["reasoning"]), env, os.path.join(root, "cwd"),
                                        req["user"], req["deadline_ms"] / 1000.0)
        return answer(rc, out, err, wall_ms, req["max_tokens"], version)
    finally:
        remove_root(root)


# ----------------------------------------------------------------------------------------------------------------- the probe

def runner_sha256():
    """sha256 over the files adapter.json lists as `text_files`: for each, in sorted name order, the name, a newline, its bytes, a newline."""
    try:
        names = json.loads((HERE / "adapter.json").read_text(encoding="utf-8"))["text_files"]
        digest = hashlib.sha256()
        for name in sorted(names):
            digest.update(name.encode("utf-8") + b"\n" + (HERE / name).read_bytes() + b"\n")
    except (OSError, ValueError, KeyError, TypeError):
        raise Fail("E_INTERNAL")
    return digest.hexdigest()


def replace_probe(value):
    """The probe system text becomes <SYSTEM> and the probe user text <USER>, wherever they stand in a string."""
    if isinstance(value, str):
        return value.replace(PROBE_SYSTEM, "<SYSTEM>").replace(PROBE_USER, "<USER>")
    if isinstance(value, list):
        return [replace_probe(v) for v in value]
    if isinstance(value, dict):
        return {k: replace_probe(v) for k, v in value.items()}
    return value


def betas_of(headers):
    values = []
    for key, value in headers.items():
        if key.lower() == "anthropic-beta":
            values += [v.strip() for v in value.split(",") if v.strip()]
    return sorted(set(values))


def normalise(body, headers):
    """The envelope: the request body with the probe texts replaced, metadata.user_id dropped and the sorted beta values added."""
    body = replace_probe(json.loads(json.dumps(body)))
    if isinstance(body.get("metadata"), dict):
        body["metadata"].pop("user_id", None)
    return {"beta": betas_of(headers), "body": body}


def blocks(field, value):
    """(where, text) for every text of a request field: a plain string, or the `text` of each content block."""
    if isinstance(value, str):
        return [(field, value)]
    found = []
    if isinstance(value, list):
        for i, block in enumerate(value):
            if isinstance(block, str):
                found.append(("%s[%d]" % (field, i), block))
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                found.append(("%s[%d]" % (field, i), block["text"]))
            elif isinstance(block, dict) and isinstance(block.get("content"), (list, str)):
                found += blocks("%s[%d].content" % (field, i), block["content"])
    return found


def texts_of(body):
    found = blocks("system", body.get("system"))
    for m, message in enumerate(body.get("messages") or []):
        if isinstance(message, dict):
            found += blocks("messages[%d].content" % m, message.get("content"))
    return found


def read_request_body(request):
    return request["body"] if isinstance(request.get("body"), dict) else {}


def examine(requests):
    """What one CLI run sent: its messages requests, the exactness of the two texts, the extras and the values sent."""
    messages = [r for r in requests if r["method"] == "POST" and r["path"] == "/v1/messages"]
    paths = {}
    for r in requests:
        paths[r["path"]] = paths.get(r["path"], 0) + 1
    chosen = next((r for r in messages if PROBE_USER in json.dumps(read_request_body(r), ensure_ascii=False)), None)
    if chosen is None:
        chosen = messages[0] if messages else {"body": {}, "headers": {}}
    body = read_request_body(chosen)
    whole = json.dumps(body, ensure_ascii=False)
    texts = texts_of(body)
    system_hits = [w for w, t in texts if w.startswith("system") and t == PROBE_SYSTEM]
    user_hits = [w for w, t in texts if w.startswith("messages") and t == PROBE_USER]
    extras = []
    for where, text in texts:
        if text in (PROBE_SYSTEM, PROBE_USER):
            continue
        chars = len(text) - (len(PROBE_SYSTEM) if PROBE_SYSTEM in text else len(PROBE_USER) if PROBE_USER in text else 0)
        extras.append({"where": where, "chars": chars})
    if body.get("tools"):
        extras.append({"where": "tools", "chars": len(json.dumps(body["tools"], ensure_ascii=False))})
    config = body.get("output_config") if isinstance(body.get("output_config"), dict) else {}
    effort = config.get("effort", body.get("effort"))
    return {"messages_requests": len(messages), "paths": paths,
            "system_verbatim": len(system_hits) == 1 and whole.count(json.dumps(PROBE_SYSTEM)[1:-1]) == 1,
            "user_verbatim": len(user_hits) == 1 and whole.count(json.dumps(PROBE_USER)[1:-1]) == 1,
            "extras": extras,
            "sent": {"max_tokens": body.get("max_tokens"), "temperature": body.get("temperature"),
                     "thinking": body.get("thinking"), "effort": effort},
            "envelope_sha256": sha256(canonical(normalise(body, chosen.get("headers") or {})))}


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(math.ceil(fraction * len(ordered))) - 1))]


def probe(model, max_tokens, reasoning, repeat):
    if not shutil.which("claude", path=os.environ.get("PATH", "")):
        raise Fail("E_INTERNAL")
    server = stub.start()
    runs, walls, version = [], [], None
    try:
        port = server.server_address[1]
        for _ in range(repeat):
            server.reset()
            root = make_root()
            try:
                dead = "http://127.0.0.1:9"   # a closed port: any other host the CLI tries through a proxy fails closed
                env = build_env(root, PROBE_TOKEN, max_tokens, reasoning,
                                {"ANTHROPIC_BASE_URL": "http://127.0.0.1:%d" % port, "HTTP_PROXY": dead, "HTTPS_PROXY": dead,
                                 "ALL_PROXY": dead, "NO_PROXY": "127.0.0.1,localhost,::1"})
                version = version or cli_version(env)
                rc, out, err, wall_ms = run_cli(build_argv(model, PROBE_SYSTEM, reasoning), env, os.path.join(root, "cwd"),
                                                PROBE_USER, PROBE_DEADLINE_MS / 1000.0)
                code = classify(rc, out, err, result_object(out), limit_markers())
                if code:
                    raise Fail(code)
                walls.append(wall_ms)
                runs.append(examine(server.requests()))
            finally:
                remove_root(root)
    finally:
        server.shutdown()
        server.server_close()
    first = runs[0]
    stable = all(r == first for r in runs)
    return {"runner_version": runner_version(version), "runner_sha256": runner_sha256(),
            "envelope_sha256": first["envelope_sha256"], "system_verbatim": all(r["system_verbatim"] for r in runs),
            "user_verbatim": all(r["user_verbatim"] for r in runs), "messages_requests": first["messages_requests"],
            "paths": first["paths"], "extras": first["extras"], "sent": first["sent"], "stable": stable,
            "overhead_ms": {"p50": percentile(walls, 0.5), "p95": percentile(walls, 0.95)}}


# ---------------------------------------------------------------------------------------------------------------------- main

def parse_args(argv):
    opts, i = {"probe": False, "repeat": "1"}, 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--probe":
            opts["probe"] = True
            i += 1
        elif arg in ("--model", "--max-tokens", "--reasoning", "--repeat") and i + 1 < len(argv):
            opts[arg[2:].replace("-", "_")] = argv[i + 1]
            i += 2
        else:
            raise Fail("E_USAGE")
    check_model(opts.get("model"))
    if not opts["probe"]:
        if set(opts) != {"probe", "repeat", "model"} or opts["repeat"] != "1":
            raise Fail("E_USAGE")   # a call takes --model alone: everything else is in the request
        return opts
    try:
        opts["max_tokens"], opts["repeat"] = int(opts["max_tokens"]), int(opts["repeat"])
    except (KeyError, ValueError):
        raise Fail("E_USAGE")
    if not 1 <= opts["max_tokens"] <= MAX_TOKENS_LIMIT or not 1 <= opts["repeat"] <= 50 or opts.get("reasoning") not in REASONING:
        raise Fail("E_USAGE")
    return opts


def on_signal(signum, frame):
    raise SystemExit(128 + signum)


def main(argv):
    if any(a in ("--help", "-h") for a in argv):
        print(__doc__)
        return 0
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, on_signal)
    try:
        opts = parse_args(argv)
        if opts["probe"]:
            result = probe(opts["model"], opts["max_tokens"], opts["reasoning"], opts["repeat"])
        else:
            result = call(opts["model"], read_request(sys.stdin.buffer))
    except Fail as exc:
        sys.stderr.write("run-text: %s\n" % exc.code)
        return EXIT[exc.code]
    except Exception:   # nothing of a request or of the CLI's output is ever printed, not even in a traceback
        sys.stderr.write("run-text: E_INTERNAL\n")
        return EXIT["E_INTERNAL"]
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
