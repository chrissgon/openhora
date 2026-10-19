#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The files family of the natural writes (package NR-5a), pure: a new file, a new revision of a file that is a source, and the saving of a file someone sent, read from a
line by closed heads and markers (`requests.writes.files` of the language tables). The interface is runtime/natural_writes.py's.

  file-create    a create verb, an object (file, document, note; or a Google Doc), "chamado <name>" and a content marker (or a colon) with the text. Taken only with BOTH
                 the name and the content. Slots: name (the person's words, as written), content (the person's words, verbatim), folder (a name), account (a service word),
                 gdoc (the object said a Google Doc)
  file-replace   a replace verb, "the text of" and the words that name the file, then a marker ("por", "with") or a colon and the new text. Slots: words, content
  file-save      a save verb and a file somebody sent: "esse pdf", "o anexo", "o arquivo 3". Taken only when the object is "this" file, an attachment, or a number; the
                 line may name a service and a folder and nothing else. Slots: attachment (an integer), kind (pdf, docx...), folder, account

Whether the file is one the sender sent, which account a name belongs to and whether a folder is configured are runtime/ops_natural_files.py's. Standard library only. Runs
on Python 3.9: python3 runtime/natural_writes_files.py --help
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import natural_writes as nw  # noqa: E402

FOLDER = re.compile(r"\s*([a-z0-9][a-z0-9-]{0,31})(?![a-z0-9-])")
NUMBER = re.compile(r"\s*#?\s*([0-9]{1,6})(?![a-z0-9])")
REQUIRED = {"file-create": ("name", "content"), "file-replace": ("words", "content"), "file-save": ("attachment",)}


def _list(tables, key):
    return nw.listed(tables, "files", key)


def HEADS(tables):
    return _list(tables, "create_verbs") + _list(tables, "replace_verbs") + _list(tables, "save_verbs")


def _at(line: "nw.Line", at: int, phrases: list):
    """(s, e) of a phrase that starts at `at` after blanks, or None."""
    here = at
    while here < len(line.norm) and line.norm[here] == " ":
        here += 1
    found = line.find(phrases, here, here + 40)
    return found if found and found[0] == here else None


def _content_start(line: "nw.Line", start: int, markers: list):
    """(where the marker begins, where the content begins) of the first content marker at or after `start`: a marker phrase or a colon, whichever is first. The content
    begins after the marker and an optional colon."""
    word = line.find(markers, start)
    colon = line.norm.find(":", start)
    best = None
    if word and (colon < 0 or word[0] < colon):
        best = (word[0], word[1])
        if line.norm[word[1]:].lstrip().startswith(":"):
            best = (word[0], line.norm.index(":", word[1]) + 1)
    elif colon >= 0:
        best = (colon, colon + 1)
    return best


def _span(line: "nw.Line", start: int, end: int, key: str):
    """The person's words in [start, end), verbatim, or None when empty or over the cap."""
    text = line.span(start, end).strip()
    return text if text and len(text) <= nw.SPAN_MAX[key] else None


def _create(line: "nw.Line", tables: list):
    verb = line.lead(_list(tables, "create_verbs"), tables)
    if verb is None:
        return None
    here = nw.skip_articles(line, verb, tables)
    gdoc = _at(line, here, _list(tables, "gdoc"))
    noun = gdoc or _at(line, here, _list(tables, "nouns"))
    if noun is None:
        return None
    named = _at(line, noun[1], _list(tables, "named"))
    if named is None:
        return None
    cut = _content_start(line, named[1], _list(tables, "content"))
    if cut is None:
        return None
    middle_end = cut[0]
    # between the name marker and the content: the name, then (any order) a folder and a service
    stop = middle_end
    folder_spot = line.find(_list(tables, "folder"), named[1], middle_end)
    if folder_spot:
        stop = min(stop, folder_spot[0])
    service = nw.service(line, tables, named[1], middle_end)
    if service:
        stop = min(stop, service[1])
    name = _span(line, named[1], stop, "name")
    content = _span(line, cut[1], len(line.norm), "content")
    if not name or not content or re.search(r"[:/\\]", name):
        return None
    slots = {"name": name, "content": content}
    if gdoc:
        slots["gdoc"] = True
    if folder_spot:
        m = FOLDER.match(line.norm, nw.skip_articles(line, folder_spot[1], tables))
        if not m:
            return None
        slots["folder"] = m.group(1)
    if service:
        slots["account"] = service[0]
    return {"op": "file-create", "slots": slots, "spans": {"name": name, "content": content}, "ranges": {"content": (cut[1], len(line.norm))}, "need": [],
            "engine": None, "doubt": False}


def _replace(line: "nw.Line", tables: list):
    verb = line.lead(_list(tables, "replace_verbs"), tables)
    if verb is None:
        return None
    here = nw.skip_articles(line, verb, tables)
    text_word = _at(line, here, _list(tables, "text_words"))
    if text_word is None:
        return None
    of = _at(line, text_word[1], _list(tables, "of"))
    if of is None:
        return None
    start = nw.skip_articles(line, of[1], tables)
    noun = _at(line, start, _list(tables, "nouns")) or _at(line, start, _list(tables, "held_nouns"))
    if noun:
        start = noun[1]
    marker = _content_start(line, start, _list(tables, "replace_with"))
    if marker is None:
        return None
    words = _span(line, start, marker[0], "name")
    content = _span(line, marker[1], len(line.norm), "content")
    if not words or not content:
        return None
    return {"op": "file-replace", "slots": {"words": words, "content": content}, "spans": {"words": words, "content": content},
            "ranges": {"content": (marker[1], len(line.norm))}, "need": [], "engine": None, "doubt": False}


def _save(line: "nw.Line", tables: list):
    verb = line.lead(_list(tables, "save_verbs"), tables)
    if verb is None:
        return None
    here = nw.skip_articles(line, verb, tables)
    this = _at(line, here, _list(tables, "this"))
    pos = this[1] if this else here
    pos = nw.skip_articles(line, pos, tables)
    kind_name, end = None, pos
    for table in tables:
        for name, words in (nw.writes_of(table).get("files", {}).get("kinds") or {}).items():
            spot = _at(line, pos, words)
            if spot and spot[1] > end:
                kind_name, end = name, spot[1]
    noun = _at(line, pos, _list(tables, "held_nouns"))
    if noun and noun[1] > end:
        end = noun[1]
    elif kind_name is None:
        noun = None
    m = NUMBER.match(line.norm, end)
    number = int(m.group(1)) if m and int(m.group(1)) >= 1 and m.group(1) == str(int(m.group(1))) else None
    if number:
        end = m.end()
    anchored = this is not None or number is not None or (noun is not None and line.norm[noun[0]:noun[1]] in ("anexo", "attachment"))
    if not anchored or (kind_name is None and noun is None):
        return None
    slots = {}
    if number:
        slots["attachment"] = number
    if kind_name:
        slots["kind"] = kind_name
    cuts = []
    folder_spot = line.find(_list(tables, "folder"), end)
    if folder_spot:
        m = FOLDER.match(line.norm, nw.skip_articles(line, folder_spot[1], tables))
        if not m:
            return None
        slots["folder"] = m.group(1)
        cuts.append((folder_spot[0], m.end()))
    service = nw.service(line, tables, end)
    if service:
        slots["account"] = service[0]
        cuts.append((service[1], service[2]))
    left = line.norm[end:]
    for s, e in sorted(cuts, reverse=True):
        left = left[:s - end] + " " + left[e - end:]
    polite = {w for p in nw.listed(tables, None, "polite") + [x for t in tables for x in t.get("polite", [])] for w in p.split()}
    if [w for w in re.findall(r"[a-z0-9]+", left) if w not in polite and w not in nw.listed(tables, None, "articles")]:
        return None
    return {"op": "file-save", "slots": slots, "spans": {}, "ranges": {}, "need": [] if number else ["attachment"], "engine": None, "doubt": False}


def read(line, tables, now=None, op=None):
    """The reading of a files line (see runtime/natural_writes.py), or None. With `op` only that operation is tried."""
    shaped = nw.Line(line if isinstance(line, str) else "")
    for name, reader in (("file-replace", _replace), ("file-create", _create), ("file-save", _save)):
        if op in (None, name):
            got = reader(shaped, tables)
            if got:
                return got
    return None


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
