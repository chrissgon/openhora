#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The step kind `project-script`: run one of the project's own scripts as a step, under limits that live in code (package P9, decision D25).

A script is the project's own code, written by the person or by a model they reviewed, so it is run only after its EXACT content has been
approved, only in a sandbox, and only with what its approval names. The approval is the plan's: the arguments below are in the plan hash
(runtime/plan.py shows them and hashes them), so a plan that names a script cannot be approved for one file and run for another.

Arguments (checked when the task is planned; `prepare` below builds them from the files and refuses a credential first):

  {"script": "scripts/report.py",        the script's path in the project: relative, plain names, no folder or file starting with a dot,
                                         `.py` (Python) or `.sh` (bash), inside no sources folder
   "sha256": "<64 hex>",                 the sha256 of the script's exact bytes
   "source": "<source id>",              the source the result becomes a new version of (a `file` source; registered here when new)
   "destinations": ["api.example:443"],  the host:port pairs the script may reach, lowercase DNS names (no IP literal, no wildcard); [] for none
   "lock": "scripts/requirements.lock",  optional, Python only: a hashed lock file (`name==version --hash=sha256:...`, nothing else)
   "lock_sha256": "<64 hex>"}            the sha256 of the lock file's exact bytes (given with `lock`, never without)

What each step does (steps verify, deps and run; the task is resumable at the one that failed):

  verify   reads the script (and the lock file) from the project, one folder at a time with O_NOFOLLOW, from the project root; compares
           its sha256 with the approved one (`script_changed`: the step stops, nothing is staged, nothing runs, and the person plans the
           step again, so the new hash is approved by a plan of its own); scans it for credentials and names the LINE, never the value
           (`script_has_credential`). The same checks run again on the bytes the `run` step stages, so a file swapped after `verify` changes
           nothing: the staged bytes are the ones that were hashed.
  deps     with a lock file: the provider builds, in a container with NO mount and with network only to the package index through a
           per-step proxy, an image layer that holds the installed wheels (pip --require-hashes --only-binary=:all: --no-deps), cached by
           the lock's sha256. Without one: nothing.
  run      the provider runs the staged script in a sandbox (providers/script/container.py): no credential in its environment, a read-only
           root, only the script mounted (read-only), the installed dependencies read-only, a size-capped memory-backed folder for the
           output, a non-root user, no capability, no network unless destinations are declared and then only those, through a per-step
           egress proxy on an internal network. The result file comes back as frames (never a folder), is read back by the host with the
           rules of limit L24, and becomes a NEW VERSION of the source, labelled as produced by the script (its sha256 is in the manifest
           and in the converter's record). A script has no other way to write anything: not in the project, not in the sources folder
           but through this import, and it has no way to cause an effect (a post, a message, a commit): an effect goes through the effect
           gate, which a script cannot open.

The kind `brings_source` (the flow check sees the source its result makes, like an ingest's) and is NOT `unattended`: the dispatcher never starts it on its own; a person starts it (run-step). The kind is `networked` (always: it cannot know at registration whether a task declares destinations), so a routine whose flow holds one is made and changed only from the terminal or the page (limit L33), and the routine's approved content holds, for each such step, the script's sha256, its destinations, the lock file's sha256 and the definition hash of the script image (`Kind.routine_slot`, `steps.routine_slots`, the `scripts` slot of runtime/routines.py), so that a change to any of them stops the routine and asks. A routine that fires finds the task held `start it by hand`: the kind is not unattended, and running a script without a person is a later decision.
The person's brake does not matter to this kind: it is never started by the dispatcher anyway.

The files are also checked when a plan is built and before it is approved (`vet`, steps.Kind.vet; runtime/ops_flows.py): a hash written
by hand into a flow is compared with the file and the file is scanned for credentials before anyone approves the plan.

The result recorded is closed words and numbers: the source id, the version, whether a version was made, the exit code and milliseconds.
The script's own output text (its log) is never kept: it is not in the state, a note or a decision (run the script yourself to debug it).

  python3 runtime/step_project_script.py prepare --project <dir> --script <rel path> --source <id> [--destination <host:port>]...
                                                [--lock <rel path>]
      prints the arguments (JSON) for a plan: the hashes of the files as they are now, after the credential scan. Writes nothing.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import errno
import hashlib
import ipaddress
import json
import os
import re
import shutil
import stat
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import ops_core as core  # noqa: E402  (read as core.<name>)
import ops_sources  # noqa: E402
import sources  # noqa: E402
import steps  # noqa: E402

KEYS = ("script", "sha256", "source", "destinations", "lock", "lock_sha256")
SHA256 = re.compile(r"[0-9a-f]{64}")
SEGMENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*")
EXTENSIONS = {".py": "py", ".sh": "sh"}
FILE_CAP = 256 * 1024                      # a script and a lock file (the provider's FILE_CAP)
DESTINATIONS_MAX = 8                       # the provider's DESTINATIONS_MAX
HOST = re.compile(r"(?=.{1,253}\Z)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+")
TOP_LABEL = re.compile(r"[a-z][a-z0-9-]*")
LOCK_REQUIREMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9][A-Za-z0-9._!+-]*")
LOCK_HASH = re.compile(r"--hash=sha256:[0-9a-f]{64}")
SCRIPT_CLASS = "script:project"
SCRIPT_TIMEOUT = 300                       # seconds a script may run (the provider's DEFAULT_TIMEOUT): in code, not in an argument
DEPS_TIMEOUT = 900                         # seconds a dependency build may take (the provider's BUILD_TIMEOUT)
CALL_MARGIN = 180                          # seconds beyond the container's limit that the provider's own set-up and clean-up may take
OUTPUT_NAMES = ("result.md", "result.csv", "result.txt", "info.json")
OUTPUT_ENTRIES_MAX = 2
RESULT_KIND = {"result.md": "markdown", "result.txt": "markdown", "result.csv": None}   # None: the normal path (sniffed, converted)
ERROR_WORD = re.compile(r"error: ([a-z][a-z_]{1,40}):")
# The words the provider may answer with (providers/script/container.py ProviderError.word and the container helper's codes): a failure
# the runtime records is one of these or `provider_failed`.
PROVIDER_WORDS = ("not_configured", "usage", "bad_image", "bad_output", "bad_lock", "lock_changed", "bad_environment", "build_failed",
                  "time_limit", "stopped", "output_too_large", "container_failed", "network_failed", "network_not_internal",
                  "proxy_failed", "destination_unresolvable", "destination_not_public", "destination_bad_declaration",
                  "destination_refused", "docker_missing", "docker_unusable", "docker_daemon_not_local", "docker_daemon_unknown")
HOW_TO_PLAN = ("read the file, then plan the step again with `python3 runtime/step_project_script.py prepare ...`: its new hash is "
               "approved by the new plan")


def _script_error(code: str, field: str = "script", next: str = "") -> "steps.StepFailure":
    return steps.StepFailure(code, field, "", next)


def kind_of_script(path: str) -> str:
    """`py` or `sh`, from the extension; StepFailure(bad_args, script) for any other."""
    ext = os.path.splitext(path)[1]
    if ext not in EXTENSIONS:
        raise _script_error("bad_args")
    return EXTENSIONS[ext]


def check_path(value, field: str) -> str:
    """A path in the project as a plan carries it: relative, at most 120 characters, 1 to 6 plain segments, none starting with a dot
    (no `.git`, no `.workbench-local`, no credential file named `.env`)."""
    if not isinstance(value, str) or not value or len(value) > 120 or not steps.REL_PATH.fullmatch(value):
        raise steps.StepFailure("bad_args", field)
    parts = value.split("/")
    if len(parts) > 6 or not all(SEGMENT.fullmatch(p) for p in parts):
        raise steps.StepFailure("bad_args", field)
    return value


def check_destination(item) -> str:
    """One declared destination as the proxy reads it: a lowercase DNS name with a dot and a top label that starts with a letter (so no
    IP literal and no decimal, hexadecimal or octal spelling of an address), and a port from 1 to 65535. Returns `host:port`, the host
    with one trailing dot dropped. The same rule as providers/script/egress_proxy.py `parse_declared` (a test holds them equal)."""
    if not isinstance(item, str):
        raise steps.StepFailure("bad_args", "destinations")
    host, sep, port = item.rpartition(":")
    host = host.lower()
    host = host[:-1] if host.endswith(".") else host
    if not sep or not HOST.fullmatch(host) or not TOP_LABEL.fullmatch(host.rsplit(".", 1)[1]) or not port.isdigit() \
            or len(port) > 5 or not 1 <= int(port) <= 65535:
        raise steps.StepFailure("bad_args", "destinations")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return f"{host}:{int(port)}"
    raise steps.StepFailure("bad_args", "destinations")


def check(args) -> dict:
    """The arguments of a project script, checked and made canonical (the keys in a fixed set, the destinations sorted and distinct)."""
    if not isinstance(args, dict) or set(args) - set(KEYS):
        raise steps.StepFailure("bad_args", "args")
    for key in ("script", "sha256", "source"):
        if args.get(key) is None:
            raise steps.StepFailure("bad_args", key)
    script = check_path(args["script"], "script")
    kind = kind_of_script(script)
    if not isinstance(args["sha256"], str) or not SHA256.fullmatch(args["sha256"]):
        raise steps.StepFailure("bad_args", "sha256")
    try:
        source = sources.check_id(args["source"])
    except sources.SourcesError:
        raise steps.StepFailure("bad_args", "source") from None
    declared = args.get("destinations", [])
    if not isinstance(declared, (list, tuple)) or len(declared) > DESTINATIONS_MAX:
        raise steps.StepFailure("bad_args", "destinations")
    out = {"script": script, "sha256": args["sha256"], "source": source,
           "destinations": sorted({check_destination(item) for item in declared})}
    if (args.get("lock") is None) != (args.get("lock_sha256") is None):
        raise steps.StepFailure("bad_args", "lock_sha256")
    if args.get("lock") is not None:
        if kind != "py":
            raise steps.StepFailure("bad_args", "lock")          # a shell script has no dependencies
        out["lock"] = check_path(args["lock"], "lock")
        if not isinstance(args["lock_sha256"], str) or not SHA256.fullmatch(args["lock_sha256"]):
            raise steps.StepFailure("bad_args", "lock_sha256")
        out["lock_sha256"] = args["lock_sha256"]
    return out


# --- the files -----------------------------------------------------------------------------------------------------------------------


def read_project_file(project: str, rel: str, protected=lambda path: False, field: str = "script") -> bytes:
    """The bytes of a file of the project, read from the project root one folder at a time with O_NOFOLLOW (a link anywhere on the way
    is refused), the file opened with O_NOFOLLOW | O_NONBLOCK and looked at again through its descriptor (a regular file, the same inode),
    at most FILE_CAP bytes. A path inside what `protected` names (the sources folder) is refused. StepFailure: script_missing,
    script_too_large, path_unsafe, protected_path."""
    root = os.path.realpath(project)
    parts = rel.split("/")
    if protected(os.path.join(root, *parts)):
        raise steps.StepFailure("protected_path", field)
    opened = []
    try:
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        opened.append(fd)
        for part in parts[:-1]:
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            opened.append(fd)
        before = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise steps.StepFailure("script_missing", field)
        leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        opened.append(leaf)
        after = os.fstat(leaf)
        if not stat.S_ISREG(after.st_mode) or not os.path.samestat(before, after):
            raise steps.StepFailure("script_missing", field)
        if after.st_size > FILE_CAP:
            raise steps.StepFailure("script_too_large", field)
        data = os.read(leaf, FILE_CAP + 1)
        if len(data) > FILE_CAP:
            raise steps.StepFailure("script_too_large", field)
        return data
    except OSError as e:
        if e.errno in steps.LINK_ERRNOS:
            raise steps.StepFailure("path_unsafe", field) from None
        raise steps.StepFailure("script_missing", field) from None
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)


def credential_line(data: bytes, field: str):
    """Look for a credential in a file. Raises StepFailure(script_not_text) when the bytes are not UTF-8 text without a NUL, and
    StepFailure(script_has_credential, line_<n>) naming the first line that looks like one and its label (a format name, never the
    value). Returns None when the file is clean."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise _script_error("script_not_text", field) from None
    if "\x00" in text:
        raise _script_error("script_not_text", field)
    findings = sources._workcopy().credential_findings
    for number, line in enumerate(text.splitlines(), 1):
        found = findings(line)
        if found:
            label = re.sub(r"[^A-Za-z0-9 _.-]", "", str(found[0]))[:40]
            raise steps.StepFailure("script_has_credential", f"line_{number}", "",
                                    f"line {number} of the {field} looks like a credential ({label}): take it out of the file and plan the step again")
    return None


def lock_problem(data: bytes):
    """Why a lock file is not one, or None. The rules of the build container (providers/script/_inner.py `check_lock`; the runtime does not
    reach into the provider's files, so they are written here too, and a test holds the two equal): blank lines, whole-line comments, and
    `name==version` followed by one or more `--hash=sha256:<64 hex>` options, on the same line or on continuation lines (a trailing
    backslash); 1 to 200 requirements; nothing else (no index, URL, path, editable install or other file)."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "a lock file is UTF-8 text"
    count, pending = 0, []
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            if pending:
                return "a lock file ends a continued line with a blank or comment line"
            continue
        joined = line.endswith("\\")
        pending += (line[:-1] if joined else line).split()
        if not joined:
            if len(pending) < 2 or not LOCK_REQUIREMENT.fullmatch(pending[0]) or not all(LOCK_HASH.fullmatch(p) for p in pending[1:]):
                return "a lock line is `name==version` with --hash=sha256:<hex> options, nothing else"
            count, pending = count + 1, []
    if pending:
        return "a lock file ends inside a continued line"
    if not 1 <= count <= 200:
        return "a lock file names from 1 to 200 requirements"
    return None


def prepare(project: str, script: str, source: str, destinations=(), lock=None, protected=lambda path: False) -> dict:
    """The arguments of a project script for a plan, from the files as they are now: read, scanned for credentials (a refusal names the
    line, never the value) and hashed. StepFailure when a file is refused. Writes nothing."""
    path = check_path(script, "script")
    body = {"script": path, "source": source, "destinations": list(destinations)}
    data = read_project_file(project, path, protected, "script")
    credential_line(data, "script")
    body["sha256"] = hashlib.sha256(data).hexdigest()
    if lock is not None:
        lock_path = check_path(lock, "lock")
        lock_data = read_project_file(project, lock_path, protected, "lock")
        credential_line(lock_data, "lock")
        problem = lock_problem(lock_data)
        if problem:
            raise steps.StepFailure("bad_lock", "lock", "", problem)
        body.update(lock=lock_path, lock_sha256=hashlib.sha256(lock_data).hexdigest())
    return check(body)


class Files:
    """The verified bytes of a task's script (and lock file): what the steps stage and hash again."""

    def __init__(self, script: bytes, lock):
        self.script, self.lock = script, lock


def load_files(ctx: "steps.Context") -> Files:
    """The task's script and lock file read and checked (load_checked) for the run."""
    return load_checked(ctx.project, ctx.args, ctx.protected)


def load_checked(project: str, args: dict, protected=lambda path: False) -> Files:
    """Read the script and lock file the arguments name and check them against the approved hashes, in this order: the hash
    (`script_changed`, `lock_changed`), the credential scan, the lock file's form. The bytes returned are the ones hashed."""
    data = read_project_file(project, args["script"], protected, "script")
    if hashlib.sha256(data).hexdigest() != args["sha256"]:
        raise _script_error("script_changed", "script", HOW_TO_PLAN)
    credential_line(data, "script")
    lock = None
    if args.get("lock"):
        lock = read_project_file(project, args["lock"], protected, "lock")
        if hashlib.sha256(lock).hexdigest() != args["lock_sha256"]:
            raise _script_error("lock_changed", "lock", HOW_TO_PLAN)
        credential_line(lock, "lock")
        problem = lock_problem(lock)
        if problem:
            raise steps.StepFailure("bad_lock", "lock", "", problem)
    return Files(data, lock)


def vet(project: str, args: dict, protected=lambda path: False) -> None:
    """The kind's hook for the plan (steps.Kind.vet): the files the arguments name are read and checked now, when the plan is built and
    before it is approved, with the checks of the run, so that a hash written by hand into a flow is scanned for credentials, and
    compared with the file, before a person approves it."""
    load_checked(project, check(args), protected)


# --- the provider ------------------------------------------------------------------------------------------------------------------------


def provider_call(ctx: "steps.Context", cfg: dict, verb: str, args: list, timeout: int) -> dict:
    """One verb of the provider of script:project, through providers/resolve.py, in a process that has the minimum environment and no
    secret. `ctx.services["script_call"](verb, args, timeout)` is the seam a test replaces. StepFailure with a closed word."""
    seam = ctx.services.get("script_call")
    try:
        if seam is not None:
            out = seam(verb, args, timeout)
        else:
            resolver = sources._lazy("workbench_sources_resolve", os.path.join(cfg["workbench"], "providers", "resolve.py"))
            out = resolver.call(SCRIPT_CLASS, verb, args, root=cfg["workbench"], timeout=timeout + CALL_MARGIN,
                                env=sources._provider_env(cfg, SCRIPT_CLASS))
    except steps.StepFailure:
        raise
    except Exception as e:
        reason = getattr(e, "reason", None) or str(e)
        found = ERROR_WORD.search(reason)
        word = found.group(1) if found and found.group(1) in PROVIDER_WORDS else "provider_failed"
        if getattr(e, "kind", "") == "timeout":
            word = "time_limit"
        raise steps.StepFailure(word, "", "script", "run `python3 providers/script/container.py --check`; the reason is on its standard error") from None
    if not isinstance(out, dict):
        raise steps.StepFailure("provider_failed", "", "script")
    return out


def stage(cfg: dict, files: Files, kind: str) -> str:
    """A private staging folder (the sources module's: <data_dir>/sources-staging/<token>/{in,out}, 0700) holding the verified script
    (mode 0444: the container's user is not this one) and lock file (0400). Returns the folder; the caller removes it."""
    token = os.urandom(8).hex()
    folder = sources._make_staging(cfg["data_dir"], token)
    for name, data, mode in (("script", files.script, 0o444), ("lock", files.lock, 0o400)):
        if data is None:
            continue
        fd = os.open(os.path.join(folder, "in", name), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    return folder


# --- the steps ---------------------------------------------------------------------------------------------------------------------------


def _verify(ctx: "steps.Context", state: dict) -> dict:
    files = load_files(ctx)
    out = {"script_sha256": ctx.args["sha256"], "bytes": len(files.script)}
    if files.lock is not None:
        out["lock_sha256"] = ctx.args["lock_sha256"]
    return out


def _deps(ctx: "steps.Context", state: dict) -> dict:
    if not ctx.args.get("lock"):
        return {"deps": "none"}
    files = load_files(ctx)
    cfg = core.context(ctx.project)["cfg"]
    folder = stage(cfg, Files(None, files.lock), "py")      # only the lock file goes to the provider's staging
    try:
        done = provider_call(ctx, cfg, "deps", ["--lock", os.path.join(folder, "in", "lock"), "--lock-sha256", ctx.args["lock_sha256"],
                                                "--timeout", str(DEPS_TIMEOUT)], DEPS_TIMEOUT)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    image = done.get("image")
    if not isinstance(image, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise steps.StepFailure("provider_failed", "image", "script")
    return {"deps": "cached" if done.get("cached") else "built", "image": image}


def _source_row(cctx: dict, source_id: str, script: str) -> dict:
    """The registry row of the source the result goes to: the registered one (a `file` source), or a new one."""
    store = cctx["store"]
    try:
        row = sources.public_row(store.source_get(cctx["conn"], source_id))
    except store.StoreError:
        return sources.register(cctx, source_id, "file", "script-" + script.rsplit("/", 1)[1])
    if row["type"] != "file":
        raise steps.StepFailure("source_type", "source", "sources", "a script's result becomes a version of a `file` source")
    return row


def _run(ctx: "steps.Context", state: dict) -> dict:
    args = ctx.args
    files = load_files(ctx)
    kind = kind_of_script(args["script"])
    cctx = core.context(ctx.project)
    cfg = cctx["cfg"]
    image = ((state.get("steps") or {}).get("deps") or {}).get("result", {}).get("image") if args.get("lock") else None
    if args.get("lock") and not image:
        raise steps.StepFailure("deps_missing", "lock", "", "prepare the deps step again")
    folder = stage(cfg, files, kind)
    try:
        call = ["--script", os.path.join(folder, "in", "script"), "--kind", kind, "--out-dir", os.path.join(folder, "out"),
                "--timeout", str(SCRIPT_TIMEOUT)]
        if image:
            call += ["--image", image, "--lock-sha256", args["lock_sha256"]]    # the image must carry the approved lock's hash
        for item in args["destinations"]:
            call += ["--destination", item]
        done = provider_call(ctx, cfg, "run", call, SCRIPT_TIMEOUT)
        if done.get("signal"):
            raise steps.StepFailure("script_killed", f"signal_{int(done['signal'])}"[:40], "", "the script was ended by a signal (memory, processes or time)")
        if done.get("exit") != 0:
            raise steps.StepFailure("script_failed", f"exit_{int(done['exit'])}"[:40] if isinstance(done.get("exit"), int) else "", "",
                                    "the script's log is not kept: run it yourself to see why it failed")
        if done.get("refused"):
            raise steps.StepFailure("output_refused", "result", "", "the script left a file that is not result.md, result.csv or result.txt "
                                    "in $OUTPUT_DIR, or more than one result")
        try:
            outputs = sources.collect_outputs(os.path.join(folder, "out"), names=OUTPUT_NAMES, entries_max=OUTPUT_ENTRIES_MAX, who="script")
        except sources.SourcesError as e:
            raise steps.StepFailure("output_too_large" if e.code == "size" else "output_refused", "result") from None
        found = [n for n in outputs if n in RESULT_KIND]
        if len(found) != 1:
            raise steps.StepFailure("no_result", "result", "", "write the result to result.md, result.csv or result.txt in $OUTPUT_DIR")
        made = _import(ctx, cctx, args, files, found[0], outputs[found[0]])
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return {"source": args["source"], "version": made.get("version") if isinstance(made.get("version"), int) else None,
            "made": bool(made.get("imported")), "unchanged": not made.get("imported"),
            "exit": 0, "duration_ms": done.get("duration_ms") if isinstance(done.get("duration_ms"), int) else None}


def _import(ctx: "steps.Context", cctx: dict, args: dict, files: Files, name: str, data: bytes) -> dict:
    """The result becomes a new version of the source, through the one door every version uses (sources.import_version: the intake's
    bounds, the credential scan of the text, the folder written through its descriptor with O_NOFOLLOW, the lease). The manifest and the
    record of the converter say it was produced by this script: its path, its sha256, its destinations and its lock file's sha256."""
    cfg = cctx["cfg"]
    produced = {"script": args["script"], "script_sha256": args["sha256"], "destinations": args["destinations"]}
    if args.get("lock_sha256"):
        produced["lock_sha256"] = args["lock_sha256"]
    try:
        evidence = ops_sources._evidence_base()      # the local evidence folder (limit L22), asked of the lab by the sources operations
        row = _source_row(cctx, args["source"], args["script"])
        convert = ctx.services.get("convert") or sources.provider_convert(cfg)
        return sources.import_version(
            cctx, row, data, convert=convert, label="import", by="runtime", kind=RESULT_KIND[name],
            name=f"{args['script'].rsplit('/', 1)[1]}: {name}", evidence_base=evidence,
            manifest_extra={"converter": {"name": "project-script", "tools": produced}, "produced_by": {"kind": "project-script", **produced}})
    except sources.SourcesError as e:
        word = e.code if re.fullmatch(r"[a-z]{3,12}", str(e.code)) else "refused"
        raise steps.StepFailure(f"import_{word}", "source", "sources", "run the same import by hand to read the reason") from None


SCRIPT_IMAGE_FILES = ("Dockerfile", ".dockerignore", "_inner.py", "egress_proxy.py")      # providers/script/container.py DEFINITION_FILES


def image_definition(workbench_root: str):
    """The definition hash of the script image of this checkout (the same sha256 as providers/script/container.py `definition_hash`,
    computed from the same four files; a test holds the two equal), or None when the folder is not there. A routine's approved content
    holds it, so that a changed image definition stops the routine."""
    folder = os.path.join(workbench_root, "providers", "script")
    digest = hashlib.sha256()
    try:
        for name in sorted(SCRIPT_IMAGE_FILES):
            with open(os.path.join(folder, name), "rb") as f:
                digest.update(name.encode() + b"\0" + f.read() + b"\0")
    except OSError:
        return None
    return digest.hexdigest()


def routine_slot(args: dict, workbench_root: str) -> dict:
    """What a routine's approved content holds for a project-script step (steps.Kind.routine_slot): the script's path and sha256, the
    declared destinations, the lock file's sha256 and the definition hash of the script image. Read from the template as written."""
    destinations = args.get("destinations")
    return {"script": args.get("script"), "sha256": args.get("sha256"),
            "destinations": sorted(destinations) if isinstance(destinations, list) and all(isinstance(d, str) for d in destinations) else destinations,
            "lock_sha256": args.get("lock_sha256"), "image_definition": image_definition(workbench_root)}


KIND = steps.register(steps.Kind(
    name="project-script",
    order=("verify", "deps", "run"),
    executors={"verify": _verify, "deps": _deps, "run": _run},
    footprint=lambda args: (),
    check=check,
    unattended=False,
    vet=vet,
    routine_slot=routine_slot,
    networked=True,          # the kind cannot know at registration whether a task declares destinations, so every flow that holds one is terminal/page only (L33)
    brings_source=True,      # its `source` argument names the source its result becomes a version of: the tasks after it receive it
))


# --- the command line --------------------------------------------------------------------------------------------------------------------


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help") or argv[0] != "prepare":
        print(__doc__.strip(), file=sys.stdout if argv[:1] in (["-h"], ["--help"]) else sys.stderr)
        return 0 if argv[:1] in (["-h"], ["--help"]) else 2
    options, destinations, i = {}, [], 1
    while i < len(argv):
        if argv[i] in ("--project", "--script", "--source", "--lock", "--destination") and i + 1 < len(argv):
            if argv[i] == "--destination":
                destinations.append(argv[i + 1])
            else:
                options[argv[i][2:]] = argv[i + 1]
            i += 2
        else:
            print(f"error: unknown argument {argv[i][:40]!r}; see --help", file=sys.stderr)
            return 2
    for need in ("project", "script", "source"):
        if need not in options:
            print(f"error: --{need} is required", file=sys.stderr)
            return 2
    protected = lambda path: False   # noqa: E731
    try:
        cfg = core._config_of(options["project"])
        protected = lambda path: sources.inside(cfg, path)   # noqa: E731
    except core.OpsError:
        pass                          # the run asks again with the configuration in hand
    try:
        print(json.dumps(prepare(options["project"], options["script"], options["source"], destinations, options.get("lock"), protected),
                         indent=1, sort_keys=True))
    except steps.StepFailure as e:
        print(f"refused: {e.code} {e.field}".strip() + (f" -- {e.next}" if e.next else ""), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
