#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Documents provider on the local disk: an implementation of the class integration:documents in which the documents
of a project are mirrored as Markdown files in a folder of the machine, outside the project, that a person edits with
any editor.

The folder is `dir` of the project configuration's `documents` object (an absolute path). The id of a document is
its path relative to the project (docs/brand/strategy.md), and its file is <dir>/<path>. Comments are the lines
starting "- " of the side file <dir>/<path>.comments.md, which a person writes; the id of a comment is the first 16
hex characters of the sha256 of its text. `version` is the sha256 of the document's bytes: it covers the content,
so it changes when a person edits the document, and only then; a comment does not move it (comments lists them
whatever the version). A write replaces the whole document (atomically), never merges, and leaves the side file as
it is.

A notice (write --notice, the verb notice) is the file's first line, "> [notice] <text>", and one empty line: it
stays above the document, a write with --notice writes it first, and read leaves it out of markdown and prints it as
notice (null when the file has none). The notice is written by the runtime, never by a person; the version, the
sha256 of the file's bytes, moves when it is added.

Usage:
  python3 providers/documents/local.py --help
  python3 providers/documents/local.py --check --config-file <f>
  python3 providers/documents/local.py stat  --config-file <f> --id <id>
  python3 providers/documents/local.py read  --config-file <f> --id <id>
  python3 providers/documents/local.py comments --config-file <f> --id <id>
  python3 providers/documents/local.py write --config-file <f> [--id <id>] --path <project-relative path>
                                       --markdown-file <f> --idempotency-key <k> [--notice <text>]
                                       (--dry-run | --confirmed)
  python3 providers/documents/local.py notice --config-file <f> --id <id> --text <text> (--dry-run | --confirmed)
  python3 providers/documents/local.py resolve --config-file <f> --idempotency-key <k>
                                       (--id <id> | --not-created) (--dry-run | --confirmed)

--config-file is a JSON file holding the project configuration's documents object, whole: {"provider": "local",
"dir": "<absolute folder>"}. Without --id, write creates the document at --path (titled by its path); the key of a
creation is kept in <dir>/.keys.json, so the same key never creates twice (a second write with it writes to the
document it created); resolve records what a person found for a key (--id) or releases it (--not-created).

Prints one JSON object on stdout; diagnostics on stderr. Exit codes: 0 ok, 1 failed (a document that does not
exist, a damaged file), 2 usage (a missing flag, a path that is absolute, holds "..", or does not end in .md, a write
without --dry-run or --confirmed, a relative dir), 3 not configured (no config file, no dir, a dir that does not
exist). No credential, no network. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import sys
import tempfile

KEYS_FILE = ".keys.json"
LOCK_FILE = ".lock"
SIDE = ".comments.md"
NOTICE_PREFIX = "> [notice] "
NOTICE_LIMIT = 2000


class Refused(Exception):
    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = code


def emit(data: dict) -> int:
    print(json.dumps(data, ensure_ascii=False, sort_keys=True))
    return 0


def documents_dir(config_file) -> str:
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
        raise Refused("the configuration file holds the documents object", 2)
    folder = config.get("dir")
    if not isinstance(folder, str) or not folder.strip():
        raise Refused("documents.dir is not set: the documents' folder, an absolute path", 3)
    if not os.path.isabs(folder):
        raise Refused("documents.dir must be an absolute path", 2)
    if not os.path.isdir(folder):
        raise Refused(f"the documents' folder {folder} does not exist", 3)
    return folder


def doc_id(value, flag: str) -> str:
    """A project-relative path of a Markdown document: relative, no "." or ".." part, ending in .md."""
    if not isinstance(value, str) or not value:
        raise Refused(f"{flag} is required", 2)
    parts = value.split("/")
    if (value.startswith(("/", "~")) or "\\" in value or any(p in ("", ".", "..") for p in parts)
            or not value.endswith(".md") or value.endswith(SIDE) or re.search(r"[\x00-\x1f\x7f]", value)):
        raise Refused(f"{flag} must be a relative path inside the project that ends in .md", 2)
    return value


def file_of(folder: str, ident: str) -> str:
    return os.path.join(folder, *ident.split("/"))


def read_bytes(path: str):
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


def version_of(folder: str, ident: str) -> str:
    data = read_bytes(file_of(folder, ident))
    if data is None:
        raise Refused(f"no document {ident}", 1)
    return hashlib.sha256(data).hexdigest()


def comments_of(folder: str, ident: str) -> list:
    side = read_bytes(file_of(folder, ident) + SIDE)
    out = []
    for line in (side or b"").decode("utf-8", errors="replace").splitlines():
        if line.startswith("- ") and line[2:].strip():
            said = line[2:].strip()
            out.append({"id": hashlib.sha256(said.encode("utf-8")).hexdigest()[:16], "author": None,
                        "created_at": None, "text": said})
    return out


def notice_text(value, flag: str) -> str:
    """A notice: one line of at most NOTICE_LIMIT characters."""
    if not isinstance(value, str) or not value.strip() or len(value) > NOTICE_LIMIT \
            or re.search(r"[\x00-\x1f\x7f]", value):
        raise Refused(f"{flag} is one line of at most {NOTICE_LIMIT} characters", 2)
    return value.strip()


def split_notice(data: bytes) -> tuple:
    """(the notice's text or None, the document's bytes without it)."""
    head = NOTICE_PREFIX.encode("utf-8")
    if not data.startswith(head):
        return None, data
    line, _, rest = data.partition(b"\n")
    if rest.startswith(b"\n"):
        rest = rest[1:]
    return line[len(head):].decode("utf-8", errors="replace"), rest


def with_notice(text: str, data: bytes) -> bytes:
    return (NOTICE_PREFIX + text + "\n\n").encode("utf-8") + data


def write_file(path: str, data: bytes) -> None:
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".doc-", dir=folder)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
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
        raise Refused(f"{KEYS_FILE} of the documents' folder is damaged", 1) from None
    if not isinstance(keys, dict):
        raise Refused(f"{KEYS_FILE} of the documents' folder is damaged", 1)
    return keys


def mode_of(args: dict) -> str:
    if args.get("--dry-run") and args.get("--confirmed"):
        raise Refused("give --dry-run or --confirmed, not both", 2)
    if not args.get("--dry-run") and not args.get("--confirmed"):
        raise Refused("this verb changes a document: give --dry-run to see the write, or --confirmed to make it", 2)
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
    documents_dir(args.get("--config-file"))
    return emit({"ok": True})


def cmd_stat(args: dict) -> int:
    folder = documents_dir(args.get("--config-file"))
    ident = doc_id(args.get("--id"), "--id")
    return emit({"id": ident, "version": version_of(folder, ident), "archived": False})


def cmd_read(args: dict) -> int:
    folder = documents_dir(args.get("--config-file"))
    ident = doc_id(args.get("--id"), "--id")
    version = version_of(folder, ident)
    notice, data = split_notice(read_bytes(file_of(folder, ident)) or b"")
    return emit({"id": ident, "version": version, "markdown": data.decode("utf-8", errors="replace"),
                 "notice": notice, "comments": comments_of(folder, ident)})


def cmd_comments(args: dict) -> int:
    folder = documents_dir(args.get("--config-file"))
    ident = doc_id(args.get("--id"), "--id")
    version_of(folder, ident)  # a document that does not exist has no comments: exit 1
    return emit({"id": ident, "comments": comments_of(folder, ident)})


def cmd_write(args: dict) -> int:
    folder = documents_dir(args.get("--config-file"))
    mode = mode_of(args)
    key = key_of(args)
    path = doc_id(args.get("--path"), "--path")
    given = args.get("--id")
    ident = doc_id(given, "--id") if given is not None else None
    source = args.get("--markdown-file")
    if not source:
        raise Refused("--markdown-file is required", 2)
    try:
        with open(source, "rb") as f:
            data = f.read()
    except OSError:
        raise Refused(f"the Markdown file {source} cannot be read", 2) from None
    notice = notice_text(args["--notice"], "--notice") if args.get("--notice") is not None else None
    if notice is not None:
        data = with_notice(notice, data)  # one notice, first, whatever the document held before
    with Lock(folder):
        keys = read_keys(folder)
        if ident is None:
            ident = keys.get(key) or path
        created = read_bytes(file_of(folder, ident)) is None
        if mode == "dry":
            return emit({"dry_run": True, "would": {"verb": "write", "id": ident, "create": created,
                                                     "bytes": len(data), "path": path}})
        if given is None and key not in keys:
            keys[key] = ident
            write_file(os.path.join(folder, KEYS_FILE), (json.dumps(keys, indent=1, sort_keys=True) + "\n").encode("utf-8"))
        write_file(file_of(folder, ident), data)
        version = version_of(folder, ident)
    return emit({"id": ident, "version": version, "created": created, "url": "file://" + file_of(folder, ident)})


def cmd_notice(args: dict) -> int:
    """Add the notice as the document's first block when it has none; the document itself is not touched."""
    folder = documents_dir(args.get("--config-file"))
    mode = mode_of(args)
    ident = doc_id(args.get("--id"), "--id")
    text = notice_text(args.get("--text"), "--text")
    with Lock(folder):
        data = read_bytes(file_of(folder, ident))
        if data is None:
            raise Refused(f"no document {ident}", 1)
        add = split_notice(data)[0] is None
        if mode == "dry":
            return emit({"dry_run": True, "would": {"verb": "notice", "id": ident, "add": add}})
        if add:
            write_file(file_of(folder, ident), with_notice(text, data))
    return emit({"id": ident, "added": add})


def cmd_resolve(args: dict) -> int:
    folder = documents_dir(args.get("--config-file"))
    mode = mode_of(args)
    key = key_of(args)
    given, not_created = args.get("--id"), args.get("--not-created")
    if (given is None) == (not not_created):
        raise Refused("give --id <id> or --not-created", 2)
    ident = doc_id(given, "--id") if given is not None else None
    with Lock(folder):
        keys = read_keys(folder)
        if ident is not None and read_bytes(file_of(folder, ident)) is None:
            raise Refused(f"no document {ident}", 1)
        after = dict(keys)
        if ident is not None:
            after[key] = ident
        else:
            after.pop(key, None)
        if mode == "dry":
            return emit({"dry_run": True, "would": {"verb": "resolve", "key": key, "id": ident}})
        write_file(os.path.join(folder, KEYS_FILE), (json.dumps(after, indent=1, sort_keys=True) + "\n").encode("utf-8"))
    return emit({"key": key, "id": ident, "resolved": True})


VERBS = {"stat": cmd_stat, "read": cmd_read, "comments": cmd_comments, "write": cmd_write, "notice": cmd_notice,
         "resolve": cmd_resolve}
VALUE_FLAGS = ("--config-file", "--id", "--path", "--markdown-file", "--idempotency-key", "--notice", "--text")
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
