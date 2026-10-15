#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The runner of a project's own script (class script:project, package P9). A class the runtime uses, not one a skill may require: the
step kind `project-script` (runtime/step_project_script.py) is its one caller, and it is on purpose not in contracts/environment.md.
It does one thing: run one script file, whose bytes the runtime has already checked against the person's approval, in a sandboxed
container, and hand back the one result file the script made. Everything it starts is made here, labelled `org.openhora.script` with a
deadline, named `openhora-script-<role>-<16 hex>` (a name the eval harness's orphan sweep, runtime/orphans.py, never selects) and removed
by name when the run ends; what a SIGKILL leaves is reaped by the next run (the `reap` verb) from the labels.

What a run is (the limits are providers/_container.py's argv, with the additions below; no flag is turned off):

  - no network, or, when the step declares destinations, only a per-step INTERNAL network (`docker network create --internal` with the
    gateway mode `isolated`: no route out, no external DNS, and no address of the host on it; read back, and refused without the
    isolation) whose other member is the step's egress proxy (providers/script/egress_proxy.py, same image): CONNECT
    to the declared host:port pairs and nothing else, refusing by name and by address;
  - the environment is an allow-list written out in `-e NAME=VALUE` pairs from the closed list ENV_ALLOWED, built from nothing but the
    arguments of the call: this process's own environment is never read into the container;
  - the script is the only host path mounted, read-only, at /in/script; there is no other bind mount. The installed dependencies are not
    a mount: they are the layer of an image this provider built (below), read-only because the root file system is;
  - the result leaves as frames on the container's standard output (never a folder it left), capped by the host, and is written by the
    host into an empty folder of its own, a regular file at a time (O_EXCL, O_NOFOLLOW), from the names result.md, result.csv or
    result.txt (at most one) and info.json.

Dependencies (Python only; a shell script has none): a hashed lock file is the whole input. The build container is the same image started
with NO mount and NO volume: the lock file arrives on its standard input, pip installs wheels only (--only-binary=:all: --require-hashes
--no-deps) into /deps through the same kind of per-step proxy, allowed to reach only the package index (pypi.org and
files.pythonhosted.org), and the container's file system is kept as an image layer (`docker commit`), tagged with the lock file's sha256
and the image definition's hash, so a lock file is built once. A run of the script uses that image read-only.

Usage:
  python3 providers/script/container.py --help
  python3 providers/script/container.py --check
  python3 providers/script/container.py build (--dry-run | --confirmed)
  python3 providers/script/container.py run --script <abs file> --kind py|sh --out-dir <folder> [--image <deps image id>
                                           --lock-sha256 <hex>]
                                           [--destination <host>:<port>]... [--timeout <seconds>]
  python3 providers/script/container.py deps --lock <abs file> --lock-sha256 <hex>
  python3 providers/script/container.py reap

Exit codes: 0 ok, 1 failed, 2 usage, 3 not configured (no docker, a remote daemon, no image). A failure prints `error: <code>: <sentence>`
on standard error, <code> being a closed word. Standard library only; the docker command-line client is the one outside tool.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import select
import signal
import stat
import subprocess
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import _container as box  # noqa: E402  (providers/_container.py: the one home of the container's lifecycle and limits)

CLASS = "script:project"
IMAGE_REPOSITORY = "openhora-script"
DEPS_REPOSITORY = "openhora-script-deps"
LABEL_DEFINITION = "org.openhora.definition"
LABEL_RUN = "org.openhora.script"
LABEL_LOCK = "org.openhora.script.lock"
DEFINITION_FILES = ("Dockerfile", ".dockerignore", "_inner.py", "egress_proxy.py")
NAME_PREFIX = "openhora-script-"
TOKEN = re.compile(r"[0-9a-f]{16}")
INTERNAL_NETWORK = re.compile(r"openhora-script-in-[0-9a-f]{16}")
EGRESS_NETWORK = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,62}")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
SHA256 = re.compile(r"[0-9a-f]{64}")
KINDS = ("py", "sh")
RESULT_NAMES = ("result.md", "result.csv", "result.txt")
OUTPUT_NAMES = RESULT_NAMES + ("info.json",)
OUTPUT_ENTRIES_MAX = 2                    # one result and the account of the run
RESULT_CAP = 1024 * 1024 + 1              # one byte over runtime/sources.py CONVERTED_CAP: the caller sees "over the cap" and refuses
INFO_CAP = 16 * 1024
STDOUT_CAP = RESULT_CAP + INFO_CAP + 4096
FILE_CAP = 256 * 1024                     # a script, and a lock file
MEMORY_MB, CPUS, SCRATCH_MB, PIDS = 1024, 1, 128, 128
PROXY_MEMORY_MB, PROXY_CPUS, PROXY_SCRATCH_MB, PROXY_PIDS = 128, 0.5, 16, 64
DEFAULT_TIMEOUT, MAX_TIMEOUT = 300, 900
BUILD_TIMEOUT = 900
PROXY_START_TIMEOUT = 30
PROXY_PORT = 3128
PROXY_ALIAS = "egress"
PACKAGE_INDEX = ("pypi.org:443", "files.pythonhosted.org:443")
DESTINATIONS_MAX = 8
# The only variables a container gets, each written out as NAME=VALUE. No name outside this list is ever put in a command.
ENV_ALLOWED = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy", "SCRIPT_DESTINATIONS",
               "SCRIPT_INDEX_URL", "PIP_CERT", "SSL_CERT_FILE")
# A plain `--internal` bridge still has the host's own address on it (its gateway): a container reaches the host's services there without the
# proxy. `isolated` gives the network no gateway address at all; the network is read back and refused without it.
GATEWAY_OPTION, GATEWAY_ISOLATED, IPV6_OPTION = "com.docker.network.bridge.gateway_mode_ipv4", "isolated", "com.docker.network.enable_ipv6"
BUILD_TMP_MB = 512                        # the build's memory-backed /tmp (pip unpacks the wheels there); a wheel larger than this does not build
LOG_OPTS = ("--log-opt", "max-size=1m", "--log-opt", "max-file=1")
BAD_VALUE = re.compile(r"[\x00-\x1f\x7f]")
EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_NOT_CONFIGURED = 0, 1, 2, 3
FRAME_START, FRAME_END = b"OHF1\n", b"END\n"
FRAME_HEAD = re.compile(rb"FILE ([a-z.]{1,20}) ([0-9]{1,9})\n")


class ProviderError(Exception):
    """A failure with a closed `word` (what the runtime reads), a sentence, and the exit code."""

    def __init__(self, word: str, message: str, code: int = EXIT_FAILED):
        super().__init__(message)
        self.word, self.code = word, code


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


proxy = _load("openhora_script_egress_proxy", os.path.join(HERE, "egress_proxy.py"))   # the declaration rules, once
inner = _load("openhora_script_inner", os.path.join(HERE, "_inner.py"))               # the lock file rules, once


# --- the definition and the image -----------------------------------------------------------------------------------------------


def definition_hash(folder: str = HERE) -> str:
    """The sha256 of the files the image is built from, by name and content, in a fixed order."""
    digest = hashlib.sha256()
    for name in sorted(DEFINITION_FILES):
        with open(os.path.join(folder, name), "rb") as f:
            digest.update(name.encode() + b"\0" + f.read() + b"\0")
    return digest.hexdigest()


def image_tag(folder: str = HERE) -> str:
    return f"{IMAGE_REPOSITORY}:{definition_hash(folder)[:12]}"


def deps_tag(lock_sha256: str, folder: str = HERE) -> str:
    """The tag of the image that holds the dependencies of one lock file: its sha256 and the definition of the image under it."""
    return f"{DEPS_REPOSITORY}:{lock_sha256[:16]}-{definition_hash(folder)[:12]}"


def local_daemon() -> None:
    try:
        box.require_local_daemon()
    except box.ContainerError as e:
        raise ProviderError("not_configured", f"the docker daemon is not usable as a local one ({e.code})", EXIT_NOT_CONFIGURED) from None


def inspect(tag: str, fmt: str, docker=None):
    """One field of `docker image inspect`, or None when the image is not there."""
    done = (docker or box.docker)(["image", "inspect", "--format", fmt, tag])
    return done.stdout.strip() if done.returncode == 0 else None


def image_id(tag: str, docker=None) -> str:
    """The id of the image of this definition, or ProviderError (3) when it has not been built here."""
    try:
        found = inspect(tag, "{{.Id}}", docker)
    except box.ContainerError as e:
        raise ProviderError("not_configured", f"docker cannot be used here ({e.code})", EXIT_NOT_CONFIGURED) from None
    if not found or not IMAGE_ID.fullmatch(found):
        raise ProviderError("not_configured", f"the script image {tag} is not built on this machine: run "
                            "`python3 providers/script/container.py build --confirmed` (once; it needs the network)", EXIT_NOT_CONFIGURED)
    return found


def deps_image(image: str, lock_sha256: str, docker=None) -> str:
    """An image id given for a run, accepted only when this provider built it for THIS lock file (its lock label is the approved
    lock_sha256) from the image definition now current (its definition label is definition_hash())."""
    if not IMAGE_ID.fullmatch(image or "") or not SHA256.fullmatch(lock_sha256 or ""):
        raise ProviderError("bad_image", "--image is an image id (sha256:<64 hex>), given with the approved --lock-sha256", EXIT_USAGE)
    found_lock = inspect(image, '{{index .Config.Labels "%s"}}' % LABEL_LOCK, docker)
    found_definition = inspect(image, '{{index .Config.Labels "%s"}}' % LABEL_DEFINITION, docker)
    if found_lock != lock_sha256 or found_definition != definition_hash():
        raise ProviderError("bad_image", "--image is not the image this provider built for that lock file with the current definition", EXIT_USAGE)
    return image


# --- the frames ------------------------------------------------------------------------------------------------------------------


def parse_frames(data: bytes) -> dict:
    """The outputs a container printed, {name: bytes}, or ProviderError. The rules: the stream starts with FRAME_START and ends with
    FRAME_END and nothing follows it; each record is `FILE <name> <size>\\n` and exactly <size> bytes; a name is one of OUTPUT_NAMES
    and appears once; a result is at most RESULT_CAP bytes, info.json at most INFO_CAP; at most OUTPUT_ENTRIES_MAX records; at most one
    result file; an info.json is always there. Anything else is the container's fault and nothing is kept."""
    if not data.startswith(FRAME_START):
        raise ProviderError("bad_output", "the container's output is not a result (no start marker)")
    at, out = len(FRAME_START), {}
    while True:
        if data.startswith(FRAME_END, at):
            if at + len(FRAME_END) != len(data):
                raise ProviderError("bad_output", "the container wrote after the end marker")
            break
        head = FRAME_HEAD.match(data, at)
        if head is None:
            raise ProviderError("bad_output", "the container's output is cut or malformed")
        name, size = head.group(1).decode("ascii"), int(head.group(2))
        if name not in OUTPUT_NAMES or name in out or len(out) >= OUTPUT_ENTRIES_MAX:
            raise ProviderError("bad_output", f"the container wrote an output that is not taken: {name!r}")
        if size > (INFO_CAP if name == "info.json" else RESULT_CAP):
            raise ProviderError("bad_output", f"the container's output {name} is {size} bytes, over its cap")
        start = head.end()
        if start + size > len(data):
            raise ProviderError("bad_output", "the container's output is cut short")
        out[name] = data[start:start + size]
        at = start + size
    if "info.json" not in out:
        raise ProviderError("bad_output", "the container gave no account of the run")
    return out


def check_out_dir(path: str) -> None:
    """The folder the outputs go to: a real folder (not a link), this user's, mode 0700, empty."""
    try:
        info = os.lstat(path)
    except OSError:
        raise ProviderError("usage", f"--out-dir {path} does not exist", EXIT_USAGE) from None
    if not stat.S_ISDIR(info.st_mode) or (hasattr(os, "getuid") and info.st_uid != os.getuid()) or stat.S_IMODE(info.st_mode) != 0o700:
        raise ProviderError("usage", "--out-dir must be a real folder of this user with mode 0700", EXIT_USAGE)
    if os.listdir(path):
        raise ProviderError("usage", "--out-dir must be empty", EXIT_USAGE)


def write_outputs(out_dir: str, outputs: dict) -> list:
    """Write each output into the folder as a new regular file: O_CREAT|O_EXCL|O_NOFOLLOW, mode 0600. Returns the names."""
    fd = os.open(out_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in sorted(outputs):
            mark = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            with os.fdopen(mark, "wb") as f:
                f.write(outputs[name])
    finally:
        os.close(fd)
    return sorted(outputs)


# --- the commands ------------------------------------------------------------------------------------------------------------------


def env_args(pairs: dict) -> list:
    """`-e NAME=VALUE` for each pair, in the order given. A name outside ENV_ALLOWED, or a value with a control character, is refused: the
    environment of a container is this list and nothing else, and no pair is ever written as a bare name (which docker would fill from
    the client's own environment)."""
    out = []
    for name, value in pairs.items():
        if name not in ENV_ALLOWED or not isinstance(value, str) or BAD_VALUE.search(value) or len(value) > 2000:
            raise ProviderError("bad_environment", f"the variable {str(name)[:30]!r} is not one a script container gets")
        out += ["-e", f"{name}={value}"]
    return out


def shape(command: list, inner_args, *, extras=(), network=None, rm=True, read_only=True, interactive=False) -> list:
    """A command of `_container.argv` (built with no inner arguments, so the image is its last word) given its extra options before the
    image, the inner arguments after it, and, for a networked container, its network in place of `none`. `rm` and `read_only` are
    turned off only by the dependency build. Nothing else of the helper's limits is touched."""
    out = list(command)
    image = out.pop()
    if network is not None:
        if out.count("--network") != 1:
            raise ProviderError("internal", "the command has no `--network none` to replace")
        i = out.index("--network")
        if out[i + 1] != "none":
            raise ProviderError("internal", "the command has no `--network none` to replace")
        out[i + 1] = network
    if not rm:
        out.remove("--rm")
    if not read_only:
        out.remove("--read-only")
    if interactive:
        out.insert(out.index("--init"), "-i")
    return out + list(LOG_OPTS) + list(extras) + [image] + list(inner_args)


def run_command(name: str, image: str, kind: str, script_path: str, *, deadline: int, network=None, env=None, platform=None) -> list:
    """The exact `docker run` command of one script: the helper's limits, the script mounted read-only at /in/script and nothing else
    mounted, the environment of `env_args`, and the internal network of the step (or none)."""
    if kind not in KINDS:
        raise ProviderError("usage", f"--kind is one of {', '.join(KINDS)}", EXIT_USAGE)
    if network is not None and not INTERNAL_NETWORK.fullmatch(network):
        raise ProviderError("internal", "a script joins only the internal network of its step")
    base = box.argv(name, image, [], label=LABEL_RUN, deadline=deadline, mounts=[(script_path, "/in/script", "ro")],
                    memory_mb=MEMORY_MB, cpus=CPUS, scratch_mb=SCRATCH_MB, pids_limit=PIDS, platform=platform)
    return shape(base, ["python3", "-I", "/opt/script/_inner.py", "run", "--kind", kind], extras=env_args(env or {}), network=network)


def proxy_command(name: str, image: str, destinations, egress_network: str, *, deadline: int, lifetime: int,
                  allow_private: bool = False, platform=None) -> list:
    """The exact `docker run` command of a step's egress proxy: the helper's limits (no mount at all), the egress network in place of
    `none`, and the declared pairs as its arguments."""
    if not EGRESS_NETWORK.fullmatch(egress_network or ""):
        raise ProviderError("internal", "the egress network is a plain network name")
    base = box.argv(name, image, [], label=LABEL_RUN, deadline=deadline, mounts=[], memory_mb=PROXY_MEMORY_MB, cpus=PROXY_CPUS,
                    scratch_mb=PROXY_SCRATCH_MB, pids_limit=PROXY_PIDS, platform=platform)
    inner_args = ["python3", "-I", "/opt/script/egress_proxy.py", "--listen", f"0.0.0.0:{PROXY_PORT}", "--max-seconds", str(int(lifetime))]
    for item in destinations:
        inner_args += ["--allow", item]
    if allow_private:
        inner_args.append("--allow-private")
    return shape(base, inner_args, network=egress_network)


def internal_network_args(name: str, label_args) -> list:
    """The `docker network create` of a step's internal network: `--internal` (no route out, no external DNS) and the isolated gateway mode
    (the host has no address on it), with the run's labels."""
    return ["network", "create", "--driver", "bridge", "--internal", "-o", f"{GATEWAY_OPTION}={GATEWAY_ISOLATED}", *label_args, name]


def isolated(inspected: str) -> bool:
    """Whether the read-back of `docker network inspect --format '{{.Internal}} {{json .Options}}'` says: internal, the gateway mode isolated,
    and no IPv6 (a second family nobody isolated)."""
    head, _, rest = (inspected or "").strip().partition(" ")
    try:
        options = json.loads(rest) if rest else {}
    except ValueError:
        return False
    return head == "true" and isinstance(options, dict) and options.get(GATEWAY_OPTION) == GATEWAY_ISOLATED \
        and options.get(IPV6_OPTION, "false") != "true"


def build_command(name: str, image: str, *, deadline: int, network: str, env=None, platform=None) -> list:
    """The exact `docker run` command of the dependency build: NO mount, NO volume (nothing in it names a host path), the lock file
    arriving on standard input (-i), a writable root file system whose changes become the image layer (no --rm), the helper's other
    limits, and the internal network of the step."""
    if not INTERNAL_NETWORK.fullmatch(network or ""):
        raise ProviderError("internal", "the build joins only the internal network of its step")
    base = box.argv(name, image, [], label=LABEL_RUN, deadline=deadline, mounts=[], memory_mb=MEMORY_MB, cpus=CPUS,
                    scratch_mb=SCRATCH_MB, pids_limit=PIDS, tmp_mb=BUILD_TMP_MB, platform=platform)
    return shape(base, ["python3", "-I", "/opt/script/_inner.py", "build"], extras=env_args(env or {}), network=network,
                 rm=False, read_only=False, interactive=True)


def new_token() -> str:
    return uuid.uuid4().hex[:16]


def names_of(token: str) -> dict:
    return {"run": f"{NAME_PREFIX}run-{token}", "proxy": f"{NAME_PREFIX}proxy-{token}", "build": f"{NAME_PREFIX}build-{token}",
            "internal": f"{NAME_PREFIX}in-{token}", "egress": f"{NAME_PREFIX}out-{token}"}


# --- the network of one step -------------------------------------------------------------------------------------------------------


class Egress:
    """The network of one step that declares destinations, as a context manager: an INTERNAL network for the script, an egress network
    for the proxy alone (made here, or the one a test gives), and the proxy, started on the egress network, read to its `ready`
    line (it resolved every declared name, and each is a public address), then joined to the internal network under the alias
    `egress`. On exit the proxy, then both networks, are removed by name, whatever happened. `.network` is the internal network and
    `.env` the proxy variables the script gets."""

    def __init__(self, destinations, *, token: str, image: str, timeout: int, allow_private: bool = False, egress_network=None,
                 docker=None, popen=None, platform=None, clock=time.time):
        self.destinations = list(destinations)
        self.token, self.image, self.allow_private, self.platform = token, image, allow_private, platform
        self.names = names_of(token)
        self.clock = clock
        self.deadline = int(clock()) + timeout + 120
        self.own_egress = egress_network is None
        self.egress_network = egress_network or self.names["egress"]
        self.docker = docker or box.docker
        self.popen = popen or subprocess.Popen
        self.proc, self.reader = None, None
        self.network = self.names["internal"]
        self.env = {}

    def _label_args(self):
        return ["--label", f"{LABEL_RUN}=1", "--label", f"{box.deadline_label(LABEL_RUN)}={self.deadline}"]

    def _docker(self, args):
        done = self.docker(args)
        if done.returncode != 0:
            raise ProviderError("network_failed", f"docker {args[0]} {args[1] if len(args) > 1 else ''} failed")
        return done

    def __enter__(self):
        try:
            self._docker(internal_network_args(self.network, self._label_args()))
            read_back = self._docker(["network", "inspect", "--format", "{{.Internal}} {{json .Options}}", self.network]).stdout
            if not isolated(read_back):
                raise ProviderError("network_not_internal", "the step's network is not internal with an isolated gateway (an older daemon "
                                    "cannot make one): nothing was started")
            if self.own_egress:
                self._docker(["network", "create", "--driver", "bridge", *self._label_args(), self.egress_network])
            command = proxy_command(self.names["proxy"], self.image, self.destinations, self.egress_network, deadline=self.deadline,
                                    lifetime=self.deadline - int(self.clock()), allow_private=self.allow_private, platform=self.platform)
            try:
                self.proc = self.popen([box.docker_binary()] + command[1:], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, env=box.docker_environment(), start_new_session=True)
            except OSError:
                raise ProviderError("proxy_failed", "the docker client could not be started") from None
            self.reader = box._StderrCap(self.proc.stderr)
            line = self._first_line()
            if line.startswith("refused "):
                word = line.split()[1] if len(line.split()) > 1 else "refused"
                raise ProviderError("destination_" + word if re.fullmatch(r"[a-z_]{1,30}", word) else "destination_refused",
                                    f"the declared destinations were refused: {line[:120]}")
            if not line.startswith("ready"):
                raise ProviderError("proxy_failed", "the egress proxy did not start")
            self._docker(["network", "connect", "--alias", PROXY_ALIAS, self.network, self.names["proxy"]])
            url = f"http://{PROXY_ALIAS}:{PROXY_PORT}"
            self.env = {"HTTP_PROXY": url, "HTTPS_PROXY": url, "http_proxy": url, "https_proxy": url,
                        "SCRIPT_DESTINATIONS": ",".join(self.destinations)}
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def _first_line(self) -> str:
        fd = self.proc.stdout.fileno()
        end = time.monotonic() + PROXY_START_TIMEOUT
        data = b""
        while b"\n" not in data and time.monotonic() < end:
            ready, _, _ = select.select([fd], [], [], 1)
            if ready:
                chunk = os.read(fd, 4096)
                if not chunk:
                    break
                data += chunk
            elif self.proc.poll() is not None:
                break
        return data.decode("utf-8", errors="replace").split("\n")[0].strip()

    def __exit__(self, *exc):
        if self.proc is not None:
            if self.proc.poll() is None:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except OSError:
                    pass
            try:
                self.proc.wait(timeout=10)
            except Exception:
                pass
            if self.reader is not None:
                self.reader.finish(2)
            try:
                self.proc.stdout.close()
            except OSError:
                pass
        box.remove(self.names["proxy"])
        for network in ([self.network] + ([self.egress_network] if self.own_egress else [])):
            try:
                self.docker(["network", "rm", network])
            except box.ContainerError:
                pass
        return False


# --- the verbs ---------------------------------------------------------------------------------------------------------------------


def check_file(path: str, what: str) -> bytes:
    """The bytes of a regular file of at most FILE_CAP, opened without following a link; ProviderError (usage) otherwise."""
    if not isinstance(path, str) or not os.path.isabs(path):
        raise ProviderError("usage", f"{what} is an absolute path", EXIT_USAGE)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise ProviderError("usage", f"{what} cannot be opened as a regular file", EXIT_USAGE) from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > FILE_CAP:
            raise ProviderError("usage", f"{what} must be a regular file of at most {FILE_CAP} bytes", EXIT_USAGE)
        data = os.read(fd, FILE_CAP + 1)
    finally:
        os.close(fd)
    if len(data) > FILE_CAP:
        raise ProviderError("usage", f"{what} must be a regular file of at most {FILE_CAP} bytes", EXIT_USAGE)
    return data


def check_destinations(items) -> list:
    """The declared destinations as the proxy reads them: `host:port` words, at most DESTINATIONS_MAX, a lowercase DNS name and a port."""
    items = list(items)
    if len(items) > DESTINATIONS_MAX:
        raise ProviderError("usage", f"at most {DESTINATIONS_MAX} destinations", EXIT_USAGE)
    try:
        if items:
            proxy.parse_declared(items)
    except proxy.Refused as e:
        raise ProviderError("usage", f"a destination is a lowercase host name and a port: {e.what}", EXIT_USAGE) from None
    return sorted(set(proxy.normal(i.rpartition(":")[0]) + ":" + i.rpartition(":")[2] for i in items))


def reap_all(docker=None) -> dict:
    """Remove what a killed run left: containers of the run label whose deadline passed (the helper's reap) and networks of the label
    whose deadline passed. Returns {"containers": [...], "networks": [...]}; a listing that fails raises nothing here."""
    docker = docker or box.docker
    removed = {"containers": [], "networks": []}
    try:
        removed["containers"] = box.reap(LABEL_RUN)
    except box.ContainerError:
        pass
    done = docker(["network", "ls", "--filter", f"label={LABEL_RUN}=1", "--format",
                   '{{.ID}} {{.Label "%s"}}' % box.deadline_label(LABEL_RUN)])
    if done.returncode == 0:
        for line in done.stdout.splitlines():
            parts = line.split()
            if parts and box.CONTAINER_ID.fullmatch(parts[0]):
                deadline = int(parts[1]) if len(parts) > 1 and box.DEADLINE.fullmatch(parts[1]) else 0
                if deadline < time.time() and docker(["network", "rm", parts[0]]).returncode == 0:
                    removed["networks"].append(parts[0])
    return removed


def run_script(script_path: str, kind: str, out_dir: str, *, image=None, lock_sha256=None, destinations=(), timeout: int = DEFAULT_TIMEOUT,
               allow_private: bool = False, egress_network=None, run=None, docker=None, base=None, platform=None) -> dict:
    """Run one script. `image` is the id of a dependency image this provider built (None: the base image), given with the approved
    `lock_sha256` it must have been built for. Returns {"exit", "signal",
    "duration_ms", "results", "refused", "outputs": [names written to out_dir], "image"}. `run`, `docker`, `base` (the base image id) and
    `egress_network` are the seams a test replaces; `allow_private` is the proxy's test switch and no verb passes it."""
    if kind not in KINDS:
        raise ProviderError("usage", f"--kind is one of {', '.join(KINDS)}", EXIT_USAGE)
    check_file(script_path, "--script")
    declared = check_destinations(destinations)
    if not 1 <= timeout <= MAX_TIMEOUT:
        raise ProviderError("usage", f"--timeout is from 1 to {MAX_TIMEOUT} seconds", EXIT_USAGE)
    check_out_dir(out_dir)
    if base is None:
        local_daemon()
        base = image_id(image_tag(), docker)
    if bool(image) != bool(lock_sha256):
        raise ProviderError("usage", "--image and --lock-sha256 are given together", EXIT_USAGE)
    run_image = deps_image(image, lock_sha256, docker) if image else base
    reap_all(docker)
    token = new_token()
    names = names_of(token)
    deadline = int(time.time()) + timeout + 60
    try:
        if declared:
            with Egress(declared, token=token, image=base, timeout=timeout, allow_private=allow_private,
                        egress_network=egress_network, docker=docker, platform=platform) as egress:
                command = run_command(names["run"], run_image, kind, script_path, deadline=deadline, network=egress.network,
                                      env=egress.env, platform=platform)
                done = (run or box.run)(command, names["run"], timeout, stdout_cap=STDOUT_CAP)
        else:
            command = run_command(names["run"], run_image, kind, script_path, deadline=deadline, platform=platform)
            done = (run or box.run)(command, names["run"], timeout, stdout_cap=STDOUT_CAP)
    except box.ContainerError as e:
        raise ProviderError(e.code, f"the script did not finish ({e.code})") from None
    if done.returncode != 0:
        tail = " ".join((done.stderr or "").split())[-300:]
        raise ProviderError("container_failed", f"the container failed: {tail or 'exit ' + str(done.returncode)}")
    outputs = parse_frames(done.stdout)
    try:
        about = json.loads(outputs["info.json"].decode("utf-8"))
    except ValueError:
        about = {}
    if not isinstance(about, dict):
        about = {}
    names_written = write_outputs(out_dir, outputs)
    return {"exit": about.get("exit"), "signal": about.get("signal"), "duration_ms": about.get("duration_ms"),
            "results": about.get("results") or [], "refused": about.get("refused") or [], "outputs": names_written,
            "image": run_image}


def commit_args(lock_sha256: str, container: str, tag: str) -> list:
    """The `docker commit` that keeps a finished build container's file system as the image of a lock file. A commit also keeps the
    container's configuration, so every part of it that belongs to the build and not to the image is put back: the variables it was given
    (the proxy of the build), the user it was started as, the labels that mark the build container and its deadline, and its command. What
    is added is the lock's sha256 (the label a run checks before it takes the image) and the definition's hash."""
    changes = [f"LABEL {LABEL_LOCK}={lock_sha256}", f"LABEL {LABEL_DEFINITION}={definition_hash()}", f"LABEL {LABEL_RUN}=",
               f"LABEL {box.deadline_label(LABEL_RUN)}=", "USER 65534:65534", 'CMD ["python3", "-I", "/opt/script/_inner.py", "--help"]']
    changes += [f"ENV {name}=" for name in ENV_ALLOWED]
    out = ["commit"]
    for change in changes:
        out += ["--change", change]
    return out + [container, tag]


def build_deps(lock: bytes, lock_sha256: str, *, timeout: int = BUILD_TIMEOUT, index_url=None, index_hosts=PACKAGE_INDEX,
               allow_private: bool = False, egress_network=None, docker=None, base=None, popen=None, platform=None) -> dict:
    """The image of one lock file: the cached one when it is there, else built now. `lock` is the file's bytes and `lock_sha256` the hash
    the person approved; they must agree, and every line of the lock must be a pinned requirement with hashes (the same check the build
    container makes again). The build container has no mount; the lock arrives on its standard input. Returns {"image", "tag",
    "cached"}. `index_url`, `index_hosts`, `allow_private`, `egress_network`, `docker`, `base`, `popen` are the seams a test replaces."""
    docker = docker or box.docker
    popen = popen or subprocess.Popen
    if not SHA256.fullmatch(lock_sha256 or "") or hashlib.sha256(lock).hexdigest() != lock_sha256:
        raise ProviderError("lock_changed", "the lock file is not the one that was approved")
    if len(lock) > FILE_CAP:
        raise ProviderError("usage", "the lock file is too large", EXIT_USAGE)
    try:
        inner.check_lock(lock.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise ProviderError("bad_lock", str(e)) from None
    tag = deps_tag(lock_sha256)
    cached = inspect(tag, '{{index .Config.Labels "%s"}}' % LABEL_LOCK, docker)
    if cached == lock_sha256 and inspect(tag, '{{index .Config.Labels "%s"}}' % LABEL_DEFINITION, docker) == definition_hash():
        return {"image": inspect(tag, "{{.Id}}", docker), "tag": tag, "cached": True}
    if base is None:
        local_daemon()
        base = image_id(image_tag(), docker)
    reap_all(docker)
    token = new_token()
    names = names_of(token)
    deadline = int(time.time()) + timeout + 120
    env_extra = {"SCRIPT_INDEX_URL": index_url} if index_url else {}
    try:
        with Egress(list(index_hosts), token=token, image=base, timeout=timeout, allow_private=allow_private,
                    egress_network=egress_network, docker=docker, platform=platform) as egress:
            command = build_command(names["build"], base, deadline=deadline, network=egress.network,
                                    env={**egress.env, **env_extra}, platform=platform)
            proc = popen([box.docker_binary()] + command[1:], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                         stderr=subprocess.PIPE, env=box.docker_environment(), start_new_session=True)
            reader = box._StderrCap(proc.stderr)
            try:
                try:
                    proc.stdin.write(lock)
                    proc.stdin.close()
                except OSError:
                    pass
                try:
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    raise ProviderError("time_limit", "the dependency build ran past its time limit") from None
                tail, _ = reader.finish()
                if proc.returncode != 0:
                    raise ProviderError("build_failed", "the dependency build failed: " + " ".join(tail.split())[-300:])
                done = docker(commit_args(lock_sha256, names["build"], tag))
                if done.returncode != 0:
                    raise ProviderError("build_failed", "the installed dependencies could not be kept as an image")
            finally:
                if proc.poll() is None:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except OSError:
                        pass
                    proc.wait()
                box.remove(names["build"])
    except box.ContainerError as e:
        raise ProviderError(e.code, f"the dependency build did not finish ({e.code})") from None
    return {"image": inspect(tag, "{{.Id}}", docker), "tag": tag, "cached": False}


# --- the command line --------------------------------------------------------------------------------------------------------------


def cmd_check(args: dict) -> int:
    local_daemon()
    tag = image_tag()
    print(json.dumps({"ok": True, "image": image_id(tag), "tag": tag, "definition": definition_hash()}))
    return EXIT_OK


def cmd_build(args: dict) -> int:
    if bool(args.get("--dry-run")) == bool(args.get("--confirmed")):
        raise ProviderError("usage", "give --dry-run to see the build, or --confirmed to make it", EXIT_USAGE)
    digest = definition_hash()
    command = ["docker", "build", "--label", f"{LABEL_DEFINITION}={digest}", "--build-arg", f"DEFINITION_HASH={digest}",
               "-t", image_tag(), HERE]
    if args.get("--dry-run"):
        print(json.dumps({"dry_run": True, "would": {"command": command, "tag": image_tag()}}))
        return EXIT_OK
    local_daemon()
    try:
        done = subprocess.run([box.docker_binary()] + command[1:], env=box.docker_environment(), timeout=3600, check=False,
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except (box.ContainerError, OSError, subprocess.SubprocessError) as e:
        raise ProviderError("build_failed", f"the build did not run ({type(e).__name__})") from None
    if done.returncode != 0:
        tail = " ".join(done.stderr.decode("utf-8", "replace").split())[-400:]
        raise ProviderError("build_failed", f"the build failed: {tail}")
    print(json.dumps({"built": True, "tag": image_tag(), "image": image_id(image_tag())}))
    return EXIT_OK


def _seconds(args: dict) -> int:
    try:
        return int(args.get("--timeout") or DEFAULT_TIMEOUT)
    except ValueError:
        raise ProviderError("usage", "--timeout is a whole number of seconds", EXIT_USAGE) from None


def cmd_run(args: dict) -> int:
    for flag in ("--script", "--kind", "--out-dir"):
        if not args.get(flag):
            raise ProviderError("usage", f"{flag} is required", EXIT_USAGE)
    print(json.dumps(run_script(args["--script"], args["--kind"], args["--out-dir"], image=args.get("--image"), lock_sha256=args.get("--lock-sha256"),
                                destinations=args.get("--destination") or [], timeout=_seconds(args))))
    return EXIT_OK


def cmd_deps(args: dict) -> int:
    for flag in ("--lock", "--lock-sha256"):
        if not args.get(flag):
            raise ProviderError("usage", f"{flag} is required", EXIT_USAGE)
    print(json.dumps(build_deps(check_file(args["--lock"], "--lock"), args["--lock-sha256"],
                                timeout=int(args["--timeout"]) if args.get("--timeout") else BUILD_TIMEOUT)))
    return EXIT_OK


def cmd_reap(args: dict) -> int:
    print(json.dumps(reap_all()))
    return EXIT_OK


VERBS = {"build": cmd_build, "run": cmd_run, "deps": cmd_deps, "reap": cmd_reap}
VALUE_FLAGS = ("--script", "--kind", "--out-dir", "--image", "--timeout", "--lock", "--lock-sha256", "--config-file")
LIST_FLAGS = ("--destination",)
SWITCHES = ("--dry-run", "--confirmed", "--check")


def parse_args(argv: list) -> tuple:
    verb, args, i = None, {}, 0
    while i < len(argv):
        word = argv[i]
        if word in VALUE_FLAGS or word in LIST_FLAGS:
            if i + 1 >= len(argv):
                raise ProviderError("usage", f"{word} needs a value", EXIT_USAGE)
            if word in LIST_FLAGS:
                args.setdefault(word, []).append(argv[i + 1])
            else:
                args[word] = argv[i + 1]
            i += 2
        elif word in SWITCHES:
            args[word] = True
            i += 1
        elif verb is None and word in VERBS:
            verb = word
            i += 1
        else:
            raise ProviderError("usage", f"unknown argument {word[:60]!r}; see --help", EXIT_USAGE)
    return verb, args


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("--help", "-h"):
        print(__doc__.strip(), file=sys.stdout if argv else sys.stderr)
        return EXIT_OK if argv else EXIT_USAGE
    try:
        verb, args = parse_args(argv)
        if args.get("--check"):
            if verb is not None:
                raise ProviderError("usage", "--check takes no verb", EXIT_USAGE)
            return cmd_check(args)
        if verb is None:
            raise ProviderError("usage", "give a verb or --check; see --help", EXIT_USAGE)
        return VERBS[verb](args)
    except ProviderError as e:
        print(f"error: {e.word}: {e}", file=sys.stderr)
        return e.code
    except box.ContainerError as e:
        print(f"error: {e.code}: the container helper refused", file=sys.stderr)
        return EXIT_NOT_CONFIGURED if e.code in ("docker_missing", "docker_unusable") else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
