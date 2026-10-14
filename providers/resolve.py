#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Resolve a requirement class to the provider script that satisfies it.

This is the one place that turns a class from contracts/environment.md (`scheduler:job`,
`publisher:<platform>`, `integration:vcs`) into a script under providers/. Skills, the agent
runtime and scripts/doctor.py all ask here; none of them names an implementation.

Usage:
  python3 providers/resolve.py --class <class> [--json] [--root <workbench root>]
  python3 providers/resolve.py --list [--root <workbench root>]
  python3 providers/resolve.py --help

  --class <class>  print the absolute path of the provider script chosen for the class
                   (with --json: class, implementation, path, source, variables)
  --list           print, as JSON, every class with its folder, its variables, the
                   implementations shipped and the one that resolves now
  --root <path>    the workbench checkout to look in, instead of WORKBENCH_ROOT

A class is <role>:<target> (providers/CONTRACT.md). How it maps to a folder and to its variables:
  <role>:<target>        -> providers/<role>/      generator:image -> providers/generator/
                            <ROLE>_<TARGET>_PROVIDER, then <ROLE>_PROVIDER
  integration:<service>  -> providers/<service>/   integration:vcs -> providers/vcs/
                            INTEGRATION_<SERVICE>_PROVIDER only: one integration never serves another
  the four classes of the table FIXED keep the folder and the variable they had when their names
  were bare:
    reader:email   -> providers/mailbox/    MAILBOX_PROVIDER
    sender:email   -> providers/mailer/     MAILER_PROVIDER
    scheduler:job  -> providers/scheduler/  SCHEDULER_PROVIDER
    store:runtime  -> providers/store/      STORE_PROVIDER
  Their old names (mailbox, mailer, scheduler, store) are still read, as aliases: a job scheduled
  before the rename runs a copy of the runtime that asks for `store`.
An implementation is providers/<folder>/<name>.py; helpers next to it (auth.py) are not one.

A class with a parameter. In `publisher:<platform>` and `messenger:<platform>` the part after the colon is not a second name
of the class: it is handed to the implementation as --platform, and one implementation may serve
several platforms. Each implementation of such a class declares the platforms it serves in one
line at the top level of its file, `PLATFORMS = ("<platform>", ...)`, which is read here as text,
without importing the file. `publisher:<p>` is resolved among the implementations that serve <p>;
an implementation that declares nothing serves nothing. Written with the placeholder
(`publisher:<platform>`) the class means "any platform": every implementation is a candidate.

How the implementation is chosen, first match wins:
  0. An implementation the caller names explicitly (the function's `implementation` argument;
     the runtime passes what a project's runtime.json names). Not available on the command line.
  1. The environment, most specific variable first (PUBLISHER_<PLATFORM>_PROVIDER, then
     PUBLISHER_PROVIDER; a hyphen becomes "_"). For a class with a parameter the general variable
     is a preference: when the implementation it names does not serve the platform asked, it is
     passed over, so that a variable set for a first platform does not break a second.
  2. The platform default, where the class has one and that implementation is shipped:
     scheduler:job is launchd on macOS and systemd on Linux.
  3. The only candidate, when exactly one implementation is left.
Otherwise nothing resolves (exit 3): the message names the variable to set and the choices.
From code, `call(cls, verb, args, ...)` does the whole job (resolve, interpreter, start, parse) and is the one
function a caller of the runtime uses to run a provider's verb; see "Calling a provider from code" in
providers/CONTRACT.md.
A name from the environment or the caller is accepted only when it is an implementation shipped
in the class's folder (and, for a class with a parameter, one that serves the platform asked);
it is never used as a path.

environment variables:
  WORKBENCH_ROOT            the workbench checkout a project uses (an absolute path). Default:
                            the checkout this script is in.
  <ROLE>[_<TARGET>]_PROVIDER      the implementation of a class, as above.

output: the path on stdout (JSON with --json or --list); diagnostics on stderr.
exit codes: 0 resolved, 2 usage error or unknown class, 3 nothing resolves.
Standard library only. Runs on the system interpreter (Python 3.9): the scheduled runtime
imports it (providers/CONTRACT.md, "Python version").
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT_VARIABLE = "WORKBENCH_ROOT"
NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
PLACEHOLDER = re.compile(r"<[^<>]*>")
NOT_IMPLEMENTATIONS = {"auth"}  # helpers that live next to providers (providers/CONTRACT.md)
# Every class of contracts/environment.md, as it is written there.
LISTED = ["generator:image", "generator:video", "integration:design-tool", "integration:issue-tracker",
          "integration:vcs", "publisher:<platform>", "reader:email", "scheduler:job", "search:web", "sender:email",
          "store:runtime"]
# Roles whose folder and variables are derived from the text of the class. messenger, transcriber and renderer are classes the
# runtime uses and no skill requires (decision D11 of the short-video plan), so they are not in LISTED (nor in contracts/environment.md).
ROLES = {"integration", "search", "generator", "publisher", "messenger", "transcriber", "renderer"}
# The four classes that were bare names: (folder, variable), both kept as they were, so that no provider file,
# no test folder, no scheduled job and no project's environment has to move.
FIXED = {"reader:email": ("mailbox", "MAILBOX_PROVIDER"), "sender:email": ("mailer", "MAILER_PROVIDER"),
         "scheduler:job": ("scheduler", "SCHEDULER_PROVIDER"), "store:runtime": ("store", "STORE_PROVIDER")}
# The old names, still read.
ALIASES = {"mailbox": "reader:email", "mailer": "sender:email", "scheduler": "scheduler:job", "store": "store:runtime"}
# The roles whose part after the colon is a parameter handed to the implementation (--platform).
PARAMETER_ROLES = {"publisher", "messenger"}
PLATFORMS_LINE = re.compile(r"^PLATFORMS\s*=\s*([(\[].*?[)\]])\s*(?:#.*)?$", re.M)
# Documented defaults per platform (sys.platform prefix -> implementation).
PLATFORM_DEFAULTS = {"scheduler:job": {"darwin": "launchd", "linux": "systemd"}}

EXIT_OK, EXIT_USAGE, EXIT_UNRESOLVED = 0, 2, 3


class UnknownClass(ValueError):
    """The text is not a requirement class of contracts/environment.md."""
    code = EXIT_USAGE


class Unresolved(LookupError):
    """The class is known and no implementation can be chosen for it."""
    code = EXIT_UNRESOLVED


def canonical(cls: str) -> str:
    """The class as contracts/environment.md writes it: an old bare name becomes its <role>:<target>."""
    return ALIASES.get(str(cls), str(cls))


def split_class(cls: str) -> tuple[str, str | None]:
    """(role, target): ("publisher", "<p>") for publisher:<p>, ("reader", "email") for reader:email and for its
    old name. The target is None when it is absent or written as a placeholder."""
    cls = canonical(cls)
    parts = cls.split(":")
    if cls in FIXED:
        return parts[0], parts[1]
    head = parts[0]
    if len(parts) != 2 or head not in ROLES:
        # Every class is <role>:<target> (contracts/environment.md); a bare role is none (RS4). The four old bare
        # names are aliases, already read by canonical() above.
        raise UnknownClass(f"unknown class {cls!r}; known: {', '.join(LISTED)}")
    sub = parts[1] if len(parts) == 2 else None
    if sub is not None and PLACEHOLDER.fullmatch(sub):
        sub = None
    if sub is not None and not NAME.fullmatch(sub):
        raise UnknownClass(f"unknown class {cls!r}: the part after the colon must be lowercase letters, digits and hyphens")
    if head == "integration" and sub is None:
        raise UnknownClass(f"unknown class {cls!r}: an integration names its service, for example integration:vcs")
    return head, sub


def platform_of(cls: str) -> str | None:
    """The platform a class with a parameter asks for (publisher:<p> gives <p>); None for every other class
    and for the placeholder form, which means any platform."""
    head, sub = split_class(cls)
    return sub if head in PARAMETER_ROLES else None


def folder(cls: str) -> str:
    """The folder under providers/ for a class: the table FIXED, integration:<service> -> <service>, else the role."""
    head, sub = split_class(cls)
    if canonical(cls) in FIXED:
        return FIXED[canonical(cls)][0]
    return sub if head == "integration" else head


def variables(cls: str) -> list[str]:
    """The environment variables that select the implementation, most specific first."""
    head, sub = split_class(cls)
    if canonical(cls) in FIXED:
        return [FIXED[canonical(cls)][1]]

    def key(parts):
        return "_".join(parts).upper().replace("-", "_") + "_PROVIDER"

    names = [key([head, sub])] if sub else []
    if head != "integration":  # integration:<service> classes are unrelated services: no shared fallback
        names.append(key([head]))
    return names


def workbench_root(root=None, env=None) -> Path:
    """The workbench checkout: the argument, else WORKBENCH_ROOT, else the checkout this file is in."""
    env = os.environ if env is None else env
    if root:
        return Path(root).expanduser().resolve()
    if env.get(ROOT_VARIABLE):
        path = Path(env[ROOT_VARIABLE]).expanduser()
        if not path.is_absolute():
            raise Unresolved(f"{ROOT_VARIABLE} must be an absolute path, not {env[ROOT_VARIABLE]!r}")
        return path.resolve()
    return Path(__file__).resolve().parent.parent


def implementations_in(folder_name: str, root=None, env=None) -> list[str]:
    """Implementation names in providers/<folder_name>/: <name>.py files, helpers excluded."""
    if not NAME.fullmatch(str(folder_name)):
        return []
    base = workbench_root(root, env) / "providers" / folder_name
    if not base.is_dir():
        return []
    return sorted(p.stem for p in base.glob("*.py")
                  if p.is_file() and NAME.fullmatch(p.stem) and p.stem not in NOT_IMPLEMENTATIONS)


def implementations(cls: str, root=None, env=None) -> list[str]:
    """Implementation names shipped for a class."""
    return implementations_in(folder(cls), root, env)


def served_platforms(cls: str, name: str, root=None, env=None) -> list[str]:
    """The platforms an implementation of a class with a parameter declares, read from the one line
    `PLATFORMS = (...)` at the top level of its file, as text: the file is never imported. [] when the file
    declares nothing, or something that is not a list of names."""
    path = workbench_root(root, env) / "providers" / folder(cls) / f"{name}.py"
    try:
        found = PLATFORMS_LINE.search(path.read_text(encoding="utf-8"))
        value = ast.literal_eval(found.group(1)) if found else ()
    except (OSError, ValueError, SyntaxError):
        return []
    return [v for v in value if isinstance(v, str) and NAME.fullmatch(v)] if isinstance(value, (tuple, list)) else []


def serving(cls: str, root=None, env=None) -> list[str]:
    """The implementations that can satisfy the class: for publisher:<p>, those that declare <p>; for every
    other class, and for the placeholder form, every implementation shipped."""
    shipped, asked = implementations(cls, root, env), platform_of(cls)
    if asked is None:
        return shipped
    return [name for name in shipped if asked in served_platforms(cls, name, root, env)]


def from_environment(cls: str, env=None) -> tuple[str | None, str | None]:
    """(variable, value) of the first selection variable that is set, or (None, None)."""
    env = os.environ if env is None else env
    for name in variables(cls):
        if env.get(name):
            return name, env[name]
    return None, None


def resolve(cls: str, root=None, env=None, platform=None, implementation=None) -> dict:
    """Choose the provider script for a class. Returns class (as contracts/environment.md writes it),
    implementation, path, source, variable, variables.

    source is one of: configuration (the caller's `implementation`), environment, platform-default,
    only-implementation. Raises UnknownClass (not a class) or Unresolved (nothing to choose).
    `platform` is the operating system (sys.platform), for the platform default; the platform of a class
    with a parameter is part of the class.
    """
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    names = variables(cls)  # raises UnknownClass first
    cls = canonical(cls)
    base = workbench_root(root, env) / "providers" / folder(cls)
    shipped = implementations(cls, root, env)
    asked = platform_of(cls)
    candidates = serving(cls, root, env)

    def chosen(name: str, source: str, variable=None) -> dict:
        return {"class": cls, "implementation": name, "path": str(base / f"{name}.py"), "source": source,
                "variable": variable, "variables": names}

    def checked(name: str, origin: str) -> str:
        if name not in shipped:
            raise Unresolved(f"{name!r} (from {origin}) is not a provider of {cls} "
                             f"(providers/{folder(cls)}/); shipped: {shipped}")
        if name not in candidates:
            raise Unresolved(f"{name!r} (from {origin}) does not serve {asked}: providers/{folder(cls)}/{name}.py "
                             f"does not list it in PLATFORMS; providers that serve it: {candidates}")
        return name

    if implementation is not None:
        return chosen(checked(str(implementation), "the caller's configuration"), "configuration")
    for variable in names:
        value = env.get(variable)
        if not value:
            continue
        general = asked is not None and variable == names[-1]
        if general and value in shipped and value not in candidates:
            continue  # a preference set for another platform: passed over, never an error
        return chosen(checked(value, variable), "environment", variable)
    for prefix, name in PLATFORM_DEFAULTS.get(cls, {}).items():
        if platform.startswith(prefix) and name in candidates:
            return chosen(name, "platform-default")
    if len(candidates) == 1:
        return chosen(candidates[0], "only-implementation")
    if not shipped:
        raise Unresolved(f"no provider is shipped for {cls} (providers/{folder(cls)}/ has none); "
                         f"a provider added there is selected with {names[0]}")
    if not candidates:
        raise Unresolved(f"no provider in providers/{folder(cls)}/ serves {asked} (shipped: {shipped}; each lists "
                         "the platforms it serves in PLATFORMS)")
    raise Unresolved(f"{cls} has several providers and none is selected: set {names[0]} to one of {candidates}")


def provider_path(cls: str, **kw) -> Path:
    """The path of the provider script for a class (see resolve)."""
    return Path(resolve(cls, **kw)["path"])


def secret_resolver(root=None, env=None) -> Path:
    """The secret resolver every provider reads credentials through (contracts/secrets.md). Not a class."""
    return workbench_root(root, env) / "providers" / "secrets" / "resolver.py"


# --- calling a provider from code -----------------------------------------------------------------------------

NO_DEPENDENCIES = re.compile(r"^# dependencies = \[\]\s*$", re.M)
HEADER_BYTES = 4096
STDERR_TAIL = 300


class ProviderCallError(Exception):
    """A provider's verb did not give one JSON object. kind: "usage" (exit 2), "not-configured" (exit 3, or the
    class does not resolve), "failed" (any other exit, no JSON, a program that could not start) or "timeout"."""

    def __init__(self, kind: str, reason: str, exit_code=None, stderr_tail: str = ""):
        super().__init__(f"{kind}: {reason}")
        self.kind = kind
        self.reason = reason
        self.exit_code = exit_code
        self.stderr_tail = stderr_tail


def interpreter_for(path) -> list:
    """The command that starts the provider script at `path`: this interpreter when its header declares
    `# dependencies = []` (nothing to install), else `uv run`, which installs what the header pins. When a lockfile
    `<script>.lock` sits next to the script (`uv lock --script`), `uv run --locked`: uv installs only the locked,
    hash-checked files, and refuses to start when the header and the lock disagree instead of resolving anew."""
    try:
        with open(path, encoding="utf-8") as f:
            header = f.read(HEADER_BYTES)
    except OSError as e:
        raise ProviderCallError("not-configured", f"{path}: {e.strerror}") from None
    if NO_DEPENDENCIES.search(header):
        return [sys.executable]
    return ["uv", "run", "--locked"] if os.path.isfile(f"{path}.lock") else ["uv", "run"]


def _run(argv, timeout, env):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False, env=env)


def invoke(path, verb, args, *, config=None, timeout=600, env=None, run=None) -> dict:
    """Start the provider script at `path` with one verb and return the one JSON object it printed. `verb` may be
    None (the verb is then the first of `args`). `config`, when given, is written as JSON to a temporary file of
    mode 0600, passed after the verb as `--config-file`, and removed afterwards. `env`, when given, is the whole
    environment of the child; else it inherits the caller's. `run(argv)` replaces the process start (a stand-in
    in tests) and returns an object with returncode, stdout and stderr. No credential is read or passed here: a
    provider reads its own. Raises ProviderCallError."""
    argv = interpreter_for(path) + [str(path)] + ([verb] if verb else [])
    config_file = None
    try:
        if config is not None:
            fd, config_file = tempfile.mkstemp(prefix="provider-config-", suffix=".json")
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(config, f)
            argv += ["--config-file", config_file]
        argv += [str(a) for a in args]
        try:
            done = (run or (lambda a: _run(a, timeout, env)))(argv)
        except subprocess.TimeoutExpired:
            raise ProviderCallError("timeout", f"the provider ran over {timeout} s") from None
        except (OSError, subprocess.SubprocessError) as e:
            raise ProviderCallError("failed", f"the provider could not be run: {type(e).__name__}") from None
    finally:
        if config_file:
            try:
                os.unlink(config_file)
            except OSError:
                pass
    tail = " ".join((done.stderr or "").split())[-STDERR_TAIL:]
    if done.returncode != 0:
        kind = {2: "usage", 3: "not-configured"}.get(done.returncode, "failed")
        raise ProviderCallError(kind, tail or f"exit {done.returncode}", done.returncode, tail)
    try:
        out = json.loads(done.stdout)
    except ValueError:
        out = None
    if not isinstance(out, dict):
        raise ProviderCallError("failed", "the provider did not print one JSON object", done.returncode, tail)
    return out


def call(cls: str, verb, args, *, root=None, implementation=None, platform=None, config=None, timeout=600,
         env=None, run=None) -> dict:
    """Resolve the class (see resolve: `implementation` names one, `platform` is the operating system), start the
    provider's verb with `invoke`, and return the one JSON object it printed. A class that does not resolve is a
    ProviderCallError of kind "not-configured"."""
    try:
        path = resolve(cls, root=root, env=env, platform=platform, implementation=implementation)["path"]
    except (UnknownClass, Unresolved) as e:
        raise ProviderCallError("not-configured", str(e)) from None
    return invoke(path, verb, args, config=config, timeout=timeout, env=env, run=run)


def start(cls: str, verb: str, args, *, root=None, implementation=None, platform=None, env=None):
    """Start a provider's long-lived verb and return the running `subprocess.Popen` (a messenger's `listen`,
    providers/messenger/README.md). The class is resolved and the interpreter chosen exactly as `call` does. The child
    has binary standard input, output and error pipes (the caller owns all three), its own session (so a signal to its
    process group reaches what it started and nothing else), and no file descriptor of this process. `env`, when given,
    is the whole environment of the child. Nothing is read or written here and no credential is passed: a provider reads
    its own. Raises ProviderCallError: "not-configured" when the class does not resolve, "failed" when it cannot start.
    `platform` is the operating system (see resolve), not the messenger's platform: that one goes in `args`."""
    try:
        path = resolve(cls, root=root, env=env, platform=platform, implementation=implementation)["path"]
    except (UnknownClass, Unresolved) as e:
        raise ProviderCallError("not-configured", str(e)) from None
    argv = interpreter_for(path) + [str(path), verb] + [str(a) for a in args]
    try:
        return subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False,
                                start_new_session=True, close_fds=True, env=env)
    except (OSError, subprocess.SubprocessError) as e:
        raise ProviderCallError("failed", f"the provider could not be run: {type(e).__name__}") from None


def listing(root=None, env=None, platform=None) -> dict:
    rows = []
    for cls in LISTED:
        row = {"class": cls, "folder": f"providers/{folder(cls)}/", "variables": variables(cls),
               "implementations": implementations(cls, root, env), "resolves": None, "source": None, "note": None}
        if split_class(cls)[0] in PARAMETER_ROLES:  # which platforms each implementation serves
            row["platforms"] = {name: served_platforms(cls, name, root, env) for name in row["implementations"]}
        if cls in ALIASES.values():
            row["old_name"] = next(old for old, new in ALIASES.items() if new == cls)
        try:
            got = resolve(cls, root=root, env=env, platform=platform)
            row.update(resolves=got["implementation"], source=got["source"], path=got["path"])
        except Unresolved as e:
            row["note"] = str(e)
        rows.append(row)
    return {"root": str(workbench_root(root, env)), "root_variable": ROOT_VARIABLE, "classes": rows}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--class", dest="cls", metavar="<class>")
    p.add_argument("--list", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--root", metavar="<path>")
    a = p.parse_args(argv)
    if bool(a.cls) == bool(a.list):
        print("error: give exactly one of --class <class> and --list. See --help.", file=sys.stderr)
        return EXIT_USAGE
    try:
        if a.list:
            print(json.dumps(listing(root=a.root), indent=1))
            return EXIT_OK
        got = resolve(a.cls, root=a.root)
        if a.cls in ALIASES:
            print(f"note: {a.cls} is the old name of the class {ALIASES[a.cls]}", file=sys.stderr)
    except (UnknownClass, Unresolved) as e:
        print(f"error: {e}", file=sys.stderr)
        return e.code
    print(json.dumps(got, indent=1) if a.json else got["path"])
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
