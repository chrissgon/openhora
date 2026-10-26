#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Write the registry data files from the language tables at the current commit (S41-9; contracts/runtime.md, limit L63; decision OPEN-41-11).

The two files of runtime/registry/ (`private_words.json`, `search_stop_words.json`) are made here, once, from runtime/natural_lang_*.py and from the closed words that
runtime/event_lookup.py held in code (`CAL_WORDS`, `LEADS`, `PLURAL`, `STOP_EXTRA`, copied below as they were at the commit the data was made from). The build is deterministic: the
same tables and the same commit name give the same bytes. After S41-11 the keys it reads are gone, so this script is deleted there and the files are edited by hand under review.

  python3 scripts/registry_build.py                     write both files (the commit name is `git rev-parse --short HEAD` unless --made-from gives one)
  python3 scripts/registry_build.py --check             write nothing; exit 1 when a file differs from what the tables give (the commit name is not compared)
  python3 scripts/registry_build.py --made-from <name>  name the commit the data is made from
  python3 scripts/registry_build.py --out <folder>      write into <folder> instead of runtime/registry/

The private rule the data states (read by `turn_gate.private_line`): a line is private when it is not a typed command (it does not start with "/") and one of these holds, over the line
folded as the tables fold it (lower case, no accent): (1) it starts, after blanks, marks and polite words, with a `lead` phrase; (2) it starts with a `lead_with_time` phrase and the time
engine finds a time in it; (3) it holds an `anywhere_with_time` phrase and the time engine finds a time in it; (4) it starts with a `verb_noun` verb, at most `verb_noun_gap_max` words,
then a `verb_noun` noun; (5) it starts with a head of a write family and holds a marker of the same family; (6) it has no "?", the time engine finds a clock or a relative time in it,
its first word is not a `work_starters` word and no more than `bare_words_max` words are left once the time is taken out. This is wider than the old `natural.private` in each
step (it drops the conditions that need a full reading of the line), never narrower: the old detector stays in runtime/natural.py until S41-11 as the oracle of the tests.

Python 3.9. Standard library and the runtime's own pure modules only; no network, no model.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME = os.path.join(ROOT, "runtime")
FOLDER = os.path.join(RUNTIME, "registry")
sys.path.insert(0, RUNTIME)

import natural  # noqa: E402
import natural_time as nt  # noqa: E402
import natural_writes as nw  # noqa: E402

RULE_PRIVATE = ("a line that is not a typed command is private when it starts with a lead phrase, starts with a lead_with_time phrase or holds an anywhere_with_time phrase with a time in it, "
                "starts with a verb_noun verb then a noun, starts with a write head and holds a marker of its family, or is a short bare line with a clock or a relative time and no work starter")
RULE_SEARCH = ("the folded words of a line that name no event (stop_words, brand words left out), the lead and calendar words that introduce an account, the plural words, "
               "the calendar nouns and the brand words of each account")

# What runtime/event_lookup.py held in code before S41-9, copied here as it was (commit 2fb497d); after the first write these words are data and live in the file.
CAL_WORDS = {"agenda", "agendas", "calendar", "calendars", "calendario", "calendarios", "calendrier", "calendriers", "kalender", "calendari"}
LEADS = CAL_WORDS | {"no", "na", "nos", "nas", "pelo", "pela", "via", "usando", "pro", "pra", "em", "de", "do", "da", "meu", "minha",  # validate: allow english-only -- the closed words of the languages a line may be written in, copied as they were
                     "on", "in", "to", "from", "using", "of", "my", "at",
                     "en", "del", "por", "mi", "mis", "con",
                     "sur", "dans", "avec", "mon", "ma", "chez",
                     "im", "auf", "bei", "mit", "uber", "mein", "meine", "unter",
                     "su", "sul", "sulla", "nel", "nella", "tramite", "mio", "mia", "di"}
PLURAL = {"os", "as", "uns", "umas", "aos", "los", "las", "les", "die", "gli", "le", "ambos", "ambas", "todos", "todas", "both", "all"}
STOP_EXTRA = {"para", "as", "que", "com", "sem", "e", "and", "with", "the", "a", "an", "for", "at", "please", "por", "favor", "pra", "pro"}  # validate: allow english-only -- the closed words of the languages a line may be written in, copied as they were
SERVICES = ("google", "microsoft")
MAIL_TAIL_MAX = 16          # words (not digits, joiners or range words) after the mail noun in a line that has no text marker: "o ultimo e-mail da Ana sobre a fatura pelo outlook" has 8; a reference names at most WORDS_CAP (3) content words
ATTACHMENT_WORDS = ["anexo", "attachment"]      # the two nouns natural_writes_files.py `_save` takes as the anchor of a file somebody sent (code constants there)
VERB_NOUN_GAP_MAX = 2          # words between the scheduling verb and the reminder noun ("schedule a new reminder"), as natural.py `_verb_noun` reads them


def _words(phrase: str) -> list:
    return natural.normal(phrase).split()


def _listed(tables, section, key) -> list:
    return nw.listed(tables, section, key)


def _sorted(items) -> list:
    return sorted({item for item in items if item})


def _shapes(tables, table) -> dict:
    """The write shapes of one language: for each family a list of {op, heads, needs}. A shape is a necessary condition of what the families of runtime/natural_writes_*.py read: a head at the
    start of the line and every one of its needs (a need holds when ANY of its alternatives does: a phrase of `words`, a digit, a colon, an address mark, or a line that holds nothing but
    the words of `only`). The conditions are read from the families' code at commit 2fb497d and proven against it by the corpora and by the differential test."""
    one = [table]
    L = lambda section, *keys: _sorted(p for key in keys for p in _listed(one, section, key))      # noqa: E731
    polite = _sorted(table["polite"] + nw.writes_of(table).get("polite", []))
    articles = L(None, "articles")
    services = _sorted(p for account in SERVICES for p in _listed(one, "services", account))
    nouns = L("calendar", "nouns")
    need = lambda **given: given                                                                  # noqa: E731
    cal_only = _sorted(w for p in polite + articles + nouns + L(None, "service_in") + services for w in p.split())
    kinds = _sorted(p for ps in (nw.writes_of(table).get("files", {}).get("kinds") or {}).values() for p in ps)
    mail_nouns = L("mail", "nouns", "plural")
    mail_ref = {"digit": True, "words": L("mail", "of", "newest")}
    mail_tail = {"words": L("mail", "body"), "colon": True, "tail_after": mail_nouns, "tail_skip": L(None, "joiners", "range"), "tail_max": MAIL_TAIL_MAX}      # a text after the noun, or a short tail: a reference alone is short
    return {
        "calendar": [
            {"op": "event-change", "heads": L("calendar", "change_verbs"), "needs": [need(words=nouns), need(digit=True)]},
            {"op": "event-rename", "heads": L("calendar", "rename"), "needs": [need(words=nouns), need(digit=True)]},
            {"op": "event-cancel", "heads": L("calendar", "cancel_verbs"), "needs": [need(words=nouns), need(digit=True, only=cal_only)]},
        ],
        "mail": [
            {"op": "mail-new", "heads": L("mail", "send_verbs", "draft_verbs"), "needs": [need(words=mail_nouns), need(words=L("mail", "to")), need(address=True, colon=True, words=L("mail", "body"))]},
            {"op": "mail-reference", "heads": L("mail", "reply_verbs", "archive_verbs", "trash_verbs", "mark_verbs"), "needs": [need(words=mail_nouns), mail_ref, mail_tail]},
            {"op": "mail-move", "heads": L("mail", "move_verbs"), "needs": [need(words=mail_nouns), need(words=L("mail", "folder")), mail_ref]},
            {"op": "mail-reply-draft", "heads": L("mail", "draft_verbs"), "needs": [need(words=mail_nouns), need(words=L("mail", "reply_verbs")), mail_ref, mail_tail]},
        ],
        "files": [
            {"op": "file-create", "heads": L("files", "create_verbs"), "needs": [need(words=L("files", "nouns", "gdoc")), need(words=L("files", "named")), need(colon=True, words=L("files", "content"))]},
            {"op": "file-replace", "heads": L("files", "replace_verbs"), "needs": [need(words=L("files", "text_words")), need(words=L("files", "of")), need(colon=True, words=L("files", "replace_with"))]},
            {"op": "file-save", "heads": L("files", "save_verbs"), "needs": [need(digit=True, words=_sorted(L("files", "this") + ATTACHMENT_WORDS + services)), need(words=_sorted(L("files", "held_nouns") + kinds + services))]},
        ],
    }


def private_words(made_from: str) -> dict:
    """The content of private_words.json from the language tables."""
    languages = {}
    for table in nt.languages():
        tag, triggers, writes = table["tag"], table["triggers"], nw.writes_of(table)
        languages[tag] = {
            "polite": _sorted(table["polite"] + writes.get("polite", [])),
            "lead": _sorted(triggers["remind"] + triggers["note"] + triggers["calendar"]),
            "lead_with_time": _sorted(triggers["calendar_verb"]),
            "anywhere_with_time": _sorted(triggers["remind_anywhere"]),
            "verb_noun": {"verbs": _sorted(triggers["calendar_verb"] + triggers["calendar_loose"] + triggers["calendar_noun"]), "nouns": _sorted(table["remind_nouns"])},
            "writes": _shapes(nt.languages(), table),
            "work_starters": _sorted(table["work_starters"]),
        }
    return {"v": 1, "made_from": made_from, "rule": RULE_PRIVATE,
            "numbers": {"bare_words_max": natural.BARE_WORDS_MAX, "verb_noun_gap_max": VERB_NOUN_GAP_MAX},
            "languages": dict(sorted(languages.items()))}


def search_stop_words(made_from: str) -> dict:
    """The content of search_stop_words.json: what `event_lookup._stop_words`, `_brands` and `_noun_words` computed from the tables and the closed words at commit 2fb497d."""
    tables = natural._tables(None)
    brands = {account: [_words(p) for p in _listed(tables, "calendar", "brands_" + account)] for account in SERVICES}
    found = set(STOP_EXTRA) | set(LEADS) | set(CAL_WORDS) | PLURAL
    for section, key in ((None, "articles"), ("calendar", "cancel_verbs"), ("calendar", "change_verbs"), ("calendar", "to_time"), ("calendar", "rename"), ("calendar", "in_calendar")):
        for phrase in _listed(tables, section, key):
            found.update(_words(phrase))
    for table in tables:
        for phrase in nw.writes_of(table).get("polite", []) + table.get("polite", []):
            found.update(_words(phrase))
    for listed in brands.values():
        for words in listed:
            found.difference_update(words)
    nouns = {w for key in ("nouns", "nouns_plural") for phrase in _listed(tables, "calendar", key) for w in _words(phrase)}
    return {"v": 1, "made_from": made_from, "rule": RULE_SEARCH, "stop_words": sorted(found), "leads": sorted(LEADS), "cal_words": sorted(CAL_WORDS), "plural": sorted(PLURAL),
            "nouns": sorted(nouns), "brands": brands}


def render(data: dict) -> str:
    """The file's text: two-space indent, a list of words one word to a line (a review reads one word at a time), a brand one line."""
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


def build(made_from: str) -> dict:
    return {"private_words.json": private_words(made_from), "search_stop_words.json": search_stop_words(made_from)}


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog="\n".join(__doc__.split("\n\n")[1:3]))
    parser.add_argument("--check", action="store_true", help="write nothing; exit 1 when a file differs from what the tables give (the commit name is not compared)")
    parser.add_argument("--made-from", default=None, help="the name of the commit the data is made from (default: git rev-parse --short HEAD)")
    parser.add_argument("--out", default=FOLDER, help="the folder to write into (default: runtime/registry/)")
    args = parser.parse_args(argv)
    made = args.made_from or _commit()
    built = build(made)
    if args.check:
        bad = []
        for name, data in built.items():
            try:
                with open(os.path.join(args.out, name), encoding="utf-8") as handle:
                    have = json.load(handle)
            except (OSError, ValueError):
                bad.append(f"{name}: cannot be read")
                continue
            have["made_from"] = data["made_from"]
            if have != data:
                bad.append(f"{name}: differs from what the language tables give")
        for line in bad:
            print(line, file=sys.stderr)
        print("registry data equals the tables" if not bad else f"{len(bad)} file(s) differ")
        return 1 if bad else 0
    os.makedirs(args.out, exist_ok=True)
    for name, data in built.items():
        with open(os.path.join(args.out, name), "w", encoding="utf-8") as handle:
            handle.write(render(data))
        print(f"wrote {os.path.join(args.out, name)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
