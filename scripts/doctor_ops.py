#!/usr/bin/env python3
"""The doctor's checks for a machine that runs the task runtime unattended (package P-OPS, finding I3 and I6): a sibling of
scripts/doctor.py, which calls `run_all` when it is given `--unattended`. Each check is a function that takes what it reads as
arguments (a command runner, a disk-usage function, a folder listing), so that a test passes a fake and no check needs a real
machine. A check returns {"status", "detail"} and, where it applies, "fix": the command or the setting that clears it.

status is one of
  ok          the check ran and the thing is as it should be
  warn        the check ran and found a problem the person should fix
  unverified  the doctor cannot tell from here; detail says what to check by hand
  na          the check does not apply on this machine

What each check can and cannot verify:
  linger          Linux: `loginctl show-user <user> --property=Linger --value`. It CAN tell whether the user manager keeps the user's
                  services running after the last login (without it a scheduled job of a user systemd stops when the session ends,
                  and a server reboot starts nothing until someone logs in). It cannot tell whether the timers themselves are enabled
                  (that is the scheduler provider's check). Elsewhere: na.
  sources_access  macOS: whether a scheduler job (launchd) can read the sources folder. It CAN tell whether the folder lies in a
                  place macOS protects (Desktop, Documents, Downloads, iCloud Drive, a cloud provider's folder under CloudStorage,
                  a network or removable volume) and whether THIS process can list it. It CANNOT tell whether the interpreter a
                  launchd job runs with has been granted access: that permission belongs to the program, is asked of the person in
                  a window, and has no query that does not start a job. So for a protected place the status is "unverified" and the
                  detail names the requirement and the System Settings path. Elsewhere: na.
  disk            free space on the filesystems of data_dir and sources_dir against a threshold (MIN_FREE_GIB, or --min-free-gib). It
                  CAN tell what the filesystem reports; it cannot tell what a quota or a full cloud drive will let a sync client keep.
  proxy_logs      the log limits of the harness's long-lived proxy containers (`docker inspect` of the containers labelled wb.eval
                  whose names are a proxy's or a key holder's). It CAN tell that a limit is set (a log with none fills the disk over
                  weeks); it reads, never changes. It cannot see a container that is not running here. Without docker: unverified.
  secret_store    whether the OS secret store answers (resolver.probe_store: a locked store is not a missing secret). It CAN tell
                  locked, unavailable (no backend on a machine with no desktop session) or answering; it cannot tell that a given
                  secret is in it.
  image           the eval image (the states of scripts/doctor.py image_state), with the setup command to run when it is not present
                  (decision D39: the first pull is an explicit step, never automatic and never in the middle of a dispatch).
  images          the images of earlier definitions of the providers that build one (the converter, the exporter): their count and total
                  size, and the command that removes them (`python3 scripts/doctor.py --remove-old-images --dry-run`, then
                  `--confirmed`). It CAN tell, from the label org.openhora.definition, the repository and the tag, which images are not
                  the current definition's (providers/_container.py old_definition_images); it removes nothing, and its status is never
                  `warn`, so it never changes the exit code. Without docker: unverified.

Standard library only.
"""
from __future__ import annotations

import getpass
import os
import platform
import shutil
import subprocess

MIN_FREE_GIB = 5.0
GIB = 1024 ** 3
LOG_SIZE_KEYS = ("max-size", "max_size")
PROXY_PREFIXES = ("wb-eval-proxy-", "wb-eval-keys-")   # the harness's long-lived proxy and key holders; a run's own containers have no log limit
MAC_PROTECTED = (("Desktop",), ("Documents",), ("Downloads",), ("Library", "Mobile Documents"), ("Library", "CloudStorage"))
MAC_SETTINGS = ("System Settings > Privacy & Security > Full Disk Access (or Files & Folders), add the interpreter the scheduler's job runs "
                "(/usr/bin/python3, the line `ProgramArguments` of the job's plist shows it)")
GiB = lambda n: f"{n / GIB:.1f} GiB"  # noqa: E731


def _run(argv, timeout=15):
    """(returncode, stdout, stderr) of a command; (127, "", why) when it cannot be run."""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, "", f"{argv[0]} cannot be run: {type(e).__name__}"
    return r.returncode, r.stdout, r.stderr


def linger_check(user=None, system=None, run=None) -> dict:
    """Whether the user manager keeps this user's services after the last login (Linux). `run` takes an argv and gives
    (returncode, stdout, stderr)."""
    system = system or platform.system()
    run = run or _run
    if system != "Linux":
        return {"status": "na", "detail": f"linger is a systemd setting; this machine is {system}"}
    user = user or os.environ.get("USER") or getpass.getuser()
    code, out, err = run(["loginctl", "show-user", user, "--property=Linger", "--value"])
    if code != 0:
        return {"status": "unverified", "detail": f"loginctl could not say ({(err or out).strip()[:120] or 'exit ' + str(code)}): check by hand with "
                                                   f"`loginctl show-user {user} --property=Linger --value`"}
    value = out.strip().lower()
    if value == "yes":
        return {"status": "ok", "detail": f"linger is on for {user}: the user's scheduled jobs survive a logout and start after a reboot"}
    if value == "no":
        return {"status": "warn", "fix": f"loginctl enable-linger {user}",
                "detail": f"linger is off for {user}: the user manager stops when the last session ends, so a scheduled job of a user "
                          "systemd does not run on a server nobody is logged in to"}
    return {"status": "unverified", "detail": f"loginctl answered {value!r}, which is neither yes nor no"}


def _protected_place(path: str, home: str, system: str):
    """Why macOS protects `path`, or None. The real path is compared with the protected folders of the home folder, and a volume."""
    real = os.path.realpath(path)
    for parts in MAC_PROTECTED:
        folder = os.path.join(os.path.realpath(home), *parts)
        if real == folder or real.startswith(folder + os.sep):
            return f"it is under ~/{'/'.join(parts)}"
    if real.startswith("/Volumes/"):
        return "it is on a removable or network volume"
    return None


def sources_access_check(sources_dir, system=None, home=None, listdir=os.listdir) -> dict:
    """macOS: whether a scheduler job can read the sources folder. See the module text for what it cannot verify."""
    system = system or platform.system()
    if system != "Darwin":
        return {"status": "na", "detail": f"the file-access permission of a scheduled job is a macOS rule; this machine is {system}"}
    if not sources_dir:
        return {"status": "unverified", "detail": "no project was given (--project), so the sources folder is not known"}
    home = home or os.path.expanduser("~")
    try:
        listdir(sources_dir)
        readable = "this process can list it"
    except OSError as e:
        readable = f"this process cannot list it ({e.strerror})"
    place = _protected_place(sources_dir, home, system)
    if place is None:
        if readable.startswith("this process cannot"):
            return {"status": "warn", "detail": f"{sources_dir}: {readable}", "fix": f"check the folder's owner and mode (0700, yours): `ls -ld '{sources_dir}'`"}
        return {"status": "ok", "detail": f"{sources_dir} is not in a place macOS protects, so a job needs no permission to read it; {readable}. "
                                          "Checked by the path, not by running a job"}
    detail = (f"{sources_dir} is in a protected place ({place}): a launchd job can read it only when the interpreter it runs has been "
              f"allowed, and no query tells whether it was; {readable}")
    if readable.startswith("this process cannot"):
        return {"status": "warn", "detail": detail, "fix": MAC_SETTINGS}
    return {"status": "unverified", "detail": detail + ". Requirement: " + MAC_SETTINGS +
            ". To test, run the scheduler's job once (`python3 scripts/runtime.py` through the scheduler) and read its log", "fix": MAC_SETTINGS}


def _existing_parent(path: str) -> str:
    current = os.path.abspath(path)
    while current and not os.path.exists(current):
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return current


def disk_check(paths: dict, min_free_gib: float = MIN_FREE_GIB, usage=shutil.disk_usage) -> dict:
    """Free space on the filesystem of each named folder ({"data_dir": path, "sources_dir": path}); warn under `min_free_gib`. A folder
    that does not exist yet is measured on its nearest existing parent."""
    rows, worst = [], "ok"
    for name, path in paths.items():
        if not path:
            continue
        where = _existing_parent(path)
        try:
            free = usage(where).free
        except OSError as e:
            rows.append({"name": name, "path": path, "status": "unverified", "detail": f"the free space cannot be read ({e.strerror})"})
            worst = worst if worst == "warn" else "unverified"
            continue
        low = free < min_free_gib * GIB
        rows.append({"name": name, "path": path, "free_bytes": free, "status": "warn" if low else "ok",
                     "detail": f"{GiB(free)} free" + (f", under the {min_free_gib:g} GiB threshold" if low else "")})
        worst = "warn" if low else worst
    if not rows:
        return {"status": "unverified", "detail": "no folder was given (--project names data_dir and sources_dir)", "rows": []}
    fix = "free space on that disk, lower run_retention_days / source_versions_kept in runtime.json, or move the folder" if worst == "warn" else None
    return {"status": worst, "detail": "; ".join(f"{r['name']}: {r['detail']}" for r in rows), "rows": rows, **({"fix": fix} if fix else {})}


def proxy_logs_check(tool=None) -> dict:
    """The log limits of the harness's proxy containers. `tool(*args) -> (returncode, stdout)` is the container client (None: docker)."""
    tool = tool or (lambda *a: _run(["docker", *a], timeout=30)[:2])
    code, out = tool("ps", "-a", "--filter", "label=wb.eval", "--format", "{{.Names}}")
    if code != 0:
        return {"status": "unverified", "detail": "docker cannot be asked (not installed, or the daemon is not running): the log limits of the "
                                                    "harness's proxies were not read"}
    names = sorted(n for n in (line.strip() for line in out.splitlines()) if n.startswith(PROXY_PREFIXES))
    if not names:
        return {"status": "ok", "detail": "no proxy container of the harness exists on this machine yet (a limit is set when it is made)", "rows": []}
    rows = []
    for name in names:
        code, text = tool("inspect", "--format", "{{json .HostConfig.LogConfig}}", name)
        limit = _log_limit(text) if code == 0 else None
        rows.append({"name": name, "limit": limit, "status": "ok" if limit else "warn"})
    bad = [r["name"] for r in rows if r["status"] == "warn"]
    if bad:
        return {"status": "warn", "rows": rows, "detail": "no size limit on the log of " + ", ".join(bad) + ": a proxy that runs for weeks fills the disk with it",
                "fix": "remove the container so the next `python3 evals/executor.py ensure` makes it again with the harness's limits "
                       "(max-size and max-file)"}
    return {"status": "ok", "rows": rows, "detail": "; ".join(f"{r['name']}: {r['limit']}" for r in rows)}


def _log_limit(text: str):
    """"max-size=10m, max-file=3" when the LogConfig of `docker inspect` sets a size limit on a json-file or local log, else None."""
    import json
    try:
        config = json.loads(text)
    except ValueError:
        return None
    if not isinstance(config, dict) or config.get("Type") not in ("json-file", "local"):
        return None
    options = config.get("Config") or {}
    size = next((options[k] for k in LOG_SIZE_KEYS if options.get(k)), None)
    if not size:
        return None
    files = options.get("max-file") or options.get("max_file")
    return f"max-size={size}" + (f", max-file={files}" if files else "")


def docker_tool(*args):
    """(returncode, stdout) of one container client command, bounded in time; (127, "") when the client cannot be run."""
    code, out, _err = _run(["docker", *args], timeout=60)
    return code, out


def images_check(tool=None, families=None, box=None) -> dict:
    """The images of earlier definitions of the providers that build one. `families` is [{"family", "repository", "hash"}] (scripts/doctor.py
    image_families), `box` the module providers/_container.py, `tool(*args) -> (returncode, stdout)` the container client (None: docker).
    The status is `ok` (or `unverified`, `na`), never `warn`: the row tells and removes nothing."""
    if not families or box is None:
        return {"status": "na", "detail": "no provider that builds an image is here"}
    tool = tool or docker_tool
    code, _out = tool("version", "--format", "{{.Server.Version}}")
    if code != 0:
        return {"status": "unverified", "detail": "docker cannot be asked (not installed, or the daemon is not running): the images of earlier "
                                                    "definitions were not looked for"}
    rows = []
    for family in families:
        for item in box.old_definition_images(tool, family["repository"], family["hash"]):
            rows.append({"family": family["family"], **item})
    command = "python3 scripts/doctor.py --remove-old-images --dry-run"
    if not rows:
        return {"status": "ok", "detail": "no image of an earlier definition is here", "rows": [], "count": 0, "bytes": 0}
    total = sum(r["size"] for r in rows)
    return {"status": "ok", "rows": rows, "count": len(rows), "bytes": total, "fix": command,
            "detail": f"{len(rows)} image(s) of earlier definitions, {total / 1024 ** 2:.0f} MiB: " + ", ".join(r["image"] for r in rows)
                      + f". To see what would go, then remove them: {command}, then the same with --confirmed"}


def secret_store_check(probe) -> dict:
    """The state of the OS secret store from `probe() -> {"state", "detail"}` (the resolver's probe_store)."""
    try:
        answer = probe()
    except Exception as e:  # a resolver that does not run here
        return {"status": "unverified", "detail": f"the secret store could not be asked: {type(e).__name__}"}
    state = answer.get("state")
    if state == "ok":
        return {"status": "ok", "detail": "the secret store answers"}
    if state in ("locked", "unavailable"):
        return {"status": "warn", "detail": "the secret store is locked or unavailable: unlock it (a locked keychain or collection); a routine that "
                                              "needs a key it holds fails until then, and the key is not missing",
                "fix": "unlock the store, or on a machine with no desktop session put the secrets in the credentials directory "
                       "(docs/architecture/platform/unattended.md)"}
    if state == "credentials-unsafe":
        return {"status": "warn", "detail": f"the credentials directory is unsafe, so no secret is read from it (a secret there is not missing): "
                                              f"{answer.get('detail')}", "fix": "give the folder and its files the mode the message names"}
    if state == "no-library":
        return {"status": "unverified", "detail": "the keyring library is not available in this Python, so the store was not asked: run with "
                                                    "`uv run --with keyring==25.7.0 python3 ...`, or use the credentials directory"}
    return {"status": "unverified", "detail": str(answer.get("detail") or state)}


def image_check(image) -> dict:
    """The eval image as a check: ok when it is present (published, or a local build), a warning with the setup command when it is not.
    `image` is scripts/doctor.py image_state with its "setup" added."""
    if not image:
        return {"status": "unverified", "detail": "the image was not looked at"}
    state = image.get("state")
    if state in ("published-present", "local-only"):
        return {"status": "ok", "state": state, "detail": ("the published image is on this machine" if state == "published-present" else
                "a local build is here and no published image is named for this definition: evidence measured in it holds on this machine only")}
    return {"status": "warn", "state": state, "detail": f"the eval image is not on this machine ({image.get('detail') or state}): no run can start",
            "fix": image.get("setup")}


def ack_lease(data_dir) -> bool:
    """Clear the record of a lease takeover (`<data_dir>/lease-takeover.json`) once a person has looked at it. True when a record was there.
    Only that one regular file of data_dir is removed, and never through a link."""
    path = os.path.join(data_dir, "lease-takeover.json")
    try:
        if not os.path.isfile(path) or os.path.islink(path):
            return False
        os.unlink(path)
        return True
    except OSError:
        return False


def lease_check(data_dir, project=None) -> dict:
    """Whether this host took over the expired lease of another host's write of the sources folder (the runtime records it in
    `<data_dir>/lease-takeover.json`). A takeover is not an error, but two machines were writing one folder not long ago, so it is told."""
    if not data_dir:
        return {"status": "unverified", "detail": "no project was given (--project), so the lease record is not known"}
    import json
    path = os.path.join(data_dir, "lease-takeover.json")
    try:
        with open(path, encoding="utf-8") as f:
            record = json.load(f)
    except OSError:
        return {"status": "ok", "detail": "this host has not taken over another host's lease of the sources folder"}
    except ValueError:
        return {"status": "unverified", "detail": f"{path} cannot be read"}
    return {"status": "warn", "detail": f"on {record.get('at')} this host took over the expired lease of the host {record.get('from_host')!r}: "
                                          "another machine wrote the sources folder shortly before. Check that only one runtime writes it",
            "fix": "if that is expected, acknowledge it: python3 scripts/doctor.py --unattended --project "
                   f"{project or '<project>'} --ack-lease"}


def run_all(*, project=None, min_free_gib=MIN_FREE_GIB, image=None, probe=None, load_config=None, tool=None, run=None,
            system=None, usage=shutil.disk_usage, listdir=os.listdir, home=None, user=None, families=None, box=None) -> dict:
    """Every check, as {"linger", "sources_access", "disk", "proxy_logs", "lease", "secret_store", "image", "images", "project"}. `load_config(project)` gives
    the project's configuration (its data_dir and sources_dir) or raises; every seam is a keyword so a test passes a fake."""
    paths, note = {}, None
    if project:
        try:
            cfg = load_config(project)
            paths = {"data_dir": cfg["data_dir"], "sources_dir": cfg["sources_dir"]}
        except Exception as e:  # a project that is not configured is reported, not raised
            note = f"{project}: {e}"
    return {
        "linger": linger_check(user=user, system=system, run=run),
        "sources_access": sources_access_check(paths.get("sources_dir"), system=system, home=home, listdir=listdir),
        "disk": disk_check(paths, min_free_gib, usage),
        "proxy_logs": proxy_logs_check(tool),
        "lease": lease_check(paths.get("data_dir"), project),
        "secret_store": secret_store_check(probe) if probe else {"status": "unverified", "detail": "no probe was given"},
        "image": image_check(image),
        "images": images_check(tool, families, box),
        "project": {"status": "warn" if note else ("ok" if project else "na"), "detail": note or (project or "no --project given")},
    }
