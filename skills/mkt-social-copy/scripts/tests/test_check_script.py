"""Offline tests of skills/mkt-social-copy/scripts/check_script.py: the ```script block against the preset
vocabulary, the closed codes it prints, and the equality of the vocabulary's two files. Every name is fictional."""
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
SCRIPT = REPO / "skills/mkt-social-copy/scripts/check_script.py"
PRESETS = REPO / "shared/references/video-presets.json"
PRESETS_MD = REPO / "shared/references/video-presets.md"

spec = importlib.util.spec_from_file_location("check_script_under_test", SCRIPT)
check_script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_script)

GOOD = """beat: 1
line: Name every euro before the month starts.
on-screen: Name every euro
preset: keyword
icon: coin

beat: 2
line: Then do three things each week: review, adjust, celebrate.
on-screen: Review | Adjust | Celebrate
preset: list
icon: check

beat: 3
line: That habit saved me 340 euros in one month.
on-screen: saved in one month
preset: number
value: 340

beat: 4
line: A friend told me small steps beat big plans.
on-screen: Small steps beat big plans.
preset: quote
author: Ana Souza

beat: 5
line: Here is what my dashboard looked like.
on-screen: My dashboard
preset: cutaway
asset: a screenshot of the budgeting dashboard
fit: contain

beat: 6
line: Watch the chart while I walk you through it.
preset: pip
asset: a bar chart of weekly savings
position: bottom

beat: 7
line: That is the whole method.
"""


def content(script, post="Three habits.\n#budget"):
    return f"# Post: demo\n\n- Network: instagram\n\n## Script\n\n```script\n{script}```\n\n## Post\n\n```post\n{post}\n```\n"


@pytest.fixture()
def run(tmp_path):
    def go(script=None, text=None, presets=PRESETS):
        path = tmp_path / "post.md"
        path.write_text(text if text is not None else content(script), encoding="utf-8")
        r = subprocess.run([sys.executable, str(SCRIPT), "--content", str(path), "--presets", str(presets)],
                           capture_output=True, text=True, timeout=60)
        return r, (json.loads(r.stdout) if r.stdout.strip() else None)
    return go


def codes(out):
    return sorted((p["beat"], p["field"], p["code"]) for p in out["problems"])


def test_help_exits_0_and_names_the_flags():
    r = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "--presets" in r.stdout and "--content" in r.stdout


def test_a_script_using_every_preset_passes_and_lists_its_slots(run):
    r, out = run(GOOD)
    assert r.returncode == 0 and out["ok"] is True and out["problems"] == [], r.stdout
    assert [b["preset"] for b in out["beats"]] == ["keyword", "list", "number", "quote", "cutaway", "pip", None]
    assert out["beats"][1]["on_screen"] == "Review | Adjust | Celebrate"
    assert out["beats"][2]["on_screen"] == "saved in one month"
    assert out["slots"] == [
        {"beat": 5, "param": "asset", "type": "image|clip", "description": "a screenshot of the budgeting dashboard"},
        {"beat": 6, "param": "asset", "type": "image|clip", "description": "a bar chart of weekly savings"}]


def test_a_post_file_with_a_script_block_still_gives_check_post_its_post_block():
    spec = importlib.util.spec_from_file_location("cp", REPO / "skills/mkt-social-copy/scripts/check_post.py")
    cp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cp)
    assert cp.blocks(content(GOOD)) == {"post": "Three habits.\n#budget"}


@pytest.mark.parametrize("edit, expected", [
    ("preset: keyword", "preset: sparkle"),
])
def test_an_unknown_preset_is_refused(run, edit, expected):
    r, out = run(GOOD.replace(edit, expected, 1))
    assert r.returncode == 1 and (1, "preset", "unknown_preset") in codes(out)


def test_only_declared_parameters_are_allowed(run):
    r, out = run(GOOD.replace("icon: coin", "icon: coin\nglow: 8", 1))
    assert (1, "glow", "undeclared_parameter") in codes(out) and r.returncode == 1
    r, out = run(GOOD.replace("preset: keyword", "preset: keyword\ntransition: zoom", 1))
    assert (1, "transition", "undeclared_parameter") in codes(out)
    r, out = run("beat: 1\nline: Hello there.\nicon: coin\n")
    assert (1, "icon", "parameter_without_preset") in codes(out)


def test_the_main_text_is_written_once_in_on_screen(run):
    r, out = run(GOOD.replace("icon: coin", "icon: coin\ntext: Name every euro", 1))
    assert (1, "text", "main_parameter_written_twice") in codes(out)
    r, out = run(GOOD.replace("on-screen: Name every euro\n", "", 1))
    assert (1, "on-screen", "missing_parameter") in codes(out)
    r, out = run("beat: 1\nline: Hello there.\non-screen: Hello\n")
    assert (1, "on-screen", "on_screen_without_preset") in codes(out)


def test_a_required_parameter_must_be_present(run):
    r, out = run(GOOD.replace("value: 340\n", "", 1))
    assert (3, "value", "missing_parameter") in codes(out)
    r, out = run(GOOD.replace("asset: a bar chart of weekly savings\n", "", 1))
    assert (6, "asset", "missing_parameter") in codes(out)


@pytest.mark.parametrize("old, new, field, code", [
    ("on-screen: Name every euro", "on-screen: " + "x" * 25, "on-screen", "text_too_long"),
    ("on-screen: Review | Adjust | Celebrate", "on-screen: a | b | c | d | e", "on-screen", "too_many_items"),
    ("on-screen: Review | Adjust | Celebrate", "on-screen: a | | c", "on-screen", "empty_item"),
    ("on-screen: Review | Adjust | Celebrate", "on-screen: Review | " + "y" * 31, "on-screen", "text_too_long"),
    ("icon: coin", "icon: rocket", "icon", "bad_value"),
    ("icon: check", "icon: Check", "icon", "bad_value"),
    ("value: 340", "value: 3 40", "value", "bad_pattern"),
    ("value: 340", "value: $340", "value", "bad_pattern"),
    ("value: 340", "value: " + "9" * 11, "value", "text_too_long"),
    ("fit: contain", "fit: stretch", "fit", "bad_value"),
    ("position: bottom", "position: top-right", "position", "bad_value"),
    ("author: Ana Souza", "author: " + "z" * 41, "author", "text_too_long"),
])
def test_values_outside_their_type_and_bounds_are_refused(run, old, new, field, code):
    assert old in GOOD
    r, out = run(GOOD.replace(old, new, 1))
    assert r.returncode == 1 and any(p["field"] == field and p["code"] == code for p in out["problems"]), out


def test_a_colour_is_a_palette_token_never_a_free_value(run):
    ok = GOOD.replace("icon: coin", "icon: coin\ncolor: accent", 1)
    assert run(ok)[1]["ok"] is True
    for free in ("#ff00ff", "neon pink", "rgb(1,2,3)", "var(--x)"):
        r, out = run(GOOD.replace("icon: coin", f"icon: coin\ncolor: {free}", 1))
        assert (1, "color", "bad_value") in codes(out), free


@pytest.mark.parametrize("description, code", [
    ("", "slot_description_missing"),
    ("ab", "slot_description_missing"),
    ("x" * 81, "slot_description_too_long"),
    ("assets/dashboard.png", "slot_path"),
    ("C:\\Users\\me\\chart", "slot_path"),
    ("~/Downloads/chart", "slot_path"),
    ("the dashboard.png", "slot_path"),
    ("a screen recording, clip.mov", "slot_path"),
    ("https://shots.example/chart", "slot_path"),
    ("see shots.example", "slot_link"),
    ("www.chart.org", "slot_link"),
    ("file:dashboard", "slot_link"),
    ("the first 5 seconds of my demo", "time_value"),
    ("the demo from 0:12", "time_value"),
    ("a 30-second screen recording", "time_value"),
    ("the clip, first five seconds", "time_value"),
])
def test_a_slot_description_holds_words_only(run, description, code):
    r, out = run(GOOD.replace("asset: a screenshot of the budgeting dashboard", f"asset: {description}", 1))
    assert r.returncode == 1 and any(p["field"] == "asset" and p["code"] == code for p in out["problems"]), out


@pytest.mark.parametrize("field", ["start", "end", "at", "time", "duration", "delay", "timestamp", "in", "out"])
def test_a_field_that_carries_a_time_is_refused(run, field):
    r, out = run(GOOD.replace("icon: coin", f"icon: coin\n{field}: 5", 1))
    assert (1, field, "time_field") in codes(out) and r.returncode == 1


@pytest.mark.parametrize("line", ["At 0:12 I show the chart.", "From 3-8 seconds I explain.", "Then (5s) the number.",
                                  "[2 sec] the number appears"])
def test_a_timestamp_or_range_in_a_text_is_refused(run, line):
    r, out = run(GOOD.replace("line: That is the whole method.", f"line: {line}", 1))
    assert (7, "line", "time_value") in codes(out), out
    r, out = run(GOOD.replace("on-screen: Name every euro", f"on-screen: {line[:24]}", 1))
    assert any(p["field"] == "on-screen" and p["code"] == "time_value" for p in out["problems"]), out


def test_a_spoken_duration_that_is_content_is_not_a_time_value(run):
    r, out = run(GOOD.replace("line: That is the whole method.", "line: It took me 10 minutes and 3 tries.", 1))
    assert r.returncode == 0, out


@pytest.mark.parametrize("bad, code", [
    ("tab\there", "forbidden_character"),
    ("bidi \u202e override", "forbidden_character"),
    ("zero\u200bwidth", "forbidden_character"),
    ("line\u2028sep", "forbidden_character"),
    ("para\u2029sep", "forbidden_character"),
    ("bell\x07", "forbidden_character"),
])
def test_control_and_format_characters_are_refused_and_never_echoed(run, bad, code):
    r, out = run(GOOD.replace("line: That is the whole method.", f"line: {bad}", 1))
    assert r.returncode == 1 and out["ok"] is False and code in {p["code"] for p in out["problems"]}
    for fragment in ("override", "width", "sep", "here"):
        assert fragment not in r.stdout


def test_text_must_be_in_nfc_form(run):
    decomposed = "cafe\u0301"
    r, out = run(GOOD.replace("line: That is the whole method.", f"line: {decomposed}", 1))
    assert (7, "line", "not_nfc") in codes(out)
    r, out = run(GOOD.replace("line: That is the whole method.", "line: caf\u00e9", 1))
    assert r.returncode == 0


def test_a_refused_text_is_never_echoed(run):
    marker = "ZZ-MARKER-TEXT"
    r, out = run(GOOD.replace("on-screen: Name every euro", f"on-screen: {marker} " + "x" * 30, 1))
    assert out["ok"] is False and marker not in r.stdout
    r, out = run(GOOD.replace("asset: a screenshot of the budgeting dashboard", f"asset: {marker}/a.png", 1))
    assert out["ok"] is False and marker not in r.stdout


def test_beat_structure(run):
    r, out = run(GOOD.replace("beat: 2", "beat: 5", 1))
    assert (2, "beat", "beat_number") in codes(out)
    r, out = run("line: before any beat\nbeat: 1\nline: Hello.\n")
    assert (None, "line", "field_before_first_beat") in codes(out)
    r, out = run("beat: 1\nline: Hello.\nline: Again.\n")
    assert (1, "line", "duplicate_field") in codes(out)
    r, out = run("beat: 1\npreset: keyword\non-screen: Hi\n")
    assert (1, "line", "missing_line") in codes(out)
    r, out = run("beat: 1\nthis is not a field\n")
    assert any(p["code"] == "bad_line" for p in out["problems"])
    r, out = run("beat: 1\nline:Hello\n")
    assert any(p["code"] == "bad_line" for p in out["problems"])
    r, out = run("\n\n")
    assert (None, "beat", "no_beats") in codes(out)


def test_the_number_of_beats_and_the_length_of_a_line_are_bounded(run):
    many = "".join(f"beat: {i}\nline: Point {i}.\n\n" for i in range(1, 14))
    r, out = run(many)
    assert (None, "beat", "too_many_beats") in codes(out)
    r, out = run("beat: 1\nline: " + "w" * 241 + "\n")
    assert (1, "line", "text_too_long") in codes(out)


def test_a_missing_or_broken_block_or_file_is_a_usage_error(run, tmp_path):
    for text, message in (("# Post\n\nno block\n", "no ```script block"),
                          (content(GOOD) + "\n```script\nbeat: 1\nline: Again.\n```\n", "more than one"),
                          ("```script\nbeat: 1\nline: never closed\n", "is not closed")):
        r, out = run(text=text)
        assert r.returncode == 2 and message in r.stderr and not r.stdout.strip() and "Traceback" not in r.stderr
    r = subprocess.run([sys.executable, str(SCRIPT), "--content", str(tmp_path / "absent.md"), "--presets", str(PRESETS)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and "Traceback" not in r.stderr
    (tmp_path / "bytes.md").write_bytes(b"\xff\xfe```script\n```\n")
    r = subprocess.run([sys.executable, str(SCRIPT), "--content", str(tmp_path / "bytes.md"), "--presets", str(PRESETS)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and "Traceback" not in r.stderr


def test_a_bad_vocabulary_file_is_a_usage_error(run, tmp_path):
    for body in ("not json", '{"version": 2}', '{"version": 1, "presets": {}}', "[]"):
        bad = tmp_path / "bad.json"
        bad.write_text(body, encoding="utf-8")
        r, out = run(GOOD, presets=bad)
        assert r.returncode == 2 and "not a preset vocabulary" in r.stderr and "Traceback" not in r.stderr
    r, out = run(GOOD, presets=tmp_path / "absent.json")
    assert r.returncode == 2


def test_the_checker_reads_the_vocabulary_it_is_given(run, tmp_path):
    vocab = json.loads(PRESETS.read_text(encoding="utf-8"))
    vocab["presets"]["keyword"]["params"]["text"]["max"] = 5
    other = tmp_path / "small.json"
    other.write_text(json.dumps(vocab), encoding="utf-8")
    r, out = run(GOOD, presets=other)
    assert (1, "on-screen", "text_too_long") in codes(out)


# The vocabulary is one source in two files: the prose a model reads and the data a program reads.

def vocabulary():
    return json.loads(PRESETS.read_text(encoding="utf-8"))


def section(md, name):
    m = re.search(rf"^### {re.escape(name)}\n(.*?)(?=^### |^## |\Z)", md, re.S | re.M)
    assert m, f"video-presets.md has no section for {name}"
    return m.group(1)


def test_the_prose_names_every_preset_and_every_parameter_of_the_data():
    md, vocab = PRESETS_MD.read_text(encoding="utf-8"), vocabulary()
    for name, preset in vocab["presets"].items():
        body = section(md, name)
        assert f"**Main:** `{preset['main']}`" in body, name
        for param, pspec in preset["params"].items():
            row = next((ln for ln in body.splitlines() if ln.startswith(f"| `{param}` |")), None)
            assert row, f"{name}.{param} has no row in video-presets.md"
            cells = [c.strip() for c in row.strip("|").split("|")]
            assert (cells[3] == "yes") == bool(pspec.get("required")), f"{name}.{param} required"
            if "max" in pspec:
                assert f"up to {pspec['max']} characters" in row, f"{name}.{param} max"
            for value in pspec.get("values", []):
                assert f"`{value}`" in row, f"{name}.{param} value {value}"
    section_names = set(re.findall(r"^### (\w+)\n", md, re.M))
    assert section_names == set(vocab["presets"]), "a preset section is missing from the data, or the reverse"


def test_the_prose_lists_the_icons_palette_types_and_limits_of_the_data():
    md, vocab = PRESETS_MD.read_text(encoding="utf-8"), vocabulary()
    assert "one of: " + ", ".join(vocab["icons"]) in md
    assert "one of: " + ", ".join(vocab["palette"]) in md
    for kind in vocab["types"]:
        assert f"| `{kind}` |" in md, kind
    assert f"at most {vocab['limits']['beats_max']} beats" in md
    assert f"spoken line of at most {vocab['limits']['line_max']} characters" in md
    lim = vocab["limits"]
    assert f"{lim['slot_description_min']} to {lim['slot_description_max']} characters" in md
    for name in vocab["always_on"]:
        assert f"`{name}` is not a preset" in md


def test_every_preset_declares_what_the_checker_needs():
    vocab = vocabulary()
    kinds = set(vocab["types"])
    for name, preset in vocab["presets"].items():
        assert preset["kind"] in ("overlay", "layout") and preset["summary"]
        assert preset["main"] in preset["params"]
        for param, pspec in preset["params"].items():
            used = pspec["type"] if isinstance(pspec["type"], list) else [pspec["type"]]
            assert set(used) <= kinds, f"{name}.{param}"
            if pspec["type"] == "text":
                assert pspec["max"] > 0
            if pspec["type"] == "choice":
                assert pspec["values"] and pspec.get("default", pspec["values"][0]) in pspec["values"]
            if "pattern" in pspec:
                re.compile(pspec["pattern"])
