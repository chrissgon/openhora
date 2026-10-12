#!/usr/bin/env python3
"""The skill-listing budget a pack needs in Claude Code, printed, or written into a settings file when asked.

Usage: python3 adapters/claude-code/listing_budget.py compute --pack <name>
       python3 adapters/claude-code/listing_budget.py apply --pack <name> [--mode print|write]
               [--scope project|local|user] [--project <dir>] [--dry-run]
       python3 adapters/claude-code/listing_budget.py undo [--dry-run]

Claude Code lists the installed skills to the model within a character budget, its bundled skills first, and
lists a skill past the budget by name only. The budget is the variable SLASH_COMMAND_TOOL_CHAR_BUDGET (the one
run-prompt.sh raises for eval runs); a settings file sets it for every session through its "env" object.

compute  the budget of a pack: each skill counted as the line `- openhora:<name>: <description>`, plus a
         margin of a quarter of that (at least 10000) for what the harness lists before the pack, rounded up to
         the next 1000.
apply    print (the default) prints the line to add and the file it goes in, and writes nothing. write merges
         the value into the settings file of --scope: project (<dir>/.claude/settings.json, the default), local
         (<dir>/.claude/settings.local.json) or user (~/.claude/settings.json, only when named). It keeps every
         other key, refuses a file that is not a JSON object, keeps a dated backup of a file it changes, never
         lowers a larger value the person set, and records what it wrote in installed/listing-budget.json
         inside this adapter (git-ignored).
undo     for each recorded write, puts back what was there before, only while the value is still the one
         written; a value changed since is left alone. Removes a file or folder it created and left empty.

Prints one JSON object on stdout; the note for the person on stderr.
Exit codes: 0 ok, 1 a settings file refused (not JSON, not an object, or a value that is not a number), 2 usage.
"""
import argparse
import datetime
import json
import math
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from select_skills import resolve  # noqa: E402
from validate import load_yaml, split_frontmatter  # noqa: E402

VAR = "SLASH_COMMAND_TOOL_CHAR_BUDGET"
RECORD = os.path.join(HERE, "installed", "listing-budget.json")
MARGIN_SHARE = 0.25
MARGIN_MIN = 10000
ROUND_TO = 1000
SCOPES = {"project": ("project", "settings.json"), "local": ("project", "settings.local.json"),
          "user": ("home", "settings.json")}


class Refused(Exception):
    pass


def plugin_name():
    with open(os.path.join(HERE, "plugin.json"), encoding="utf-8") as f:
        return json.load(f)["name"]


def compute(pack):
    prefix = plugin_name() + ":"
    names = resolve(pack=pack)
    chars = 0
    for name in names:
        fm, _ = split_frontmatter(os.path.join(ROOT, "skills", name, "SKILL.md"))
        description = str(((load_yaml(fm) if fm else None) or {}).get("description") or "").strip()
        chars += len(f"- {prefix}{name}: {description}\n")
    if not names:
        return {"pack": pack, "skills": 0, "characters": 0, "margin": 0, "budget": 0}
    margin = max(MARGIN_MIN, math.ceil(chars * MARGIN_SHARE))
    budget = math.ceil((chars + margin) / ROUND_TO) * ROUND_TO
    return {"pack": pack, "skills": len(names), "characters": chars, "margin": budget - chars, "budget": budget}


def settings_path(scope, project):
    base, file = SCOPES[scope]
    folder = os.path.expanduser("~") if base == "home" else project
    return os.path.join(os.path.abspath(folder), ".claude", file) if folder else None


def read_settings(path):
    """(data, existed). Refuses a file that is not a JSON object or whose env is not an object."""
    if not os.path.exists(path):
        return {}, False
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise Refused(f"{path} could not be read as JSON ({e}); nothing was written. Fix it, or add the line by hand.")
    if not isinstance(data, dict) or not isinstance(data.get("env", {}), dict):
        raise Refused(f"{path} is not a JSON object with an \"env\" object; nothing was written.")
    return data, True


def as_number(value, path):
    try:
        return int(str(value).strip())
    except ValueError:
        raise Refused(f"{path} sets {VAR} to {value!r}, which is not a number; it was left as it is.")


def write_json(path, data):
    folder = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".openhora-", dir=folder)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    if os.path.exists(path):
        shutil.copymode(path, tmp)
    else:
        os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def backup(path):
    stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S%f")
    dest = f"{path}.openhora-{stamp}.bak"
    shutil.copy2(path, dest)
    return dest


def load_record():
    if not os.path.isfile(RECORD):
        return []
    with open(RECORD, encoding="utf-8") as f:
        return json.load(f)


def save_record(entries):
    if entries:
        os.makedirs(os.path.dirname(RECORD), exist_ok=True)
        write_json(RECORD, entries)
    elif os.path.exists(RECORD):
        os.unlink(RECORD)
        if not os.listdir(os.path.dirname(RECORD)):
            os.rmdir(os.path.dirname(RECORD))


def line(budget):
    return f'"env": {{"{VAR}": "{budget}"}}'


def restore(path, data, entry):
    """Put back what was there before the recorded write. Returns the backup made, or None."""
    env = data.get("env", {})
    if entry["previous"] is None:
        env.pop(VAR, None)
    else:
        env[VAR] = entry["previous"]
    if entry["created_env"] and not env:
        data.pop("env", None)
    if entry["created_file"] and not data:
        os.unlink(path)
        folder = os.path.dirname(path)
        if entry["created_dir"] and not os.listdir(folder):
            os.rmdir(folder)
        return None
    saved = backup(path)
    write_json(path, data)
    return saved


def apply(opts):
    result = compute(opts.pack)
    budget = result["budget"]
    result.update({"setting": VAR, "scope": opts.scope, "mode": opts.mode})
    if budget == 0:
        result.update({"file": None, "written": False})
        return result
    path = settings_path(opts.scope, opts.project)
    shown = path or os.path.join("<project>", ".claude", SCOPES[opts.scope][1])
    command = (f"bash adapters/claude-code/install.sh --pack {opts.pack} --listing-budget write "
               + ("--settings-scope user" if opts.scope == "user" else
                  f"--project {opts.project or '<project>'}" + (" --settings-scope local" if opts.scope == "local" else "")))
    result.update({"file": shown, "line": line(budget), "apply": command, "written": False})
    head = (f"The skill listing of pack '{opts.pack}' needs {budget} characters ({result['skills']} skills, "
            f"{result['characters']} characters, margin {result['margin']}); Claude Code reads it from {VAR}.")
    if opts.mode == "print":
        print(f"{head}\nNothing was written. To apply it, add this to the top-level object of {shown} "
              f"(or only the key and value inside its \"env\" object, if it has one):\n  {line(budget)}\n"
              f"or let the installer merge it, with a backup:\n  {command}", file=sys.stderr)
        return result
    if path is None:
        raise ValueError("--mode write with --scope project or local needs --project <dir>")
    data, existed = read_settings(path)
    env = data.get("env")
    current = None if env is None else env.get(VAR)
    entries = load_record()
    mine = next((e for e in entries if e["file"] == path), None)
    if mine and current is not None and str(current) == mine["value"]:
        baseline = mine  # the value there is ours: compare with what the person had before
    else:
        entries = [e for e in entries if e is not mine]  # not ours any more, if it ever was
        mine = None
        baseline = {"previous": None if current is None else str(current), "created_file": not existed,
                    "created_env": env is None, "created_dir": not os.path.isdir(os.path.dirname(path))}
    previous = baseline["previous"]
    if previous is not None and as_number(previous, path) >= budget:
        result["kept"] = previous
        if mine and not opts.dry_run:
            result["backup"] = restore(path, data, mine)
            save_record([e for e in entries if e is not mine])
        print(f"{head}\n{path} already allows {previous} characters: left as it is.", file=sys.stderr)
        return result
    result["file"] = path
    if opts.dry_run:
        result["would_write"] = str(budget)
        return result
    # The first write keeps the file as the person had it; a later one only replaces the value written before.
    result["backup"] = backup(path) if existed and not mine else None
    data.setdefault("env", {})[VAR] = str(budget)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_json(path, data)
    entry = {"file": path, "value": str(budget), "pack": opts.pack, **{k: baseline[k] for k in
             ("previous", "created_file", "created_env", "created_dir")}}
    save_record([e for e in entries if e is not mine] + [entry])
    result["written"] = True
    print(f"{head}\nWritten into {path}" + (f" (backup: {result['backup']})." if result["backup"] else "."),
          file=sys.stderr)
    return result


def undo(opts):
    undone, left, kept = [], [], []
    for entry in load_record():
        path = entry["file"]
        if not os.path.exists(path):
            left.append({"file": path, "why": "the file no longer exists"})
            continue
        try:
            data, _ = read_settings(path)
        except Refused as e:
            left.append({"file": path, "why": str(e), "refused": True})
            kept.append(entry)
            continue
        if str(data.get("env", {}).get(VAR)) != entry["value"]:
            left.append({"file": path, "why": f"{VAR} was changed since it was written"})
            continue
        if opts.dry_run:
            undone.append({"file": path, "would_restore": entry["previous"]})
            kept.append(entry)
            continue
        undone.append({"file": path, "restored": entry["previous"], "backup": restore(path, data, entry)})
    if not opts.dry_run:
        save_record(kept)
    for item in left:
        print(f"Left {item['file']} as it is: {item['why'].rstrip('.')}.", file=sys.stderr)
    out = {}
    if undone:
        out["undone"] = undone
    if left:
        out["left"] = left
    return out


class Parser(argparse.ArgumentParser):
    def error(self, message):
        print(f"Error: {message}. See --help.", file=sys.stderr)
        sys.exit(2)


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    parser = Parser(add_help=False)
    parser.add_argument("command", choices=("compute", "apply", "undo"))
    parser.add_argument("--pack", default="default")
    parser.add_argument("--mode", choices=("print", "write"), default="print")
    parser.add_argument("--scope", choices=tuple(SCOPES), default="project")
    parser.add_argument("--project")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-h", "--help", action="store_true")
    opts = parser.parse_args(argv)
    if opts.help:
        print(__doc__)
        return 0
    try:
        if opts.command == "compute":
            out = compute(opts.pack)
        elif opts.command == "undo":
            out = undo(opts)
        else:
            if opts.mode == "write" and opts.scope != "user" and not opts.project:
                parser.error("--mode write needs --project <dir> (or --scope user)")
            out = apply(opts)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except Refused as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(out))
    return 1 if any(item.get("refused") for item in out.get("left", [])) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
