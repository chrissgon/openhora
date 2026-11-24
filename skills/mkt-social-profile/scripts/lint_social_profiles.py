#!/usr/bin/env python3
"""Check a social-profiles artifact: the length of every proposed text against the platform's own limits,
the links, the voice and sensitive-topics locks, and the approvals.

Usage:
  python3 lint_social_profiles.py --file docs/marketing/social-profiles.md
         --platforms-dir shared/references/platforms
         [--voice docs/brand/voice.md] [--profile docs/brand/profile.md] [--links-from docs/brand/strategy.md]
         [--exception <topic>]...
         [--platform-label Platform] [--status-label Status] [--verdict-label Verdict]
         [--approved-label Approved] [--applied-label Applied] [--status-words draft]
         [--change-word change] [--yes-word yes]
         [--required-headings "Across networks,Superseded,To apply by hand,Open questions,Assumptions,Sources,Method"]

What it reads. Each "## " section with a "- Platform: <name>" line is a network. Each "### ... (`<key>`)"
inside a section is a piece of it. The fenced block tagged `proposed` under a piece is its proposed text,
exactly as the person will paste it. A section with pieces and no Platform line (the link page) gets the
checks that need no platform data (links, voice, sensitive topics, approvals). The platform's limits are read
from <platforms-dir>/<name>.json, key "profile", once per platform.

What it reports, for each proposed text: its length in Unicode code points (in UTF-16 code units when the
piece's "unit" is "utf-16"), the limit and the unit used. A platform with no "profile" key, or a piece whose
limit is null, has the limit "not checked" and gives no problem. Problems, each with its line number:
  over_limit, under_limit: the length is above max_characters or below min_characters.
  unknown_piece: the piece key is not in profile.pieces of a platform that has a "profile" key.
  too_many_links: a "links" piece holds more addresses than max_count.
  link_not_allowed: an address whose host is not a host of --links-from (compared whole, case-insensitive,
    "www." ignored). An address is a text with a scheme, one that starts with "www.", one with a path, or a
    bare lowercase host name that does not end like a file name (".js", ".md", ".json" and the like).
  banned_phrase, too_many_emojis, emoji_line_start, too_many_exclamations: the shared voice_stats.py check,
    next to this script, with only the voice guide's "banned", "max_emojis", "no_emoji_line_start" and
    "max_exclamations". "end_with_question" and "max_hashtags" are left out on purpose: a bio is not a post.
  sensitive: the shared sensitive_topics.py locks the text on a topic that no --exception names.
  approved_without_words: an Approved or Applied line that starts with the yes word and has no date, or an
    Approved line with neither quoted words nor brackets that name the strategy (`yes, <date> (docs/brand/
    strategy.md, proposal 1)`), or an Applied line with neither quoted words nor words in brackets.
  change_without_proposal: a piece whose verdict is the change word and that has no proposed block, unless
    its Why line starts with "remove:" (a piece to remove has no proposed text).
  missing_section: a heading of --required-headings is not a "## " heading of the file.
  no_network: the file has no section with a Platform line.
  status: the Status line of the header holds none of --status-words.
A missing --voice or --profile gives "voice": "unchecked" or "sensitive": "unchecked", never a pass. Headings
and labels are matched case-insensitively; pass translated texts for an artifact not in English.

Output: JSON on stdout: {"ok", "networks": {"<platform>": {"limits", "pieces": {"<key>": {"length", "limit",
"unit"}}}}, "voice", "sensitive", "problems": [{"code", "line", "where", "message"}], "length_lines":
{"<platform>.<key>": "<n> of <limit> (<unit>)" | "<n> (<unit>); limit not checked"}}. Diagnostics go to stderr. Exit 0 when ok, 1 when a problem
is reported, 2 on a bad argument or an unreadable file. No network; standard library only.
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_REQUIRED = "Across networks,Superseded,To apply by hand,Open questions,Assumptions,Sources,Method"
FILE_ENDINGS = {"js", "ts", "py", "md", "json", "html", "css", "txt", "jsx", "tsx", "go", "rs", "rb", "sh",
                "yml", "yaml", "csv", "pdf", "png", "jpg", "jpeg", "gif", "svg", "xml", "toml", "ini", "cfg"}
ADDRESS = re.compile(
    r"(?<![@\w.-])((?:https?://)?(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,24})(?::\d+)?((?:/[^\s,;)>\]\"'`]*)?)")
PIECE_HEADING = re.compile(r"^###\s+.*\(`([^`]+)`\)\s*$")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class Bad(Exception):
    pass


def read_text(path, what):
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise Bad("%s: cannot read %s (%s)" % (what, path, type(e).__name__))


def addresses(text):
    """The addresses a text holds, as (host, written) pairs."""
    found = []
    for m in ADDRESS.finditer(text):
        raw, path = m.group(1), m.group(2)
        scheme = raw.lower().startswith(("http://", "https://"))
        host = re.sub(r"^https?://", "", raw, flags=re.I).lower()
        ending = host.rsplit(".", 1)[-1]
        if not (scheme or host.startswith("www.") or path):
            if raw != raw.lower() or ending in FILE_ENDINGS:
                continue
        found.append((re.sub(r"^www\.", "", host), raw + path))
    return found


def parse(text, labels):
    """Sections, pieces and header lines of the artifact, with line numbers."""
    sections, header, cur, piece, fence = [], {}, None, None, None
    for n, line in enumerate(text.split("\n"), 1):
        if fence is not None:
            if line.strip() == "```":
                fence = None
                continue
            if piece is not None and fence == "proposed":
                piece["lines"].append(line)
            continue
        m = re.match(r"^```(\S*)\s*$", line.strip())
        if m and m.group(1):
            fence = m.group(1)
            if fence == "proposed" and piece is not None:
                piece["lines"], piece["proposed_line"] = [], n
            continue
        if line.startswith("## "):
            cur = {"heading": line[3:].strip(), "line": n, "platform": None, "pieces": []}
            sections.append(cur)
            piece = None
            continue
        if line.startswith("# ") or cur is None:
            hm = re.match(r"^-\s*%s:\s*(.*)$" % re.escape(labels["status"]), line.strip(), re.I)
            if hm:
                header["status"] = (hm.group(1), n)
            continue
        pm = PIECE_HEADING.match(line.strip())
        if pm:
            piece = {"key": pm.group(1), "line": n, "lines": None, "proposed_line": None,
                     "verdict": None, "why": "", "approvals": []}
            cur["pieces"].append(piece)
            continue
        item = re.match(r"^-\s*([^:]+):\s*(.*)$", line.strip())
        if not item:
            continue
        label, value = item.group(1).strip().lower(), item.group(2).strip()
        if piece is None:
            if label == labels["platform"].lower():
                cur["platform"] = value.lower()
            continue
        if label == labels["verdict"].lower():
            piece["verdict"] = value.lower()
        elif label == "why":
            piece["why"] = value
        elif label in (labels["approved"].lower(), labels["applied"].lower()):
            piece["approvals"].append((label == labels["approved"].lower(), value, n))
    return sections, header


def load_profile(platforms_dir, name, cache):
    if name not in cache:
        path = Path(platforms_dir) / (name + ".json")
        try:
            data = json.loads(read_text(path, "platform data"))
        except ValueError:
            raise Bad("platform data: %s is not JSON" % path)
        profile = data.get("profile") if isinstance(data, dict) else None
        cache[name] = profile if isinstance(profile, dict) and isinstance(profile.get("pieces"), dict) else None
    return cache[name]


def voice_rules(path):
    text = read_text(path, "--voice")
    m = re.search(r"```voice-rules\s*\n(.*?)\n```", text, re.S)
    if not m:
        raise Bad("--voice: %s has no ```voice-rules block" % path)
    try:
        rules = json.loads(m.group(1))
    except ValueError:
        raise Bad("--voice: the voice-rules block of %s is not JSON" % path)
    keep = ("banned", "max_emojis", "no_emoji_line_start", "max_exclamations")
    return {k: rules[k] for k in keep if k in rules}


def run_json(cmd, stdin):
    try:
        r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Bad("%s: %s" % (Path(cmd[1]).name, e))
    try:
        return r.returncode, json.loads(r.stdout)
    except ValueError:
        raise Bad("%s: unreadable answer: %s" % (Path(cmd[1]).name, r.stderr.strip()[:200]))


VOICE_CODES = (("banned phrase", "banned_phrase"), ("exclamation", "too_many_exclamations"),
               ("line start", "emoji_line_start"), ("start", "emoji_line_start"), ("emoji", "too_many_emojis"))


def voice_code(message):
    for needle, code in VOICE_CODES:
        if needle in message.lower():
            return code
    return "banned_phrase"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", required=True)
    ap.add_argument("--platforms-dir", required=True)
    ap.add_argument("--voice")
    ap.add_argument("--profile")
    ap.add_argument("--links-from")
    ap.add_argument("--exception", action="append", default=[])
    ap.add_argument("--platform-label", default="Platform")
    ap.add_argument("--status-label", default="Status")
    ap.add_argument("--verdict-label", default="Verdict")
    ap.add_argument("--approved-label", default="Approved")
    ap.add_argument("--applied-label", default="Applied")
    ap.add_argument("--status-words", default="draft")
    ap.add_argument("--change-word", default="change")
    ap.add_argument("--yes-word", default="yes")
    ap.add_argument("--required-headings", default=DEFAULT_REQUIRED)
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    labels = {"platform": a.platform_label, "status": a.status_label, "verdict": a.verdict_label,
              "approved": a.approved_label, "applied": a.applied_label}
    try:
        text = read_text(a.file, "--file")
        if not Path(a.platforms_dir).is_dir():
            raise Bad("--platforms-dir: %s is not a folder" % a.platforms_dir)
        allowed = None
        if a.links_from:
            allowed = {h for h, _ in addresses(read_text(a.links_from, "--links-from"))}
        rules = voice_rules(a.voice) if a.voice else None
        if a.profile:
            read_text(a.profile, "--profile")
        out = lint(a, labels, text, allowed, rules)
    except Bad as e:
        print("lint_social_profiles.py: %s" % e, file=sys.stderr)
        return 2
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    print()
    return 0 if out["ok"] else 1


def lint(a, labels, text, allowed, rules):
    problems, networks, length_lines, cache = [], {}, {}, {}

    def add(code, line, where, message):
        problems.append({"code": code, "line": line, "where": where, "message": message})

    sections, header = parse(text, labels)
    words = [w.strip().lower() for w in a.status_words.split(",") if w.strip()]
    status = header.get("status")
    if status is None or not any(w in status[0].lower() for w in words):
        add("status", status[1] if status else 1, "header",
            "the Status line must hold one of: %s" % ", ".join(words))
    headings = {s["heading"].strip().lower() for s in sections}
    for need in [h.strip() for h in a.required_headings.split(",") if h.strip()]:
        if need.lower() not in headings:
            add("missing_section", 1, need, "no '## %s' section" % need)
    if not any(s["platform"] for s in sections):
        add("no_network", 1, "file", "no section has a '- %s:' line" % labels["platform"])

    exceptions = {e.strip().lower() for e in a.exception}
    for sec in sections:
        name = sec["platform"]
        if not sec["pieces"] and not name:
            continue
        profile = load_profile(a.platforms_dir, name, cache) if name else None
        if name:
            networks.setdefault(name, {"limits": "checked" if profile else "not checked", "pieces": {}})
        for piece in sec["pieces"]:
            where = "%s.%s" % (name or sec["heading"], piece["key"])
            for is_approval, value, n in piece["approvals"]:
                if re.match(r"^%s\b" % re.escape(a.yes_word), value, re.I):
                    quoted = re.search(r'["“][^"”]+["”]', value)
                    bracketed = re.search(r"\([^)]+\)", value)
                    from_strategy = is_approval and re.search(r"\([^)]*strategy[^)]*\)", value, re.I)
                    ok = DATE.search(value) and (
                        (quoted or from_strategy) if is_approval else (quoted or bracketed))
                    if not ok:
                        add("approved_without_words", n, where,
                            "a yes needs a date and the person's quoted words: %r" % value[:80])
            if piece["lines"] is None:
                if piece["verdict"] == a.change_word.lower() and not piece["why"].lower().startswith("remove:"):
                    add("change_without_proposal", piece["line"], where, "the verdict is a change and no proposed block")
                continue
            body = "\n".join(piece["lines"])
            line = piece["proposed_line"]
            spec = None
            if name and profile:
                spec = profile["pieces"].get(piece["key"])
                if spec is None:
                    add("unknown_piece", piece["line"], where, "'%s' is not a piece of %s" % (piece["key"], name))
                spec = spec or {}
            spec = spec or {}
            unit = "utf-16" if spec.get("unit") == "utf-16" else "code points"
            n_chars = len(body.encode("utf-16-le")) // 2 if unit == "utf-16" else len(body)
            high, low = spec.get("max_characters"), spec.get("min_characters")
            limit = high if isinstance(high, int) else "not checked"
            if name:
                key, i = piece["key"], 2
                while key in networks[name]["pieces"]:
                    key, i = "%s#%d" % (piece["key"], i), i + 1
                networks[name]["pieces"][key] = {"length": n_chars, "limit": limit, "unit": unit}
                length_lines["%s.%s" % (name, key)] = (
                    "%d of %d (%s)" % (n_chars, limit, unit) if isinstance(limit, int)
                    else "%d (%s); limit not checked" % (n_chars, unit))
            if isinstance(high, int) and n_chars > high:
                add("over_limit", line, where, "%d %s, limit %d" % (n_chars, unit, high))
            if isinstance(low, int) and n_chars < low:
                add("under_limit", line, where, "%d %s, minimum %d" % (n_chars, unit, low))
            found = addresses(body)
            maxc = spec.get("max_count")
            if piece["key"] == "links" and isinstance(maxc, int) and len(found) > maxc:
                add("too_many_links", line, where, "%d addresses, limit %d" % (len(found), maxc))
            if allowed is not None:
                for host, written in found:
                    if host not in allowed:
                        add("link_not_allowed", line, where, "%s is not a link of the strategy" % written)
            if rules is not None and body.strip():
                with tempfile.TemporaryDirectory() as tmp:
                    rp = Path(tmp) / "rules.json"
                    rp.write_text(json.dumps(rules), encoding="utf-8")
                    code, res = run_json([sys.executable, str(HERE / "voice_stats.py"), "check", "--rules", str(rp)],
                                         json.dumps({"id": where, "text": body}, ensure_ascii=False))
                if code == 2:
                    raise Bad("voice_stats.py refused its input")
                for v in res.get("violations", []):
                    add(voice_code(v), line, where, v)
            if a.profile and body.strip():
                code, res = run_json([sys.executable, str(HERE / "sensitive_topics.py"), "--profile", a.profile], body)
                if code == 2:
                    raise Bad("sensitive_topics.py: %s is not a usable profile" % a.profile)
                hits = {t: k for t, k in res.get("topics", {}).items() if t.lower() not in exceptions}
                if hits:
                    add("sensitive", line, where, "touches %s" % ", ".join(
                        "%s (%s)" % (t, ", ".join(k)) for t, k in sorted(hits.items())))
    return {"ok": not problems, "networks": networks, "voice": "checked" if rules is not None else "unchecked",
            "sensitive": "checked" if a.profile else "unchecked", "problems": problems, "length_lines": length_lines}


if __name__ == "__main__":
    sys.exit(main())
