#!/usr/bin/env python3
"""Read a post file's ```script block (the M1 format) and produce the prototype's script.json.

The format is the one `mkt-social-copy` writes (skills/mkt-social-copy/references/video-script.md): beats of
`key: value` lines, `line` (the spoken words), optional `on-screen` (the preset's main text) and `preset`, and the
parameters of that preset. This module does not parse it again: it imports the real `check_script.py` from the
repository, runs the same check, REFUSES a post file that does not pass, and reads the fields with the same parser and
the same value checks, so the two cannot drift.

Mapping of the shipped presets to the prototype's templates:

  keyword  text <- on-screen; icon; color
  list     items <- on-screen, one line separated by ' | ' (1 to 4), drawn as item1..item4; no title
  number   label <- on-screen; value is the figure as written; no prefix or suffix
  quote    text <- on-screen; author; color
  cutaway  label <- on-screen (optional); fit; asset
  pip      label <- on-screen (optional); position top|bottom; asset
  (none)   a beat with no preset is caption only: the captions are always on and nothing else is drawn

An `asset` is a description in words in the post file. The file comes from the person, one per beat, as
`--asset <beat>=<file>` (PNG or JPEG): the beat's slot id is `beat<N>`. A cutaway or pip beat with no file falls back to a
`keyword` with its label (when the label fits a keyword), or to caption only when it has none, and the fallback is
reported. Nothing is guessed: a file given for a beat that has no asset slot is an error.

  python3 from_post.py --post docs/marketing/content/2026-10-13-slug.md [--asset 3=shot.png] [--out script.json]
"""
import argparse
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
CHECKER = os.path.join("skills", "mkt-social-copy", "scripts", "check_script.py")
VOCABULARY = os.path.join("shared", "references", "video-presets.json")
VIDEO_FORMATS = ("reel", "video")
FORMAT_LINE = re.compile(r"^\s*-\s*Format:\s*([A-Za-z-]+)\s*$", re.M)
KEYWORD_MAX = 24            # a keyword's text bound; the fallback label must fit it
ASSET_PRESETS = ("cutaway", "pip")


class PostError(ValueError):
    """The post file is refused. `problems` is a list of {beat, field, code}; never the refused text."""

    def __init__(self, message, problems=None):
        super().__init__(message)
        self.problems = problems or []


def slot_id(beat):
    return "beat%d" % beat


def load_checker(repo_root=None):
    """Import the repository's own check_script.py by its path."""
    root = repo_root or REPO_ROOT
    path = os.path.join(root, CHECKER)
    if not os.path.isfile(path):
        raise PostError("check_script.py not found at %s (merge the branch that ships it, or pass --repo-root)" % path)
    spec = importlib.util.spec_from_file_location("check_script_real", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, os.path.join(root, VOCABULARY)


def post_format(text):
    m = FORMAT_LINE.search(text)
    return m.group(1).lower() if m else None


def read_post(path, repo_root=None):
    """Parse and check the post file. Returns (format, vocab, rows) where rows are the checked beats.

    A row is {"beat": N, "line": str, "preset": name|None, "values": {param: accepted value}, "slots": {param: desc}}.
    Raises PostError when the file does not pass check_script.py.
    """
    cs, vocab_path = load_checker(repo_root)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        vocab = cs.load_vocabulary(vocab_path)
        block = cs.script_block(text)
    except (OSError, ValueError) as exc:
        raise PostError("post file refused: %s" % exc)
    fmt = post_format(text)
    if fmt is not None and fmt not in VIDEO_FORMATS:
        raise PostError("the post's format is %s, not a video format (reel or video)" % fmt)
    _, _, problems = cs.check(block, vocab, fmt)
    if problems:
        raise PostError("check_script.py refused the script (%d problems: %s)" % (
            len(problems), ", ".join("beat %s %s %s" % (p["beat"], p["field"], p["code"]) for p in problems[:8])), problems)
    beats, parse_problems = cs.parse(block)
    if parse_problems:        # cannot happen after a passing check; kept so a changed checker fails loudly
        raise PostError("script block did not parse", parse_problems)
    rows = []
    for b in beats:
        fields = b["fields"]
        name = fields["preset"].strip() if "preset" in fields else None
        row = {"beat": b["n"], "line": cs.hardened(fields["line"].strip()), "preset": name, "values": {}, "slots": {}}
        if name:
            spec = vocab["presets"][name]
            for key, value in fields.items():
                if key in ("line", "preset"):
                    continue
                param = spec["main"] if key == "on-screen" else key
                accepted = cs.check_value(vocab, spec["params"][param], value)
                if cs.slot_types(spec["params"][param]):
                    row["slots"][param] = accepted
                else:
                    row["values"][param] = accepted
        rows.append(row)
    return fmt, vocab, rows


def map_beat(row, has_file, note):
    """One beat of the prototype's script.json, or None for a caption-only beat. `note` records a decision."""
    n, preset, v = row["beat"], row["preset"], dict(row["values"])
    if preset is None:
        note(n, None, "caption only", "no preset: the captions are the whole picture")
        return None
    if preset in ASSET_PRESETS:
        if not has_file:
            label = v.get("label")
            if label and len(label) <= KEYWORD_MAX:
                note(n, preset, "fallback keyword", "no file for the asset (%s); showing its label as a keyword" % row["slots"]["asset"])
                return {"id": "b%d" % n, "label": "keyword", "preset": "keyword", "line": row["line"], "params": {"text": label}}
            note(n, preset, "fallback caption only", "no file for the asset (%s) and %s" % (
                row["slots"]["asset"], "its label is longer than a keyword allows" if label else "no label to show"))
            return None
        v["image"] = slot_id(n)
    if preset == "list":
        for k, item in enumerate(v.pop("items").split(" | "), 1):
            v["item%d" % k] = item
    params = {k: val for k, val in v.items()}
    note(n, preset, "ok", "")
    return {"id": "b%d" % n, "label": preset, "preset": preset, "line": row["line"], "params": params}


def build_script(path, asset_beats=(), repo_root=None):
    """Return (script, report) for a post file. `asset_beats` is the set of beat numbers that have an uploaded file."""
    fmt, _, rows = read_post(path, repo_root)
    asset_beats = set(asset_beats)
    with_slot = {r["beat"] for r in rows if r["preset"] in ASSET_PRESETS}
    stray = sorted(asset_beats - with_slot)
    if stray:
        raise PostError("a file was given for beat %s, which has no cutaway or pip" % ", ".join(map(str, stray)))
    report = []

    def note(beat, preset, outcome, detail):
        report.append({"beat": beat, "preset": preset, "outcome": outcome, "detail": detail})

    beats, assets = [], {}
    for row in rows:
        mapped = map_beat(row, row["beat"] in asset_beats, note)
        if mapped is None:
            continue
        beats.append(mapped)
        if mapped["preset"] in ASSET_PRESETS:
            assets[slot_id(row["beat"])] = row["slots"]["asset"]
    script = {"format": fmt or "reel", "caption": {"position": "bottom"}, "assets": assets, "beats": beats}
    return script, report


def format_report(report):
    lines = ["beat  preset    outcome"]
    for r in report:
        lines.append("%-5s %-9s %s%s" % (r["beat"], r["preset"] or "-", r["outcome"], ("  (" + r["detail"] + ")") if r["detail"] else ""))
    return "\n".join(lines)


def parse_asset_flags(flags):
    """['3=a.png'] -> {3: 'a.png'}. The key is a beat number."""
    out = {}
    for item in flags or []:
        key, _, path = item.partition("=")
        if not key.isdigit() or not path:
            raise PostError("--asset takes <beat number>=<file> with a post file, got a different shape")
        if int(key) in out:
            raise PostError("--asset given twice for beat %s" % key)
        out[int(key)] = path
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--post", required=True, help="the post file with the ```script block")
    ap.add_argument("--asset", action="append", metavar="BEAT=FILE", help="a file for a cutaway or pip beat (repeatable)")
    ap.add_argument("--repo-root", help="the repository that holds check_script.py (default: this checkout)")
    ap.add_argument("--out", help="write the script.json here (default: print it)")
    args = ap.parse_args(argv)
    try:
        files = parse_asset_flags(args.asset)
        script, report = build_script(args.post, set(files), args.repo_root)
    except PostError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    print(format_report(report), file=sys.stderr)
    text = json.dumps(script, indent=1, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
