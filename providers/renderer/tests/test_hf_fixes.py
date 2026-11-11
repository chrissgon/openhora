"""V9a-1: the keyword fix (`hf:spring-pop`), the caption-highlight fix (`hf:caption-highlight`) and the gate constants they must leave alone.

Offline. The pure functions of the two ports run in node, extracted from the committed pages (they skip where node is not installed); the
HyperFrames image check reads git. All texts are fictional.
"""
from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import sys

import pytest

import renderer_kit as K
import _gsap_lint
import _hf_gate
from _vocab import load_data

HF_DIR = K.BLOCKS / "hf"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(not NODE, reason="node is not installed")


def script_of(short: str) -> str:
    text = (HF_DIR / short / "gsap.html").read_text(encoding="utf-8")
    return _gsap_lint.parse(text, "hf:" + short)["script"]


def function_of(script: str, name: str) -> str:
    """The source of one top-level function of a build script: from its line to the closing brace at the same indent."""
    found = re.search(r"^( *)function %s\(.*?\n\1}\n" % name, script, re.S | re.M)
    assert found, name
    return found.group(0)


def node_json(program: str, tmp_path, payload) -> list:
    path = tmp_path / "program.js"
    path.write_text(program, encoding="utf-8")
    done = subprocess.run([NODE, str(path), json.dumps(payload)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[:800]
    return json.loads(done.stdout)


FIT_RUN = "const input = JSON.parse(process.argv[2]);\nconsole.log(JSON.stringify(input.map(function (c) { return fit(c[0], c[1]); })));\n"


def fits(tmp_path, cases):
    return node_json(function_of(script_of("spring-pop"), "fit") + "\n" + FIT_RUN, tmp_path, cases)


# ---------------------------------------------------------------- the keyword

@needs_node
def test_fit_gives_the_worked_values(tmp_path):
    out = fits(tmp_path, [["Name every dollar", 492], ["Save money", 492], ["Go", 492]])
    assert out[0]["lines"] == ["Name every", "dollar"] and round(out[0]["size"], 1) == 110.5      # 950 / 8.6, no shrink: 2.93 x 110.5 = 323.7 <= 413.3
    assert out[1]["lines"] == ["Save money"] and round(out[1]["size"], 1) == 110.5
    assert out[2]["lines"] == ["Go"] and out[2]["size"] == 150


@needs_node
def test_fit_splits_at_the_space_nearest_the_middle(tmp_path):
    cases = [["aaaa bbbbbbbbbbbb", 492], ["one two three four", 492], ["aaaaa bbbb cccc", 492], ["Supercalifragilistic", 492], ["Save money", 492], ["twelve chars", 492]]
    out = fits(tmp_path, cases)
    assert out[0]["lines"] == ["aaaa", "bbbbbbbbbbbb"]                         # one space
    assert out[1]["lines"] == ["one two", "three four"]                         # spaces at 3, 7 and 13 of 18: 7 is nearest 9
    assert out[2]["lines"] == ["aaaaa", "bbbb cccc"]                            # spaces at 5 and 10 of 15 are the same distance from 7.5: the lower index
    assert out[3]["lines"] == ["Supercalifragilistic"]                          # no space: one line
    assert out[4]["lines"] == ["Save money"] and out[5]["lines"] == ["twelve chars"]      # 12 characters or fewer: one line


@needs_node
def test_fit_never_exceeds_the_band(tmp_path):
    texts = ["Go", "Save money", "Name every dollar", "Review every single week", "Planning a trip without stress", "abcdefghijklmnopqrstuvwx"]
    cases = [[t, h] for t in texts for h in (80, 120, 200, 320, 492, 640)]
    for (text, band), shape in zip(cases, fits(tmp_path, cases)):
        lines, size = shape["lines"], shape["size"]
        assert " ".join(lines) == text and 1 <= len(lines) <= 2 and size <= 150, (text, band)
        assert (1.1 * len(lines) + 0.73) * size <= band * 0.84 + 1e-9 or size <= 26, (text, band, size)      # it fits, or it is at the floor
        longest = max(len(line) for line in lines)
        assert size * (0.62 * longest + 1.2 + 1.2) <= 950 + 1e-6, (text, band, size)                           # and it fits the 950 px width, floor or not


def test_the_stage_layout_is_set_inline():
    script = script_of("spring-pop")
    for line in ('stage.style.position = "absolute";', 'stage.style.left = "0";', 'stage.style.top = "0";', 'stage.style.width = "100%";',
                 'stage.style.height = "100%";', 'stage.style.display = "flex";', 'stage.style.alignItems = "center";', 'stage.style.justifyContent = "center";'):
        assert line in script, line
    assert 'root.querySelector(".stage")' in script
    assert "fit(P.text, ctx.band.height)" in script
    assert "var FIT = 0.84, FS_MAX = 96" not in script                          # the old one-line sizing is gone


# ---------------------------------------------------------------- the highlight

SPANS_RUN = "const input = JSON.parse(process.argv[2]);\nconsole.log(JSON.stringify(input.map(function (words) { return spans(words); })));\n"


def spans_of(tmp_path, lists):
    return node_json(function_of(script_of("caption-highlight"), "spans") + "\n" + SPANS_RUN, tmp_path, lists)


def seeded_lists(count=200):
    rng = random.Random(9101)
    lists = []
    for _ in range(count):
        words, clock = [], rng.choice([0.0, 0.0, 0.4, -0.2])
        for _ in range(rng.randint(1, 6)):
            start = clock + rng.choice([-0.15, 0.0, 0.0, 0.05, 0.2, 0.5])      # a start that goes back or repeats: a noisy transcript
            end = start + rng.choice([-0.05, 0.0, 0.03, 0.2, 0.4, 0.9])
            words.append({"text": "w", "start": round(start, 3), "end": round(end, 3)})
            clock = start + rng.choice([0.0, 0.1, 0.3])
        lists.append(words)
    return lists


@needs_node
def test_spans_never_overlap(tmp_path):
    lists = seeded_lists()
    for words, spans in zip(lists, spans_of(tmp_path, lists)):
        assert len(spans) == len(words)
        for (s0, e0), (s1, _e1) in zip(spans, spans[1:]):
            assert e0 <= s1 + 1e-12, (words, spans)             # the fade-out of a word ends before the next one starts to light


@needs_node
def test_spans_are_monotone_and_never_negative(tmp_path):
    lists = seeded_lists()
    for words, spans in zip(lists, spans_of(tmp_path, lists)):
        starts = [s for s, _ in spans]
        assert starts == sorted(starts) and all(s >= 0 for s in starts), (words, spans)
        assert all(e >= s for s, e in spans), (words, spans)
        assert starts[0] == max(0, words[0]["start"])


@needs_node
def test_spans_give_the_worked_values(tmp_path):
    words = [{"start": 0.0, "end": 0.4}, {"start": 0.3, "end": 0.9}, {"start": 1.0, "end": 1.02}]
    (spans,) = spans_of(tmp_path, [words])
    assert spans[0] == pytest.approx([0.0, 0.3])          # the second word starts at 0.3: the first ends there, not at 0.4
    assert spans[1] == pytest.approx([0.3, 0.9])
    assert spans[2] == pytest.approx([1.0, 1.1])          # the last word keeps its own end, at least 0.1 s after its start


BUILD_STUB = r"""
let nextId = 0;
function el(cls) {
  const o = {cls: cls, id: nextId++, kids: [], text: "", style: {setProperty() {}}, removed: false};
  o.querySelector = function (sel) { const c = sel.slice(1); if (o.cls === c) return o; for (const k of o.kids) { if (k.cls === c) return k; } const k = el(c); o.kids.push(k); return k; };
  o.cloneNode = function () { return el(o.cls); };
  o.appendChild = function (k) { o.kids.push(k); return k; };
  o.remove = function () { o.removed = true; };
  Object.defineProperty(o, "textContent", {get() { return o.text; }, set(v) { o.text = v; }});
  return o;
}
const calls = [];
const tl = {fromTo(t, a, b, pos) { calls.push({kind: "fromTo", cls: t.cls, id: t.id, pos: pos, dur: b.duration}); }, set(t, v, pos) { calls.push({kind: "set", cls: t.cls, id: t.id, pos: pos}); }, to() {}};
const cases = JSON.parse(process.argv[2]);
const out = cases.map(function (words) {
  calls.length = 0;
  build(el("root"), tl, {words: words, anchor: "bottom", duration: 12}, {fps: 30, duration: 12, band: {top: 1240, height: 320}});
  return calls.slice();
});
console.log(JSON.stringify(out));
"""


def build_calls(tmp_path, lists):
    return node_json(script_of("caption-highlight") + "\n" + BUILD_STUB, tmp_path, lists)


def lit_intervals(calls):
    """For each word's backdrop, the span from its first fade-in to the end of its fade-out."""
    by_id = {}
    for c in calls:
        if c["kind"] == "fromTo" and c["cls"] == "bg":
            by_id.setdefault(c["id"], []).append(c)
    return sorted((v[0]["pos"], v[1]["pos"] + v[1]["dur"]) for v in by_id.values())


@needs_node
def test_at_most_one_word_is_lit_at_any_time(tmp_path):
    lists = seeded_lists()
    for words, calls in zip(lists, build_calls(tmp_path, lists)):
        spans = lit_intervals(calls)
        for (a0, a1), (b0, _b1) in zip(spans, spans[1:]):
            assert a1 <= b0 + 1e-9, (words, spans)


@needs_node
def test_a_zero_length_word_never_lights(tmp_path):
    words = [{"text": "a", "start": 0.0, "end": 0.5}, {"text": "b", "start": 0.5, "end": 0.9}, {"text": "c", "start": 0.5, "end": 1.2}, {"text": "d", "start": 1.3, "end": 1.9}]
    (calls,) = build_calls(tmp_path, [words])
    assert len(lit_intervals(calls)) == 3             # b starts where c does: the span of b is empty, so b gets no tween (c, the later one, lights)
    ids = {c["id"] for c in calls if c["kind"] == "fromTo" and c["cls"] == "bg"}
    assert len(ids) == 3


def test_the_old_finish_line_is_gone():
    text = (HF_DIR / "caption-highlight" / "gsap.html").read_text(encoding="utf-8")
    assert "Math.max(begin + 0.1, w.end)" not in text
    assert "function spans(words)" in text and "spans(words)" in script_of("caption-highlight")


# ---------------------------------------------------------------- what must not move

def test_the_gate_constants_are_unchanged():
    data = load_data()
    assert _hf_gate.PIXEL_MIN_PSNR_DB == 30.0
    assert _hf_gate.ZONES == ("card", "caption")
    zones = data["zones"]
    assert (zones["card_top"], zones["gap"], zones["caption_bottom"], zones["card_min_height"], zones["caption_min_height"]) == (110, 18, 1560, 80, 120)
    assert data["face_box_default"] == {"x": 240, "y": 620, "w": 600, "h": 560}


def test_the_hyperframes_image_files_are_unchanged():
    """V9a draws on the HyperFrames image as it is: the tag, the hash of the files its manifest lists, is the one the folder gave at 7ba825b.
    A package that changes the image updates this pin (and says so in its decision file)."""
    sys.path.insert(0, str(K.RENDERER / "hyperframes-image"))
    import hf_image
    assert hf_image.image_tag(str(K.RENDERER / "hyperframes-image")) == "openhora-hyperframes:e5f2134dd1b8"
