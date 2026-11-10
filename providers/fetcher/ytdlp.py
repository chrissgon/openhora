#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Fetcher provider: an implementation of the class fetcher:video (providers/CONTRACT.md) that runs a pinned yt-dlp inside a container on
this machine, for one public link a person gave, and measures the result. A runtime-only class: no skill requires it. The reference is
looked at and measured, never used: nothing here serves, copies or hands on its bytes (contracts/runtime.md, limits L72 and L73).
Standard library only; the docker command-line client is the one outside tool.

Verbs (JSON on stdout, diagnostics on stderr, input by flags, no prompt; a refusal prints {"ok": false, "code": <closed word>}):
  --check                             ready or not: a local docker, the pin filled, the image built from this definition and recorded.
  build (--confirmed | --dry-run)     build the image (the one step that uses the network, at the person's word: Debian packages and the
                                      pinned tool file). Records the image id in <state>/fetcher/image.json.
  pin-show                            the effective pin and what is missing from it. Fetches nothing.
  reap --root DIR                     remove the containers and networks past their deadline and the `.fetch-*` folders older than the
                                      longest timeout in the reference folders of DIR (which must hold the marker `.openhora-reference`).
  fetch --url U --platform P --platform-file F --stage meta|video --out DIR --language L [--max-seconds N] [--max-bytes N] [--timeout N]
                                      `meta` fetches the details and the subtitles, `video` the video file (after a person confirmed the
                                      size and length `meta` read). Three containers: the proxy (the only one with a way out), the fetch
                                      (an internal network whose only other member is the proxy) and nothing else.
  measure --in DIR --out FACTS --reference ID --platform P [--timeout N]
                                      the facts of a reference (providers/fetcher/_measure.py), in a container with no network.

Closed refusal codes. Exit 2: link_refused, platform_not_ready, out_refused, bad_arguments. Exit 1: too_long, no_duration, too_large,
network, fetch_failed, time_limit, measure_failed, facts_invalid, build_failed. Exit 3 (not configured): pin_not_filled, image_not_built,
docker_missing, docker_not_running, docker_not_local. `not_public` is not mapped: the tool's exit code does not tell a sign-in from another
failure, so until a live run gives its text the answer is fetch_failed (with the sentence that the tool may be out of date).

What the person gives, and what never is: the link of a public page, nothing else. No account, no cookie, no config file, no program to
run: the tool's argument list is built by code from a closed list of options (_fetcher_inner.py) and the host mounts no home or browser folder and
passes no environment variable. The link's host must be one of the platform's fetch file (`link.hosts`, exact names), its path must match
`link.path_pattern`, and only the query keys of `link.keep_query` are kept. The platform's fetch file is read through a path given by flag.

The network: the proxy accepts only CONNECT host:443 for an exact name of `fetch_hosts` or a name that ends with one of `fetch_suffixes`,
at a global address, with a TLS name equal to the host, with a byte cap and a deadline (providers/fetcher/_proxy.py). The fetch container
has no other route. Third-party media and text are parsed only inside containers (the tool, the measure), never on this host: the host
reads two small closed files (result.json, proxy.json) and `info.json` and `facts.json` through closed schemas, and moves the kept files
with os.link into the reference folder.

State, under the state folder (OPENHORA_STATE_DIR, else an absolute XDG_STATE_HOME + /openhora, else ~/.local/state/openhora):
fetcher/image.json (what `build` recorded).
Exit codes (providers/CONTRACT.md): 0 ok; 1 failed; 2 usage; 3 not configured.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import _container as box  # noqa: E402  (providers/_container.py: the one home of the container's lifecycle and limits)
import _fetcher_image  # noqa: E402  (providers/fetcher/_fetcher_image.py: the definition of the image)

FOLDER = HERE   # the folder the image is built from; the tests point it at a copy
EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_NOT_CONFIGURED = 0, 1, 2, 3
KINDS = {"failed": EXIT_FAILED, "usage": EXIT_USAGE, "not-configured": EXIT_NOT_CONFIGURED}

# The verbs, in the order the command line lists them (scripts/architecture_tables.py reads this line as text).
VERBS = ("pin-show", "build", "reap", "fetch", "measure")
PROVIDER_NAME = "yt-dlp"
STATE_ENV, STATE_FOLDER, BUILD_RECORD = "OPENHORA_STATE_DIR", "fetcher", "image.json"
LABEL_RUN = "org.openhora.fetcher"
RUN_PREFIX = ".fetch-"
FETCH_KEYS = {"platform", "link", "fetch_hosts", "fetch_suffixes", "extractors", "subtitles", "checked"}
LANGUAGE = re.compile(r"[a-z]{2,3}|auto")
PLATFORM_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
REFERENCE_ID = re.compile(r"[0-9a-f]{16}")
HOST = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+")
EXTRACTOR = re.compile(r"[A-Za-z0-9_]{1,40}")
LANG_PATTERN = re.compile(r"[A-Za-z0-9_.*{}-]{1,60}")
VIDEO_FILE = re.compile(r"video\.(mp4|webm|mov)")
SUBTITLE_FILE = re.compile(r"subs\.[a-z]{2,3}\.vtt")
CLOSED_CODES = ("fetch_failed", "time_limit", "too_large", "measure_failed")

# The caps (a test names each).
MAX_LINK = 2048
MIB = 1024 * 1024
STAGES = {"meta": {"timeout": 120, "file_cap": 16 * MIB}, "video": {"timeout": 600, "file_cap": 200 * MIB}}
VIDEO_MAX_SECONDS = 300
INFO_MAX_BYTES, SUBTITLE_MAX_BYTES, MAX_SUBTITLE_FILES = MIB, MIB, 4
RESULT_MAX_BYTES, PROXY_MAX_BYTES, FACTS_MAX_BYTES = 4096, 64 * 1024, 2 * MIB
MAX_OUT_ENTRIES = 12
DISK_MARGIN = 256 * MIB
PROXY_MARGIN = 1.10
PROXY_PORT = 8888
PROXY_LIMITS = {"memory_mb": 128, "cpus": 1, "pids": 64, "scratch_mb": 16, "tmp_mb": 16}
FETCH_LIMITS = {"memory_mb": 512, "cpus": 2, "pids": 128, "scratch_mb": 256, "tmp_mb": 64}
MEASURE_LIMITS = {"memory_mb": 1024, "cpus": 2, "pids": 128, "scratch_mb": 256, "tmp_mb": 64, "timeout": 300, "input_bytes": 200 * MIB}
MIN_TIMEOUT = 10
BUILD_TIMEOUT = 3600
PROBE_TIMEOUT = 60
LONGEST_TIMEOUT = 600
STOP_GRACE = 30
READY_SECONDS = 20
INFO_KEYS = ("id", "extractor_key", "duration", "width", "height", "fps", "upload_date", "title", "description", "view_count", "like_count",
             "comment_count", "subtitles")
SCHEMA_FILE = "facts.schema.json"
OUT_MODE_MASK = 0o077


class Refusal(Exception):
    """A verb that stops: `kind` is the exit code's reading, `code` the closed word printed on stdout."""

    def __init__(self, kind, code, reason=""):
        super().__init__(reason or code)
        self.kind, self.code, self.reason = kind, code, reason or code


def say(text):
    print(text, file=sys.stderr)


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --- state, docker, the image -----------------------------------------------------------------------------------------------------------


def state_dir():
    chosen = os.environ.get(STATE_ENV)
    if chosen:
        return os.path.abspath(chosen)
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg and os.path.isabs(xdg):
        return os.path.join(xdg, "openhora")
    return os.path.join(os.path.expanduser("~"), ".local", "state", "openhora")


def own_dir():
    path = os.path.join(state_dir(), STATE_FOLDER)
    os.makedirs(path, mode=0o700, exist_ok=True)
    for folder in (state_dir(), path):
        found = os.lstat(folder)
        if not stat.S_ISDIR(found.st_mode) or found.st_uid != os.getuid():
            raise Refusal("not-configured", "image_not_built", "the state folder is not a real folder of this user")
        if found.st_mode & OUT_MODE_MASK:
            os.chmod(folder, 0o700)
    return path


def refusal_of(error):
    code = error.code
    if code == "docker_missing":
        return Refusal("not-configured", "docker_missing", "docker is not installed or not on PATH (the fetcher runs in containers)")
    if code in ("docker_daemon_unknown", "docker_daemon_not_local"):
        return Refusal("not-configured", "docker_not_local", "the docker daemon is not a local one: the fetcher refuses it")
    if code in ("docker_unusable", "docker_timeout"):
        return Refusal("not-configured", "docker_not_running", "docker could not be started or did not answer")
    if code in ("bad_mount_path", "bad_mount"):
        return Refusal("usage", "out_refused", "a path holds a ':' or a control character, or is not absolute")
    return Refusal("failed", "fetch_failed", "the container could not be run (%s)" % code)


def docker(args, timeout=PROBE_TIMEOUT):
    try:
        return box.docker(args, timeout)
    except box.ContainerError as e:
        raise refusal_of(e) from None


def require_docker():
    done = docker(["version", "--format", "{{.Server.Version}}"])
    if done.returncode != 0:
        raise Refusal("not-configured", "docker_not_running", "the docker daemon is not answering: start it")
    try:
        box.require_local_daemon()
    except box.ContainerError as e:
        raise refusal_of(e) from None
    return done.stdout.strip()


def require_pin():
    """The effective pin, filled. Refused before any docker call."""
    pin = _fetcher_image.effective_pin(FOLDER)
    missing = _fetcher_image.pin_missing(pin)
    if missing:
        raise Refusal("not-configured", "pin_not_filled", "the tool's pin is not filled (%s): see providers/fetcher/README.md" % ", ".join(missing))
    return pin


def inspect_image(reference):
    done = docker(["image", "inspect", reference])
    if done.returncode != 0:
        return None
    try:
        found = json.loads(done.stdout)[0]
        return {"id": found["Id"], "labels": (found.get("Config") or {}).get("Labels") or {}}
    except (ValueError, KeyError, IndexError, TypeError):
        raise Refusal("failed", "fetch_failed", "docker image inspect did not answer with an image record") from None


def read_record():
    try:
        with open(os.path.join(state_dir(), STATE_FOLDER, BUILD_RECORD), encoding="utf-8") as f:
            record = json.load(f)
        return record if isinstance(record, dict) else None
    except (OSError, ValueError):
        return None


def check_image():
    """The image of this definition, ready to run: it exists, carries the hash and is the one `build` recorded."""
    tag, wanted = _fetcher_image.image_tag(FOLDER), _fetcher_image.definition_hash(FOLDER)
    image = inspect_image(tag)
    build = "python3 providers/fetcher/ytdlp.py build --confirmed"
    if image is None or image["labels"].get(box.LABEL_DEFINITION) != wanted:
        raise Refusal("not-configured", "image_not_built", "the image %s is not built from this definition: run `%s`" % (tag, build))
    record = read_record()
    if record is None or record.get("image_id") != image["id"]:
        raise Refusal("not-configured", "image_not_built", "the image %s is not the one `build` recorded: run `%s`" % (tag, build))
    return {"tag": tag, "id": image["id"], "definition": wanted, "tool_version": image["labels"].get("org.openhora.tool.version")}


def cmd_check(args):
    pin = require_pin()
    server = require_docker()
    image = check_image()
    return {"ok": True, "docker_server": server, "image": image, "tool": pin["version"]}


def cmd_pin_show(args):
    pin = _fetcher_image.effective_pin(FOLDER)
    missing = _fetcher_image.pin_missing(pin)
    return {"ok": True, "pin": pin, "filled": not missing, "missing": missing}


def build_argv(pin):
    return ["build", "--tag", _fetcher_image.image_tag(FOLDER), "--build-arg", "DEFINITION_HASH=%s" % _fetcher_image.definition_hash(FOLDER),
            "--build-arg", "TOOL_VERSION=%s" % pin["version"], "--build-arg", "TOOL_URL=%s" % pin["url"],
            "--build-arg", "TOOL_SIZE=%s" % pin["size"], "--build-arg", "TOOL_SHA256=%s" % pin["sha256"],
            "--build-arg", "TOOL_REDIRECT_HOSTS=%s" % ",".join(pin["redirect_hosts"]),
            "--file", os.path.join(FOLDER, "Dockerfile"), FOLDER]


def write_private_json(path, value):
    tmp = "%s.%s.tmp" % (path, uuid.uuid4().hex[:8])
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=1)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def cmd_build(args):
    if not args.confirmed and not args.dry_run:
        raise Refusal("usage", "bad_arguments", "build downloads Debian packages and the pinned tool and writes a local image: it needs "
                                                "--confirmed (or --dry-run to see the command). The person starts it, never a run.")
    pin = require_pin()
    argv = build_argv(pin)
    plan = {"command": ["docker"] + argv, "image": _fetcher_image.image_tag(FOLDER), "definition": _fetcher_image.definition_hash(FOLDER), "tool_version": pin["version"]}
    if args.dry_run:
        return dict(plan, dry_run=True)
    require_docker()
    folder = own_dir()
    say("building %s (yt-dlp %s); this downloads the packages and the tool and takes a while" % (plan["image"], pin["version"]))
    try:
        done = subprocess.run([box.docker_binary(), *argv], timeout=BUILD_TIMEOUT, env=box.docker_environment(), check=False, stdout=2, stderr=2)
    except subprocess.TimeoutExpired:
        raise Refusal("failed", "build_failed", "docker build did not finish within %d s" % BUILD_TIMEOUT) from None
    except box.ContainerError as e:
        raise refusal_of(e) from None
    if done.returncode != 0:
        raise Refusal("failed", "build_failed", "docker build failed (exit %d); its output is above" % done.returncode)
    image = inspect_image(plan["image"])
    if image is None or image["labels"].get(box.LABEL_DEFINITION) != plan["definition"]:
        raise Refusal("failed", "build_failed", "docker build ended well but the image does not carry this definition's hash")
    write_private_json(os.path.join(folder, BUILD_RECORD), {"image_tag": plan["image"], "image_id": image["id"], "definition": plan["definition"],
                                                          "tool_version": pin["version"], "built_at": utc_now()})
    return {"ok": True, "image": plan["image"], "image_id": image["id"], "tool_version": pin["version"]}


# --- closed reads of what a container wrote ----------------------------------------------------------------------------------------------


def read_regular(path, limit):
    """The bytes of a regular file a container wrote (no link, no pipe), at most `limit`; None when it is anything else or too large."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        found = os.fstat(fd)
        if not stat.S_ISREG(found.st_mode) or found.st_size > limit:
            return None
        with os.fdopen(os.dup(fd), "rb") as f:
            return f.read(limit + 1)[:limit]
    finally:
        os.close(fd)


def is_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 1 << 40


def read_result(folder):
    raw = read_regular(os.path.join(folder, "result.json"), RESULT_MAX_BYTES)
    try:
        value = json.loads(raw.decode("utf-8")) if raw is not None else None
    except ValueError:
        return None
    if not isinstance(value, dict) or set(value) != {"ok", "code", "exit"} or not isinstance(value["ok"], bool):
        return None
    if value["code"] is not None and value["code"] not in CLOSED_CODES:
        return None
    if value["exit"] is not None and not (isinstance(value["exit"], int) and not isinstance(value["exit"], bool)):
        return None
    return value


def read_proxy(folder):
    """proxy.json through its closed schema, or None."""
    raw = read_regular(os.path.join(folder, "proxy.json"), PROXY_MAX_BYTES)
    try:
        value = json.loads(raw.decode("utf-8")) if raw is not None else None
    except ValueError:
        return None
    if not isinstance(value, dict) or set(value) != {"allowed", "refused", "refused_hosts", "sni_refused", "bytes"}:
        return None
    if not all(is_count(value[k]) for k in ("allowed", "refused", "sni_refused", "bytes")):
        return None
    hosts = value["refused_hosts"]
    if not isinstance(hosts, list) or len(hosts) > 50 or not all(isinstance(h, str) and len(h) <= 253 and HOST.fullmatch(h) for h in hosts):
        return None
    return value


def check_info(value):
    """info.json through its closed schema: exactly INFO_KEYS, numbers or null, short strings. Raises Refusal(fetch_failed)."""
    bad = Refusal("failed", "fetch_failed", "the details file is not what was expected")
    if not isinstance(value, dict) or set(value) != set(INFO_KEYS):
        raise bad
    for key in INFO_KEYS:
        v = value[key]
        if key == "subtitles":
            ok = v in ("manual", "auto", "none")
        elif key in ("title", "description"):
            ok = isinstance(v, str) and len(v) <= (300 if key == "title" else 2000)
        elif key in ("id", "extractor_key", "upload_date"):
            ok = v is None or (isinstance(v, str) and len(v) <= 80)
        else:
            ok = v is None or (isinstance(v, (int, float)) and not isinstance(v, bool))
        if not ok:
            raise bad
    return value


def read_info(path):
    raw = read_regular(path, INFO_MAX_BYTES)
    try:
        return check_info(json.loads(raw.decode("utf-8"))) if raw is not None else None
    except ValueError:
        raise Refusal("failed", "fetch_failed", "the details file is not JSON") from None


def schema_check(value, schema, where="facts"):
    """A small JSON Schema reader (type, enum, properties, required, additionalProperties, items, maxItems, maxLength, pattern). Raises
    ValueError with the key path (schema names only, never a value) at the first difference."""
    if "enum" in schema and not any(value == e and type(value) == type(e) for e in schema["enum"]):
        raise ValueError(where)
    wanted = schema.get("type")
    if wanted is not None:
        names = wanted if isinstance(wanted, list) else [wanted]
        checks = {"string": lambda v: isinstance(v, str), "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
                  "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool), "boolean": lambda v: isinstance(v, bool),
                  "null": lambda v: v is None, "object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list)}
        if not any(checks[n](value) for n in names):
            raise ValueError(where)
    if isinstance(value, str):
        if len(value) > schema.get("maxLength", 1 << 30) or ("pattern" in schema and not re.search(schema["pattern"], value)):
            raise ValueError(where)
    if isinstance(value, dict) and "properties" in schema:
        props = schema["properties"]
        if schema.get("additionalProperties") is False and set(value) - set(props):
            raise ValueError(where)
        if set(schema.get("required", ())) - set(value):
            raise ValueError(where)
        for key, sub in props.items():
            if key in value:
                schema_check(value[key], sub, "%s.%s" % (where, key))
    if isinstance(value, list):
        if len(value) > schema.get("maxItems", 1 << 30):
            raise ValueError(where)
        if "items" in schema:
            for i, item in enumerate(value):
                schema_check(item, schema["items"], "%s[%d]" % (where, i))


def load_schema():
    with open(os.path.join(FOLDER, SCHEMA_FILE), encoding="utf-8") as f:
        return json.load(f)


# --- the platform's fetch file and the link ---------------------------------------------------------------------------------------------


def load_fetch_file(path, platform):
    """The checked contents of a `<platform>.fetch.json`. Raises Refusal(usage, platform_not_ready) for a file that is not one, whose
    platform differs, or whose extractors or path pattern are not filled (STOP 4 of the package fills them from a live run)."""
    bad = Refusal("usage", "platform_not_ready", "the platform's fetch file is missing, malformed or not filled yet")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, TypeError):
        raise bad from None
    if not isinstance(data, dict) or set(data) != FETCH_KEYS or data["platform"] != platform:
        raise bad
    link, subs = data["link"], data["subtitles"]
    if not isinstance(link, dict) or set(link) != {"hosts", "path_pattern", "keep_query"} or not isinstance(subs, dict) \
            or set(subs) != {"by_language", "original"}:
        raise bad
    lists = (link["hosts"], link["keep_query"], data["fetch_hosts"], data["fetch_suffixes"])
    if not all(isinstance(x, list) and all(isinstance(i, str) for i in x) for x in lists):
        raise bad
    if not link["hosts"] or not all(HOST.fullmatch(h) for h in link["hosts"] + data["fetch_hosts"]):
        raise bad
    if not all(s.startswith(".") and HOST.fullmatch(s[1:]) for s in data["fetch_suffixes"]):
        raise bad
    if not all(re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", k) for k in link["keep_query"]):
        raise bad
    ext = data["extractors"]
    if not isinstance(ext, list) or not ext or not all(isinstance(e, str) and EXTRACTOR.fullmatch(e) for e in ext):
        raise bad
    pattern = link["path_pattern"]
    if not isinstance(pattern, str) or not pattern:
        raise bad
    try:
        re.compile(pattern)
    except re.error:
        raise bad from None
    for value in (subs["by_language"], subs["original"]):
        if value is not None and not (isinstance(value, str) and LANG_PATTERN.fullmatch(value) and not value.startswith("-")):
            raise bad
    if not data["fetch_hosts"] and not data["fetch_suffixes"]:
        raise bad     # a proxy that lists nothing could only refuse: no container is started for it
    return data


def check_link(url, fetch):
    """The link a person gave, checked against the platform's fetch file, as the https URL to fetch (query cut to `keep_query`)."""
    refused = Refusal("usage", "link_refused", "the link is not a public https link of this platform")
    if not isinstance(url, str) or not url or len(url) > MAX_LINK or any(ord(c) < 33 or ord(c) > 126 for c in url):
        raise refused
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        raise refused from None
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or port is not None or "@" in parts.netloc or ":" in parts.netloc or host not in fetch["link"]["hosts"]:
        raise refused
    if not re.fullmatch(fetch["link"]["path_pattern"], parts.path):
        raise refused
    keep = fetch["link"]["keep_query"]
    pairs = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True) if k in keep]
    query = urllib.parse.urlencode(pairs)
    return "https://%s%s%s" % (host, parts.path, "?" + query if query else "")


def subtitle_languages(fetch, language):
    """The list of subtitle patterns to ask for: the platform's per-language pattern for `language` and its original-track pattern;
    with `auto`, the original-track pattern alone. Both patterns null: no subtitle."""
    subs = fetch["subtitles"]
    out = []
    if language != "auto" and subs["by_language"]:
        out.append(subs["by_language"].replace("{lang}", language))
    if subs["original"]:
        out.append(subs["original"])
    return out


def check_reference_folder(path, what="out_refused"):
    """A real folder of this user, closed to the group and others, inside a reference store (a tree that holds the marker)."""
    refused = Refusal("usage", "out_refused", "the folder is not a private folder of this user inside a reference store")
    if not isinstance(path, str) or not os.path.isabs(path):
        raise refused
    try:
        found = os.lstat(path)
        box.mount_path(path, what)
    except (OSError, box.ContainerError):
        raise refused from None
    if not stat.S_ISDIR(found.st_mode) or found.st_uid != os.getuid() or found.st_mode & OUT_MODE_MASK or not box.in_reference(path):
        raise refused
    return path


# --- one run: the folders, the proxy, the fetch, the collection --------------------------------------------------------------------------


def run_container(command, name, timeout):
    try:
        return box.run(command, name, timeout)
    except box.ContainerError as e:
        if e.code == "time_limit":
            raise Refusal("failed", "time_limit", "the container ran over %d s and was removed" % timeout) from None
        if e.code == "stopped":
            raise Refusal("failed", "fetch_failed", "stopped: the container was removed") from None
        raise refusal_of(e) from None


def container_command(name, image_id, inner, mounts, limits, network, deadline):
    try:
        return box.argv(name, image_id, inner, label=LABEL_RUN, deadline=deadline, mounts=mounts, memory_mb=limits["memory_mb"], cpus=limits["cpus"],
                        scratch_mb=limits["scratch_mb"], pids_limit=limits["pids"], tmp_mb=limits["tmp_mb"], network=network)
    except box.ContainerError as e:
        raise refusal_of(e) from None


class ProxyRun:
    """The proxy container, on its own thread: it listens until the host creates `stop` in its folder, then writes proxy.json."""

    def __init__(self, image_id, name, network, folder, fetch, max_bytes, deadline, timeout):
        inner = ["proxy", "--port", str(PROXY_PORT), "--max-bytes", str(max_bytes), "--deadline", str(deadline), "--out", "/out"]
        for host in fetch["fetch_hosts"]:
            inner += ["--allow-host", host]
        for suffix in fetch["fetch_suffixes"]:
            inner += ["--allow-suffix", suffix]
        self.name, self.folder, self.timeout, self.error = name, folder, timeout, None
        self.command = container_command(name, image_id, inner, [(folder, "/out", "rw")], PROXY_LIMITS, network, deadline)
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        try:
            box.run(self.command, self.name, self.timeout)
        except box.ContainerError as e:
            self.error = e

    def start(self):
        self.thread.start()

    def wait_ready(self, seconds=READY_SECONDS):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if read_regular(os.path.join(self.folder, "ready"), 16) is not None:
                return
            if not self.thread.is_alive():
                break
            time.sleep(0.05)
        raise Refusal("failed", "network", "the proxy did not start")

    def stop(self):
        try:
            fd = os.open(os.path.join(self.folder, "stop"), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.close(fd)
        except OSError:
            pass
        self.thread.join(10)
        if self.thread.is_alive():
            box.remove(self.name)
            self.thread.join(5)


def scan(folder, allowed, caps):
    """The names of the entries of `folder`, each a regular file (no link, no folder) whose name `allowed` takes and whose size is within
    `caps(name)`. Raises Refusal(fetch_failed) otherwise."""
    bad = Refusal("failed", "fetch_failed", "a container left something other than the files it may leave")
    try:
        entries = list(os.scandir(folder))
    except OSError:
        raise bad from None
    if len(entries) > MAX_OUT_ENTRIES:
        raise bad
    names = []
    for entry in entries:
        try:
            found = entry.stat(follow_symlinks=False)
        except OSError:
            raise bad from None
        if not stat.S_ISREG(found.st_mode) or not allowed(entry.name) or found.st_size > caps(entry.name):
            raise bad
        names.append(entry.name)
    return sorted(names)


def fetch_allowed(stage):
    def allowed(name):
        if name == "result.json":
            return True
        return bool(name == "info.json" or SUBTITLE_FILE.fullmatch(name)) if stage == "meta" else bool(VIDEO_FILE.fullmatch(name))
    return allowed


def fetch_caps(stage, file_cap):
    def caps(name):
        if name == "result.json":
            return RESULT_MAX_BYTES
        if name == "info.json":
            return INFO_MAX_BYTES
        if SUBTITLE_FILE.fullmatch(name):
            return SUBTITLE_MAX_BYTES
        return file_cap
    return caps


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(MIB), b""):
            h.update(chunk)
    return h.hexdigest()


def move_files(sources, out_dir):
    """Move each (source path, final name) into `out_dir` with os.link, never replacing: all the names are free first, or nothing moves."""
    for _, name in sources:
        if os.path.lexists(os.path.join(out_dir, name)):
            raise Refusal("usage", "out_refused", "a file of that name is already in the reference folder")
    done = []
    try:
        for source, name in sources:
            os.link(source, os.path.join(out_dir, name))
            done.append(name)
    except OSError:
        for name in done:
            try:
                os.unlink(os.path.join(out_dir, name))
            except OSError:
                pass
        raise Refusal("failed", "fetch_failed", "the files could not be moved into the reference folder") from None


def free_bytes(path):
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return 0


def clamp(value, low, high):
    return max(low, min(high, value))


def cmd_fetch(args):
    if args.stage not in STAGES or not isinstance(args.language, str) or not LANGUAGE.fullmatch(args.language) \
            or not PLATFORM_NAME.fullmatch(args.platform or ""):
        raise Refusal("usage", "bad_arguments", "a stage, a language or a platform name is not one the fetcher takes")
    for number in (args.max_seconds, args.max_bytes, args.timeout):
        if number is not None and number < 1:
            raise Refusal("usage", "bad_arguments", "a number given is not positive")
    caps = STAGES[args.stage]
    fetch = load_fetch_file(args.platform_file, args.platform)
    url = check_link(args.url, fetch)
    out_dir = check_reference_folder(os.path.abspath(args.out))
    max_seconds = min(args.max_seconds or VIDEO_MAX_SECONDS, VIDEO_MAX_SECONDS)
    if args.stage == "video":      # the host checks what `meta` read before it asks for the file
        info = read_info(os.path.join(out_dir, "info.json"))
        duration = info["duration"] if info else None
        if duration is None:
            raise Refusal("failed", "no_duration", "the details do not say how long the video is")
        if duration > max_seconds:
            raise Refusal("failed", "too_long", "the video is longer than %d s" % max_seconds)
    pin = require_pin()
    require_docker()
    image = check_image()
    room = free_bytes(out_dir) - DISK_MARGIN
    max_bytes = min(caps["file_cap"], args.max_bytes or caps["file_cap"], room)
    if max_bytes < 1:
        raise Refusal("failed", "too_large", "there is no room for the file")
    timeout = clamp(args.timeout or caps["timeout"], MIN_TIMEOUT, caps["timeout"])
    try:
        box.reap(LABEL_RUN)
    except box.ContainerError:
        pass
    token = uuid.uuid4().hex[:12]
    run_dir = os.path.join(out_dir, RUN_PREFIX + token)
    fetch_dir, proxy_dir = os.path.join(run_dir, "fetch"), os.path.join(run_dir, "proxy")
    net_in, net_out = "openhora-fetch-in-" + token, "openhora-fetch-out-" + token
    proxy_name, run_name = "openhora-fetch-proxy-" + token, "openhora-fetch-run-" + token
    deadline = int(time.time()) + timeout + STOP_GRACE
    proxy_cap = int(max_bytes * PROXY_MARGIN)
    for folder in (run_dir, fetch_dir, proxy_dir):
        os.mkdir(folder, 0o700)
    proxy = None
    try:
        box.create_network(net_out, False, LABEL_RUN, deadline)
        box.create_network(net_in, True, LABEL_RUN, deadline)
        proxy = ProxyRun(image["id"], proxy_name, net_out, proxy_dir, fetch, proxy_cap, deadline, timeout + STOP_GRACE)
        proxy.start()
        proxy.wait_ready()
        box.connect_network(net_in, proxy_name)
        inner = ["--result", "/out/result.json", "fetch", "--stage", args.stage, "--url", url, "--extractors", ",".join(fetch["extractors"]),
                 "--proxy-url", "http://%s:%d" % (proxy_name, PROXY_PORT), "--max-seconds", str(max_seconds), "--max-bytes", str(max_bytes),
                 "--langs", ",".join(subtitle_languages(fetch, args.language)) if args.stage == "meta" else "", "--timeout", str(max(5, timeout - 10))]
        command = container_command(run_name, image["id"], inner, [(fetch_dir, "/out", "rw")], FETCH_LIMITS, net_in, deadline)
        run_container(command, run_name, timeout)
        proxy.stop()
        return collect_fetch(args.stage, out_dir, fetch_dir, proxy_dir, max_bytes, proxy_cap, pin)
    finally:
        box.remove(run_name)
        if proxy is not None:
            proxy.stop()
        box.remove(proxy_name)
        box.remove_network(net_in)
        box.remove_network(net_out)
        shutil.rmtree(run_dir, ignore_errors=True)


def collect_fetch(stage, out_dir, fetch_dir, proxy_dir, max_bytes, proxy_cap, pin):
    names = scan(fetch_dir, fetch_allowed(stage), fetch_caps(stage, max_bytes))
    result = read_result(fetch_dir)
    parsed = read_proxy(proxy_dir)
    report = parsed or {"allowed": 0, "refused": 0, "refused_hosts": [], "sni_refused": 0, "bytes": 0}
    kept = [n for n in names if n != "result.json"]
    complete = (stage == "meta" and "info.json" in kept) or (stage == "video" and sum(1 for n in kept if VIDEO_FILE.fullmatch(n)) == 1)
    if result is None or not result["ok"] or not complete:
        code = result["code"] if result and result["code"] else "fetch_failed"
        if code == "fetch_failed" and report["refused"] > 0 and not kept:
            code = "network"
        elif code == "fetch_failed" and report["bytes"] >= proxy_cap:
            code = "too_large"
        raise Refusal("failed", code, "the fetch did not give the file (%s); the tool may be out of date" % code)
    info = None
    if "info.json" in kept:
        info = read_info(os.path.join(fetch_dir, "info.json"))
    sources = [(os.path.join(fetch_dir, n), n) for n in kept]
    if stage == "meta" and parsed is not None:    # the video stage's counts are in the answer only: proxy.json is already in the folder
        sources.append((os.path.join(proxy_dir, "proxy.json"), "proxy.json"))
    move_files(sources, out_dir)
    if info is None:
        info = read_info(os.path.join(out_dir, "info.json")) or {}
    files = [{"name": name, "size": os.path.getsize(os.path.join(out_dir, name)), "sha256": sha256_file(os.path.join(out_dir, name))}
             for _, name in sources]
    return {"ok": True, "stage": stage, "files": files, "duration": info.get("duration"), "width": info.get("width"), "height": info.get("height"),
            "subtitles": info.get("subtitles", "none"), "refused_hosts": len(report["refused_hosts"]), "bytes": report["bytes"], "tool": pin["version"]}


# --- measure ---------------------------------------------------------------------------------------------------------------------------


def cmd_measure(args):
    if not REFERENCE_ID.fullmatch(args.reference or "") or not PLATFORM_NAME.fullmatch(args.platform or ""):
        raise Refusal("usage", "bad_arguments", "a reference id or a platform name is not one the fetcher takes")
    limits = MEASURE_LIMITS
    folder = check_reference_folder(os.path.abspath(args.input))
    facts_path = os.path.abspath(args.out)
    parent = check_reference_folder(os.path.dirname(facts_path))
    if not facts_path.endswith(".json") or os.path.islink(facts_path) or (os.path.exists(facts_path) and not os.path.isfile(facts_path)):
        raise Refusal("usage", "out_refused", "the facts file must be a .json file that is not a link")
    total = 0
    for entry in os.scandir(folder):
        if entry.is_file(follow_symlinks=False):
            total += entry.stat(follow_symlinks=False).st_size
    if total > limits["input_bytes"]:
        raise Refusal("usage", "out_refused", "the reference folder holds more than the measure takes")
    pin = require_pin()
    require_docker()
    image = check_image()
    timeout = clamp(args.timeout or limits["timeout"], MIN_TIMEOUT, limits["timeout"])
    try:
        box.reap(LABEL_RUN)
    except box.ContainerError:
        pass
    token = uuid.uuid4().hex[:12]
    run_dir = os.path.join(parent, RUN_PREFIX + token)
    out_run = os.path.join(run_dir, "out")
    name = "openhora-fetch-measure-" + token
    os.mkdir(run_dir, 0o700)
    os.mkdir(out_run, 0o700)
    try:
        inner = ["--result", "/out/result.json", "measure", "--reference", args.reference, "--platform", args.platform]
        command = container_command(name, image["id"], inner, [(folder, "/in", "ro"), (out_run, "/out", "rw")], limits, "none", int(time.time()) + timeout + STOP_GRACE)
        try:
            run_container(command, name, timeout)
        except Refusal as e:
            raise Refusal("failed", "measure_failed" if e.code != "time_limit" else "time_limit", e.reason) from None
        try:
            scan(out_run, lambda n: n in ("result.json", "facts.json"), lambda n: FACTS_MAX_BYTES if n == "facts.json" else RESULT_MAX_BYTES)
        except Refusal:
            raise Refusal("failed", "measure_failed", "the measure left something other than the files it may leave") from None
        result = read_result(out_run)
        raw = read_regular(os.path.join(out_run, "facts.json"), FACTS_MAX_BYTES)
        if result is None or not result["ok"] or raw is None:
            raise Refusal("failed", "measure_failed", "the measure did not give a facts file")
        try:
            facts = json.loads(raw.decode("utf-8"))
            schema_check(facts, load_schema())
        except (ValueError, UnicodeDecodeError) as e:
            raise Refusal("failed", "facts_invalid", "the facts file differs from its schema at %s" % (e.args[0] if e.args else "?")) from None
        if facts["reference"] != args.reference or facts["platform"] != args.platform:
            raise Refusal("failed", "facts_invalid", "the facts file names another reference or platform")
        tmp = "%s.%s.tmp" % (facts_path, token)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(facts, f, ensure_ascii=False)
        os.replace(tmp, facts_path)
    finally:
        box.remove(name)
        shutil.rmtree(run_dir, ignore_errors=True)
    return {"ok": True, "reference": args.reference, "duration": facts["source"]["duration_s"], "subtitles": facts["source"]["subtitles"],
            "words": facts["speech"]["words"], "beats": facts["format"]["beat_count"], "cuts": facts["cuts"]["count"],
            "shot_seconds_mean": facts["cuts"]["shot_seconds"]["mean"], "frames_measured": facts["source"]["frames_measured"],
            "tool": pin["version"]}


# --- reap ------------------------------------------------------------------------------------------------------------------------------


def cmd_reap(args):
    root = os.path.abspath(args.root)
    try:
        marker = os.lstat(os.path.join(root, box.REFERENCE_MARKER))
        found = os.lstat(root)
    except OSError:
        raise Refusal("usage", "out_refused", "the folder holds no reference marker") from None
    if not stat.S_ISREG(marker.st_mode) or not stat.S_ISDIR(found.st_mode):
        raise Refusal("usage", "out_refused", "the folder holds no reference marker")
    require_docker()
    removed = box.reap(LABEL_RUN)
    cutoff = time.time() - (LONGEST_TIMEOUT + 600)
    folders = 0
    candidates = [root] + [e.path for e in os.scandir(root) if e.is_dir(follow_symlinks=False)]
    for base in candidates:
        for entry in os.scandir(base):
            try:
                if entry.name.startswith(RUN_PREFIX) and entry.is_dir(follow_symlinks=False) and entry.stat(follow_symlinks=False).st_mtime < cutoff:
                    shutil.rmtree(entry.path, ignore_errors=True)
                    folders += 1
            except OSError:
                continue
    return {"ok": True, "containers_removed": removed, "folders_removed": folders}


# --- command line ----------------------------------------------------------------------------------------------------------------------


def build_parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check", action="store_true", help="ready or not (exit 0, or 3 with the reason on stderr)")
    sub = p.add_subparsers(dest="verb")
    sub.add_parser("pin-show", help="the effective pin and what is missing from it")
    b = sub.add_parser("build", help="build the image (needs --confirmed)")
    b.add_argument("--confirmed", action="store_true")
    b.add_argument("--dry-run", action="store_true")
    r = sub.add_parser("reap", help="remove what a killed run left behind")
    r.add_argument("--root", required=True)
    f = sub.add_parser("fetch", help="fetch one public link (stage meta or video)")
    f.add_argument("--url", required=True)
    f.add_argument("--platform", required=True)
    f.add_argument("--platform-file", dest="platform_file", required=True)
    f.add_argument("--stage", required=True)
    f.add_argument("--out", required=True)
    f.add_argument("--language", required=True)
    f.add_argument("--max-seconds", dest="max_seconds", type=int)
    f.add_argument("--max-bytes", dest="max_bytes", type=int)
    f.add_argument("--timeout", type=int)
    m = sub.add_parser("measure", help="measure a reference folder (no network)")
    m.add_argument("--in", dest="input", required=True)
    m.add_argument("--out", required=True)
    m.add_argument("--reference", required=True)
    m.add_argument("--platform", required=True)
    m.add_argument("--timeout", type=int)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.check == bool(args.verb):
            raise Refusal("usage", "bad_arguments", "give --check or one verb (%s). See --help." % ", ".join(VERBS))
        if args.check:
            result = cmd_check(args)
        else:
            result = {"pin-show": cmd_pin_show, "build": cmd_build, "reap": cmd_reap, "fetch": cmd_fetch, "measure": cmd_measure}[args.verb](args)
    except Refusal as e:
        say("error: %s" % e.reason)
        print(json.dumps({"ok": False, "code": e.code}))
        return KINDS[e.kind]
    except Exception as e:   # a closed word, never the exception's text: it could quote a link
        say("error: unexpected failure (code internal-%s); its detail is not printed" % e.__class__.__name__)
        print(json.dumps({"ok": False, "code": "fetch_failed"}))
        return EXIT_FAILED
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
