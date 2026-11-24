#!/usr/bin/env python3
"""Count the habits of writing samples, or check a draft against a voice's limits.

Usage:
  python3 voice_stats.py stats <<'EOF'
  [{"id": "S1", "text": "..."}, ...]
  EOF
  python3 voice_stats.py check --rules <voice.md or rules.json> <<'EOF'
  {"id": "draft-1", "text": "..."}
  EOF

stats   reads a JSON list of samples on stdin and prints, per sample and in total: words, lines,
        emojis, lines that start with an emoji, hashtags, exclamation marks, question marks, links,
        whether the text ends with a question (hashtags and links after it are ignored), and the
        first line. Counts come from here, never from reading the text by eye.
check   reads one draft {"id", "text"} on stdin and the limits from the ```voice-rules JSON block of
        a voice guide (or a plain JSON file) with keys max_emojis, max_hashtags, max_exclamations,
        end_with_question (true/false), no_emoji_line_start (true/false), banned (list of phrases,
        case-insensitive). Prints {"ok", "violations": [...], "stats"}; exit 1 on any violation.
Exit 2 on bad input or a usage error: the arguments are checked before standard input is read, so a
wrong call never waits for input. An emoji sequence joined by zero-width joiners or modifiers counts as one.
"""
import json
import re
import sys

# Code points are written as escapes so the source stays plain ASCII (no invisible characters).
_PICT = "\\U0001F300-\\U0001FAFF\\u2600-\\u27BF"
_MOD = "[\\uFE0F\\U0001F3FB-\\U0001F3FF]*"
EMOJI = re.compile(
    "(?:[\\U0001F1E6-\\U0001F1FF]{2}"  # flags
    "|[" + _PICT + "\\u2B00-\\u2BFF\\u2300-\\u23FF\\u2190-\\u21FF\\u3030\\u303D\\u3297\\u3299\\u00A9\\u00AE]" + _MOD
    + "(?:\\u200D[" + _PICT + "]" + _MOD + ")*)")
HASHTAG = re.compile(r"(?<![\w&])#[^\s#.,;:!?()\[\]]+", re.UNICODE)
LINK = re.compile(r"https?://\S+")
KEYS = {"max_emojis": int, "max_hashtags": int, "max_exclamations": int,
        "end_with_question": bool, "no_emoji_line_start": bool, "banned": list}


def stats(text):
    lines = [l for l in text.splitlines() if l.strip()]
    tail = [l for l in lines if not re.fullmatch(r"\s*((#[^\s#]+\s*)+|\S*https?://\S+\s*|[^\w]*\s*(link|github|demo|preview)\b.*)", l, re.I)]
    last = tail[-1].strip() if tail else ""
    return {
        "words": len(re.findall(r"\w+", text)),
        "lines": len(lines),
        "emojis": len(EMOJI.findall(text)),
        "emoji_line_starts": sum(1 for l in lines if EMOJI.match(l.strip())),
        "hashtags": len(HASHTAG.findall(text)),
        "exclamations": text.count("!"),
        "questions": text.count("?"),
        "links": len(LINK.findall(text)),
        "ends_with_question": last.endswith("?"),
        "first_line": lines[0].strip() if lines else "",
    }


def load_rules(path):
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        fail(f"cannot read {path}: {exc}")
    m = re.search(r"```voice-rules\s*\n(.*?)```", raw, re.S)
    try:
        rules = json.loads(m.group(1) if m else raw)
    except ValueError:
        fail(f"{path} has no ```voice-rules block and is not JSON")
    if not isinstance(rules, dict):
        fail(f"the voice rules in {path} must be a JSON object")
    for key, value in rules.items():
        if key not in KEYS or not isinstance(value, KEYS[key]) or (KEYS[key] is int and isinstance(value, bool)):
            fail(f"rule {key!r} is unknown or has the wrong type")
    return rules


def check(draft, rules):
    s = stats(draft)
    v = []
    if "max_emojis" in rules and s["emojis"] > rules["max_emojis"]:
        v.append(f"{s['emojis']} emojis, limit {rules['max_emojis']}")
    if "max_hashtags" in rules and s["hashtags"] > rules["max_hashtags"]:
        v.append(f"{s['hashtags']} hashtags, limit {rules['max_hashtags']}")
    if "max_exclamations" in rules and s["exclamations"] > rules["max_exclamations"]:
        v.append(f"{s['exclamations']} exclamation marks, limit {rules['max_exclamations']}")
    if rules.get("end_with_question") and not s["ends_with_question"]:
        v.append("does not end with a question")
    if rules.get("no_emoji_line_start") and s["emoji_line_starts"]:
        v.append(f"{s['emoji_line_starts']} lines start with an emoji")
    low = draft.lower()
    v += [f"banned phrase: {p!r}" for p in rules.get("banned", []) if p.lower() in low]
    return v, s


def fail(msg):
    print(f"voice_stats.py: {msg}", file=sys.stderr)
    sys.exit(2)


USAGE = "usage: voice_stats.py stats | check --rules <file> (see --help)"


def main(argv):
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    # The arguments first: a wrong call says so at once, and never blocks on standard input.
    if argv == ["stats"]:
        rules = None
    elif len(argv) == 3 and argv[:2] == ["check", "--rules"]:
        rules = load_rules(argv[2])
    elif argv[:1] == ["check"] and argv[-1:] == ["--rules"]:
        fail("--rules needs a file. " + USAGE)
    else:
        fail(USAGE)
    try:
        data = json.load(sys.stdin)
    except ValueError:
        fail("stdin is not JSON")
    if argv[0] == "stats":
        if not isinstance(data, list) or not all(isinstance(d, dict) and isinstance(d.get("text"), str) for d in data):
            fail("stats expects a list of {\"id\", \"text\"}")
        rows = [{"id": d.get("id", str(i + 1)), **stats(d["text"])} for i, d in enumerate(data)]
        total = {k: sum(r[k] for r in rows) for k in ("words", "emojis", "hashtags", "exclamations", "links")}
        print(json.dumps({"samples": rows, "total": total}, ensure_ascii=False, indent=2))
        return 0
    if not isinstance(data, dict) or not isinstance(data.get("text"), str):
        fail("check expects {\"id\", \"text\"}")
    violations, s = check(data["text"], rules)
    print(json.dumps({"id": data.get("id"), "ok": not violations, "violations": violations, "stats": s},
                     ensure_ascii=False, indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
