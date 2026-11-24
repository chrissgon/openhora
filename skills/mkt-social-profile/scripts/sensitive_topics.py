#!/usr/bin/env python3
"""Match a text against the sensitive-topics lock of a brand profile.

Usage:
  python3 sensitive_topics.py --profile docs/brand/profile.md < text.txt
  python3 sensitive_topics.py --profile docs/brand/profile.md --validate

Reads the ```sensitive-topics JSON block of the profile:
  {"action": "...", "topics": {"<topic>": {"keywords": [...], "exclude": [...]}}}
Keywords match as whole words or phrases, case-insensitive, after removing every "exclude" phrase
of the same topic from the text (so "font-family" is not the topic "family"). Prints JSON:
{"locked": true|false, "topics": {"<topic>": ["<keyword>", ...]}, "action": "..."}.
Exit 1 when locked, 0 when not, 2 on a bad profile or input. --validate only checks the block.
Keywords are a first filter: a text that does not match can still touch a topic, so the caller
also judges the meaning and sends doubtful texts to the user.
"""
import argparse
import json
import re
import sys


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
    except OSError as exc:
        fail(f"cannot read {path}: {exc}")
    m = re.search(r"```sensitive-topics\s*\n(.*?)```", raw, re.S)
    if not m:
        fail(f"{path} has no ```sensitive-topics block")
    try:
        block = json.loads(m.group(1))
    except ValueError as exc:
        fail(f"the sensitive-topics block is not JSON: {exc}")
    topics = block.get("topics")
    if not isinstance(topics, dict) or not topics:
        fail("the block needs a non-empty \"topics\" object")
    for name, t in topics.items():
        if not isinstance(t, dict) or not isinstance(t.get("keywords"), list) or not t["keywords"] \
                or not all(isinstance(k, str) and k.strip() for k in t["keywords"] + t.get("exclude", [])):
            fail(f"topic {name!r} needs a non-empty list of keyword strings (and an optional exclude list)")
    return block


def match(text, block):
    found = {}
    for name, t in block["topics"].items():
        low = text.lower()
        for phrase in t.get("exclude", []):
            low = low.replace(phrase.lower(), " ")
        hits = [k for k in t["keywords"] if re.search(r"(?<!\w)" + re.escape(k.lower()) + r"(?!\w)", low)]
        if hits:
            found[name] = hits
    return found


def fail(msg):
    print(f"sensitive_topics.py: {msg}", file=sys.stderr)
    sys.exit(2)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()
    block = load(args.profile)
    if args.validate:
        print(json.dumps({"ok": True, "topics": sorted(block["topics"])}))
        return 0
    found = match(sys.stdin.read(), block)
    print(json.dumps({"locked": bool(found), "topics": found, "action": block.get("action", "")}, ensure_ascii=False))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
