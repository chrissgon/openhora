#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Transcriber provider: an implementation of the class transcriber:speech (providers/CONTRACT.md) that runs
whisper.cpp (whisper-cli) inside a container on this machine. Speech to text, word by word, with times; the audio never
leaves the computer and no model of any provider sees it. A runtime-only class: no skill requires it (the short-video
plan, decision D11). Standard library only; the docker command-line client is the one outside tool.

Verbs (JSON on stdout, diagnostics on stderr, input by flags, no prompt):
  --check [--model <name>]            ready or not: docker present and answering, the image built from this folder's
                                      definition and unchanged since it was built, and, with --model, the model file
                                      present and equal to its pinned sha256. Reads nothing secret, changes nothing.
  models                              the pinned models (name, file, size, source URL, sha256) and whether each file is
                                      in the models folder. Hashes nothing, fetches nothing.
  build (--confirmed | --dry-run)     build the image from providers/transcriber/Dockerfile (the one step that uses the
                                      network, at the person's word: it pulls the pinned base image and clones the pinned
                                      whisper.cpp tag). Prints the image id; records it in <state>/transcriber/image.json.
  transcribe --in <audio-or-video> --model <name> --language <code|auto> --out <transcript.json>
             [--timestamps word|ml1|dtw] [--timeout <s>] [--threads <n>] [--max-seconds <s>] [--memory-mb <n>]
             [--dry-run]              run the container and write the transcript (transcript.schema.json) to --out.
                                      --dry-run prints the exact docker command and runs nothing.

Timestamps (--timestamps), the three ways whisper.cpp can time a word; the comparison between them is the short-video
plan's check C3, and the provider takes no side:
  word  (default) -ojf: every token has its own start and end; tokens are joined into words by the leading space. The
        sentence segments whisper cut are kept, and the gaps between words are kept.
  ml1   -ojf -ml 1 -sow: whisper cuts a segment at every word. A word ends where the next begins, so a silence is absorbed
        by the word before it; the transcript's segments are then single words (facts.segment_unit says "word").
  dtw   -ojf -nfa -dtw <preset>: the start of each token from dynamic time warping over the attention heads (the preset
        of the model, models.json). A word ends where the next in its segment begins. whisper.cpp switches DTW off while
        flash attention is on, so -nfa is passed; a word without a DTW time fails the run instead of getting a made-up one.

The container (the limits are in code, tests/test_whispercpp.py names each): no network, a read-only root file system
with memory-backed /tmp and /scratch, every capability dropped and no new privileges, a non-root user, a limit on
processes, memory (swap included) and CPUs, no environment variable of the host, the input and the model mounted
read-only, one folder mounted read-write for the output, an image that is never pulled at run time, and a timeout after
which the container is removed by name (also when this process is stopped). The model's sha256 is computed and compared
with the pin before any container starts. The image is run by its id, which must be the one recorded at build time.

The text of the audio is never printed: the container's output is discarded, whisper's logs are off (-np), the verbs
print counts, never words, and an error shows the last 300 characters of the container's stderr, which holds the tools'
error lines only. Credentials: none are read, passed or needed (the docker client's own sign-in is used by `build` alone,
to pull the base image, and is the person's).

State, under the state folder (OPENHORA_STATE_DIR, else an absolute XDG_STATE_HOME + /openhora, else
~/.local/state/openhora; the rule of providers/messenger/whatsapp.py): transcriber/models/<file> (the model files, put
there by hand: README.md gives the commands) and transcriber/image.json (what `build` recorded). --models-dir <path>
names another models folder.

Exit codes (providers/CONTRACT.md): 0 ok; 1 failed (the container failed or timed out, a model file differs from its pin,
whisper's output is not what was expected); 2 usage (also: an input longer than --max-seconds); 3 not configured (docker
absent or stopped, the image not built, stale or replaced, a model missing or not pinned).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_NOT_CONFIGURED = 0, 1, 2, 3
KINDS = {"failed": EXIT_FAILED, "usage": EXIT_USAGE, "not-configured": EXIT_NOT_CONFIGURED}

HERE = os.path.dirname(os.path.abspath(__file__))
DOCKERFILE = "Dockerfile"
DEFINITION_FILES = ("Dockerfile", "transcribe.sh", ".dockerignore")  # what the image's definition hash covers
MODELS_FILE = os.path.join(HERE, "models.json")
SCHEMA_VERSION = 1
PROVIDER_NAME = "whisper.cpp"

IMAGE_REPOSITORY = "openhora-transcriber"
LABEL_DEFINITION = "org.openhora.definition"
LABEL_TAG, LABEL_COMMIT = "org.openhora.whisper-cpp.tag", "org.openhora.whisper-cpp.commit"
STATE_ENV = "OPENHORA_STATE_DIR"
STATE_FOLDER, MODELS_FOLDER, BUILD_RECORD = "transcriber", "models", "image.json"

# The verbs, in the order the command line lists them (scripts/architecture_tables.py reads this line as text).
VERBS = ("models", "build", "transcribe")
TIMESTAMPS = ("word", "ml1", "dtw")
LANGUAGE = re.compile(r"[a-z]{2,3}|auto")
MODEL_NAME = re.compile(r"[a-z0-9][a-z0-9.-]*")

# The limits of one container (a test names each).
PIDS_LIMIT = 256
TMP_SIZE_MB, SCRATCH_SIZE_MB = 64, 256
MOUNT_INPUT, MOUNT_MODEL, MOUNT_OUT = "/in/input", "/models/model.bin", "/out"
MIN_TIMEOUT, DEFAULT_TIMEOUT, MAX_TIMEOUT = 10, 1800, 7200
DEFAULT_MAX_SECONDS, MAX_MAX_SECONDS = 300, 3600     # the audio the container accepts, in seconds
MAX_THREADS = 32
BUILD_TIMEOUT = 3600
PROBE_TIMEOUT = 60
MAX_WHISPER_JSON = 64 * 1024 * 1024
MAX_TRANSCRIPT_BYTES = 5 * 1024 * 1024               # the run copy's scan limit (the short-video plan, P4)
STDERR_TAIL = 300
# The only variables the docker client is given: where it finds its daemon and its own configuration. No variable of
# the host reaches the container either way: the run passes no -e and no --env-file.
DOCKER_CLIENT_ENV = ("PATH", "HOME", "USER", "TMPDIR", "LANG", "LC_ALL", "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME",
                     "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH")
# whisper-cli flags, as transcribe.sh passes them (a test holds the two equal).
BASE_FLAGS = ("-np", "-ng", "-ojf")
MODE_FLAGS = {"word": (), "ml1": ("-ml", "1", "-sow"), "dtw": ("-nfa",)}


class Refusal(Exception):
    """A verb that stops: `kind` is the exit code's reading ("failed", "usage" or "not-configured")."""

    def __init__(self, kind, reason):
        super().__init__(reason)
        self.kind = kind
        self.reason = reason


def say(text):
    print(text, file=sys.stderr)


def tail(text, limit=STDERR_TAIL):
    return " ".join((text or "").split())[-limit:]


# --- the definition, the pins, the models ------------------------------------------------------------------------------


def definition_hash(folder=HERE):
    """sha256 over the files of the image's definition: sorted names and their bytes."""
    h = hashlib.sha256()
    for name in sorted(DEFINITION_FILES):
        with open(os.path.join(folder, name), "rb") as f:
            h.update(name.encode() + b"\0" + f.read() + b"\0")
    return h.hexdigest()


def image_tag(folder=HERE):
    return f"{IMAGE_REPOSITORY}:{definition_hash(folder)[:12]}"


def dockerfile_pins(folder=HERE):
    """(whisper.cpp tag, whisper.cpp commit), read from the ARG lines of the Dockerfile: the one place they are written."""
    with open(os.path.join(folder, DOCKERFILE), encoding="utf-8") as f:
        text = f.read()
    tag = re.search(r"^ARG WHISPER_CPP_TAG=(\S+)$", text, re.M)
    commit = re.search(r"^ARG WHISPER_CPP_COMMIT=([0-9a-f]{40})$", text, re.M)
    if not tag or not commit:
        raise Refusal("failed", "the Dockerfile does not pin WHISPER_CPP_TAG and WHISPER_CPP_COMMIT")
    return tag.group(1), commit.group(1)


def load_models(path=None):
    with open(path or MODELS_FILE, encoding="utf-8") as f:
        doc = json.load(f)
    return {m["name"]: m for m in doc["models"]}


def model_entry(name, models=None):
    models = load_models() if models is None else models
    if not isinstance(name, str) or not MODEL_NAME.fullmatch(name) or name not in models:
        raise Refusal("usage", f"unknown model {name!r}; pinned models: {', '.join(sorted(models))}")
    return models[name]


def state_dir():
    chosen = os.environ.get(STATE_ENV)
    if chosen:
        return os.path.abspath(chosen)
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg and os.path.isabs(xdg):
        return os.path.join(xdg, "openhora")
    return os.path.join(os.path.expanduser("~"), ".local", "state", "openhora")


def own_dir():
    return os.path.join(state_dir(), STATE_FOLDER)


def private_dir(path, what):
    """Make `path` (0700) when missing and check it: a real directory, this user's, closed to the group and others."""
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
        found = os.lstat(path)
    except OSError as e:
        raise Refusal("not-configured", f"the {what} {path} cannot be made ({e.strerror or e.__class__.__name__})")
    if not stat.S_ISDIR(found.st_mode):
        raise Refusal("not-configured", f"the {what} {path} is not a real directory; remove it")
    if found.st_uid != os.getuid():
        raise Refusal("not-configured", f"the {what} {path} is not owned by this user")
    if found.st_mode & 0o077:
        raise Refusal("not-configured", f"the {what} {path} is open to other users (mode {stat.S_IMODE(found.st_mode):04o}); "
                                        "run chmod 700 on it")
    return path


def models_folder(chosen=None):
    return os.path.abspath(chosen) if chosen else os.path.join(own_dir(), MODELS_FOLDER)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def model_state(entry, folder, hashed=True):
    """(path, status) of a model file: "unpinned" (the pin is null: refused until pinned), "missing", "not-a-file",
    "mismatch" (the file's sha256 differs from the pin) or "ok". With hashed False the file is not read: "present"."""
    path = os.path.join(folder, entry["file"])
    if not entry.get("sha256"):
        return path, "unpinned"
    try:
        found = os.lstat(path)
    except FileNotFoundError:
        return path, "missing"
    except OSError:
        return path, "not-a-file"
    if not stat.S_ISREG(found.st_mode):
        return path, "not-a-file"  # a link or a folder: the file hashed is the file mounted, so neither is accepted
    if not hashed:
        return path, "present"
    return path, "ok" if sha256_file(path) == entry["sha256"] else "mismatch"


def verified_model(name, folder):
    """The model's entry and path after its sha256 was computed and compared with the pin. Raises Refusal."""
    entry = model_entry(name)
    path, status = model_state(entry, folder)
    if status == "unpinned":
        raise Refusal("not-configured", f"model {name} has no pinned sha256 in models.json yet; pin it before using it")
    if status in ("missing", "not-a-file"):
        raise Refusal("not-configured", f"model {name} is not at {path} (a regular file is expected); "
                                        f"see providers/transcriber/README.md for where to get {entry['file']}")
    if status == "mismatch":
        raise Refusal("failed", f"{path} does not match the pinned sha256 of model {name}: it is damaged or another file; "
                                "delete it and get it again")
    return entry, path


# --- docker -------------------------------------------------------------------------------------------------------------


def docker_environment(env=None):
    env = os.environ if env is None else env
    return {k: env[k] for k in DOCKER_CLIENT_ENV if env.get(k)}


def docker_binary():
    found = shutil.which("docker")
    if not found:
        raise Refusal("not-configured", "docker is not installed or not on PATH (the transcriber runs whisper.cpp in a container)")
    return found


def docker(args, timeout=PROBE_TIMEOUT):
    """Run the docker client with a clean environment; the completed process. Raises Refusal when it cannot start or hangs."""
    try:
        return subprocess.run([docker_binary(), *args], capture_output=True, text=True, timeout=timeout,
                              env=docker_environment(), check=False)
    except subprocess.TimeoutExpired:
        raise Refusal("failed", f"docker {args[0]} did not answer within {timeout} s") from None
    except OSError as e:
        raise Refusal("not-configured", f"docker could not be started ({e.strerror or e.__class__.__name__})") from None


def require_docker():
    done = docker(["version", "--format", "{{.Server.Version}}"])
    if done.returncode != 0:
        raise Refusal("not-configured", "the docker daemon is not answering: start it. " + tail(done.stderr, 160))
    return done.stdout.strip()


def inspect_image(reference):
    """The `docker image inspect` record of an image (its id and labels), or None when there is no such image."""
    done = docker(["image", "inspect", reference])
    if done.returncode != 0:
        return None
    try:
        found = json.loads(done.stdout)[0]
        return {"id": found["Id"], "labels": (found.get("Config") or {}).get("Labels") or {}}
    except (ValueError, KeyError, IndexError, TypeError):
        raise Refusal("failed", "docker image inspect did not answer with an image record") from None


def read_record(folder=None):
    path = os.path.join(folder or own_dir(), BUILD_RECORD)
    try:
        with open(path, encoding="utf-8") as f:
            record = json.load(f)
        return record if isinstance(record, dict) else None
    except (OSError, ValueError):
        return None


def check_image():
    """The image this folder's definition describes, ready to run: it exists, carries this definition's hash, and is the
    one `build` recorded (a tag can be pointed at another image; the id cannot). Raises Refusal("not-configured")."""
    tag, wanted = image_tag(), definition_hash()
    image = inspect_image(tag)
    build = "python3 providers/transcriber/whispercpp.py build --confirmed"
    if image is None:
        raise Refusal("not-configured", f"the image {tag} is not built: run `{build}` (it downloads the base image and the "
                                        "whisper.cpp source; see providers/transcriber/README.md)")
    if image["labels"].get(LABEL_DEFINITION) != wanted:
        raise Refusal("not-configured", f"the image {tag} was not built from the definition in this folder: run `{build}`")
    record = read_record()
    if record is None or record.get("image_id") != image["id"]:
        raise Refusal("not-configured", f"the image {tag} is not the one `build` recorded (or nothing was recorded): "
                                        f"remove it with `docker image rm {tag}` and run `{build}`")
    return {"tag": tag, "id": image["id"], "definition": wanted,
            "whisper_cpp_tag": image["labels"].get(LABEL_TAG), "whisper_cpp_commit": image["labels"].get(LABEL_COMMIT)}


# --- check, models, build ----------------------------------------------------------------------------------------------


def cmd_check(args):
    server = require_docker()
    image = check_image()
    out = {"ok": True, "docker_server": server, "image": image}
    if args.model:
        entry, _ = verified_model(args.model, models_folder(args.models_dir))
        out["model"] = {"name": entry["name"], "file": entry["file"], "sha256": entry["sha256"]}
    return out


def cmd_models(args):
    folder = models_folder(args.models_dir)
    rows = []
    for entry in load_models().values():
        path, status = model_state(entry, folder, hashed=False)
        rows.append({"name": entry["name"], "file": entry["file"], "size": entry["size"], "sha256": entry["sha256"],
                     "url": entry["url"], "path": path, "file_status": status})
    return {"models_folder": folder, "models": rows}


def build_argv(folder=HERE):
    return ["build", "--tag", image_tag(folder), "--build-arg", f"DEFINITION_HASH={definition_hash(folder)}",
            "--file", os.path.join(folder, DOCKERFILE), folder]


def write_private_json(path, value):
    """Write JSON to `path` (0600) through a temporary file and a rename."""
    tmp = f"{path}.{uuid.uuid4().hex[:8]}.tmp"
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
        raise Refusal("usage", "build downloads the base image and the whisper.cpp source and writes a local image: "
                               "it needs --confirmed (or --dry-run to see the command). The person starts it, never a run.")
    tag, commit = dockerfile_pins()
    argv = build_argv()
    plan = {"command": ["docker"] + argv, "image": image_tag(), "definition": definition_hash(),
            "whisper_cpp_tag": tag, "whisper_cpp_commit": commit}
    if args.dry_run:
        return dict(plan, dry_run=True)
    require_docker()
    say(f"building {plan['image']} (whisper.cpp {tag}); this downloads the base image and the source and takes a while")
    try:
        done = subprocess.run([docker_binary(), *argv], timeout=BUILD_TIMEOUT, env=docker_environment(), check=False,
                              stdout=2, stderr=2)  # docker's progress goes to this process's stderr
    except subprocess.TimeoutExpired:
        raise Refusal("failed", f"docker build did not finish within {BUILD_TIMEOUT} s") from None
    if done.returncode != 0:
        raise Refusal("failed", f"docker build failed (exit {done.returncode}); its output is above")
    image = inspect_image(plan["image"])
    if image is None or image["labels"].get(LABEL_DEFINITION) != plan["definition"]:
        raise Refusal("failed", "docker build ended well but the image is missing or does not carry this definition's hash")
    private_dir(state_dir(), "state folder")
    folder = private_dir(own_dir(), "transcriber folder")
    write_private_json(os.path.join(folder, BUILD_RECORD),
                       {"image_tag": plan["image"], "image_id": image["id"], "definition": plan["definition"],
                        "whisper_cpp_tag": tag, "whisper_cpp_commit": commit, "built_at": utc_now()})
    return {"ok": True, "image": plan["image"], "image_id": image["id"], "whisper_cpp_tag": tag, "whisper_cpp_commit": commit,
            "record": os.path.join(folder, BUILD_RECORD)}


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --- transcribe ---------------------------------------------------------------------------------------------------------


def whisper_flags(mode, preset, language, threads):
    """The whisper-cli flags transcribe.sh passes for a request (recorded in the transcript's facts)."""
    flags = list(BASE_FLAGS) + ["-l", language, "-t", str(threads)] + list(MODE_FLAGS[mode])
    if mode == "dtw":
        flags += ["-dtw", preset]
    return flags


def container_argv(name, image_id, in_path, model_path, out_dir, *, threads, language, mode, preset, max_seconds,
                   memory_mb, cpus, platform=None):
    """The exact `docker run` command (a list; the first word is `docker`). Every limit of the container is here."""
    platform = sys.platform if platform is None else platform
    argv = ["docker", "run", "--rm", "--init", "--pull", "never", "--name", name,
            "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", str(PIDS_LIMIT),
            "--memory", f"{memory_mb}m", "--memory-swap", f"{memory_mb}m", "--cpus", str(cpus),
            "--tmpfs", f"/tmp:rw,noexec,nosuid,nodev,size={TMP_SIZE_MB}m",
            "--tmpfs", f"/scratch:rw,noexec,nosuid,nodev,size={SCRATCH_SIZE_MB}m,mode=1777"]
    if platform.startswith("linux"):  # a bind mount keeps numeric owners there; elsewhere the runtime maps them
        argv += ["--user", f"{os.getuid()}:{os.getgid()}"]
    argv += ["-v", f"{in_path}:{MOUNT_INPUT}:ro", "-v", f"{model_path}:{MOUNT_MODEL}:ro", "-v", f"{out_dir}:{MOUNT_OUT}:rw",
             image_id, str(threads), language, mode, preset or "-", str(max_seconds)]
    return argv


def remove_container(name):
    """End a container by name: the docker client's process ending does not end it. Never raises."""
    try:
        docker(["rm", "-f", name], timeout=60)
    except Refusal:
        pass


class Stopped(Exception):
    """This process was asked to stop (SIGTERM or SIGINT) while the container ran."""


def run_container(argv, name, timeout):
    """Run the container: (returncode, stderr). The container is removed by name when the timeout passes, when this
    process is stopped and when anything else goes wrong; on a normal end `--rm` has already removed it."""
    def stop(signum, frame):
        raise Stopped()

    previous = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            previous.append((sig, signal.signal(sig, stop)))
        except ValueError:  # not the main thread: the finally below still covers a timeout and an error
            pass
    proc = None
    finished = False
    try:
        try:
            proc = subprocess.Popen([docker_binary()] + argv[1:], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, text=True, env=docker_environment(), start_new_session=True)
        except OSError as e:
            raise Refusal("not-configured", f"docker could not be started ({e.strerror or e.__class__.__name__})") from None
        try:
            _, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            raise Refusal("failed", f"the transcription ran over {timeout} s: the container was removed") from None
        finished = True
        return proc.returncode, stderr or ""
    except Stopped:
        raise Refusal("failed", "stopped: the container was removed") from None
    finally:
        if not finished:
            remove_container(name)
            if proc is not None and proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    pass
                proc.wait()
        for sig, handler in previous:
            signal.signal(sig, handler)


def read_text(path, limit=64):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read(limit).strip()
    except OSError:
        return ""


def read_seconds(path, what):
    try:
        value = float(read_text(path))
    except ValueError:
        raise Refusal("failed", f"the container did not report {what}") from None
    if value != value or value < 0 or value > 10 ** 6:
        raise Refusal("failed", f"the container reported an impossible {what}")
    return value


def is_special(text):
    """A whisper control token ([_BEG_], [_TT_150], <|en|>): it is not a word."""
    return bool(re.fullmatch(r"\[_[A-Za-z0-9_]*\]", text) or re.fullmatch(r"<\|[^|]*\|>", text))


def is_annotation(text):
    """A non-speech note whisper writes ([BLANK_AUDIO], [Music], (applause), *music*): kept in the segment's text, not a word."""
    return bool(re.fullmatch(r"\[[^\]]*\]|\([^)]*\)|\*[^*]*\*|♪+", text.strip()))


def seconds_from_ms(ms):
    return round(ms / 1000.0, 3)


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


JOINING_DASHES = set("-\u2013\u2014\u2026.")
NOTE_CLOSER = {"[": "]", "(": ")"}
NOTE_MAX_WORDS = 6


def tokens_to_words(tokens):
    """Join a segment's tokens into words. A token that starts with a space starts a word; a token without one continues the
    word before it (so does a dash or an ellipsis that has a space, which is punctuation, not a word). Control tokens are
    dropped and a whitespace-only token ends a word. Returns a list of {"text", "tokens"} in order."""
    words, boundary = [], True
    for tok in tokens:
        text = tok.get("text")
        if not isinstance(text, str) or is_special(text):
            continue
        if text.strip() == "":
            boundary = True
            continue
        spaced = text[0].isspace()
        joins = bool(words) and (not boundary and not spaced or set(text.strip()) <= JOINING_DASHES)
        if joins:
            words[-1]["text"] += text.strip()
            words[-1]["tokens"].append(tok)
        else:
            words.append({"text": text.strip(), "tokens": [tok]})
        boundary = False
    return words


def without_notes(words):
    """Drop the non-speech notes whisper writes: a word that is one ([BLANK_AUDIO], (applause), ♪), or a run of up to six
    words from one that opens a bracket to one that closes it ([ Silence ]). Returns the words kept and the number of notes."""
    kept, dropped, i = [], 0, 0
    while i < len(words):
        text = words[i]["text"]
        if is_annotation(text):
            dropped, i = dropped + 1, i + 1
            continue
        closer = NOTE_CLOSER.get(text[:1])
        end = next((j for j in range(i + 1, min(i + NOTE_MAX_WORDS, len(words)))
                    if closer and closer in words[j]["text"]), None) if closer and closer not in text else None
        if end is not None:
            dropped, i = dropped + 1, end + 1
            continue
        kept.append(words[i])
        i += 1
    return kept, dropped


def token_offsets(tok):
    """(start ms, end ms) of a token from -ojf's "offsets", or None when whisper gave it no times."""
    found = tok.get("offsets")
    if isinstance(found, dict) and number(found.get("from")) and number(found.get("to")):
        return found["from"], found["to"]
    return None


def mean_probability(tokens):
    values = [t["p"] for t in tokens if number(t.get("p")) and 0 <= t["p"] <= 1]
    return round(sum(values) / len(values), 3) if values else None


def word_times(joined, mode, seg_start, seg_end):
    """(start ms, end ms, estimated) for each word of one segment.
    word, ml1: the first timed token's start and the last timed token's end.
    dtw: the DTW start of the word's first token (centiseconds, so x10); the end is the start of the next word of the
    segment, else the end of its last timed token, else the segment's end. A word with no DTW time raises.
    A word whisper gave no times (word, ml1) lies between its neighbours and is marked estimated."""
    starts, ends = [], []
    for word in joined:
        spans = [s for s in (token_offsets(t) for t in word["tokens"]) if s]
        if mode == "dtw":
            dtw = [t["t_dtw"] * 10 for t in word["tokens"] if number(t.get("t_dtw")) and t["t_dtw"] >= 0]
            if not dtw:
                raise Refusal("failed", "whisper gave a word no DTW time: the model's DTW preset does not apply, or flash "
                                        "attention was on")
            starts.append(dtw[0])
            ends.append(spans[-1][1] if spans else seg_end)
        else:
            starts.append(spans[0][0] if spans else None)
            ends.append(spans[-1][1] if spans else None)
    if mode == "dtw":
        ends = [starts[k + 1] if k + 1 < len(starts) else ends[k] for k in range(len(starts))]
    out = []
    for k in range(len(joined)):
        if starts[k] is not None:
            out.append((starts[k], ends[k], False))
            continue
        before = next((ends[j] for j in range(k - 1, -1, -1) if ends[j] is not None), seg_start)
        after = next((starts[j] for j in range(k + 1, len(starts)) if starts[j] is not None), seg_end)
        out.append((before, after, True))
    return out


def parse_whisper(raw, mode):
    """Whisper's -ojf document -> (language, segments, words, counts): the transcript schema's words and segments.
    mode is word, ml1 or dtw. Raises Refusal("failed") for a document that is not -ojf's."""
    if not isinstance(raw, dict) or not isinstance(raw.get("transcription"), list):
        raise Refusal("failed", "whisper's output has no transcription list")
    language = raw["result"].get("language") if isinstance(raw.get("result"), dict) else None
    segments, words = [], []
    counts = {"words_without_timing": 0, "clamped_words": 0, "dropped_annotations": 0}
    for index, seg in enumerate(raw["transcription"]):
        offsets = seg.get("offsets") if isinstance(seg, dict) else None
        if not isinstance(offsets, dict) or not number(offsets.get("from")) or not number(offsets.get("to")):
            raise Refusal("failed", f"whisper's segment {index} has no times")
        seg_start, seg_end = offsets["from"], max(offsets["to"], offsets["from"])
        if not isinstance(seg.get("tokens"), list):
            raise Refusal("failed", "whisper's output has no tokens: it was not run with -ojf")
        joined, dropped = without_notes(tokens_to_words(seg["tokens"]))
        counts["dropped_annotations"] += dropped
        first = len(words)
        for word, (start, end, estimated) in zip(joined, word_times(joined, mode, seg_start, seg_end)):
            if end < start:
                end = start
                counts["clamped_words"] += 1
            entry = {"index": len(words), "text": word["text"], "start": seconds_from_ms(max(start, 0)),
                     "end": seconds_from_ms(max(end, 0)), "segment": index}
            probability = mean_probability(word["tokens"])
            if probability is not None:
                entry["probability"] = probability
            if estimated:
                entry["estimated"] = True
                counts["words_without_timing"] += 1
            words.append(entry)
        text = seg.get("text")
        segments.append({"index": index, "start": seconds_from_ms(max(seg_start, 0)), "end": seconds_from_ms(max(seg_end, 0)),
                         "text": text.strip() if isinstance(text, str) else "",
                         "first_word": first if len(words) > first else None,
                         "last_word": len(words) - 1 if len(words) > first else None})
    return language, segments, words, counts


WORD_KEYS = {"index", "text", "start", "end", "segment", "probability", "estimated"}
SEGMENT_KEYS = {"index", "start", "end", "text", "first_word", "last_word"}
DOCUMENT_KEYS = {"schema_version", "language", "duration", "words", "segments", "facts"}
FACT_KEYS = ("provider", "whisper_cpp_tag", "whisper_cpp_commit", "image_id", "model", "timestamps", "flags",
             "language_requested", "language_detected", "segment_unit", "input_duration", "wall_seconds",
             "words_without_timing", "clamped_words", "dropped_annotations")


def check_transcript(doc):
    """The constraints of transcript.schema.json, checked without a schema library. Raises Refusal("failed")."""
    def need(ok, what):
        if not ok:
            raise Refusal("failed", f"the transcript is not valid: {what}")

    need(isinstance(doc, dict) and doc.get("schema_version") == SCHEMA_VERSION, "schema_version")
    need(set(doc) == DOCUMENT_KEYS, "the top-level keys")
    need(isinstance(doc.get("language"), str) and re.fullmatch(r"[a-z]{2,3}", doc["language"]), "language")
    need(number(doc.get("duration")) and doc["duration"] >= 0, "duration")
    need(isinstance(doc.get("facts"), dict) and all(k in doc["facts"] for k in FACT_KEYS), "facts")
    words, segments = doc.get("words"), doc.get("segments")
    need(isinstance(words, list) and isinstance(segments, list), "words and segments are lists")
    for i, seg in enumerate(segments):
        need(isinstance(seg, dict) and seg.get("index") == i and set(seg) == SEGMENT_KEYS, f"segment {i} has index {i} and its keys")
        need(number(seg.get("start")) and number(seg.get("end")) and 0 <= seg["start"] <= seg["end"], f"segment {i} times")
        need(isinstance(seg.get("text"), str), f"segment {i} text")
        for key in ("first_word", "last_word"):
            need(seg.get(key) is None or (isinstance(seg[key], int) and 0 <= seg[key] < len(words)), f"segment {i} {key}")
    for i, word in enumerate(words):
        need(isinstance(word, dict) and word.get("index") == i and set(word) <= WORD_KEYS, f"word {i} has index {i} and its keys")
        need(isinstance(word.get("text"), str) and word["text"] != "", f"word {i} text")
        need(number(word.get("start")) and number(word.get("end")) and 0 <= word["start"] <= word["end"], f"word {i} times")
        need(isinstance(word.get("segment"), int) and 0 <= word["segment"] < len(segments), f"word {i} segment")
        need("probability" not in word or (number(word["probability"]) and 0 <= word["probability"] <= 1), f"word {i} probability")
        need("estimated" not in word or word["estimated"] is True, f"word {i} estimated")


def build_transcript(raw, mode, *, requested, duration, facts):
    language, segments, words, counts = parse_whisper(raw, mode)
    language = language or requested
    if not language or language == "auto":
        raise Refusal("failed", "whisper did not say which language it transcribed")
    facts = dict(facts, language_requested=requested, language_detected=language,
                 segment_unit="word" if mode == "ml1" else "sentence", **counts)
    doc = {"schema_version": SCHEMA_VERSION, "language": language, "duration": round(duration, 3),
           "words": words, "segments": segments, "facts": facts}
    check_transcript(doc)
    return doc


def positive_int(value, low, high, what):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise Refusal("usage", f"{what} must be a whole number from {low} to {high}")
    return value


def default_threads():
    return max(1, min(4, os.cpu_count() or 1))


def cmd_transcribe(args):
    started = time.monotonic()
    mode = args.timestamps
    if mode not in TIMESTAMPS:
        raise Refusal("usage", f"--timestamps must be one of {', '.join(TIMESTAMPS)}")
    if not LANGUAGE.fullmatch(args.language or ""):
        raise Refusal("usage", "--language must be a two or three letter code in lower case (pt, en, es) or auto")
    threads = positive_int(args.threads if args.threads is not None else default_threads(), 1, MAX_THREADS, "--threads")
    timeout = positive_int(args.timeout if args.timeout is not None else DEFAULT_TIMEOUT, MIN_TIMEOUT, MAX_TIMEOUT, "--timeout")
    max_seconds = positive_int(args.max_seconds if args.max_seconds is not None else DEFAULT_MAX_SECONDS, 1,
                               MAX_MAX_SECONDS, "--max-seconds")
    entry = model_entry(args.model)
    memory_mb = positive_int(args.memory_mb if args.memory_mb is not None else entry["memory_mb"], 512, 65536, "--memory-mb")
    in_path = os.path.realpath(args.input) if args.input else ""
    if not in_path or not os.path.isfile(in_path) or os.path.getsize(in_path) == 0:
        raise Refusal("usage", "--in must be a file that exists and is not empty")
    if not args.out or not args.out.endswith(".json"):
        raise Refusal("usage", "--out must be a path that ends in .json")
    out_path = os.path.abspath(args.out)
    out_parent = os.path.dirname(out_path)
    if not os.path.isdir(out_parent):
        raise Refusal("usage", f"the folder of --out does not exist: {out_parent}")
    if os.path.islink(out_path) or (os.path.exists(out_path) and not os.path.isfile(out_path)):
        raise Refusal("usage", "--out is a link or not a file: it is not overwritten")
    preset = entry.get("dtw_preset") if mode == "dtw" else None
    if mode == "dtw" and not preset:
        raise Refusal("usage", f"model {entry['name']} has no DTW preset in models.json")
    name = f"openhora-whisper-{uuid.uuid4().hex[:16]}"
    folder = models_folder(args.models_dir)
    if args.dry_run:
        argv = container_argv(name, "<image id>", in_path, os.path.join(folder, entry["file"]), "<temporary output folder>",
                              threads=threads, language=args.language, mode=mode, preset=preset, max_seconds=max_seconds,
                              memory_mb=memory_mb, cpus=threads)
        return {"dry_run": True, "command": argv, "model_sha256_pinned": entry["sha256"], "timeout_seconds": timeout}

    require_docker()
    _, model_path = verified_model(args.model, folder)     # the hash is compared before any container exists
    image = check_image()
    work = tempfile.mkdtemp(prefix=".transcribe-", dir=out_parent)  # 0700, beside --out; removed below
    try:
        argv = container_argv(name, image["id"], in_path, model_path, work, threads=threads, language=args.language,
                              mode=mode, preset=preset, max_seconds=max_seconds, memory_mb=memory_mb, cpus=threads)
        began = time.monotonic()
        code, stderr = run_container(argv, name, timeout)
        wall = time.monotonic() - began
        if code == 20:
            raise Refusal("usage", f"the input is longer than --max-seconds ({max_seconds})")
        if code == 21:
            raise Refusal("usage", "the input's duration cannot be read: it is not a media file whisper's tools open")
        if code != 0:
            raise Refusal("failed", f"the container ended with exit {code}: {tail(stderr)}")
        produced = os.path.join(work, "transcript.json")
        try:
            size = os.lstat(produced).st_size
        except OSError:
            raise Refusal("failed", "the container ended well but wrote no transcript.json") from None
        if size > MAX_WHISPER_JSON:
            raise Refusal("failed", "whisper's output is larger than the limit")
        with open(produced, "rb") as f:
            text = f.read().decode("utf-8", errors="replace")
        try:
            raw = json.loads(text)
        except ValueError:
            raise Refusal("failed", "whisper's output is not JSON") from None
        flags = whisper_flags(mode, preset, args.language, threads)
        facts = {"provider": PROVIDER_NAME, "whisper_cpp_tag": image["whisper_cpp_tag"],
                 "whisper_cpp_commit": image["whisper_cpp_commit"], "image_id": image["id"],
                 "image_definition": image["definition"],
                 "model": {"name": entry["name"], "file": entry["file"], "sha256": entry["sha256"]},
                 "timestamps": mode, "flags": flags, "threads": threads, "cpus": threads, "memory_mb": memory_mb,
                 "max_seconds": max_seconds, "input_bytes": os.path.getsize(in_path),
                 "input_duration": round(read_seconds(os.path.join(work, "input_duration.txt"), "the input's duration"), 3),
                 "wall_seconds": round(wall, 2), "created_at": utc_now()}
        duration = read_seconds(os.path.join(work, "audio_duration.txt"), "the audio's duration")
        doc = build_transcript(raw, mode, requested=args.language, duration=duration, facts=facts)
        doc["facts"]["total_seconds"] = round(time.monotonic() - started, 2)
        blob = json.dumps(doc, ensure_ascii=False, indent=1) + "\n"
        if len(blob.encode("utf-8")) > MAX_TRANSCRIPT_BYTES:
            raise Refusal("failed", "the transcript is larger than 5 MiB, the limit of a run copy")
        tmp = f"{out_path}.{uuid.uuid4().hex[:8]}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(blob)
        os.replace(tmp, out_path)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"ok": True, "out": out_path, "language": doc["language"], "duration": doc["duration"], "words": len(doc["words"]),
            "segments": len(doc["segments"]), "wall_seconds": doc["facts"]["wall_seconds"], "image_id": image["id"],
            "model": entry["name"], "timestamps": mode}


# --- command line -------------------------------------------------------------------------------------------------------


def build_parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check", action="store_true", help="ready or not (exit 0, or 3 with the reason on stderr)")
    p.add_argument("--model", help="with --check: also check this model's file against its pinned sha256")
    p.add_argument("--models-dir", help="the folder of the model files (default: <state>/transcriber/models)")
    sub = p.add_subparsers(dest="verb")
    m = sub.add_parser("models", help="the pinned models and whether their files are present")
    m.add_argument("--models-dir", default=argparse.SUPPRESS)
    b = sub.add_parser("build", help="build the image (needs --confirmed)")
    b.add_argument("--confirmed", action="store_true")
    b.add_argument("--dry-run", action="store_true")
    t = sub.add_parser("transcribe", help="transcribe one file")
    t.add_argument("--in", dest="input", required=True)
    t.add_argument("--model", required=True, default=argparse.SUPPRESS)
    t.add_argument("--language", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--timestamps", default="word", choices=TIMESTAMPS)
    t.add_argument("--timeout", type=int)
    t.add_argument("--threads", type=int)
    t.add_argument("--max-seconds", dest="max_seconds", type=int)
    t.add_argument("--memory-mb", dest="memory_mb", type=int)
    t.add_argument("--models-dir", default=argparse.SUPPRESS)
    t.add_argument("--dry-run", action="store_true")
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.check == bool(args.verb):
            raise Refusal("usage", "give --check or one verb (models, build, transcribe). See --help.")
        if args.check:
            result = cmd_check(args)
        else:
            result = {"models": cmd_models, "build": cmd_build, "transcribe": cmd_transcribe}[args.verb](args)
    except Refusal as e:
        say(f"error: {e.reason}")
        return KINDS[e.kind]
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
