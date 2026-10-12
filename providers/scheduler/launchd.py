#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Scheduler provider for macOS: run a command through launchd, once at a set time or every N minutes.

Sources (Apple documentation and manual pages, accessed 2026-09-26 and 2026-09-29):
- launchd.plist(5): StartCalendarInterval (Month, Day, Hour, Minute in local time; a
  missed interval while the computer sleeps fires once on wake), ProgramArguments,
  WorkingDirectory, EnvironmentVariables, StandardOutPath, StandardErrorPath.
- launchd.plist(5), man page dated 30 July 2019, read on macOS 27.0.1 on 2026-09-29:
  StartInterval starts the job every N seconds; a firing due while the system is asleep
  is missed, and a firing due while the job is still running is missed too. RunAtLoad
  defaults to false, so the first firing comes one interval after loading.
- launchctl(1): `bootstrap gui/<uid> <plist>` loads a user agent, `bootout gui/<uid>/<label>`
  unloads it and stops its processes.
- Creating Launch Daemons and Agents (Daemons and Services Programming Guide):
  https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html

What a job guarantees:
- Every file the command reads through its arguments is in the command file's "snapshot":
  an argument that names an existing file, bare or as --flag=/path (absolute or relative to
  cwd), and is not listed there makes the job refused. The files are copied into the job
  folder with their SHA-256 and the arguments are swapped for the copies, so switching
  branches or editing the originals cannot change what runs.
- The scheduled program (argv[0]) and this runner script are hashed too; the runner itself is
  copied into the job folder and launchd calls the copy.
- The hashes are fixed at approval: the dry run prints a digest of everything that will run,
  and the confirmed call must pass it back with --approved. At run time the copies, the
  program and the runner are hashed again and the command is refused if any differs.
- The command runs at most once: the runner takes run.lock, records the job as running, and
  removes its launchd agent afterwards. launchd fires a missed time on wake; a run later than
  the grace period is recorded as missed and does not run. A firing up to 26 hours early (the
  system time zone changed after scheduling; the plist holds local wall time) waits for the
  time and then runs; an earlier one is logged and leaves the job scheduled.
- A one-shot job always ends: the command runs in its own process group for at most
  timeout_minutes (10 when the command file gives none); its output is kept as bytes, whatever
  it printed (the last MiB of each stream); an error in the runner records the job as failed. A job left "running" by a
  runner that died is settled with cancel or resolve.
- Job folders are 0700 and the files written in them 0600 (copies 0400).

What a recurring job (--every) adds:
- Every firing re-verifies the copies, the program and the runner; a mismatch records the
  firing as refused, marks the job refused and unloads it, so it stops firing.
- A firing while the previous one still runs records skipped-overlap and exits: run.lock in
  the job folder holds an flock and the holder's PID; the kernel drops the flock when the
  holder dies, so a lock left by a dead runner is stale and taken over. The command's process
  group is kept in run.group while it runs: a command that outlived a killed runner is found
  there, and the firing records skipped-overlap instead of starting it again.
- Each firing appends one line to runs.jsonl (started_at, ended_at, status, exit code,
  stdout and stderr tails of at most 4 kB each).
- The command runs in its own process group; past timeout_minutes the group is killed and
  the firing recorded as failed with reason timeout.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import plistlib
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

LABEL_PREFIX = "dev.ai-workbench.scheduler."
EARLY_TOLERANCE = timedelta(minutes=5)
# A one-shot plist holds local wall time, so a change of the system time zone between scheduling and the slot
# fires the job early, by at most the widest gap between two time zones (UTC-12 to UTC+14): the runner waits.
EARLY_WAIT_LIMIT = timedelta(hours=26)
WAIT_STEP_SECONDS = 60  # the wall clock is read again after each step: a sleep may not count system sleep
DEFAULT_GRACE_MINUTES = 120
MAX_GRACE_MINUTES = 10080  # a week: a one-shot run may start at most this late
LAUNCHCTL_TIMEOUT_SECONDS = 30
NOTIFY_TIMEOUT_SECONDS = 10
ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9.-]{0,62}")  # with fullmatch: "$" lets a final newline in
DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")
RUN_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
HISTORY = ".history"
GROUP_FILE = "run.group"  # the running command's process-group id, beside run.lock
EVERY_MIN_MINUTES, EVERY_MAX_MINUTES = 5, 1440
DEFAULT_TIMEOUT_MINUTES, MAX_TIMEOUT_MINUTES = 30, 240
DEFAULT_ONE_SHOT_TIMEOUT_MINUTES = 10  # a one-shot command without timeout_minutes in its command file
CANCEL_WAIT_SECONDS = 15  # how long cancel waits for a stopped runner to record its own outcome
TIMEOUT_UNIT_SECONDS = 60  # seconds per timeout minute; tests shorten it in-process
KILL_GRACE_SECONDS = 5  # between SIGTERM and SIGKILL to the command's process group
TAIL_BYTES = 4096
RUNS_MAX_BYTES = 4 * 1024 * 1024  # runs.jsonl is rotated to runs.1.jsonl past this size
OUTPUT_MAX_BYTES = 1024 * 1024  # run.stdout.log, run.stderr.log and the service logs keep their last MiB
HISTORY_KEEP = 100  # .history/ keeps the 100 folders archived last

EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED = 0, 1, 2, 3
# The one key of a command's output the scheduler reads, for the job record and the notification: the
# address of a published post, under the name providers/CONTRACT.md gives it ("Verbs per class", the
# "Prints" column of publisher:<platform>). The scheduler depends on the contract's name, never on what one
# implementation happens to print; a test compares this constant with that column.
ADDRESS_KEY = "post_url"

HELP_EPILOG = """\
verbs:
  schedule  Run the command in --command-file once at --at, or every --every
            minutes (5 to 1440). Run it first with --dry-run: it prints the job
            and its "approved" digest. After the calling skill's gate, run it
            again with --confirmed --approved <digest>; it refuses when anything
            changed since the dry run.
  list      Print every job with its status (scheduled, running, done, failed,
            refused, missed, cancelled). A recurring job also shows every_minutes
            and last_run (its last firing: done, failed, refused, skipped-overlap).
  cancel    Unload a scheduled job, one-shot or recurring; needs --confirmed.
            A one-shot job caught while running is stopped and recorded as
            cancelled with "interrupted": its command may have acted.
  resolve   Settle a one-shot job left "running" by a runner that is gone (a
            crash, a power loss), after checking what its command did: --done
            or --failed, and --confirmed (or --dry-run). Refused while the
            runner still holds the job's lock.
  run       Internal: what launchd calls at the set time or at each interval.

command file (JSON):
  {
    "argv": ["uv", "run", "/abs/providers/publisher/linkedin.py", "publish", ...],
    "cwd": "/absolute/working/directory",
    "snapshot": ["/abs/providers/publisher/linkedin.py", "/abs/post.txt"],
    "outputs": ["/abs/result.json"],
    "grace_minutes": 120
  }
  With --at, "grace_minutes" (default 120, 0 to 10080: a week) is how late the
  run may start; a later firing is recorded as missed and runs nothing.
  With --every, "grace_minutes" is refused and "timeout_minutes" (default 30,
  1 to 240) bounds each firing: past it the command's process group is killed
  and the firing is recorded as failed with reason timeout.
  With --at, "timeout_minutes" is optional (default 10, 1 to 240) and bounds the
  one run the same way: past it the command's whole process group is killed,
  the job is recorded as failed with reason timeout, and what the command had
  printed is kept in run.stdout.log and run.stderr.log. Give a command that
  needs longer its own timeout_minutes; it is part of the approved digest.
  "snapshot" is required. Every argv entry after argv[0] that names an existing
  file, bare or as --flag=<path>, absolute or relative to cwd, must be listed in
  it (as an absolute path) and is replaced by the job's copy of that file; a file
  argument left out makes the job refused, and so does a file named in another
  spelling (-f<path>, key=<path>, a list joined by ',', ':' or ';'), which the
  scheduler cannot swap for a copy. "outputs" (optional) lists absolute
  paths the command writes and does not read; they are exempt. argv[0] is resolved to an absolute
  path at schedule time and hashed. Directories are not snapshotted: files the
  command reads from cwd or from a directory argument are not verified.

environment variables:
  SCHEDULER_HOME        job folders. Default: ~/Library/Application Support/ai-workbench/scheduler
  SCHEDULER_AGENTS_DIR  where plists go. Default: ~/Library/LaunchAgents
  SCHEDULER_TEST        1 enables test mode; required for SCHEDULER_LAUNCHCTL.
  SCHEDULER_LAUNCHCTL   tests only (with SCHEDULER_TEST=1): replaces /bin/launchctl.
  SCHEDULER_NOTIFY      0 disables the macOS notification after a run.

output: JSON on stdout; diagnostics on stderr.
exit codes: 0 success, 1 provider error, 2 usage error, 3 not configured.

The computer must be on, awake and logged in at the set time (a user agent runs in the
login session). A time missed while asleep runs on wake, within the grace period.
A recurring job's first firing comes one interval after loading; per launchd.plist(5), an
interval firing due while the Mac sleeps, or while the previous firing runs, is missed.

examples:
  python3 providers/scheduler/launchd.py --check
  python3 providers/scheduler/launchd.py schedule --id launch-post \\
      --at 2026-09-29T09:00:00-03:00 --command-file job.json --dry-run
  python3 providers/scheduler/launchd.py schedule --id launch-post \\
      --at 2026-09-29T09:00:00-03:00 --command-file job.json --confirmed --approved <digest>
  python3 providers/scheduler/launchd.py schedule --id social-tick --every 15 \
      --command-file tick.json --dry-run
  python3 providers/scheduler/launchd.py list
  python3 providers/scheduler/launchd.py cancel --id launch-post --confirmed
"""


class ProviderError(Exception):
    def __init__(self, message: str, code: int = EXIT_SERVICE):
        super().__init__(message)
        self.code = code


def log(message: str) -> None:
    print(message, file=sys.stderr)


def now() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso(value: str) -> datetime:
    raw = value.strip()
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        raise ValueError(f"{value!r} has no offset: write it as 2026-09-29T09:00:00-03:00 or with Z")
    return parsed


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def home() -> Path:
    override = os.environ.get("SCHEDULER_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / "Library" / "Application Support" / "ai-workbench" / "scheduler"


def agents_dir() -> Path:
    override = os.environ.get("SCHEDULER_AGENTS_DIR")
    return Path(override).expanduser() if override else Path.home() / "Library" / "LaunchAgents"


def test_mode() -> bool:
    return os.environ.get("SCHEDULER_TEST") == "1"


def launchctl() -> str:
    override = os.environ.get("SCHEDULER_LAUNCHCTL")
    if override:
        if not test_mode():
            raise ProviderError("SCHEDULER_LAUNCHCTL is for tests only and needs SCHEDULER_TEST=1", EXIT_USAGE)
        return override
    return "/bin/launchctl"


def run_launchctl(*args: str) -> subprocess.CompletedProcess | None:
    """Run launchctl with a timeout; None when it timed out or could not be started."""
    try:
        return subprocess.run([launchctl(), *args], capture_output=True, text=True,
                              timeout=LAUNCHCTL_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        log(f"launchctl {args[0]} timed out after {LAUNCHCTL_TIMEOUT_SECONDS} s")
        return None
    except OSError as exc:
        log(f"launchctl {args[0]} could not be started: {type(exc).__name__}")
        return None


def domain() -> str:
    return f"gui/{os.getuid()}"


def label(job_id: str) -> str:
    return LABEL_PREFIX + job_id


def plist_path(job_id: str) -> Path:
    return agents_dir() / f"{label(job_id)}.plist"


def job_dir(job_id: str) -> Path:
    return home() / job_id


def private_dir(path: Path) -> None:
    """Create path (and missing parents) as 0700 and make sure path itself is 0700."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def write_private(path: Path, data: bytes) -> None:
    """Write data to path atomically, readable by the owner only."""
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def cut_note(cut: int) -> bytes:
    """The first line of an output file that was cut to its last OUTPUT_MAX_BYTES."""
    return f"[{cut} earlier bytes were cut: only the last {OUTPUT_MAX_BYTES} are kept]\n".encode("ascii")


def keep_tail(data: bytes) -> bytes:
    """data, or its last OUTPUT_MAX_BYTES after a line that says how much was cut."""
    if len(data) <= OUTPUT_MAX_BYTES:
        return data
    return cut_note(len(data) - OUTPUT_MAX_BYTES) + data[-OUTPUT_MAX_BYTES:]


def trim_in_place(path: Path) -> None:
    """Cut a log the service appends to down to its last OUTPUT_MAX_BYTES.

    The file is rewritten in place, not replaced: the service opened it in append mode for the running process,
    and that descriptor goes on writing at the new end."""
    try:
        with path.open("r+b") as fh:
            size = fh.seek(0, os.SEEK_END)
            if size <= OUTPUT_MAX_BYTES:
                return
            fh.seek(size - OUTPUT_MAX_BYTES)
            kept = fh.read(OUTPUT_MAX_BYTES)
            fh.seek(0)
            fh.write(cut_note(size - OUTPUT_MAX_BYTES) + kept)
            fh.truncate()
    except OSError as exc:
        log(f"could not cut {path}: {exc}")


def read_job(job_id: str) -> dict:
    path = job_dir(job_id) / "job.json"
    if not path.is_file():
        raise ProviderError(f"no job with id {job_id!r}", EXIT_USAGE)
    return json.loads(path.read_text(encoding="utf-8"))


def write_job(job: dict) -> None:
    data = (json.dumps(job, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    write_private(job_dir(job["id"]) / "job.json", data)


def python_for_launchd() -> str:
    # The system interpreter survives cache cleaning and version-manager changes.
    return "/usr/bin/python3" if Path("/usr/bin/python3").exists() else sys.executable


def validate_id(job_id: str) -> str:
    if not ID_PATTERN.fullmatch(job_id or ""):
        raise ProviderError("--id must be lowercase letters, digits, dots and hyphens (at most 63)", EXIT_USAGE)
    return job_id


def load_command_file(path_arg: str, recurring: bool = False) -> dict:
    path = Path(path_arg)
    if not path.is_file():
        raise ProviderError(f"--command-file not found: {path}", EXIT_USAGE)
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise ProviderError("--command-file is not valid JSON", EXIT_USAGE)
    argv = spec.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        raise ProviderError("the command file needs argv: a non-empty list of strings", EXIT_USAGE)
    cwd = spec.get("cwd")
    if not cwd or not Path(cwd).is_absolute() or not Path(cwd).is_dir():
        raise ProviderError("the command file needs cwd: an existing absolute directory", EXIT_USAGE)
    if "snapshot" not in spec:
        raise ProviderError("the command file needs snapshot: the list of files the command reads "
                            "([] only when no argument names a file)", EXIT_USAGE)
    snapshot = spec["snapshot"]
    if not isinstance(snapshot, list) or not all(isinstance(s, str) for s in snapshot):
        raise ProviderError("snapshot must be a list of absolute file paths", EXIT_USAGE)
    for item in snapshot:
        if not Path(item).is_absolute() or not Path(item).is_file():
            raise ProviderError(f"snapshot entries must be existing absolute files: {item}", EXIT_USAGE)
    outputs = spec.get("outputs", [])
    if not isinstance(outputs, list) or not all(isinstance(o, str) and Path(o).is_absolute() for o in outputs):
        raise ProviderError("outputs must be a list of absolute paths", EXIT_USAGE)
    names = [Path(item).name for item in snapshot]
    if len(set(names)) != len(names):
        raise ProviderError("snapshot files must have distinct names", EXIT_USAGE)
    if recurring:
        if "grace_minutes" in spec:
            raise ProviderError("grace_minutes applies to --at only; a recurring job uses timeout_minutes", EXIT_USAGE)
        timeout = spec.get("timeout_minutes", DEFAULT_TIMEOUT_MINUTES)
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= MAX_TIMEOUT_MINUTES:
            raise ProviderError(f"timeout_minutes must be an integer from 1 to {MAX_TIMEOUT_MINUTES}", EXIT_USAGE)
        return {"argv": argv, "cwd": cwd, "snapshot": snapshot, "outputs": outputs, "timeout_minutes": timeout}
    grace = spec.get("grace_minutes", DEFAULT_GRACE_MINUTES)
    if isinstance(grace, bool) or not isinstance(grace, int) or not 0 <= grace <= MAX_GRACE_MINUTES:
        raise ProviderError(f"grace_minutes must be an integer from 0 to {MAX_GRACE_MINUTES} (a week)", EXIT_USAGE)
    out = {"argv": argv, "cwd": cwd, "snapshot": snapshot, "outputs": outputs, "grace_minutes": grace}
    if "timeout_minutes" in spec:
        # Optional for --at: without it the command gets DEFAULT_ONE_SHOT_TIMEOUT_MINUTES, and the job and its
        # digest are what they always were.
        timeout = spec["timeout_minutes"]
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= MAX_TIMEOUT_MINUTES:
            raise ProviderError(f"timeout_minutes must be an integer from 1 to {MAX_TIMEOUT_MINUTES}", EXIT_USAGE)
        out["timeout_minutes"] = timeout
    return out


def resolve_program(program: str, cwd: str) -> str:
    if os.path.isabs(program):
        found = program
    elif os.sep in program:
        found = str(Path(cwd) / program)
    else:
        found = shutil.which(program, path=os.environ.get("PATH", "") + os.pathsep + RUN_PATH)
        if not found:
            raise ProviderError(f"argv[0] {program!r} not found on PATH", EXIT_USAGE)
    resolved = Path(found).resolve()
    if not resolved.is_file():
        raise ProviderError(f"argv[0] {program!r} is not a file", EXIT_USAGE)
    return str(resolved)


def split_argument(arg: str) -> tuple[str, str]:
    """Split '--flag=value' into ('--flag=', 'value'); any other argument into ('', arg)."""
    if arg.startswith("-") and "=" in arg:
        flag, value = arg.split("=", 1)
        return flag + "=", value
    return "", arg


def argument_file(value: str, cwd: str) -> Path | None:
    """The resolved file an argument value names, or None when it names no existing file."""
    if not value:
        return None
    path = Path(value) if os.path.isabs(value) else Path(cwd) / value
    try:
        return path.resolve() if path.is_file() else None
    except OSError:
        return None


def unverified_file(arg: str, cwd: str) -> Path | None:
    """A file an argument names in a spelling this provider does not understand, or None.

    Two spellings are understood, and swapped for the verified copy: the argument is the path, or it is
    '--flag=<path>'. A path glued to a short flag ('-f/abs/file'), a 'key=<path>' pair, and a list of paths
    joined by ',', ':' or ';' would reach the command as written: the job would read the live file at its
    slot, which nobody approved. A piece counts when it is the absolute path of an existing file; relative
    pieces count only when every piece of the argument is an existing file (a list of files), so that a
    sentence which happens to hold a file's name is not taken for one."""
    prefix, value = split_argument(arg)
    if not prefix and arg.startswith("-") and not arg.startswith("--") and len(arg) > 2:
        glued = argument_file(arg[2:], cwd)
        if glued is not None:
            return glued
    if not any(sep in value for sep in "=,:;"):
        return None
    pieces = [piece for piece in value.replace("=", ",").replace(":", ",").replace(";", ",").split(",") if piece]
    found = [argument_file(piece, cwd) for piece in pieces]
    for piece, target in zip(pieces, found):
        if target is not None and os.path.isabs(piece):
            return target
    if len(pieces) > 1 and all(target is not None for target in found):
        return found[0]
    return None


def snapshot_argv(argv: list[str], cwd: str, copies: dict[Path, str], outputs: set[Path]) -> list[str]:
    """Swap every file argument for its copy; refuse a file argument that has no copy, and one in a
    spelling that cannot be swapped."""
    out = []
    for arg in argv:
        prefix, value = split_argument(arg)
        target = argument_file(value, cwd)
        if target is None:
            hidden = unverified_file(arg, cwd)
            if hidden is not None:
                raise ProviderError(
                    f"the argument {arg!r} names the file {hidden} in a spelling the scheduler cannot verify; "
                    "pass a file as an argument of its own or as --flag=<path>, and list it in the command "
                    "file's snapshot", EXIT_USAGE)
        if target is None or (target in outputs and target not in copies):
            out.append(arg)
            continue
        if target not in copies:
            raise ProviderError(
                f"the argument {arg!r} names the file {target}, which is not in the command file's "
                "snapshot; add it so the job runs on a verified copy", EXIT_USAGE)
        out.append(prefix + copies[target])
    return out


def approval_digest(job: dict) -> str:
    """SHA-256 over everything that decides what runs; printed by the dry run, checked on --confirmed."""
    if job.get("kind") == "recurring":
        keys = ("id", "kind", "every_minutes", "timeout_minutes", "argv", "cwd", "outputs", "program")
    else:
        keys = ("id", "at", "grace_minutes", "argv", "cwd", "outputs", "program")
        if "timeout_minutes" in job:  # only when the command file sets it: other one-shot digests are unchanged
            keys += ("timeout_minutes",)
    fields = {key: job[key] for key in keys}
    fields["files"] = {source: entry["sha256"] for source, entry in job["files"].items()}
    fields["runner"] = job["runner"]["sha256"]
    blob = json.dumps(fields, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def plan_job(job_id: str, at: datetime | None, spec: dict, every: int | None = None) -> dict:
    """The job as it will run, hashed from the current files; nothing is written.

    A one-shot job (at) keeps the fields it always had; a recurring job (every) has kind,
    every_minutes and timeout_minutes instead of at, at_local and grace_minutes.
    """
    folder = job_dir(job_id)
    files, copies = {}, {}
    for source in spec["snapshot"]:
        copy = folder / "files" / Path(source).name
        files[source] = {"copy": str(copy), "sha256": sha256(Path(source)), "bytes": Path(source).stat().st_size}
        copies[Path(source).resolve()] = str(copy)
    program = resolve_program(spec["argv"][0], spec["cwd"])
    outputs = {Path(o).resolve() for o in spec["outputs"]}
    argv = [program] + snapshot_argv(spec["argv"][1:], spec["cwd"], copies, outputs)
    runner = Path(__file__).resolve()
    job = {"id": job_id, "label": label(job_id)}
    if every is None:
        job.update({"at": iso(at), "at_local": at.astimezone().isoformat(), "grace_minutes": spec["grace_minutes"]})
        if "timeout_minutes" in spec:
            job["timeout_minutes"] = spec["timeout_minutes"]
    else:
        job.update({"kind": "recurring", "every_minutes": every, "timeout_minutes": spec["timeout_minutes"]})
    job.update({
        "argv": argv,
        "cwd": spec["cwd"],
        "files": files,
        "outputs": spec["outputs"],
        "program": {"path": program, "sha256": sha256(Path(program))},
        "runner": {"source": str(runner), "copy": str(folder / "runner" / runner.name), "sha256": sha256(runner)},
        "status": "scheduled",
    })
    job["approved"] = approval_digest(job)
    return job


def build_plist(job: dict) -> dict:
    folder = job_dir(job["id"])
    if job.get("kind") == "recurring":
        # launchd.plist(5): StartInterval starts the job every N seconds.
        start = {"StartInterval": job["every_minutes"] * 60}
    else:
        local = parse_iso(job["at"]).astimezone()
        start = {"StartCalendarInterval": {
            "Month": local.month, "Day": local.day, "Hour": local.hour, "Minute": local.minute,
        }}
    return {
        "Label": label(job["id"]),
        "ProgramArguments": [python_for_launchd(), job["runner"]["copy"], "run", "--id", job["id"]],
        **start,
        "EnvironmentVariables": {
            "PATH": RUN_PATH,
            "SCHEDULER_HOME": str(home()),
            "SCHEDULER_AGENTS_DIR": str(agents_dir()),
        },
        "StandardOutPath": str(folder / "launchd.out.log"),
        "StandardErrorPath": str(folder / "launchd.err.log"),
    }


def archive_finished(job_id: str, existing: dict) -> str:
    """Move a finished job's folder to <home>/.history/ so the id can be scheduled again; keep HISTORY_KEEP there."""
    stamp = re.sub(r"[^0-9A-Za-z]", "", existing.get("finished_at") or existing.get("created_at") or iso(now()))
    target = home() / HISTORY / f"{job_id}-{stamp}"
    n = 1
    while target.exists():
        n += 1
        target = home() / HISTORY / f"{job_id}-{stamp}-{n}"
    private_dir(target.parent)
    os.replace(job_dir(job_id), target)
    os.utime(target)  # the time it was archived: the newest HISTORY_KEEP folders are kept
    folders = sorted((p for p in target.parent.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime_ns)
    for old in folders[:-HISTORY_KEEP]:
        shutil.rmtree(old, ignore_errors=True)
    return str(target)


def copy_verified(source: str, copy: Path, expected: str, mode: int) -> None:
    shutil.copyfile(source, copy)
    os.chmod(copy, mode)
    if sha256(copy) != expected:
        raise ProviderError(f"{source} changed after the dry run: its copy does not match the approved hash")


# --- verbs ---------------------------------------------------------------------


def cmd_schedule(args) -> int:
    job_id = validate_id(args.id)
    every = args.every
    if every is not None:
        at = None
        if not EVERY_MIN_MINUTES <= every <= EVERY_MAX_MINUTES:
            raise ProviderError(f"--every must be from {EVERY_MIN_MINUTES} to {EVERY_MAX_MINUTES} minutes", EXIT_USAGE)
        spec = load_command_file(args.command_file, recurring=True)
    else:
        try:
            at = parse_iso(args.at)
        except (TypeError, ValueError):
            raise ProviderError(f"--at must be an ISO-8601 time with an offset, e.g. 2026-09-29T09:00:00-03:00 "
                                f"or 2026-09-29T12:00:00Z: {args.at}", EXIT_USAGE)
        if at <= now():
            raise ProviderError("--at is in the past", EXIT_USAGE)
        if at - now() > timedelta(days=330):
            raise ProviderError("--at is more than 330 days away; launchd calendar times repeat yearly", EXIT_USAGE)
        spec = load_command_file(args.command_file)
    if not args.dry_run and not args.confirmed:
        raise ProviderError(
            "refusing to schedule without --confirmed; the calling skill must pass its confirmation "
            "gate first (use --dry-run to preview)",
            EXIT_USAGE,
        )
    if not args.dry_run and not DIGEST_PATTERN.fullmatch(args.approved or ""):
        raise ProviderError("--confirmed needs --approved <digest>: the digest the dry run printed", EXIT_USAGE)
    existing = None
    if (job_dir(job_id) / "job.json").exists():
        existing = read_job(job_id)
        if existing["status"] == "scheduled":
            raise ProviderError(f"job {job_id!r} is scheduled; cancel it or wait for it first", EXIT_USAGE)
        if existing["status"] == "running":
            raise ProviderError(f"job {job_id!r} is running; wait for it, or, when its runner is gone (a crash, a "
                                "power loss), check what the command did and settle it with resolve --id "
                                f"{job_id} (--done | --failed) --confirmed, or cancel it", EXIT_USAGE)

    job = plan_job(job_id, at, spec, every)
    plist = build_plist(job)
    if args.dry_run:
        out = {"dry_run": True, "approved": job["approved"], "job": job,
               "plist_path": str(plist_path(job_id)), "plist": plist}
        if existing:
            out["replaces_finished_job"] = {"status": existing["status"], "moved_to": str(home() / HISTORY)}
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return EXIT_OK
    if args.approved != job["approved"]:
        raise ProviderError(
            "the job changed since the dry run (a file, the program, the runner or the command file): "
            "run --dry-run again and show the new payload before confirming", EXIT_USAGE)
    launchctl()  # refuse an untrusted launchctl override before writing anything

    private_dir(home())
    if existing:
        job["replaced"] = archive_finished(job_id, existing)
    folder = job_dir(job_id)
    if folder.exists() and not (folder / "job.json").exists():
        shutil.rmtree(folder)  # left by an interrupted schedule; it never held a job record
    private_dir(folder / "files")
    private_dir(folder / "runner")
    try:
        for source, entry in job["files"].items():
            copy_verified(source, Path(entry["copy"]), entry["sha256"], 0o400)
        copy_verified(job["runner"]["source"], Path(job["runner"]["copy"]), job["runner"]["sha256"], 0o500)
        if sha256(Path(job["program"]["path"])) != job["program"]["sha256"]:
            raise ProviderError(f"{job['program']['path']} changed after the dry run")
    except ProviderError:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    for name in ("launchd.out.log", "launchd.err.log"):
        write_private(folder / name, b"")
    job["created_at"] = iso(now())
    write_job(job)
    if not agents_dir().exists():
        private_dir(agents_dir())
    write_private(plist_path(job_id), plistlib.dumps(plist))
    run_launchctl("bootout", f"{domain()}/{label(job_id)}")
    loaded = run_launchctl("bootstrap", domain(), str(plist_path(job_id)))
    if loaded is None or loaded.returncode != 0:
        job["status"] = "failed"
        job["error"] = ("launchctl bootstrap timed out" if loaded is None
                        else f"launchctl bootstrap exited {loaded.returncode}: {loaded.stderr.strip()}")
        write_job(job)
        plist_path(job_id).unlink(missing_ok=True)
        raise ProviderError(job["error"])
    print(json.dumps(job, indent=2, ensure_ascii=False))
    return EXIT_OK


def cmd_list(_args) -> int:
    jobs = []
    if home().is_dir():
        for folder in sorted(home().iterdir()):
            if (folder / "job.json").is_file():
                job = json.loads((folder / "job.json").read_text(encoding="utf-8"))
                job["plist_present"] = plist_path(job["id"]).exists()
                if job.get("kind") == "recurring":
                    last = last_firing(folder)
                    job["last_run"] = ({k: last.get(k) for k in ("started_at", "ended_at", "status", "exit_code", "reason")}
                                       if last else None)
                jobs.append(job)
    print(json.dumps({"jobs": jobs}, indent=2, ensure_ascii=False))
    return EXIT_OK


def unload(job_id: str) -> None:
    plist_path(job_id).unlink(missing_ok=True)
    run_launchctl("bootout", f"{domain()}/{label(job_id)}")


def cmd_cancel(args) -> int:
    job = read_job(validate_id(args.id))
    if not args.confirmed and not args.dry_run:
        raise ProviderError("refusing to cancel without --confirmed (use --dry-run to preview)", EXIT_USAGE)
    if args.dry_run:
        print(json.dumps({"dry_run": True, "would_cancel": job}, indent=2, ensure_ascii=False))
        return EXIT_OK
    launchctl()
    folder = job_dir(job["id"])
    fd, _ = acquire_lock(folder)
    if fd is None:
        # A runner holds the job: it waits for its time, or runs the command. Unloading stops it: one that runs the
        # command kills it and records "failed" before it lets go of the lock; one that waits records nothing.
        unload(job["id"])
        fd = wait_for_lock(folder, CANCEL_WAIT_SECONDS)
        if fd is None:
            raise ProviderError(f"job {job['id']!r} was unloaded, but its runner still held it {CANCEL_WAIT_SECONDS} s "
                                "later; nothing was recorded: run cancel again")
    try:
        job = read_job(job["id"])  # again, now that no runner can change it
        if job["status"] == "scheduled":
            job.update(status="cancelled", finished_at=iso(now()))
            write_job(job)
        elif job["status"] == "running":
            # A one-shot job whose runner is gone (a crash, a power loss): it recorded nothing, and the job would
            # stay "running" for ever with its id blocked.
            job.update(status="cancelled", finished_at=iso(now()), interrupted=True,
                       reason=f"cancelled while running (started at {job.get('started_at', 'an unknown time')}): "
                              "the command may have acted and its outcome is unknown; check what it did before "
                              "scheduling it again")
            write_job(job)
        unload(job["id"])
    finally:
        release_lock(fd)
    print(json.dumps(job, indent=2, ensure_ascii=False))
    return EXIT_OK


def cmd_resolve(args) -> int:
    """Settle a one-shot job left "running" by a runner that is gone: the user says what the command did."""
    job = read_job(validate_id(args.id))
    if bool(args.done) == bool(args.failed):
        raise ProviderError("resolve needs exactly one of --done (the command did its work) or --failed", EXIT_USAGE)
    if job["status"] != "running":
        raise ProviderError(f"job {job['id']!r} is {job['status']}, not running; nothing to resolve", EXIT_USAGE)
    if not args.confirmed and not args.dry_run:
        raise ProviderError("refusing to resolve without --confirmed; the user decides what happened "
                            "(use --dry-run to preview)", EXIT_USAGE)
    status = "done" if args.done else "failed"
    if args.dry_run:
        print(json.dumps({"dry_run": True, "would_resolve": job, "as": status}, indent=2, ensure_ascii=False))
        return EXIT_OK
    launchctl()
    # The kernel drops the lock when its holder dies, so a lock that can be taken means no runner of this version
    # runs the job (a runner copied into a job folder before one-shot jobs took the lock holds none).
    fd, _ = acquire_lock(job_dir(job["id"]))
    if fd is None:
        raise ProviderError(f"job {job['id']!r} still runs (its runner holds the lock); wait for it, or cancel it")
    try:
        job = read_job(job["id"])  # again, now that no runner can change it
        if job["status"] != "running":
            raise ProviderError(f"job {job['id']!r} is {job['status']}, not running; nothing to resolve", EXIT_USAGE)
        job.update(status=status, finished_at=iso(now()), resolved=True)
        write_job(job)
        unload(job["id"])
    finally:
        release_lock(fd)
    print(json.dumps(job, indent=2, ensure_ascii=False))
    return EXIT_OK


def notify(title: str, message: str) -> None:
    if os.environ.get("SCHEDULER_NOTIFY", "1") == "0":
        return
    script = f"display notification {json.dumps(message)} with title {json.dumps(title)}"
    try:
        subprocess.run(["/usr/bin/osascript", "-e", script], capture_output=True, timeout=NOTIFY_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        pass


def finish(job: dict, status: str, **fields) -> int:
    job.update(fields)
    job["status"] = status
    job["finished_at"] = iso(now())
    write_job(job)
    summary = fields.get(ADDRESS_KEY) or fields.get("reason") or f"exit {fields.get('exit_code')}"
    notify(f"openhora: {job['id']} {status}", summary)
    log(f"job {job['id']}: {status} ({summary})")
    # Unloading stops this process's launchd job, so it is the last thing done.
    unload(job["id"])
    return EXIT_OK if status == "done" else EXIT_SERVICE


def changed_since_approval(job: dict) -> str | None:
    """Name what no longer matches its approved hash, or None when everything matches."""
    for source, entry in job["files"].items():
        copy = Path(entry["copy"])
        if not copy.is_file() or sha256(copy) != entry["sha256"]:
            return f"the copy of {Path(source).name} changed after scheduling"
    program = Path(job["program"]["path"])
    if not program.is_file() or sha256(program) != job["program"]["sha256"]:
        return f"the program {program} changed after scheduling"
    if sha256(Path(__file__).resolve()) != job["runner"]["sha256"]:
        return "the runner script changed after scheduling"
    return None


# --- recurring jobs --------------------------------------------------------------


class Stopped(Exception):
    """The runner received SIGTERM, as launchd sends when the job is unloaded."""


def runs_path(folder: Path) -> Path:
    return folder / "runs.jsonl"


def last_firing(folder: Path) -> dict | None:
    """The last record in runs.jsonl, or None when the job has not fired yet."""
    path = runs_path(folder)
    if not path.is_file():
        return None
    for line in reversed(path.read_text(encoding="utf-8", errors="replace").splitlines()):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            return record
    return None


def record_firing(folder: Path, record: dict) -> None:
    """Append one firing to runs.jsonl (0600); past RUNS_MAX_BYTES the file moves to runs.1.jsonl first."""
    path = runs_path(folder)
    if path.is_file() and path.stat().st_size > RUNS_MAX_BYTES:
        os.replace(path, folder / "runs.1.jsonl")
    line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, line)
    finally:
        os.close(fd)


def acquire_lock(folder: Path) -> tuple[int | None, str]:
    """Take run.lock: (fd, stale PID or "") when taken, (None, holder PID) when a firing still runs.

    The flock is what excludes; the PID written in the file names the holder. The kernel
    releases the flock when its holder dies, so a PID left in a lock that can be taken
    belongs to a runner that died mid-firing: the lock was stale.
    """
    fd = os.open(folder / "run.lock", os.O_RDWR | os.O_CREAT, 0o600)
    os.fchmod(fd, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        holder = os.read(fd, 64).decode("ascii", errors="replace").strip()
        os.close(fd)
        return None, holder
    stale = os.read(fd, 64).decode("ascii", errors="replace").strip()
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, f"{os.getpid()}\n".encode("ascii"))
    return fd, stale


def release_lock(fd: int) -> None:
    os.ftruncate(fd, 0)
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


def wait_for_lock(folder: Path, seconds: float) -> int | None:
    """Take run.lock, waiting up to `seconds` for its holder to let go: the fd, or None when it still holds it."""
    deadline = time.monotonic() + seconds
    while True:
        fd, _ = acquire_lock(folder)
        if fd is not None or time.monotonic() >= deadline:
            return fd
        time.sleep(0.1)


def record_group(folder: Path, pgid: int | None) -> None:
    """Write the running command's process-group id beside run.lock (GROUP_FILE), or remove it (None) at its end."""
    path = folder / GROUP_FILE
    try:
        if pgid is None:
            path.unlink(missing_ok=True)
        else:
            write_private(path, f"{pgid}\n".encode("ascii"))
    except OSError as exc:
        log(f"could not record the command's process group in {path}: {exc}")


def orphan_group(folder: Path) -> str | None:
    """The process group of a command whose runner died while it ran, when that group still lives; else None.

    The kernel drops run.lock when its holder dies, but the command runs in a session of its own and outlives a
    runner that was killed or crashed: a firing that took the free lock and started the command again would run
    beside it. A group that is gone has its record removed."""
    path = folder / GROUP_FILE
    try:
        pgid = int(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None
    if pgid <= 1:
        return None
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        record_group(folder, None)
        return None
    except PermissionError:
        pass  # the group exists, under another user
    return str(pgid)


def tail(data: bytes | None) -> str:
    return (data or b"")[-TAIL_BYTES:].decode("utf-8", errors="replace")


def kill_group(proc: subprocess.Popen) -> tuple[bytes, bytes]:
    """SIGTERM the command's process group, SIGKILL it after KILL_GRACE_SECONDS; return its output."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            return proc.communicate(timeout=KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            continue
    # A process that left the group still holds the pipes; give up on its output.
    for pipe in (proc.stdout, proc.stderr):
        if pipe:
            pipe.close()
    try:
        proc.wait(timeout=KILL_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    return b"", b""


def execute(job: dict) -> dict:
    """One firing of a recurring job, bounded by timeout_minutes: its outcome with the output's tails."""
    outcome, out, err = run_command(job, job["timeout_minutes"] * TIMEOUT_UNIT_SECONDS,
                                    f"timeout_minutes ({job['timeout_minutes']})")
    if out is None:  # the command could not be started
        return outcome
    return {"exit_code": outcome.pop("exit_code"), "stdout_tail": tail(out), "stderr_tail": tail(err), **outcome}


def run_command(job: dict, timeout: float, limit: str) -> tuple[dict, bytes | None, bytes | None]:
    """Run the command in its own process group, for at most `timeout` seconds.

    Returns ({status, exit_code[, reason]}, stdout, stderr). The output is bytes, never decoded here: a command
    may print anything. Past the limit, or when the runner is told to stop, the whole process group is killed
    and what the command had printed is still returned. The output is (None, None) only when the command could
    not be started. `limit` names the bound in the reason."""
    try:
        proc = subprocess.Popen(job["argv"], cwd=job["cwd"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True, env={**os.environ, "PATH": RUN_PATH})
    except OSError as exc:
        return {"status": "failed", "exit_code": None, "reason": f"{type(exc).__name__}: {exc}"}, None, None
    folder = job_dir(job["id"])
    record_group(folder, proc.pid)  # start_new_session: the command leads a process group of its own
    stopping = []

    def on_term(_signum, _frame):
        if not stopping:
            stopping.append(True)
            raise Stopped()

    try:
        previous = signal.signal(signal.SIGTERM, on_term)
    except ValueError:  # not the main thread; launchd always runs the runner as the main thread
        previous = None
    reason = None
    try:
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            reason = f"timeout: ran longer than {limit}; its process group was killed"
            out, err = kill_group(proc)
        except Stopped:
            reason = "the runner received SIGTERM (the job was cancelled or unloaded); the command's process group was killed"
            out, err = kill_group(proc)
    finally:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)
        record_group(folder, None)
    result = {"exit_code": proc.returncode}
    if reason:
        result.update(status="failed", reason=reason)
    else:
        result["status"] = "done" if proc.returncode == 0 else "failed"
    return result, out, err


def run_recurring(job: dict) -> int:
    """One firing of a recurring job: lock, verify, run, record. Never runs two firings at once."""
    folder = job_dir(job["id"])
    if job["status"] != "scheduled":
        log(f"job {job['id']} is {job['status']}; nothing to run")
        unload(job["id"])
        return EXIT_OK
    started = iso(now())
    fd, other = acquire_lock(folder)
    if fd is None:
        record_firing(folder, {"started_at": started, "ended_at": iso(now()), "status": "skipped-overlap",
                               "exit_code": None, "reason": f"the previous firing (pid {other or 'unknown'}) still runs"})
        return EXIT_OK
    orphan = orphan_group(folder)
    if orphan:
        record_firing(folder, {"started_at": started, "ended_at": iso(now()), "status": "skipped-overlap",
                               "exit_code": None, "reason": f"the command of an earlier firing (process group {orphan}) "
                                                            "still runs; its runner is gone"})
        release_lock(fd)
        return EXIT_OK
    previous = last_firing(folder)
    record = {"started_at": started}
    if other:
        record["stale_lock_pid"] = other
    try:
        reason = changed_since_approval(job)
        if reason:
            record.update(ended_at=iso(now()), status="refused", exit_code=None, reason=reason)
            record_firing(folder, record)
            job.update(status="refused", reason=reason, finished_at=record["ended_at"])
            write_job(job)
        else:
            outcome = execute(job)
            record.update(ended_at=iso(now()), **outcome)
            record_firing(folder, record)
    finally:
        release_lock(fd)
    status = record["status"]
    summary = record.get("reason") or f"exit {record.get('exit_code')}"
    if status == "refused" or (status == "failed" and (previous or {}).get("status") != "failed"):
        notify(f"openhora: {job['id']} {status}", summary)
    if status != "done":
        log(f"job {job['id']} firing: {status} ({summary})")
    if status == "refused":
        # A recurring job that no longer matches its approval must stop firing. Unloading
        # stops this process's launchd job, so it is the last thing done.
        unload(job["id"])
    return EXIT_OK if status == "done" else EXIT_SERVICE


def cmd_run(args) -> int:
    job = read_job(validate_id(args.id))
    for name in ("launchd.out.log", "launchd.err.log"):
        trim_in_place(job_dir(job["id"]) / name)
    if job.get("kind") == "recurring":
        return run_recurring(job)
    folder = job_dir(job["id"])
    fd, other = acquire_lock(folder)
    if fd is None:
        log(f"job {job['id']}: another runner (pid {other or 'unknown'}) holds it; nothing to run")
        return EXIT_OK
    # From here to the recorded outcome the runner holds the lock, as cancel and resolve do: none of them writes
    # over another. Unloading at the end may stop this process; the kernel then drops the lock.
    try:
        job = read_job(job["id"])  # again, now that no other runner can change it
        if job["status"] != "scheduled":
            log(f"job {job['id']} is {job['status']}; nothing to run")
            unload(job["id"])
            return EXIT_OK
        at = parse_iso(job["at"])
        current = now()
        if current < at - EARLY_TOLERANCE:
            if at - current > EARLY_WAIT_LIMIT:
                log(f"job {job['id']} fired at {iso(current)}, before its time {job['at']}; waiting")
                return EXIT_OK
            # launchd would fire it next a year later. Wait for the time here, still holding the job: cancel unloads
            # the job, and launchd's SIGTERM ends this wait.
            log(f"job {job['id']} fired at {iso(current)}, before its time {job['at']} (the time zone changed?); "
                "waiting for it")
            while now() < at:
                time.sleep(min(WAIT_STEP_SECONDS, max((at - now()).total_seconds(), 0.0)))
            current = now()
        if current > at + timedelta(minutes=job["grace_minutes"]):
            return finish(job, "missed", reason=f"fired at {iso(current)}, after the {job['grace_minutes']}-minute grace")
        if "program" not in job or "runner" not in job:
            return finish(job, "refused", reason="the job was scheduled without program and runner hashes; schedule it again")
        reason = changed_since_approval(job)
        if reason:
            return finish(job, "refused", reason=reason)
        job["status"] = "running"
        job["started_at"] = iso(current)
        write_job(job)
        try:
            status, fields = run_one_shot(job, folder)
        except Exception as exc:  # whatever breaks from here on, the job ends: it never stays "running"
            status, fields = "failed", {"reason": f"{type(exc).__name__}: {exc}"}
        return finish(job, status, **fields)
    finally:
        release_lock(fd)


def run_one_shot(job: dict, folder: Path) -> tuple[str, dict]:
    """Run a one-shot job's command within its limit; (status, the fields to record). The output is kept as
    the command wrote it, also when the limit killed it."""
    if "timeout_minutes" in job:
        limit = f"timeout_minutes ({job['timeout_minutes']})"
    else:
        limit = (f"the one-shot limit of {DEFAULT_ONE_SHOT_TIMEOUT_MINUTES} minutes (set timeout_minutes in the "
                 "command file for a longer one)")
    seconds = job.get("timeout_minutes", DEFAULT_ONE_SHOT_TIMEOUT_MINUTES) * TIMEOUT_UNIT_SECONDS
    outcome, out, err = run_command(job, seconds, limit)
    write_private(folder / "run.stdout.log", keep_tail(out or b""))
    write_private(folder / "run.stderr.log", keep_tail(err or b""))
    fields = {"exit_code": outcome["exit_code"]}
    if outcome.get("reason"):
        fields["reason"] = outcome["reason"]
    try:
        output = json.loads((out or b"").decode("utf-8", errors="replace"))
        if isinstance(output, dict) and output.get(ADDRESS_KEY):
            fields[ADDRESS_KEY] = output[ADDRESS_KEY]
    except ValueError:
        pass
    return outcome["status"], fields


def cmd_check() -> int:
    if sys.platform != "darwin" and not test_mode():
        raise ProviderError("launchd exists only on macOS")
    if not Path(launchctl()).exists():
        raise ProviderError(f"launchctl not found at {launchctl()}")
    # Jobs are loaded into the user's own launchd domain, which exists only while the user has a graphical
    # session: without it every schedule would fail at bootstrap. That is "not configured" (exit 3): the
    # person has something to do, the same reading systemd.py gives an unreachable user manager.
    probe = run_launchctl("print", domain())
    if probe is None or probe.returncode != 0:
        detail = "timed out or could not run" if probe is None else probe.stderr.strip()
        raise ProviderError(f"the user's launchd domain is not reachable (launchctl print {domain()}: {detail}); "
                            "log in to the Mac's desktop as this user, then try again", EXIT_NOT_CONFIGURED)
    print(json.dumps({
        "ready": True,
        "jobs_dir": str(home()),
        "agents_dir": str(agents_dir()),
        "launchd_python": python_for_launchd(),
        "timezone": datetime.now().astimezone().tzname(),
    }, indent=2))
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="launchd.py",
        description="Scheduler provider for macOS: runs a command through launchd once at a set time or every N minutes.",
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("verb", nargs="?", choices=["schedule", "list", "cancel", "resolve", "run"])
    parser.add_argument("--check", action="store_true", help="verify launchd is usable; no side effects")
    parser.add_argument("--id", help="job id: lowercase letters, digits, dots and hyphens")
    parser.add_argument("--at", help="ISO-8601 time with an offset (required), e.g. 2026-09-29T09:00:00-03:00")
    parser.add_argument("--every", type=int, metavar="MINUTES",
                        help=f"run every MINUTES ({EVERY_MIN_MINUTES} to {EVERY_MAX_MINUTES}) instead of once at --at")
    parser.add_argument("--command-file", help="JSON file with argv, cwd, snapshot and grace_minutes (--at) "
                        "or timeout_minutes (--every)")
    parser.add_argument("--dry-run", action="store_true", help="print the job, its approved digest and the plist; do nothing")
    parser.add_argument("--confirmed", action="store_true", help="required to schedule, cancel or resolve")
    parser.add_argument("--done", action="store_true", help="with resolve: the command did its work")
    parser.add_argument("--failed", action="store_true", help="with resolve: the command did not do its work")
    parser.add_argument("--approved", help="with schedule --confirmed: the digest the dry run printed")
    return parser


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)  # every file and folder this provider creates is private to the user
    args = build_parser().parse_args(argv)
    try:
        if args.check:
            return cmd_check()
        if args.verb == "schedule":
            if args.at and args.every is not None:
                raise ProviderError("--at and --every are mutually exclusive", EXIT_USAGE)
            if not args.id or not (args.at or args.every is not None) or not args.command_file:
                raise ProviderError("schedule needs --id, --command-file and one of --at or --every", EXIT_USAGE)
            return cmd_schedule(args)
        if args.verb == "list":
            return cmd_list(args)
        if args.verb in ("cancel", "resolve", "run"):
            if not args.id:
                raise ProviderError(f"{args.verb} needs --id", EXIT_USAGE)
            return {"cancel": cmd_cancel, "resolve": cmd_resolve, "run": cmd_run}[args.verb](args)
        raise ProviderError("give a verb (schedule, list, cancel, resolve) or --check; see --help", EXIT_USAGE)
    except ProviderError as exc:
        log(f"error: {exc}")
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
