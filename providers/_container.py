#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The one home of a sandboxed container job, for a provider that runs a program inside a container on this machine
(providers/CONTRACT.md, "Shared provider code"). It owns the whole lifecycle, so that the limits are written once:

  argv(...)               the exact `docker run` command: no network, a read-only root, every capability dropped, no new
                          privileges, a limit on processes, memory (swap included) and CPUs, memory-backed /tmp and /scratch
                          with no exec, an image that is never pulled at run time, a label that marks the run and a label
                          that holds its deadline, a non-root user on Linux, and the bind mounts the caller lists;
  mount_path(...)         a path that may go into a bind mount (absolute, no ':' and no control character);
  docker_binary(), docker_environment()   the docker command-line client and the environment it is started with;
  provider_environment(cls)   the environment a provider's process gets: a fixed minimum plus exactly the variables that
                          select the implementation of the class (providers/resolve.py `variables`), never a list of
                          provider names;
  run(argv, name, timeout)    start, wait for the end or the timeout, and remove the container by name on a timeout, on
                          SIGTERM/SIGINT and on any error; the container's stderr is read on a thread and only its last
                          STDERR_CAP bytes are kept; with `stdout_cap` its standard output is read too, on a thread, and
                          only its first `stdout_cap` bytes are kept: a container that writes more is killed and removed
                          (output_too_large). A job whose result is a stream (the converter's frames) takes it this way,
                          out of a memory-backed folder of its own, and the host decides what to write from it;
  remove(name), stop(name)    end a container by name; never raise;
  require_local_daemon()  refuse a docker client that talks to a daemon that is not on this machine (a unix socket);
  reap(label)             remove every container of the run label whose deadline label has passed (what a run that was
                          killed with SIGKILL, a crash or a power cut leaves behind).

Each limit is a named constant or an argument of `argv`; the names are those of the first two users (the renderer and the
transcriber of the short-video work). The constants are the stricter default; a job that needs more passes its own number.

What it does not own: the image (its build, its pin, its id), the folders a job uses, what a provider prints, and
the decision to check the daemon: `run()` does not call `require_local_daemon`; each provider calls it before a job.
`evals/executor.py`, the eval container's runner, does not use this file.

Errors are one class, `ContainerError(code, what)`: `code` is a closed machine word (bad_mount_path, bad_mount, docker_missing,
docker_unusable, docker_timeout, docker_ps_failed, docker_daemon_unknown, docker_daemon_not_local, bad_label, time_limit, stopped, output_too_large); `what` names the thing, never a path's content.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import Dict, Iterable, List, NamedTuple, Optional, Sequence, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))

# The limits of one container (the stricter default; `argv` takes a number for a job that needs more).
PIDS_LIMIT = 256
TMP_SIZE_MB = 64
MOUNT_SCRATCH = "/scratch"
PROBE_TIMEOUT = 60                       # seconds, one docker command that is not the job
STDERR_CAP = 64 * 1024                   # the most of a container's stderr the host keeps (its last bytes); the rest is read and dropped

# What finds a program, a home, a docker daemon and the state folder. The variables that select a provider are not here.
DOCKER_CLIENT_ENV = ("PATH", "HOME", "USER", "TMPDIR", "LANG", "LC_ALL", "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME",
                     "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH")
# ENV_MINIMUM, the variables a provider's process keeps besides the ones that select its class, lives in providers/resolve.py now (the
# runtime builds a provider's environment through the resolver and may not reach this file): `box.ENV_MINIMUM` still answers it.

LABEL = re.compile(r"[a-z0-9][a-z0-9.-]*")
DEADLINE = re.compile(r"[0-9]{1,18}")
LAUNCH_FAILED = (125, 126, 127)          # the docker client's own codes: the daemon refused, the command is not executable, not found
BAD_PATH = re.compile(r"[:\x00-\x1f\x7f]")
CONTAINER_ID = re.compile(r"[0-9a-f]{6,64}")


class ContainerError(Exception):
    """A refusal of the helper. `code` is the machine word (see the module text), `what` names the thing."""

    def __init__(self, code: str, what: str):
        super().__init__(f"{code}: {what}")
        self.code, self.what = code, what


class Finished(NamedTuple):
    returncode: int
    stderr: str                          # at most STDERR_CAP bytes, the last ones
    truncated: bool                      # more than STDERR_CAP bytes were written
    stdout: bytes = b""                  # the container's standard output, only when run() was given a stdout_cap


class Stopped(Exception):
    """This process was asked to stop (SIGTERM or SIGINT) while the container ran."""


# --- the environment --------------------------------------------------------------------------------------------------------


def _resolver():
    """providers/resolve.py, loaded by path (it is a script, not a package), once."""
    name = "workbench_provider_resolve"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, "resolve.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def __getattr__(name: str):
    if name == "ENV_MINIMUM":
        return _resolver().ENV_MINIMUM
    raise AttributeError(name)


def provider_environment(cls: str, env=None) -> Dict[str, str]:
    """The whole environment a provider's process gets for the class `cls`: ENV_MINIMUM plus the variables
    `resolve.variables(cls)` returns, each only if it is set and not empty. No other variable of `env` (a key, a token,
    the choice of another class's provider) passes. An unknown class is refused by the resolver (UnknownClass). The one
    definition is `resolve.provider_environment` (the runtime reaches it there); this is the same function."""
    return _resolver().provider_environment(cls, env)


def docker_environment(env=None) -> Dict[str, str]:
    """The environment the docker client is started with: DOCKER_CLIENT_ENV, nothing else."""
    env = os.environ if env is None else env
    return {k: env[k] for k in DOCKER_CLIENT_ENV if env.get(k)}


def docker_binary() -> str:
    found = shutil.which("docker")
    if not found:
        raise ContainerError("docker_missing", "docker")
    return found


def docker(args: Sequence[str], timeout: float = PROBE_TIMEOUT):
    """One docker command: a CompletedProcess (text, errors replaced). ContainerError when the client is missing, cannot be
    started or does not answer in time."""
    try:
        return subprocess.run([docker_binary(), *args], capture_output=True, text=True, errors="replace", timeout=timeout,
                              env=docker_environment(), check=False)
    except subprocess.TimeoutExpired:
        raise ContainerError("docker_timeout", args[0]) from None
    except OSError:
        raise ContainerError("docker_unusable", "docker") from None


def require_local_daemon(env=None) -> None:
    """The docker client must talk to a daemon on this machine, through a unix socket: with a remote one (DOCKER_HOST=tcp://
    or ssh://, or a remote docker context) the files a job mounts and the files it writes would cross a network. DOCKER_HOST
    is read from `env` (default: the process environment); with none, `docker context inspect` says which host the current
    context uses. ContainerError docker_daemon_unknown when that cannot be told, docker_daemon_not_local when it is not a
    unix socket (`what` is the host with any user part cut, at most 60 characters)."""
    env = os.environ if env is None else env
    host = env.get("DOCKER_HOST")
    if not host:
        done = docker(["context", "inspect", "--format", "{{.Endpoints.docker.Host}}"])
        host = done.stdout.strip() if done.returncode == 0 else ""
        if not host:
            raise ContainerError("docker_daemon_unknown", "docker")
    if not host.startswith("unix://"):
        raise ContainerError("docker_daemon_not_local", host.split("@")[-1][:60])


# --- the command ------------------------------------------------------------------------------------------------------------


def mount_path(path: str, what: str) -> str:
    """An absolute path for a bind mount: ':' separates the fields of -v, and a control character has no place in a path
    that goes to a command line. ContainerError (bad_mount_path) otherwise."""
    if not isinstance(path, str) or not os.path.isabs(path) or BAD_PATH.search(path):
        raise ContainerError("bad_mount_path", what)
    return path


def check_label(label: str) -> str:
    """The run label as a name a docker label key and a `--filter` can carry: lowercase letters, digits, dots and hyphens,
    starting with a letter or digit. ContainerError (bad_label) otherwise."""
    if not isinstance(label, str) or not LABEL.fullmatch(label):
        raise ContainerError("bad_label", "label")
    return label


def deadline_label(label: str) -> str:
    """The label that holds a run's deadline, as an epoch: the run label plus `.deadline`."""
    return check_label(label) + ".deadline"


def argv(name: str, image_id: str, inner_args: Iterable[str], *, label: str, deadline: int,
         mounts: Sequence[Tuple[str, str, str]], memory_mb: int, cpus, scratch_mb: int,
         pids_limit: int = PIDS_LIMIT, tmp_mb: int = TMP_SIZE_MB, platform: Optional[str] = None) -> List[str]:
    """The exact `docker run` command (a list; the first word is `docker`). Every limit of the container is here.

    `label` is the run label (`org.openhora.<job>`), set to 1, and `deadline` (an epoch, seconds) goes in the label
    `label + ".deadline"`; `reap` reads both. `mounts` is a list of (host path, container path, "ro" or "rw") in the order
    they are given; the host path goes through `mount_path`. The image is run by its id, which is never pulled. On Linux the
    container runs as the caller's numeric user and group (a bind mount keeps numeric owners there; elsewhere the runtime
    maps them)."""
    platform = sys.platform if platform is None else platform
    check_label(label)
    out = ["docker", "run", "--rm", "--init", "--pull", "never", "--name", name,
           "--label", "%s=1" % label, "--label", "%s=%d" % (deadline_label(label), deadline),
           "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
           "--pids-limit", str(pids_limit), "--memory", "%dm" % memory_mb, "--memory-swap", "%dm" % memory_mb,
           "--cpus", str(cpus),
           "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=%dm" % tmp_mb,
           "--tmpfs", "%s:rw,noexec,nosuid,nodev,size=%dm,mode=1777" % (MOUNT_SCRATCH, scratch_mb)]
    if platform.startswith("linux"):
        out += ["--user", "%d:%d" % (os.getuid(), os.getgid())]
    for host, inside, mode in mounts:
        if mode not in ("ro", "rw"):
            raise ContainerError("bad_mount", "mode")
        out += ["-v", "%s:%s:%s" % (mount_path(host, "mount source"), mount_path(inside, "mount target"), mode)]
    out += [image_id, *inner_args]
    return out


# --- the run ----------------------------------------------------------------------------------------------------------------


def remove(name: str) -> None:
    """End a container by name (`docker rm -f`): the docker client's process ending does not end it. Never raises."""
    try:
        docker(["rm", "-f", name], timeout=PROBE_TIMEOUT)
    except ContainerError:
        pass


def stop(name: str) -> None:
    """Stop a container and remove it, by name. A job has no state worth a graceful stop, so this is `remove`."""
    remove(name)


class _StderrCap:
    """Read a pipe to its end on a thread and keep only the last `cap` bytes: what is over the cap is read and dropped, so a
    container that spams stderr can neither fill the host's memory nor block on a full pipe."""

    def __init__(self, stream, cap: int = STDERR_CAP):
        self.stream, self.cap, self.kept, self.total = stream, cap, bytearray(), 0
        self.thread = threading.Thread(target=self._pump, daemon=True)
        self.thread.start()

    def _pump(self):
        try:
            fd = self.stream.fileno()
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    return
                self.total += len(chunk)
                self.kept += chunk
                if len(self.kept) > self.cap:
                    del self.kept[:len(self.kept) - self.cap]
        except (OSError, ValueError):   # the pipe was closed under the thread
            return

    def finish(self, wait: float = 5):
        self.thread.join(wait)
        try:
            self.stream.close()
        except OSError:
            pass
        return self.kept.decode("utf-8", errors="replace"), self.total > self.cap


class _StdoutCap:
    """Read a pipe to its end on a thread and keep its FIRST `cap` bytes. The moment more than `cap` bytes were written,
    `on_over()` is called (it ends the container) and `over` is set: the rest is read and dropped, so a container that
    writes without end can neither fill the host's memory nor block on a full pipe."""

    def __init__(self, stream, cap: int, on_over):
        self.stream, self.cap, self.on_over = stream, cap, on_over
        self.kept, self.total, self.over = bytearray(), 0, False
        self.thread = threading.Thread(target=self._pump, daemon=True)
        self.thread.start()

    def _pump(self):
        try:
            fd = self.stream.fileno()
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    return
                self.total += len(chunk)
                if self.total > self.cap:
                    if not self.over:
                        self.over = True
                        self.on_over()
                    self.kept = self.kept[:self.cap]
                    continue
                self.kept += chunk
        except (OSError, ValueError):   # the pipe was closed under the thread
            return

    def finish(self, wait: float = 5):
        self.thread.join(wait)
        try:
            self.stream.close()
        except OSError:
            pass
        return bytes(self.kept), self.over


def run(command: Sequence[str], name: str, timeout: float, *, stdout_cap: Optional[int] = None) -> Finished:
    """Run the container `command` built by `argv`: Finished(returncode, stderr, truncated, stdout). The docker client is
    started in its own process group with the environment of `docker_environment`; its standard output is discarded unless
    `stdout_cap` is given: then the first `stdout_cap` bytes of it come back in `stdout`, and a container that writes more is
    killed and removed (ContainerError output_too_large). The container is
    removed by name when `timeout` passes (ContainerError time_limit), when this process is stopped (stopped), when the client
    cannot be started (docker_unusable) and when anything else goes wrong; on a normal end `--rm` has already removed it."""
    def on_signal(signum, frame):
        raise Stopped()

    previous = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            previous.append((sig, signal.signal(sig, on_signal)))
        except ValueError:   # not the main thread: the finally below still covers a timeout and an error
            pass
    proc, reader, finished, sink = None, None, False, None
    try:
        try:
            proc = subprocess.Popen([docker_binary()] + list(command)[1:], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL if stdout_cap is None else subprocess.PIPE,
                                    stderr=subprocess.PIPE, env=docker_environment(), start_new_session=True)
        except OSError:
            raise ContainerError("docker_unusable", "docker") from None
        reader = _StderrCap(proc.stderr)
        if stdout_cap is not None:
            def end_it():
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    pass
                remove(name)
            sink = _StdoutCap(proc.stdout, int(stdout_cap), end_it)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ContainerError("time_limit", "container") from None
        stdout, over = sink.finish() if sink is not None else (b"", False)
        if over:
            raise ContainerError("output_too_large", "container")
        finished = True
        stderr, truncated = reader.finish()
        if proc.returncode in LAUNCH_FAILED:   # the client's own failure codes: make sure no container is left (idempotent)
            remove(name)
        return Finished(proc.returncode, stderr, truncated, stdout)
    except Stopped:
        raise ContainerError("stopped", "container") from None
    finally:
        for sig, _ in previous:   # the cleanup below is not interrupted by a second signal
            signal.signal(sig, signal.SIG_IGN)
        if not finished:
            if proc is not None and proc.poll() is None:   # the client first: it must not outlive the container
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    pass
                proc.wait()
            if sink is not None:
                sink.finish(2)
            if reader is not None:   # the reader thread ends with the pipe; give it a moment and close our end
                reader.finish(2)
            elif proc is not None:
                try:
                    proc.stderr.close()
                except OSError:
                    pass
            remove(name)
        for sig, handler in previous:
            signal.signal(sig, handler)


def reap(label: str, now: Optional[float] = None) -> List[str]:
    """Remove every container (running or not) that carries the run label `label` and whose deadline label is before `now`
    (default: the time of the call); a container with no readable deadline counts as past. Returns the ids removed.
    ContainerError (docker_ps_failed) when the list cannot be read."""
    now = time.time() if now is None else now
    deadline_key = deadline_label(label)    # also refuses a label that is not a plain name
    done = docker(["ps", "-a", "--filter", "label=%s=1" % label, "--format", '{{.ID}} {{.Label "%s"}}' % deadline_key])
    if done.returncode != 0:
        raise ContainerError("docker_ps_failed", "docker")
    removed = []
    for line in done.stdout.splitlines():
        parts = line.split()
        if not parts or not CONTAINER_ID.fullmatch(parts[0]):
            continue
        deadline = int(parts[1]) if len(parts) > 1 and DEADLINE.fullmatch(parts[1]) else 0
        if deadline < now and docker(["rm", "-f", parts[0]], timeout=PROBE_TIMEOUT).returncode == 0:
            removed.append(parts[0])
    return removed
