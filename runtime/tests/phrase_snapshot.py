#!/usr/bin/env python3
"""The phrase snapshot (T8-0b): every key of the phrase table, in each language, rendered with fixed fictional field values, one line per key, sorted.

A test no longer quotes a sentence of the table (it names a key and its fields: runtime/tests/phrase_kit.py), so the table's own wording is pinned here, once,
in `runtime/tests/snapshots/phrases.en.txt` and `phrases.pt-BR.txt`. A reviewer who changes a sentence, adds a key or renames a field sees it in the diff of those
two files, with the values in place; no converted test fails for a rewording. The keys of the phrase parts (runtime/phrases_parts/) are in the table, so they are in
the snapshot.

  python3 runtime/tests/phrase_snapshot.py --write     rewrite both files from the table as it is now
  python3 runtime/tests/phrase_snapshot.py --check     exit 0 when both files equal the table, else exit 1 and print what differs and the command above
  python3 runtime/tests/phrase_snapshot.py --help

A line is `KEY: sentence`, a newline inside a sentence is written `\\n` and a backslash `\\\\`. A `{field}` takes the value `VALUES` gives its name (a fictional day, a
name, a count...), and any other field the text `<field>`, so a field that a sentence gains, loses or renames shows in the diff. The snapshot is generated: a conflict in
a snapshot file is resolved by running `--write` on the rebased tree, never by hand (SPEC-V3-STRUCTURE OPEN-S10). The test is runtime/tests/test_phrase_snapshot.py.

Standard library only; Python 3.9.
"""
from __future__ import annotations

import argparse
import difflib
import os
import string
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import phrases  # noqa: E402  (runtime/: the table)

SNAPSHOTS = os.path.join(HERE, "snapshots")
LANGUAGES = ("en", "pt-BR")
COMMAND = "python3 runtime/tests/phrase_snapshot.py --write"

# The fixed fictional value of a field by its name. Every value is invented (principle 8); a name not listed here renders as `<name>`.
VALUES = {
    "n": "3", "k": "2", "i": "1", "m": "5", "p": "4", "a": "6", "b": "7",
    "count": "3", "number": "12", "max": "10", "cap": "25", "days": "2", "minutes": "15", "rows": "8", "runs": "3", "step": "2", "done": "1", "total": "4",
    "remaining": "2", "held": "1", "position": "2", "bytes": "2048", "size": "3.5 KiB", "kib": "64", "revision": "3", "version": "1.2.0",
    "id": "42", "ref": "R-17", "ids": "41, 42", "refs": "R-17, R-18", "message_id": "m-9001", "event_id": "ev-31", "reference": "REF-7",
    "name": "Ana Lima", "names": "Ana Lima, Bruno Reis", "sender": "Bruno Reis", "who": "Bruno Reis", "agent": "planner",
    "title": "Quarterly review", "subject": "Lunch on Friday", "text": "see you soon", "body": "See you on Friday.", "content": "a short note",
    "note": "bring the report", "notes": "bring the report", "question": "which day?", "request": "move the review", "why": "it is the only free slot",
    "reason": "the file is too large", "detail": "the server did not answer", "failure": "the connection closed", "line": "one line of text",
    "words": "move, review", "label": "work", "labels": "work, home", "value": "yes", "passage": "the review is on Friday",
    "service": "Example Calendar", "account": "ana@mail.example", "address": "ana@mail.example", "addresses": "ana@mail.example, bruno@mail.example",
    "to": "ana@mail.example", "cc": "bruno@mail.example", "bcc": "carla@mail.example", "url": "https://page.example/p/1", "route": "primary",
    "source": "notes.example", "project": "Acme Launch", "projects": "Acme Launch, Beta Site", "flow": "weekly report", "skill": "eng-implement",
    "model": "model-x", "platform": "social-x",
    "when": "Wed 21/10/2026 13:00", "at": "Wed 21/10/2026 13:00", "date": "21/10/2026", "day": "Wed 21/10/2026", "time": "13:00", "weekday": "Wed", "wd": "Wed",
    "since": "Mon 19/10/2026", "now": "Wed 21/10/2026 12:00", "old": "Wed 21/10/2026 13:00", "new": "Thu 22/10/2026 13:00", "zone": "America/Sao_Paulo",
    "read_at": "Wed 21/10/2026 12:00", "snapshot_at": "Wed 21/10/2026 12:00", "received": "Wed 21/10/2026 09:30", "modified": "Tue 20/10/2026 18:00",
    "wall": "Wed 21/10/2026 13:00", "location": "Room 4", "place": "Room 4",
    "kind": "plan", "state": "open", "status": "pending", "given": "plan", "filter": "open", "open": "2", "waiting": "1", "pending": "2", "wanted": "pdf",
    "shown": "3", "first": "1", "last": "3", "item": "the first item", "items": "3", "other": "another one", "example": "an example", "rule": "no weekends",
    "command": "/pending", "commands": "/pending, /help", "options": "yes, no", "extensions": "pdf, png", "type": "image/png", "declared": "image/png",
    "sniffed": "application/pdf", "file": "photo.png", "path": "docs/notes.md", "rel": "docs/notes.md", "folder": "Inbox", "folders": "Inbox, Archive",
    "box": "Inbox", "boxes": "Inbox, Archive", "first_box": "Inbox", "second_box": "Archive", "calendar": "Work", "sha": "0123456789abcdef", "sha_short": "0123456",
    "etag_short": "a1b2c3d", "dm": "Bruno Reis", "named": "Ana Lima", "list": "one, two, three",
    "read": "notes.example, plan.example", "what": "move the review to Friday",
    "where": "on the platform's page",
}


def _fields(template: str) -> list:
    names = []
    for _literal, name, _spec, _conv in string.Formatter().parse(template):
        if name is not None and name not in names:
            names.append(name)
    return names


def render_sentence(template: str, values=None) -> str:
    """`template` with every field in place: the value `values` (default `VALUES`) gives its name, else `<name>`. A format spec or a conversion of a field is applied as the table's own `format` does."""
    values = VALUES if values is None else values
    return template.format(**{name: values.get(name, "<" + name + ">") for name in _fields(template)})


def _escape(sentence: str) -> str:
    return sentence.replace("\\", "\\\\").replace("\n", "\\n")


def render(language: str, table=None) -> str:
    """The snapshot of one language: `KEY: sentence`, one line per key of its table, sorted by key, a newline at the end."""
    table = (phrases.TABLE if table is None else table)[language]
    return "".join(f"{key}: {_escape(render_sentence(table[key]))}\n" for key in sorted(table))


def path_of(language: str, folder=None) -> str:
    return os.path.join(SNAPSHOTS if folder is None else folder, f"phrases.{language}.txt")


def _read(path: str):
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            return handle.read()
    except FileNotFoundError:
        return None


def write(folder=None, table=None) -> list:
    """Rewrite the snapshot of every language; returns the paths written."""
    folder = SNAPSHOTS if folder is None else folder
    os.makedirs(folder, exist_ok=True)
    paths = []
    for language in LANGUAGES:
        path = path_of(language, folder)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(render(language, table))
        paths.append(path)
    return paths


def differences(folder=None, table=None, limit: int = 40) -> list:
    """What differs between the snapshot files and the table: a list of lines, empty when they are equal. A missing file is said so; a difference is a unified diff
    (snapshot to table), cut at `limit` lines per language."""
    found = []
    for language in LANGUAGES:
        path = path_of(language, folder)
        want = render(language, table)
        have = _read(path)
        if have is None:
            found.append(f"{os.path.basename(path)}: the file does not exist")
        elif have != want:
            lines = list(difflib.unified_diff(have.splitlines(), want.splitlines(), f"{os.path.basename(path)} (snapshot)", f"{language} (table)", lineterm="", n=0))
            found.extend(lines[:limit])
            if len(lines) > limit:
                found.append(f"... {len(lines) - limit} more lines")
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="The snapshot of the phrase table: every key of each language with fixed fictional field values.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="rewrite runtime/tests/snapshots/phrases.<language>.txt from the table")
    mode.add_argument("--check", action="store_true", help="exit 1, with the differences, when a snapshot file is not the table's")
    args = parser.parse_args(argv)
    if args.write:
        for path in write():
            print(f"wrote {os.path.relpath(path)}", file=sys.stderr)
        return 0
    found = differences()
    if not found:
        return 0
    print("\n".join(found), file=sys.stderr)
    print(f"the phrase snapshot is not the table's: review the wording above, then run `{COMMAND}`", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
