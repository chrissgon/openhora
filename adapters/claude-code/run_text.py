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
and never forwarded; this runner writes the system text, the user text and the reply nowhere (the CLI is told to keep no session;
what it writes anyway is what `--probe` lists as files_outside_root).

The call runs the CLI in a fresh working folder and a fresh configuration folder (one temporary root, mode 700, under the fixed
folder /tmp/run-text-<uid>), in its own process group, with an environment of a closed list of names. One monotonic deadline
starts when the request is read and covers `claude --version` and the call; the runner returns within deadline_ms + 3 s. Stop it
with TERM (it then ends the CLI's group and removes its root); after KILL the root stays until the next call of the same user,
which removes roots older than the longest deadline plus a minute, and the CLI, in a session of its own, runs on until it ends. The credential is CLAUDE_CODE_OAUTH_TOKEN, read from this
process's environment (the caller puts it there; nothing here reads the OS secret store). Tests only: RUN_TEXT_TEST=1 with
RUN_TEXT_KEEP_TMP=1 keeps the temporary root so that a test can look for what must not be there.
"""
from __future__ import annotations

import glob
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import signal
import stat
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
KILL_GRACE_S = 1.5
DRAIN_S = 1.0                  # after the KILL: how long to wait for the pipes before closing them
VERSION_LIMIT_S = 10.0
TOKEN_NAME = "CLAUDE_CODE_OAUTH_TOKEN"
PASS_THROUGH = ("PATH", "LANG")   # HOME is the temporary root's own
FIXED_ENV = {"DISABLE_AUTOUPDATER": "1", "DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1",
             "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "ENABLE_CLAUDEAI_MCP_SERVERS": "false"}
# Texts that look like what a person writes and what a harness may trim, split or read as a command: leading and trailing spaces and
# newlines, several lines, CRLF, non-ASCII with a combining mark, lines that start with /, !, # and @, an e-mail address, a quote.
SYSTEM_TEMPLATE = "probe system text alpha {nonce}\nsecond line: a\u00e7\u00e3o \u2014 \u00fcn\u00ef\u00e7ode\n  indented third line  \n"
USER_TEMPLATE = ("\n  \r\n/x first line  \r\n!bang\n#hash\n@bia ana.lima@mail.example said \"hi\"\n"
                 "cafe\u0301 a\u00e7\u00e3o \u65e5\u672c\u8a9e probe-user-{nonce}\n\n  last line, trailing spaces   \n\n")
NONCE_BYTES = 8   # token_hex(8): 16 characters, always the same length, so the envelope does not change with it


def probe_texts(nonce=None):
    """(system, user, nonce) of one probe. The nonce is fresh for each probe and is the only thing a file is searched for: this source,
    and anything that quotes it (the log of a session that runs the probe), holds the templates and never a nonce."""
    nonce = nonce or secrets.token_hex(NONCE_BYTES)
    return SYSTEM_TEMPLATE.replace("{nonce}", nonce), USER_TEMPLATE.replace("{nonce}", nonce), nonce


BASE_PREFIX = "/tmp/run-text-"   # + the user id: the fixed folder of the roots, never the caller's TMPDIR
STALE_AFTER_S = MAX_DEADLINE_MS / 1000.0 + 60
SCAN_LIMIT = 100000
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


def test_mode():
    return os.environ.get("RUN_TEXT_TEST") == "1"


def root_base():
    """The fixed folder of the roots, /tmp/run-text-<uid> (tests only: RUN_TEXT_BASE), mode 700, ours, not a link."""
    base = os.environ.get("RUN_TEXT_BASE") if test_mode() and os.environ.get("RUN_TEXT_BASE") else BASE_PREFIX + str(os.getuid())
    try:
        os.makedirs(base, 0o700, exist_ok=True)
        info = os.lstat(base)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise Fail("E_INTERNAL")
        if stat.S_IMODE(info.st_mode) & 0o077:
            os.chmod(base, 0o700)
    except OSError:
        raise Fail("E_INTERNAL")
    return base


def sweep_stale(base):
    """Roots a killed runner left: folders of the base older than the longest deadline plus a minute. Links are left alone."""
    try:
        for entry in os.scandir(base):
            if entry.name.startswith("run-text-") and entry.is_dir(follow_symlinks=False) \
                    and time.time() - entry.stat(follow_symlinks=False).st_mtime > STALE_AFTER_S:
                shutil.rmtree(entry.path, ignore_errors=True)
    except OSError:
        pass


def make_root(base):
    """One temporary root (mode 700) with the working folder, the configuration folder, a temp folder and a home folder."""
    root = tempfile.mkdtemp(prefix="run-text-", dir=base)
    os.chmod(root, 0o700)
    for name in ("cwd", "config", "tmp", "home"):
        os.mkdir(os.path.join(root, name), 0o700)
    return root


def remove_root(root):
    if test_mode() and os.environ.get("RUN_TEXT_KEEP_TMP") == "1":
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
            proc.poll()   # reaps the leader, so that a dead group is seen as gone
            try:
                os.killpg(proc.pid, 0)
            except (ProcessLookupError, PermissionError):
                return
            time.sleep(0.05)


def drain(proc):
    """After the group is ended: take what the pipes hold for DRAIN_S, then close them, so that a process that left the group
    (its own session) and still holds a pipe cannot hold this runner."""
    try:
        proc.communicate(timeout=DRAIN_S)
    except subprocess.TimeoutExpired:
        pass
    except (OSError, ValueError):
        pass
    for pipe in (proc.stdin, proc.stdout, proc.stderr):
        try:
            if pipe:
                pipe.close()
        except (OSError, ValueError):
            pass
    try:
        proc.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        pass


def run_cli(argv, env, cwd, stdin_text, limit_s):
    """(returncode, stdout, stderr, wall_ms). The output is read in memory; nothing is forwarded or written. At limit_s the
    CLI's group is ended and the call is E_TIMEOUT."""
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                                cwd=cwd, start_new_session=True)
    except OSError:
        raise Fail("E_INTERNAL")
    started = time.monotonic()
    try:
        out, err = proc.communicate(stdin_text.encode("utf-8"), timeout=max(limit_s, 0.001))
    except subprocess.TimeoutExpired:
        end_group(proc)
        drain(proc)
        raise Fail("E_TIMEOUT")
    except BaseException:
        end_group(proc)
        drain(proc)
        raise
    wall_ms = int((time.monotonic() - started) * 1000)
    end_group(proc)   # the CLI returned: anything it left running in its group ends now
    return proc.returncode, out.decode("utf-8", errors="replace"), err.decode("utf-8", errors="replace"), wall_ms


def cli_version(env, root, deadline_at):
    """The CLI's own version, from `claude --version` (no network, no model). Part of runner_version. It runs inside the
    call's deadline, with a limit of its own of VERSION_LIMIT_S at most."""
    remaining = deadline_at - time.monotonic()
    if remaining <= 0:
        raise Fail("E_TIMEOUT")
    rc, out, _err, _ms = run_cli(["claude", "--version"], env, os.path.join(root, "cwd"), "", min(VERSION_LIMIT_S, remaining))
    found = re.search(r"\d+\.\d+\.\d+", out)
    if rc != 0 or not found:
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
    if any(m in haystack for m in UPSTREAM_MARKERS):
        return "E_UPSTREAM"
    if rc == 0:
        return "E_RESPONSE" if obj is None else "E_UPSTREAM"
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
    deadline_at = time.monotonic() + req["deadline_ms"] / 1000.0   # one deadline for the version and the call
    base = root_base()
    sweep_stale(base)
    root = make_root(base)
    try:
        env = build_env(root, token, req["max_tokens"], req["reasoning"])
        version = cli_version(env, root, deadline_at)
        rc, out, err, wall_ms = run_cli(build_argv(model, req["system"], req["reasoning"]), env, os.path.join(root, "cwd"),
                                        req["user"], deadline_at - time.monotonic())
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


def replace_probe(value, texts):
    """The probe system text becomes <SYSTEM> and the probe user text <USER>, wherever they stand in a string."""
    if isinstance(value, str):
        return value.replace(texts[0], "<SYSTEM>").replace(texts[1], "<USER>")
    if isinstance(value, list):
        return [replace_probe(v, texts) for v in value]
    if isinstance(value, dict):
        return {k: replace_probe(v, texts) for k, v in value.items()}
    return value


def betas_of(headers):
    values = []
    for key, value in headers.items():
        if key.lower() == "anthropic-beta":
            values += [v.strip() for v in value.split(",") if v.strip()]
    return sorted(set(values))


DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?")
TODAY_RE = re.compile(r"(Today's date is )[A-Za-z0-9 ,:/\-]+")


def scrub_body(body, root=None):
    """(a copy of the body with the values that vary from run to run replaced, how many of each). The root of the run, in every
    form the CLI may write it (its path, its real path, its random name), becomes <ROOT>; a date, a time and the sentence
    "Today's date is ..." become <DATE>. Keys are never changed."""
    counts = {"root": 0, "date": 0}
    forms = sorted({os.path.realpath(root), root, os.path.basename(root)}, key=len, reverse=True) if root else []

    def text(value):
        for form in forms:
            counts["root"] += value.count(form)
            value = value.replace(form, "<ROOT>")
        value, n = TODAY_RE.subn(r"\1<DATE>", value)
        counts["date"] += n
        value, n = DATE_RE.subn("<DATE>", value)
        counts["date"] += n
        return value

    def walk(value):
        if isinstance(value, str):
            return text(value)
        if isinstance(value, list):
            return [walk(v) for v in value]
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        return value

    return walk(json.loads(json.dumps(body))), counts


def envelope_of(scrubbed, headers, texts):
    """The envelope: the body with the probe texts replaced and metadata.user_id dropped, and the sorted beta values added."""
    body = replace_probe(scrubbed, texts)
    if isinstance(body.get("metadata"), dict):
        body["metadata"].pop("user_id", None)
    return {"beta": betas_of(headers), "body": body}


def normalise(body, headers, texts, root=None):
    return envelope_of(scrub_body(body, root)[0], headers, texts)


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


def occurrences(value, needle):
    """How many times the needle stands in the strings of a request body (keys are not searched)."""
    if isinstance(value, str):
        return value.count(needle)
    if isinstance(value, list):
        return sum(occurrences(v, needle) for v in value)
    if isinstance(value, dict):
        return sum(occurrences(v, needle) for v in value.values())
    return 0


CREDENTIAL_HEADERS = ("authorization", "proxy-authorization", "x-api-key")


def credential_ok(requests):
    """True when the stub saw no credential but the placeholder, in any request."""
    for request in requests:
        for name in CREDENTIAL_HEADERS:
            value = (request.get("headers") or {}).get(name)
            if value is not None and value not in (PROBE_TOKEN, "Bearer " + PROBE_TOKEN):
                return False
    return True


def examine(requests, probe_texts_, root=None):
    """What one CLI run sent: its messages requests, the exactness of the two texts, the extras and the values sent."""
    probe_system, probe_user = probe_texts_[0], probe_texts_[1]
    messages = [r for r in requests if r["method"] == "POST" and r["path"] == "/v1/messages"]
    paths = {}
    for r in requests:
        paths[r["path"]] = paths.get(r["path"], 0) + 1
    chosen = next((r for r in messages if occurrences(read_request_body(r), probe_user)), None)
    if chosen is None:
        chosen = messages[0] if messages else {"body": {}, "headers": {}}
    body, replaced = scrub_body(read_request_body(chosen), root)
    texts = texts_of(body)
    system_hits = [w for w, t in texts if w.startswith("system") and t == probe_system]
    user_hits = [w for w, t in texts if w.startswith("messages") and t == probe_user]
    extras = []
    for where, text in texts:
        if text in (probe_system, probe_user):
            continue
        chars = len(text) - (len(probe_system) if probe_system in text else len(probe_user) if probe_user in text else 0)
        extras.append({"where": where, "chars": chars})   # counted after the replacement of <ROOT> and <DATE>
    if body.get("tools"):
        extras.append({"where": "tools", "chars": len(json.dumps(body["tools"], ensure_ascii=False))})
    config = body.get("output_config") if isinstance(body.get("output_config"), dict) else {}
    effort = config.get("effort", body.get("effort"))
    return {"messages_requests": len(messages), "paths": paths,
            "system_verbatim": len(system_hits) == 1 and occurrences(body, probe_system) == 1,
            "user_verbatim": len(user_hits) == 1 and occurrences(body, probe_user) == 1,
            "extras": extras, "replaced": replaced, "credential_ok": credential_ok(requests),
            "sent": {"max_tokens": body.get("max_tokens"), "temperature": body.get("temperature"),
                     "thinking": body.get("thinking"), "effort": effort},
            "envelope_sha256": sha256(canonical(envelope_of(body, chosen.get("headers") or {}, probe_texts_)))}


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(math.ceil(fraction * len(ordered))) - 1))]


def outside_locations():
    """(folder or file, depth) the probe looks in for what the CLI wrote outside its root. Tests only: RUN_TEXT_OUTSIDE."""
    if test_mode() and os.environ.get("RUN_TEXT_OUTSIDE"):
        return [(p, 4) for p in os.environ["RUN_TEXT_OUTSIDE"].split(os.pathsep) if p]
    home = os.path.expanduser("~")
    found = [("/tmp/claude-%d" % os.getuid(), 8), ("/tmp", 2), ("/private/tmp", 2)]
    if os.environ.get("TMPDIR"):
        found.append((os.environ["TMPDIR"], 2))
    return found + [(path, 4) for path in sorted(glob.glob(os.path.join(home, ".claude*")))]


def scan_outside(locations, skip, since):
    """Entries created or changed since `since` (names and times; the content of a file is read only to look for the probe texts),
    and whether the scan was whole. Links are not followed; the folders in `skip` are not entered."""
    skip = {os.path.realpath(p) for p in skip}
    found, visited, complete = {}, 0, True
    for top, depth in locations:
        stack = [(top, 0)]
        while stack:
            path, level = stack.pop()
            try:
                info = os.lstat(path)
            except OSError:
                continue
            if os.path.realpath(path) in skip:
                continue
            visited += 1
            if visited > SCAN_LIMIT:
                return found, False
            born = getattr(info, "st_birthtime", 0) or 0
            if level > 0 or not stat.S_ISDIR(info.st_mode):
                if born >= since or info.st_mtime >= since:
                    found[os.path.realpath(path)] = (path, info)
            if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode) and level < depth:
                try:
                    stack += [(entry.path, level + 1) for entry in os.scandir(path)]
                except OSError:
                    complete = False
    return found, complete


def own_names(root_names):
    """The names by which the harness may know a run's root in a path or in the name of a folder it derives from the working folder
    (its path with every character but letters and digits turned into a dash): the root's random name, spelled both ways."""
    names = set()
    for name in root_names:
        names |= {name, re.sub(r"[^A-Za-z0-9]", "-", name)}
    return names


def outside_report(found, root_names, nonce):
    names = own_names(root_names)
    report = []
    for key in sorted(found):
        path, info = found[key]
        texts = False
        if stat.S_ISREG(info.st_mode) and info.st_size <= 1048576:
            try:
                data = Path(path).read_bytes()
                texts = nonce.encode("utf-8") in data   # the nonce is ASCII: no escaping hides it
            except OSError:
                pass
        report.append({"path": path, "mtime": round(info.st_mtime, 3), "probe_text": texts,
                       "own_folder": any(name in path for name in names)})
    return report   # all of them; the caller decides on all and prints the flagged ones first


def one_run(model, max_tokens, reasoning, server, version, texts):
    """One CLI run against the stub: (its examination, the CLI's wall time, whether the reply read as the stub's, the version)."""
    server.reset()
    base = root_base()
    root = make_root(base)
    try:
        dead = "http://127.0.0.1:9"   # a closed port: any other host the CLI tries through a proxy fails closed
        env = build_env(root, PROBE_TOKEN, max_tokens, reasoning,
                        {"ANTHROPIC_BASE_URL": "http://127.0.0.1:%d" % server.server_address[1], "HTTP_PROXY": dead,
                         "HTTPS_PROXY": dead, "ALL_PROXY": dead, "NO_PROXY": "127.0.0.1,localhost,::1"})
        deadline_at = time.monotonic() + PROBE_DEADLINE_MS / 1000.0
        version = version or cli_version(env, root, deadline_at)
        rc, out, err, wall_ms = run_cli(build_argv(model, texts[0], reasoning), env, os.path.join(root, "cwd"), texts[1],
                                        deadline_at - time.monotonic())
        code = classify(rc, out, err, result_object(out), limit_markers())
        if code:
            raise Fail(code)
        try:
            reply = answer(rc, out, err, wall_ms, max_tokens, version)
            reply_ok = reply["text"] == stub.ANSWER and reply["finish"] == "stop" and reply["usage"] == stub.USAGE
        except Fail as exc:
            if exc.code != "E_RESPONSE":
                raise
            reply_ok = False
        return examine(server.requests(), texts, root), wall_ms, reply_ok, version, os.path.basename(root)
    finally:
        remove_root(root)


def probe(model, max_tokens, reasoning, repeat):
    if not shutil.which("claude", path=os.environ.get("PATH", "")):
        raise Fail("E_INTERNAL")
    base = root_base()
    sweep_stale(base)
    locations, since, texts = outside_locations(), time.time() - 0.05, probe_texts()
    server = stub.start()
    runs, walls, replies, version, root_names = [], [], [], None, []
    try:
        for _ in range(repeat):
            run_report, wall_ms, reply_ok, version, root_name = one_run(model, max_tokens, reasoning, server, version, texts)
            root_names.append(root_name)
            runs.append(run_report)
            walls.append(wall_ms)
            replies.append(reply_ok)
    finally:
        server.shutdown()
        server.server_close()
    found, complete = scan_outside(locations, [base], since)
    first = runs[0]
    files = outside_report(found, root_names, texts[2])
    flagged = [f for f in files if f["probe_text"] or f["own_folder"]]
    # Others write under the same folders (other sessions of the harness, whose folders can carry a person's project names): only the
    # flagged entries are printed, with a count of the others. A scan that stopped early, a file that holds the probe's nonce and
    # anything under the probe's own folder fail the rule.
    outside_ok = complete and not flagged
    return {"runner_version": runner_version(version), "runner_sha256": runner_sha256(),
            "envelope_sha256": first["envelope_sha256"], "system_verbatim": all(r["system_verbatim"] for r in runs),
            "user_verbatim": all(r["user_verbatim"] for r in runs), "messages_requests": first["messages_requests"],
            "paths": first["paths"], "extras": first["extras"], "replaced": first["replaced"], "sent": first["sent"],
            "stable": all(r == first for r in runs), "reply_ok": all(replies),
            "credential_ok": all(r["credential_ok"] for r in runs), "files_outside_root": flagged[:200],
            "outside_other_count": len(files) - len(flagged), "outside_scan_complete": complete, "outside_ok": outside_ok,
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
