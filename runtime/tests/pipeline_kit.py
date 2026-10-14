"""Fictional fixtures and stand-in providers for the tests of the media pipeline (runtime/pipeline.py, runtime/captions.py). Not a
test file. Everything is invented: the speaker, the sentences (Brazilian Portuguese as it is spoken: "pra", "tá", "a gente"), the
figures, the recording (a few bytes, never a video).

The stand-in providers sit in the tree the operations layer is pointed at (`providers/transcriber/standin.py` and
`providers/renderer/standin.py`) and are resolved by providers/resolve.py like the real ones. The renderer's stand-in runs the REAL
`base`, `align` and `check` of providers/renderer/_inner.py (they need no container, no ffmpeg and no browser), so the retakes, the
re-timed words, the alignment and the anchors the tests see are the renderer's own; only `analyse`, `render` and `cover` are made
up, and the transcriber's `transcribe` returns the fixture's transcript. Each stand-in logs its argv to calls.jsonl beside it, and
fails when `fail.json` says so: {"<verb>": {"skip": n calls first, "times": n, "exit": code, "stderr": text}}.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import standin_tree as st

REPO = st.REPO
INNER = REPO / "providers" / "renderer" / "_inner.py"

# (the pause before the sentence in seconds, the sentence). The fourth is said twice: the first take stops short, the second is whole.
SENTENCES = [
    (1.2, "Oi gente, tá bom? Hoje eu vou contar uma história rápida sobre dinheiro."),
    (0.9, "Ano passado a gente anotou cada gasto durante noventa dias."),
    (1.0, "A primeira regra é simples: dá um nome pra cada real."),
    (0.8, "Depois faz três coisas toda semana."),
    (1.0, "Depois faz três coisas toda semana: revisar, ajustar e comemorar."),
    (0.9, "Esse hábito me poupou trezentos e quarenta reais num mês só."),
    (1.0, "Uma amiga sábia me disse: passos pequenos vencem planos grandes."),
    (0.9, "Olha só como ficou o meu painel."),
    (1.0, "Segue a gente pra mais passos pequenos."),
]
TAIL = 1.2

POST_SLOT = """# Post: Três hábitos com o dinheiro (a fictional fixture)

- Owner: mkt-social-copy
- Status: draft
- Network: instagram
- Format: reel

## Script

```script
beat: 1
line: Oi gente, tá bom? Hoje eu vou contar uma história rápida sobre dinheiro.

beat: 2
line: Ano passado a gente anotou cada gasto durante noventa dias.

beat: 3
line: A primeira regra é simples: dá um nome pra cada real.
on-screen: Um nome pra cada real
preset: keyword
icon: coin

beat: 4
line: Depois faz três coisas toda semana: revisar, ajustar e comemorar.
on-screen: Revisar | Ajustar | Comemorar
preset: list
icon: check

beat: 5
line: Esse hábito me poupou trezentos e quarenta reais num mês só.
on-screen: reais poupados em um mês
preset: number
value: 340

beat: 6
line: Uma amiga sábia me disse: passos pequenos vencem planos grandes.
on-screen: Passos pequenos vencem planos grandes.
preset: quote
author: Uma amiga sábia

beat: 7
line: Olha só como ficou o meu painel.
on-screen: Meu painel
preset: cutaway
asset: a screenshot of the budgeting dashboard
fit: cover

beat: 8
line: Segue a gente pra mais passos pequenos.
```

## Post

```post
Três hábitos com o dinheiro. Qual você começa hoje?

#dinheiro #habitos
```
"""
# The same post with no asset slot: beat 7 is a keyword. Most tests use this one; the slot tests use POST_SLOT.
POST = POST_SLOT.replace("""on-screen: Meu painel
preset: cutaway
asset: a screenshot of the budgeting dashboard
fit: cover""", """on-screen: Meu painel
preset: keyword
icon: coin""")
assert POST != POST_SLOT
POST_PATH = "docs/marketing/content/2027-01-10-tres-habitos.md"


def facts_block(language="pt", timestamps="dtw") -> dict:
    return {"provider": "fixture", "whisper_cpp_tag": "v0", "whisper_cpp_commit": "0" * 40, "image_id": "sha256:fixture",
            "cpu_arch": "arm64", "cpu_flags": "none", "model": {"name": "small", "file": "ggml-small.bin", "sha256": "0" * 64},
            "timestamps": timestamps, "flags": [], "language_requested": language, "language_detected": language,
            "segment_unit": "sentence", "input_duration": 0.0, "wall_seconds": 0.0, "words_without_timing": 0, "clamped_words": 0,
            "dropped_annotations": 0}


def build_transcript(sentences=SENTENCES, tail=TAIL, misplace=True, unplace_last=False):
    """(transcript, silences): a transcript in the transcriber's format, one segment per sentence, and the silences between them.
    With `misplace` the first two words are timed inside the leading silence, as a transcriber does with an opening hook, so that
    the renderer's own base list re-times them. With `unplace_last` the last word is timed inside the silence that follows the
    previous word, with no room before it and none after: the renderer finds no voiced span for it and leaves it out."""
    words, segments, t = [], [], 0.0
    for seg, (pause, sentence) in enumerate(sentences):
        t += pause
        first, seg_start = len(words), t
        for tok in sentence.split():
            dur = round(0.10 + 0.045 * sum(ch.isalpha() for ch in tok), 3)
            words.append({"index": len(words), "text": tok, "start": round(t, 3), "end": round(t + dur, 3), "segment": seg})
            t += dur + 0.07
            if tok.endswith(","):
                t += 0.15
            if tok.endswith(":"):
                t += 0.75
        segments.append({"index": seg, "start": round(seg_start, 3), "end": words[-1]["end"], "text": sentence, "first_word": first,
                         "last_word": len(words) - 1})
    duration = round(words[-1]["end"] + tail, 3)
    silences, cursor = [], 0.0
    for w in words:
        if w["start"] - cursor >= 0.25:
            silences.append({"start": round(cursor, 3), "end": round(w["start"], 3)})
        cursor = w["end"]
    if duration - cursor >= 0.25:
        silences.append({"start": round(cursor, 3), "end": duration})
    if misplace:
        for i, (a, b) in enumerate(((0.20, 0.45), (0.50, 0.85))):
            words[i]["start"], words[i]["end"] = a, b
    if unplace_last:
        before, last = words[-2], words[-1]
        last["start"], last["end"] = round(before["end"] + 0.2, 3), round(before["end"] + 0.55, 3)
        silences = [s for s in silences if s["start"] < before["end"] - 0.01] + [{"start": before["end"], "end": duration}]
    return {"schema_version": 1, "language": "pt", "duration": duration, "words": words, "segments": segments, "facts": facts_block()}, silences


# --- the stand-in providers -----------------------------------------------------------------------------------------------------

HEADER = '''#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
import hashlib, json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
INNER = %(inner)r
argv = sys.argv[1:]
with open(os.path.join(HERE, "calls.jsonl"), "a") as log:
    log.write(json.dumps(argv) + "\\n")
verb = argv[0] if argv else ""


def injected():
    """The failure the test asked for on this call of this verb, or None."""
    path = os.path.join(HERE, "fail.json")
    if not os.path.exists(path):
        return None
    plan = json.load(open(path))
    rule = plan.get(verb)
    if not rule:
        return None
    seen = plan.setdefault("_seen", {})
    seen[verb] = seen.get(verb, 0) + 1
    hit = rule.get("skip", 0) < seen[verb] <= rule.get("skip", 0) + rule.get("times", 1)
    json.dump(plan, open(path, "w"))
    return rule if hit else None


def arg(flag, default=None):
    return argv[argv.index(flag) + 1] if flag in argv else default


rule = injected()
if rule:
    print(rule["stderr"], file=sys.stderr)
    sys.exit(rule["exit"])
'''

TRANSCRIBER = HEADER + '''
if verb in ("build", "models", "fetch-model", "pin-browser"):
    print("a setup verb was called: that is the person's command, never a pipeline's", file=sys.stderr)
    sys.exit(2)
if verb != "transcribe":
    print(json.dumps({"ok": True}))
    sys.exit(0)
doc = json.load(open(os.path.join(HERE, "transcript-source.json")))
doc["facts"]["timestamps"] = arg("--timestamps")
doc["facts"]["language_requested"] = arg("--language")
out = arg("--out")
with open(out, "w") as f:
    json.dump(doc, f)
os.chmod(out, 0o600)
print(json.dumps({"out": out, "language": doc["language"], "duration": doc["duration"], "words": len(doc["words"]),
                  "segments": len(doc["segments"]), "wall_seconds": 1.5, "image_id": "sha256:fixture", "model": arg("--model"),
                  "timestamps": arg("--timestamps")}))
'''

RENDERER = HEADER + '''
MP4_HEAD = b"\\x00\\x00\\x00\\x18ftypisom\\x00\\x00\\x02\\x00isomiso2fictional mp4 "
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000001e221bc330000000049454e44ae426082")
if verb in ("build", "pin-browser", "pin-templates", "reap"):
    print("a setup verb was called: that is the person's command, never a pipeline's", file=sys.stderr)
    sys.exit(2)
if verb == "analyse":
    data = open(arg("--in"), "rb").read()
    doc = json.load(open(os.path.join(HERE, "analysis-source.json")))
    doc["facts"]["sha256"] = hashlib.sha256(data).hexdigest()
    with open(arg("--out"), "w") as f:
        json.dump(doc, f)
    os.chmod(arg("--out"), 0o600)
    print(json.dumps({"ok": True, "out": arg("--out"), "duration": doc["facts"]["duration"], "sha256": doc["facts"]["sha256"],
                      "silences": len(doc["silences"]), "has_audio": True}))
elif verb in ("base", "align", "check"):
    done = subprocess.run([sys.executable, INNER] + argv, capture_output=True, text=True)
    sys.stdout.write(done.stdout)
    sys.stderr.write(done.stderr)
    sys.exit(done.returncode)
elif verb == "render":
    edl = json.load(open(arg("--edl")))
    body = open(arg("--edl"), "rb").read() + open(arg("--beats"), "rb").read()
    digest = hashlib.sha256(MP4_HEAD + body).hexdigest()
    folder = arg("--out")
    path = os.path.join(folder, "render-%%s.mp4" %% digest[:12])
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(MP4_HEAD + body)
        os.chmod(path, 0o400)
    print(json.dumps({"ok": True, "path": path, "sha256": hashlib.sha256(open(path, "rb").read()).hexdigest(), "bytes": os.path.getsize(path),
                      "seconds": round(edl["out_frames"] / edl["fps"], 3),
                      "output": {"duration": round(edl["out_frames"] / edl["fps"], 3), "width": 1080, "height": 1920, "fps": 30, "codec": "h264", "audio_codec": "aac", "bytes": os.path.getsize(path)}, "unmatched_beats": [], "fonts": {"caption": "inter"},
                      "browser": "fixture", "browser_sandbox": "off", "image": {"id": "sha256:renderer", "tag": "fixture"}, "verified": True,
                      "replayed": False}))
elif verb == "cover":
    with open(arg("--out"), "wb") as f:
        f.write(PNG)
    print(json.dumps({"ok": True, "path": arg("--out")}))
else:
    print(json.dumps({"ok": True}))
'''


def stand_in_providers(tree: Path, transcript: dict, silences: list, raw_sha: str = "0" * 64) -> dict:
    """Write the stand-in providers, the files they read, and what the pipeline reads from the checkout, into the tree."""
    paths = {}
    for role, text in (("transcriber", TRANSCRIBER), ("renderer", RENDERER)):
        folder = tree / "providers" / role
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "standin.py").write_text(text % {"inner": str(INNER)} if "%(inner)r" in text else text, encoding="utf-8")
        paths[role] = folder
    (paths["transcriber"] / "transcript-source.json").write_text(json.dumps(transcript), encoding="utf-8")
    analysis = {"schema_version": 1, "noise_db": -35, "min_silence": 0.25, "silences": silences,
                "facts": {"duration": transcript["duration"], "width": 1080, "height": 1920, "fps": 30.0, "has_audio": True,
                          "sha256": raw_sha, "color_space": "bt709", "video_codec": "h264", "audio_codec": "aac"}}
    (paths["renderer"] / "analysis-source.json").write_text(json.dumps(analysis), encoding="utf-8")
    for rel in ("shared/references/video-presets.json", "shared/references/platforms/instagram.json", "shared/references/platforms/tiktok.json",
                "skills/mkt-social-copy/scripts/check_script.py"):
        target = tree / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / rel, target)
    return paths


def calls(tree: Path, role: str) -> list:
    path = tree / "providers" / role / "calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []


def verbs(tree: Path, role: str) -> list:
    return [c[0] if c else "" for c in calls(tree, role)]


def fail(tree: Path, role: str, verb: str, *, exit=1, stderr="refused: browser_failed render", times=1, skip=0) -> None:
    """The next call of `verb` (after `skip` calls) fails `times` times, as a provider does: its stderr and its exit code."""
    path = tree / "providers" / role / "fail.json"
    plan = json.loads(path.read_text()) if path.is_file() else {}
    plan[verb] = {"exit": exit, "stderr": stderr, "times": times, "skip": skip}
    plan.pop("_seen", None)
    path.write_text(json.dumps(plan))


def heal(tree: Path, role: str) -> None:
    path = tree / "providers" / role / "fail.json"
    if path.is_file():
        path.unlink()


def make_recording(data_dir: str, media, *, posts=None) -> dict:
    """A recording id with a raw file the store accepts as its own, made without ffprobe (the intake is tested elsewhere)."""
    record = media.create(data_dir, posts=posts)
    folder = media.folder_of(data_dir, record["id"])
    payload = b"fictional recording bytes " * 40
    with open(os.path.join(folder, "raw.mov"), "wb") as f:
        f.write(payload)
    os.chmod(os.path.join(folder, "raw.mov"), 0o600)
    info = {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "type": "mov", "name": "clip.mov", "uploaded_at": media.stamp(),
            "duration": 30.0, "width": 1080, "height": 1920, "fps": 30.0, "file": "raw.mov"}
    return media.update(data_dir, record["id"], lambda r: r.update(raw=info))
