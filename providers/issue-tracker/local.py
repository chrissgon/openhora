#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Task-board provider on the local disk: an implementation of the class integration:issue-tracker in which the
board is a folder of Markdown files, one per item, that a person edits with any editor.

The board is the folder `dir` of the project configuration's `task_board` object (an absolute path):
<dir>/<id>.md per item, the id matching [a-z0-9][a-z0-9-]*. An item this provider creates gets the id t<n>, n the
smallest positive integer not in use. A file a person writes by hand in the folder is an item too. The file:

  # <title>

  State: <state>

  <text, any Markdown>

  ## Comments

  - <one comment per line>

  ## Runtime

  - <key>: <value>

Reading: the title is the first line without its "# "; the state is the first line "State: <word>" (absent: requested;
a word that is not one of the nine task states: null); the text is what lies between the state line (or the title)
and the first of "## Comments" or "## Runtime", stripped; a comment is a line starting "- " under "## Comments", its
id the first 16 hex characters of the sha256 of its text. "## Runtime" is written from the item's `shown` fields and
never read back. `version` is the sha256 of the file's bytes without its "## Comments" section: it covers the content,
so a comment does not move it (comments lists them whatever the version); `archived` is always false. A write keeps
every part whose key the item file does not name, so a write of the state alone never replaces a title the person
edited.

Usage:
  python3 providers/issue-tracker/local.py --help
  python3 providers/issue-tracker/local.py --check --config-file <f>
  python3 providers/issue-tracker/local.py list --config-file <f>
  python3 providers/issue-tracker/local.py get --config-file <f> --id <id>
  python3 providers/issue-tracker/local.py comments --config-file <f> --id <id>
  python3 providers/issue-tracker/local.py upsert --config-file <f> [--id <id>] --item-file <json>
                                          --idempotency-key <k> (--dry-run | --confirmed)
  python3 providers/issue-tracker/local.py resolve --config-file <f> --idempotency-key <k>
                                          (--id <id> | --not-created) (--dry-run | --confirmed)

--config-file is a JSON file holding the project configuration's task_board object, whole: {"provider": "local",
"dir": "<absolute folder>"}. The item file is {"title", "text", "state", "shown"}, every key optional; a key that is
absent is not written; "shown" is an object of text values, displayed and never read back. A creation needs a title.
The key of a creation is kept in <dir>/.keys.json, so the same key never creates twice (a second upsert with it writes
to the item it created); resolve records what a person found for a key (--id) or releases it (--not-created).

Prints one JSON object on stdout; diagnostics on stderr. Exit codes: 0 ok, 1 failed (an item that does not exist, a
damaged file), 2 usage (a missing flag, an id or a state that is not well formed, upsert without --dry-run or
--confirmed, a relative dir), 3 not configured (no config file, no dir, a dir that does not exist).
No credential, no network. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import sys
import tempfile

STATES = ("requested", "planned", "ready", "running", "waiting", "blocked", "done", "failed", "cancelled")
ID = re.compile(r"[a-z0-9][a-z0-9-]*")
STATE_LINE = re.compile(r"^State: (\S+)\s*$")
CREATED_ID = re.compile(r"t([1-9][0-9]*)")
ITEM_KEYS = ("title", "text", "state", "shown")
KEYS_FILE = ".keys.json"
LOCK_FILE = ".lock"
COMMENTS = "## Comments"
RUNTIME = "## Runtime"


class Refused(Exception):
    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = code


def emit(data: dict) -> int:
    print(json.dumps(data, ensure_ascii=False, sort_keys=True))
    return 0


def board_dir(config_file) -> str:
    if not config_file:
        raise Refused("--config-file is required", 2)
    try:
        with open(config_file, encoding="utf-8") as f:
            config = json.load(f)
    except OSError:
        raise Refused(f"the configuration file {config_file} cannot be read", 3) from None
    except ValueError:
        raise Refused(f"the configuration file {config_file} is not JSON", 2) from None
    if not isinstance(config, dict):
        raise Refused("the configuration file holds the task_board object", 2)
    folder = config.get("dir")
    if not isinstance(folder, str) or not folder.strip():
        raise Refused("task_board.dir is not set: the board's folder, an absolute path", 3)
    if not os.path.isabs(folder):
        raise Refused("task_board.dir must be an absolute path", 2)
    if not os.path.isdir(folder):
        raise Refused(f"the board's folder {folder} does not exist", 3)
    return folder


def item_id(value) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise Refused("an id is lowercase letters, digits and hyphens, starting with a letter or a digit", 2)
    return value


def item_path(folder: str, ident: str) -> str:
    return os.path.join(folder, ident + ".md")


def parse(text: str) -> dict:
    """The parts of an item file: title, state (None when absent), raw_state (the word as written, or None), text,
    comments (raw lines of the section), runtime (raw lines of the section)."""
    lines = text.splitlines()
    title = lines[0][2:].strip() if lines and lines[0].startswith("# ") else (lines[0].strip() if lines else "")
    body = lines[1:]
    raw_state, start = None, 0
    for i, line in enumerate(body):
        if line.strip() in (COMMENTS, RUNTIME):
            break
        m = STATE_LINE.match(line)
        if m:
            raw_state, start = m.group(1), i + 1
            break
    # Without a state line the text starts right after the title. A line under a section stays in it, whatever it
    # is, so that a write never drops what a person typed there.
    sections, current = {"text": list(body[:max(start - 1, 0)]), COMMENTS: [], RUNTIME: []}, "text"
    for line in body[start:]:
        if line.strip() in (COMMENTS, RUNTIME):
            current = line.strip()
            continue
        sections[current].append(line)
    return {"title": title, "raw_state": raw_state,
            "state": "requested" if raw_state is None else (raw_state if raw_state in STATES else None),
            "text": "\n".join(sections["text"]).strip(), "comments": sections[COMMENTS],
            "runtime": sections[RUNTIME]}


def comments_of(lines) -> list:
    out = []
    for line in lines:
        if line.startswith("- ") and line[2:].strip():
            said = line[2:].strip()
            out.append({"id": hashlib.sha256(said.encode("utf-8")).hexdigest()[:16], "author": None,
                        "created_at": None, "text": said})
    return out


def render(parts: dict) -> str:
    out = [f"# {parts['title']}", ""]
    if parts["raw_state"] is not None:
        out += [f"State: {parts['raw_state']}", ""]
    if parts["text"]:
        out += [parts["text"], ""]
    comments = [line for line in parts["comments"]]
    while comments and not comments[-1].strip():
        comments.pop()
    while comments and not comments[0].strip():
        comments.pop(0)
    out += [COMMENTS, ""] + (comments + [""] if comments else [])
    runtime = list(parts["runtime"])
    while runtime and not runtime[-1].strip():
        runtime.pop()
    while runtime and not runtime[0].strip():
        runtime.pop(0)
    out += [RUNTIME, ""] + (runtime + [""] if runtime else [])
    return "\n".join(out).rstrip("\n") + "\n"


def version_of(data: bytes) -> str:
    """The sha256 of an item file without its "## Comments" section (heading and lines): the version covers the
    content, never the comments."""
    kept, inside = [], False
    for line in data.decode("utf-8", errors="replace").splitlines(keepends=True):
        if line.strip() in (COMMENTS, RUNTIME):
            inside = line.strip() == COMMENTS
            if inside:
                continue
        if not inside:
            kept.append(line)
    return hashlib.sha256("".join(kept).encode("utf-8")).hexdigest()


def read_item(folder: str, ident: str) -> tuple:
    path = item_path(folder, ident)
    try:
        with open(path, "rb") as f:
            data = f.read()
    except FileNotFoundError:
        raise Refused(f"no item {ident} on the board", 1) from None
    except OSError as e:
        raise Refused(f"item {ident} cannot be read: {e.strerror}", 1) from None
    return data, parse(data.decode("utf-8", errors="replace"))


def write_file(path: str, text: str) -> None:
    folder = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".item-", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_keys(folder: str) -> dict:
    try:
        with open(os.path.join(folder, KEYS_FILE), encoding="utf-8") as f:
            keys = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise Refused(f"{KEYS_FILE} of the board is damaged", 1) from None
    if not isinstance(keys, dict):
        raise Refused(f"{KEYS_FILE} of the board is damaged", 1)
    return keys


def item_ids(folder: str) -> list:
    out = []
    for name in sorted(os.listdir(folder)):
        if name.startswith(".") or not name.endswith(".md"):
            continue
        stem = name[:-3]
        if ID.fullmatch(stem) and os.path.isfile(os.path.join(folder, name)):
            out.append(stem)
    return out


def new_id(folder: str) -> str:
    used = {int(m.group(1)) for m in (CREATED_ID.fullmatch(i) for i in item_ids(folder)) if m}
    n = 1
    while n in used:
        n += 1
    return f"t{n}"


def item_file(path) -> dict:
    if not path:
        raise Refused("--item-file is required", 2)
    try:
        with open(path, encoding="utf-8") as f:
            item = json.load(f)
    except OSError:
        raise Refused(f"the item file {path} cannot be read", 2) from None
    except ValueError:
        raise Refused(f"the item file {path} is not JSON", 2) from None
    if not isinstance(item, dict):
        raise Refused("the item file holds an object", 2)
    unknown = sorted(set(item) - set(ITEM_KEYS))
    if unknown:
        raise Refused(f"the item file has unknown keys: {', '.join(unknown)}", 2)
    if "title" in item and (not isinstance(item["title"], str) or not item["title"].strip() or "\n" in item["title"]):
        raise Refused("title is one line of text", 2)
    if "text" in item and not isinstance(item["text"], str):
        raise Refused("text is text", 2)
    if "state" in item and item["state"] not in STATES:
        raise Refused(f"state is one of {', '.join(STATES)}", 2)
    if "shown" in item and (not isinstance(item["shown"], dict)
                            or not all(isinstance(k, str) and ID.fullmatch(k.replace("_", "-"))
                                       and isinstance(v, str) and "\n" not in v for k, v in item["shown"].items())):
        raise Refused("shown is an object of one-line text values, keyed by lowercase names", 2)
    return item


def merged(parts: dict, item: dict) -> dict:
    out = dict(parts)
    if "title" in item:
        out["title"] = item["title"].strip()
    if "text" in item:
        out["text"] = item["text"].strip()
    if "state" in item:
        out["raw_state"] = item["state"]
    if "shown" in item:
        out["runtime"] = [f"- {k}: {v}" for k, v in sorted(item["shown"].items())]
    return out


def mode_of(args: dict) -> str:
    if args.get("--dry-run") and args.get("--confirmed"):
        raise Refused("give --dry-run or --confirmed, not both", 2)
    if not args.get("--dry-run") and not args.get("--confirmed"):
        raise Refused("this verb changes the board: give --dry-run to see the write, or --confirmed to make it", 2)
    return "dry" if args.get("--dry-run") else "confirmed"


def key_of(args: dict) -> str:
    key = args.get("--idempotency-key")
    if not isinstance(key, str) or not key.strip() or len(key) > 512 or re.search(r"[\x00-\x1f\x7f]", key):
        raise Refused("--idempotency-key is required: one line of at most 512 characters", 2)
    return key


class Lock:
    def __init__(self, folder: str):
        self.path = os.path.join(folder, LOCK_FILE)

    def __enter__(self):
        self.fd = os.open(self.path, os.O_WRONLY | os.O_CREAT, 0o600)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        os.close(self.fd)


def cmd_check(args: dict) -> int:
    board_dir(args.get("--config-file"))
    return emit({"ok": True})


def cmd_list(args: dict) -> int:
    folder = board_dir(args.get("--config-file"))
    items = []
    for ident in item_ids(folder):
        with open(item_path(folder, ident), "rb") as f:
            items.append({"id": ident, "version": version_of(f.read()), "archived": False})
    return emit({"items": items, "truncated": False})


def cmd_get(args: dict) -> int:
    folder = board_dir(args.get("--config-file"))
    ident = item_id(args.get("--id"))
    data, parts = read_item(folder, ident)
    return emit({"id": ident, "version": version_of(data), "title": parts["title"],
                 "text": parts["text"], "state": parts["state"], "archived": False,
                 "comments": comments_of(parts["comments"]), "url": "file://" + item_path(folder, ident)})


def cmd_comments(args: dict) -> int:
    folder = board_dir(args.get("--config-file"))
    ident = item_id(args.get("--id"))
    _data, parts = read_item(folder, ident)
    return emit({"id": ident, "comments": comments_of(parts["comments"])})


def cmd_upsert(args: dict) -> int:
    folder = board_dir(args.get("--config-file"))
    mode = mode_of(args)
    key = key_of(args)
    given = args.get("--id")
    ident = item_id(given) if given is not None else None
    item = item_file(args.get("--item-file"))
    with Lock(folder):
        keys = read_keys(folder)
        created = False
        if ident is None and key in keys:
            ident = keys[key]
        if ident is None:
            if "title" not in item:
                raise Refused("an item is created with a title", 2)
            ident, created = new_id(folder), True
            parts = {"title": "", "raw_state": None, "text": "", "comments": [], "runtime": []}
        else:
            _data, parts = read_item(folder, ident)
        text = render(merged(parts, item))
        if mode == "dry":
            return emit({"dry_run": True, "would": {"verb": "upsert", "id": None if created else ident,
                                                     "create": created, "item": item}})
        if created:
            keys[key] = ident
            write_file(os.path.join(folder, KEYS_FILE), json.dumps(keys, indent=1, sort_keys=True) + "\n")
        write_file(item_path(folder, ident), text)
    return emit({"id": ident, "version": version_of(text.encode("utf-8")), "created": created})


def cmd_resolve(args: dict) -> int:
    folder = board_dir(args.get("--config-file"))
    mode = mode_of(args)
    key = key_of(args)
    given, not_created = args.get("--id"), args.get("--not-created")
    if (given is None) == (not not_created):
        raise Refused("give --id <id> or --not-created", 2)
    ident = item_id(given) if given is not None else None
    with Lock(folder):
        keys = read_keys(folder)
        if ident is not None and not os.path.isfile(item_path(folder, ident)):
            raise Refused(f"no item {ident} on the board", 1)
        after = dict(keys)
        if ident is not None:
            after[key] = ident
        else:
            after.pop(key, None)
        if mode == "dry":
            return emit({"dry_run": True, "would": {"verb": "resolve", "key": key, "id": ident}})
        write_file(os.path.join(folder, KEYS_FILE), json.dumps(after, indent=1, sort_keys=True) + "\n")
    return emit({"key": key, "id": ident, "resolved": True})


VERBS = {"list": cmd_list, "get": cmd_get, "comments": cmd_comments, "upsert": cmd_upsert, "resolve": cmd_resolve}
VALUE_FLAGS = ("--config-file", "--id", "--item-file", "--idempotency-key")
SWITCHES = ("--dry-run", "--confirmed", "--not-created", "--check")


def parse_args(argv: list) -> tuple:
    verb, args, i = None, {}, 0
    while i < len(argv):
        word = argv[i]
        if word in VALUE_FLAGS:
            if i + 1 >= len(argv):
                raise Refused(f"{word} needs a value", 2)
            args[word] = argv[i + 1]
            i += 2
        elif word in SWITCHES:
            args[word] = True
            i += 1
        elif verb is None and word in VERBS:
            verb = word
            i += 1
        else:
            raise Refused(f"unknown argument {word!r}; see --help", 2)
    return verb, args


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("--help", "-h"):
        print(__doc__.strip(), file=sys.stdout if argv else sys.stderr)
        return 0 if argv else 2
    try:
        verb, args = parse_args(argv)
        if args.get("--check"):
            if verb is not None:
                raise Refused("--check takes no verb", 2)
            return cmd_check(args)
        if verb is None:
            raise Refused("give a verb or --check; see --help", 2)
        return VERBS[verb](args)
    except Refused as e:
        print(f"error: {e}", file=sys.stderr)
        return e.code
    except OSError as e:
        print(f"error: {e.strerror or e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
