"""Beats: the post file's ```script block, checked by the skill's own checker and aligned to the transcript's words.

  run_checker   runs the script checker of the post-writing skill as an isolated subprocess and refuses a post it does
                not pass. The renderer never imports that code and never reads a beat the checker refused.
  read_script   the checked block's header (the script-level fields) and beats (number, spoken line, role, emphasis,
                preset, parameters), parsed with the same fence and `key: value` rules; read_beats is its beats.
  script_object the header's `title` and `loop`, as the optional `script` object of beats.json.
  annotate      writes each beat's role and emphasis into beats.json's entries and report, and the script object.
  align_line    the best window of the transcript for one spoken line: NFKC, casefold and punctuation normalised, free
                start and end, a spoken word that is not in the line costs little, a missing one costs a full word,
                figures excluded from scoring, a tie goes to the last occurrence (a retake wins), a threshold.
  align_beats   every beat with a preset, an order check, an unmatched beat reported and given no overlay.

Standard library only.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata

from _text import Refusal, clean_text
from _vocab import check_params, script_section, slot_params, slot_types

FENCE = re.compile(r"^```([\w-]*)\s*$")
KEY_LINE = re.compile(r"^([a-z][a-z0-9_-]{0,31}):(?: (.*))?$")
FORMAT_LINE = re.compile(r"^\s*-\s*Format:\s*([A-Za-z-]+)\s*$", re.M)
VIDEO_FORMATS = ("reel", "video")
DEL_COST = 1.0      # a beat token that was not spoken
INS_COST = 0.3      # a spoken word that is not in the beat (an ad-lib inside the line)
SIM_FLOOR = 0.75    # a token similarity below this is a plain mismatch
DEFAULT_THRESHOLD = 0.6


def post_format(text: str):
    m = FORMAT_LINE.search(text)
    return m.group(1).lower() if m else None


def run_checker(checker: str, content: str, vocabulary: str, fmt: str, timeout: float = 60) -> dict:
    """The checker's verdict as a dict. Refuses (a Refusal with `problems` set) when it did not pass the post."""
    if not os.path.isfile(checker):
        raise Refusal("checker_missing", "checker")
    home = tempfile.mkdtemp(prefix="renderer-checker-")
    try:
        env = {"PATH": os.environ.get("PATH") or os.defpath, "HOME": home, "TMPDIR": home, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
        try:
            done = subprocess.run([sys.executable, "-I", "-E", "-s", checker, "--content", content, "--presets", vocabulary,
                                   "--format", fmt], cwd=home, env=env, capture_output=True, text=True, timeout=timeout,
                                  check=False, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            raise Refusal("checker_failed", "checker") from None
    finally:
        shutil.rmtree(home, ignore_errors=True)
    if done.returncode == 2:
        raise Refusal("script_unreadable", "post")
    try:
        verdict = json.loads(done.stdout)
        problems = verdict["problems"]
    except (ValueError, KeyError, TypeError):
        raise Refusal("checker_failed", "checker") from None
    if done.returncode != 0 or not verdict.get("ok"):
        err = Refusal("script_refused", "post")
        err.problems = [{"beat": p.get("beat"), "field": str(p.get("field"))[:40], "code": str(p.get("code"))[:40]}
                        for p in problems[:50] if isinstance(p, dict)]
        raise err
    return verdict


def script_block(text: str) -> str:
    found, name, buf = [], None, []
    for line in text.split("\n"):
        m = FENCE.match(line.rstrip("\r"))
        if name is None:
            if m and m.group(1) == "script":
                name, buf = "script", []
        elif m and m.group(1) == "":
            found.append("\n".join(buf))
            name = None
        else:
            buf.append(line)
    if name is not None or len(found) != 1:
        raise Refusal("script_block", "post")
    return found[0]


BEAT_KEYS = ("line", "role", "emphasis", "on-screen", "preset")


def read_header(lines: list, vocab: dict) -> dict:
    """The script header: (key, value) lines checked against the vocabulary (a version 2 file): keys from its closed list, each at
    most once, values from the closed lists or bounded hardened text. A version 1 vocabulary has no header: any line is refused."""
    script = script_section(vocab)
    header = {}
    for key, value in lines:
        if script is None or key not in script["header"]["keys"] or key in header:
            raise Refusal("script_header", "post")
        field = "script." + key
        if key in ("title", "send_to"):
            header[key] = clean_text(value, script["limits"]["title_max" if key == "title" else "send_to_max"], field)
        elif value not in script["header"][key]:
            raise Refusal("script_header", field)
        else:
            header[key] = value
    return header


def read_script(text: str, vocab: dict) -> tuple:
    """(header, rows) of an already-checked post. rows: [{beat, line, role, emphasis, preset, params, slots}]; `params` holds the
    values with the main parameter under its own name (never `on-screen`); `slots` maps a slot parameter to its description;
    role and emphasis are None when the beat has none. An unknown key, an undeclared parameter and a value outside a
    closed list are refused."""
    script = script_section(vocab)
    beats, current, header_lines = [], None, []
    header_keys = script["header"]["keys"] if script else ()
    for raw in script_block(text).split("\n"):
        line = raw.rstrip("\r").strip(" ")
        if not line:
            continue
        m = KEY_LINE.match(line)
        if not m:
            raise Refusal("script_line", "post")
        key, value = m.group(1), (m.group(2) or "").strip()
        if key == "beat":
            current = {"beat": len(beats) + 1, "fields": {}}
            beats.append(current)
        elif current is None:
            if key not in header_keys:
                raise Refusal("script_header" if script and key not in BEAT_KEYS else "script_line", "post")
            header_lines.append((key, value))
        else:
            current["fields"][key] = value
    header = read_header(header_lines, vocab)
    rows = []
    for b in beats:
        f = b["fields"]
        name = f.get("preset")
        row = {"beat": b["beat"], "line": clean_text(f.get("line", ""), vocab["limits"]["line_max"], "beat%d.line" % b["beat"]),
               "role": None, "emphasis": None, "preset": name, "params": {}, "slots": {}}
        for key, listed in (("role", "roles"), ("emphasis", "emphasis")):
            if key in f:
                if script is None or f[key] not in script[listed]:
                    raise Refusal("bad_" + key, "beat%d.%s" % (b["beat"], key))
                row[key] = f[key]
        if name:
            if name not in vocab["presets"]:
                raise Refusal("unknown_preset", "beat%d" % b["beat"])
            spec = vocab["presets"][name]
            for key, value in f.items():
                if key in BEAT_KEYS and key != "on-screen":
                    continue
                param = spec["main"] if key == "on-screen" else key
                if param not in spec["params"]:
                    raise Refusal("undeclared_param", "beat%d.%s" % (b["beat"], key))
                if slot_types(spec["params"][param]):
                    row["slots"][param] = clean_text(value, vocab["limits"]["slot_description_max"], "beat%d.%s" % (b["beat"], key))
                else:
                    row["params"][param] = value
        else:
            for key in f:
                if key not in ("line", "role", "emphasis"):
                    raise Refusal("undeclared_param", "beat%d.%s" % (b["beat"], key))
        rows.append(row)
    return header, rows


def read_beats(text: str, vocab: dict) -> list:
    """The beats of an already-checked post (see read_script)."""
    return read_script(text, vocab)[1]


def script_object(header: dict) -> dict:
    """The header's `title` and `loop` for beats.json; the rest of the header stays in the post file. {} when there are none."""
    out = {}
    if "title" in header:
        out["title"] = header["title"]
    if "loop" in header:
        out["loop"] = header["loop"] == "yes"
    return out


def annotate(beats: dict, rows: list, header: dict) -> dict:
    """Writes the role and the emphasis of each beat into beats.json's entries and report items, and the `script` object when the
    header has a title or a loop. Nothing is added for a beat that has neither, so a post without them gives the file it always gave."""
    meta = {r["beat"]: {k: r[k] for k in ("role", "emphasis") if r.get(k)} for r in rows}
    for bucket in ("overlays", "layouts", "report"):
        for item in beats[bucket]:
            item.update(meta.get(item.get("beat"), {}))
    script = script_object(header)
    if script:
        beats["script"] = script
    return beats


# ---------------------------------------------------------------- alignment

def norm_tokens(text: str) -> list:
    """NFKC, casefold, apostrophes dropped, other punctuation to a space; the tokens."""
    t = unicodedata.normalize("NFKC", text).casefold()
    t = re.sub(r"['’]", "", t)
    t = re.sub(r"[^\w\s]|_", " ", t)
    return t.split()


def has_digit(tok: str) -> bool:
    return any(c.isdigit() for c in tok)


_SIM = {}


def token_sim(a: str, b: str) -> float:
    if a == b:
        return 1.0
    key = (a, b)
    if key not in _SIM:
        r = difflib.SequenceMatcher(None, a, b).ratio()
        _SIM[key] = r if (r >= SIM_FLOOR and min(len(a), len(b)) > 3) else 0.0
    return _SIM[key]


def flatten_words(words: list) -> tuple:
    """Live transcript words -> (tokens, the transcript word index of each token)."""
    toks, widx = [], []
    for w in words:
        for t in norm_tokens(w["text"]):
            toks.append(t)
            widx.append(w["index"])
    return toks, widx


def align_line(line: str, flat: tuple, threshold: float = DEFAULT_THRESHOLD) -> dict:
    """Best window of the transcript for one spoken line. Free start and end (approximate substring matching).
    Digit tokens are excluded from the scoring on both sides. A tie goes to the last occurrence."""
    toks, widx = flat
    beat = [t for t in norm_tokens(line) if not has_digit(t)]
    n, m = len(beat), len(toks)
    if n == 0 or m == 0:
        return {"score": 0.0, "word_from": None, "word_to": None, "matched": False}
    wild = [has_digit(t) for t in toks]
    prev = [(0.0, -i) for i in range(m + 1)]     # (cost, -start): lower cost first, then the later start
    for j in range(1, n + 1):
        cur = [(j * DEL_COST, 0)] + [None] * m
        for i in range(1, m + 1):
            cands = []
            if not wild[i - 1]:
                sim = token_sim(beat[j - 1], toks[i - 1])
                c, s = prev[i - 1]
                cands.append((round(c + (1.0 - sim if sim else 1.0), 6), s))
            c, s = prev[i]
            cands.append((round(c + DEL_COST, 6), s))
            c, s = cur[i - 1]
            cands.append((round(c + (0.0 if wild[i - 1] else INS_COST), 6), s))
            cur[i] = min(cands)
        prev = cur
    best_i = min(range(1, m + 1), key=lambda i: (prev[i][0], -i))   # lowest cost, then the last end
    cost, neg_start = prev[best_i]
    start_tok = -neg_start
    score = max(0.0, 1.0 - cost / n)
    if start_tok >= best_i or score <= 0.0:
        return {"score": 0.0, "word_from": None, "word_to": None, "matched": False}
    return {"score": round(score, 4), "word_from": widx[start_tok], "word_to": widx[best_i - 1], "matched": score >= threshold}


def expand_digit_words(words: list, w_from: int, w_to: int) -> tuple:
    """A window grows over the neighbouring live words that hold only figures (they were excluded from scoring)."""
    pos = {w["index"]: k for k, w in enumerate(words)}

    def only_digits(w):
        ts = norm_tokens(w["text"])
        return bool(ts) and all(has_digit(t) for t in ts)

    a, b = pos[w_from], pos[w_to]
    while a > 0 and only_digits(words[a - 1]):
        a -= 1
    while b + 1 < len(words) and only_digits(words[b + 1]):
        b += 1
    return words[a]["index"], words[b]["index"]


def align_beats(words: list, beats: list, threshold: float = DEFAULT_THRESHOLD) -> list:
    """One result per beat of `beats` (each with `line`): score, word range, matched, reordered."""
    flat = flatten_words(words)
    results, last_from = [], -1
    for b in beats:
        r = align_line(b["line"], flat, threshold)
        r["reordered"] = False
        if r["matched"]:
            r["word_from"], r["word_to"] = expand_digit_words(words, r["word_from"], r["word_to"])
            if r["word_from"] < last_from:
                r["reordered"] = True
            last_from = max(last_from, r["word_from"])
        results.append(r)
    return results


def build_beats(rows: list, results: list, vocab: dict, threshold: float, empty_slots: dict) -> dict:
    """beats.json from the checked beats and their alignment. Only indices, preset names, typed parameters and slot ids.

    `empty_slots` maps a slot id to the person's choice for a slot with no file: `keyword` (the beat's label shown as a
    keyword, when it fits) or `none` (caption only)."""
    overlays, layouts, slots, report, fallbacks = [], [], [], [], []
    keyword_max = vocab["presets"].get("keyword", {}).get("params", {}).get("text", {}).get("max", 0)
    for row, res in zip(rows, results):
        beat, preset = row["beat"], row["preset"]
        if preset is None:
            report.append({"beat": beat, "preset": None})
            continue
        params = check_params(vocab, preset, dict(row["params"], **{p: "x" for p in row["slots"]}), "beat%d" % beat)
        for p in row["slots"]:
            params[p] = "beat%d" % beat if len(row["slots"]) == 1 else "beat%d-%s" % (beat, p)
        own_slots = [{"slot": params[p], "beat": beat, "param": p,
                      "type": "|".join(slot_types(vocab["presets"][preset]["params"][p])), "description": desc}
                     for p, desc in row["slots"].items()]
        entry = {"id": "b%d" % beat, "beat": beat, "preset": preset, "params": params, "word_from": res["word_from"],
                 "word_to": res["word_to"], "score": res["score"]}
        item = {"beat": beat, "preset": preset, "score": res["score"], "matched": res["matched"], "reordered": res["reordered"],
                "word_from": res["word_from"], "word_to": res["word_to"]}
        if res.get("anchored"):
            item["anchored"] = True
        choice = None
        for p in row["slots"]:
            choice = empty_slots.get(params[p])
        if choice is not None:
            label = row["params"].get("label")
            if choice == "keyword" and label and len(label) <= keyword_max:
                entry = dict(entry, preset="keyword", params=check_params(vocab, "keyword", {"text": label}, "beat%d" % beat))
                fallbacks.append({"beat": beat, "from": preset, "to": "keyword"})
                item["preset"] = "keyword"
            else:
                fallbacks.append({"beat": beat, "from": preset, "to": "none"})
                item["matched"] = False
                item["fallback"] = "none"
                report.append(item)
                continue
        else:
            slots.extend(own_slots)
        report.append(item)
        if res["matched"]:
            (layouts if vocab["presets"][entry["preset"]]["kind"] == "layout" else overlays).append(entry)
    return {"schema_version": 1, "threshold": threshold, "overlays": overlays, "layouts": layouts, "slots": slots, "report": report,
            "unmatched": [r["beat"] for r in report if r.get("preset") and not r["matched"] and "fallback" not in r],
            "fallbacks": fallbacks}
