"""The renderer slice of the script vocabulary version 2 (short-video P5c-0): a beat's `role` and `emphasis`, the script header,
the optional `script` object of beats.json, the vocabulary file at version 2, and the checker that `align` runs isolated.
Version 1 posts and beats files keep working. Every name and sentence is fictional."""
from __future__ import annotations

import copy
import json

import pytest

import renderer_kit as K
import _align as A
import _edl
import _timeline as T
from _text import Refusal
from _vocab import load_data, load_vocabulary

DATA = load_data()
VOCAB = load_vocabulary(str(K.VOCABULARY))
ALLOW = {"fixture-800": {"id": "fixture-800"}}

HEADER = "hook_type: story\ntitle: quick story about money\ncta_kind: save\nloop: yes\n\n"
ROLES = ["hook", "setup", "point", "point", "proof", "proof", "setup", "payoff", "cta"]


def v2_post():
    """The fixture post of the renderer's tests with a header, a role on every beat and one punch. Beat 5's figure is written as
    digits, as the checker's `number` predicate asks."""
    post = K.POST.replace("```script\n", "```script\n" + HEADER, 1)
    for n, role in enumerate(ROLES, 1):
        post = post.replace("beat: %d\n" % n, "beat: %d\nrole: %s\n" % (n, role) + ("emphasis: punch\n" if n in (3, 7) else ""), 1)
    return post.replace("saved me three hundred forty dollars", "saved me 340 dollars")


def build(post):
    doc = K.build_transcript()
    analysis = {"facts": {"duration": doc["duration"], "sha256": "c" * 64, "width": 1080, "height": 1920, "has_audio": True}, "silences": None}
    edl, _ = _edl.build_base(doc, analysis, DATA, ALLOW)
    header, rows = A.read_script(post, VOCAB)
    with_preset = [r for r in rows if r["preset"]]
    tr = T.check_transcript(doc, DATA["limits"])
    words, _ = T.normalise_words(tr["words"], tr["segments"], tr["duration"])
    beats = A.build_beats(with_preset, A.align_beats([w for w in words if not w["dropped"]], with_preset), VOCAB, 0.6, {})
    beats["report"] = sorted(beats["report"] + [{"beat": r["beat"], "preset": None} for r in rows if not r["preset"]], key=lambda x: x["beat"])
    return edl, A.annotate(beats, rows, header)


def refused(fn, *args):
    with pytest.raises(Refusal) as e:
        fn(*args)
    return e.value


# ---------------------------------------------------------------- reading a script

def test_a_beat_with_a_role_and_an_emphasis_is_read_with_its_header():
    header, rows = A.read_script(v2_post(), VOCAB)
    assert header == {"hook_type": "story", "title": "quick story about money", "cta_kind": "save", "loop": "yes"}
    assert [r["role"] for r in rows] == ROLES
    assert [r["emphasis"] for r in rows] == [None, None, "punch", None, None, None, "punch", None, None]
    assert rows[2]["params"] == {"text": "Name every dollar", "icon": "coin"}          # role and emphasis are not parameters of the preset
    assert [r["preset"] for r in rows] == [None, None, "keyword", "list", "number", "quote", "cutaway", "pip", None]
    assert "role" not in rows[2]["params"] and "emphasis" not in rows[2]["params"]


def test_a_version_1_post_is_read_as_before_with_no_header_and_no_role():
    header, rows = A.read_script(K.POST, VOCAB)
    assert header == {} and all(r["role"] is None and r["emphasis"] is None for r in rows)
    assert A.read_beats(K.POST, VOCAB) == rows


@pytest.mark.parametrize("old, new, code", [
    ("role: setup", "role: intro", "bad_role"),
    ("role: setup", "role: Setup", "bad_role"),
    ("emphasis: punch", "emphasis: loud", "bad_emphasis"),
    ("emphasis: punch", "emphasis: ", "bad_emphasis"),
])
def test_a_value_outside_the_closed_lists_is_refused(old, new, code):
    assert refused(A.read_script, v2_post().replace(old, new, 1), VOCAB).code == code


def test_an_unknown_beat_key_and_an_undeclared_parameter_are_still_refused():
    post = v2_post()
    # a beat with a preset: a key its preset does not declare
    assert refused(A.read_script, post.replace("icon: coin", "icon: coin\nglow: 8", 1), VOCAB).code == "undeclared_param"
    # a beat with no preset: any key but line, role and emphasis
    no_preset = post.replace("line: Last year I tracked every expense for ninety days.", "line: Last year I tracked every expense for ninety days.\nglow: 8", 1)
    assert refused(A.read_script, no_preset, VOCAB).code == "undeclared_param"
    on_screen = post.replace("line: Last year I tracked every expense for ninety days.", "line: Last year I tracked every expense for ninety days.\non-screen: Hi", 1)
    assert refused(A.read_script, on_screen, VOCAB).code == "undeclared_param"
    assert refused(A.read_script, post.replace("preset: keyword", "preset: confetti", 1), VOCAB).code == "unknown_preset"


@pytest.mark.parametrize("edit, code", [
    (lambda p: p.replace("loop: yes\n", "loop: yes\nloop: no\n", 1), "script_header"),                      # repeated
    (lambda p: p.replace("loop: yes\n", "loop: yes\nmood: calm\n", 1), "script_header"),                    # unknown key
    (lambda p: p.replace("loop: yes", "loop: maybe", 1), "script_header"),                                  # outside the list
    (lambda p: p.replace("hook_type: story", "hook_type: shocking", 1), "script_header"),
    (lambda p: p.replace("title: quick story about money", "title: " + "x" * 41, 1), "text_too_long"),
])
def test_a_header_with_an_unknown_or_repeated_key_or_a_bad_value_is_refused(edit, code):
    assert refused(A.read_script, edit(v2_post()), VOCAB).code == code


def test_a_line_before_the_first_beat_that_is_not_a_header_key_is_refused():
    post = v2_post().replace(HEADER, "line: Hello there.\n\n", 1)
    assert refused(A.read_script, post, VOCAB).code == "script_line"
    assert refused(A.read_script, v2_post().replace("title: quick story about money\n", "title quick story\n", 1), VOCAB).code == "script_line"


def test_a_version_1_vocabulary_has_no_header_and_no_role():
    v1 = copy.deepcopy(VOCAB)
    v1["version"] = 1
    del v1["script"]
    assert refused(A.read_script, v2_post(), v1).code == "script_line"
    assert refused(A.read_script, K.POST.replace("beat: 1\n", "beat: 1\nrole: hook\n", 1), v1).code == "bad_role"
    assert A.read_script(K.POST, v1)[1][0]["role"] is None


# ---------------------------------------------------------------- the vocabulary file at version 2

def test_the_vocabulary_loader_accepts_versions_1_and_2_and_refuses_3(tmp_path):
    assert VOCAB["version"] == 2 and VOCAB["script"]["roles"][0] == "hook"
    path = tmp_path / "v.json"
    v1 = copy.deepcopy(VOCAB)
    v1["version"] = 1
    del v1["script"]
    path.write_text(json.dumps(v1), encoding="utf-8")
    assert load_vocabulary(str(path))["version"] == 1
    with_script = copy.deepcopy(VOCAB)
    with_script["version"] = 1
    path.write_text(json.dumps(with_script), encoding="utf-8")
    assert "script" not in load_vocabulary(str(path))                    # a version 1 file is read as version 1, whatever it carries
    v3 = copy.deepcopy(VOCAB)
    v3["version"] = 3
    path.write_text(json.dumps(v3), encoding="utf-8")
    assert refused(load_vocabulary, str(path)).code == "not_a_vocabulary"
    v2 = copy.deepcopy(VOCAB)
    del v2["script"]
    path.write_text(json.dumps(v2), encoding="utf-8")
    assert refused(load_vocabulary, str(path)).code == "not_a_vocabulary"        # version 2 without its script section
    v2 = copy.deepcopy(VOCAB)
    v2["script"]["roles"] = "hook"
    path.write_text(json.dumps(v2), encoding="utf-8")
    assert refused(load_vocabulary, str(path)).code == "not_a_vocabulary"


def test_the_schema_enums_are_the_vocabularys_lists():
    schema = json.loads((K.RENDERER / "edl.schema.json").read_text())["$defs"]
    assert schema["entry"]["properties"]["role"]["enum"] == VOCAB["script"]["roles"]
    assert schema["entry"]["properties"]["emphasis"]["enum"] == VOCAB["script"]["emphasis"]
    assert schema["beats"]["properties"]["report"]["items"]["properties"]["role"]["enum"] == VOCAB["script"]["roles"]
    assert set(schema["entry"]["required"]) == _edl.ENTRY_REQUIRED and set(schema["beats"]["required"]) == _edl.BEATS_REQUIRED
    assert set(schema["entry"]["properties"]) == _edl.ENTRY_KEYS and set(schema["beats"]["properties"]) == _edl.BEATS_KEYS
    assert set(schema["beats"]["properties"]["script"]["properties"]) == _edl.SCRIPT_KEYS
    assert schema["beats"]["properties"]["script"]["additionalProperties"] is False
    assert schema["beats"]["properties"]["schema_version"] == {"const": 1}                # the fields are optional: the beats schema stays version 1


# ---------------------------------------------------------------- beats.json

def test_the_beats_file_carries_roles_emphasis_and_the_script_object_and_passes_its_check():
    edl, beats = build(v2_post())
    assert beats["schema_version"] == 1 and beats["script"] == {"title": "quick story about money", "loop": True}
    by_beat = {e["beat"]: e for e in beats["overlays"] + beats["layouts"]}
    assert by_beat[3]["role"] == "point" and by_beat[3]["emphasis"] == "punch" and by_beat[5]["role"] == "proof" and "emphasis" not in by_beat[5]
    report = {r["beat"]: r for r in beats["report"]}
    assert [report[n]["role"] for n in range(1, 10)] == ROLES                    # also the beats with no preset
    assert report[1] == {"beat": 1, "preset": None, "role": "hook"} and report[3]["emphasis"] == "punch"
    assert _edl.check_beats(beats, edl, VOCAB)["texts"]


def test_a_beats_file_without_the_new_fields_stays_valid():
    edl, beats = build(K.POST)
    assert "script" not in beats
    assert all(set(e) == {"id", "beat", "preset", "params", "word_from", "word_to", "score"} for e in beats["overlays"] + beats["layouts"])
    assert all("role" not in r and "emphasis" not in r for r in beats["report"])
    assert _edl.check_beats(beats, edl, VOCAB)["texts"]


def test_the_script_object_holds_only_the_title_and_the_loop():
    assert A.script_object({"hook_type": "story", "cta_kind": "save", "send_to": "a friend", "pattern": "list"}) == {}
    assert A.script_object({"title": "three words here", "loop": "no"}) == {"title": "three words here", "loop": False}
    assert A.script_object({"loop": "yes"}) == {"loop": True}


def test_the_check_refuses_an_unknown_role_emphasis_or_script_key_and_a_bad_title_or_loop():
    edl, beats = build(v2_post())
    for mutate, code in (
            (lambda b: b["overlays"][0].update(role="boss"), "bad_role"),
            (lambda b: b["overlays"][0].update(emphasis="loud"), "bad_emphasis"),
            (lambda b: b["overlays"][0].update(extra=1), "unknown_key"),
            (lambda b: b["report"][0].update(role="boss"), "bad_role"),
            (lambda b: b["report"][0].update(emphasis="loud"), "bad_emphasis"),
            (lambda b: b["script"].update(extra=1), "unknown_key"),
            (lambda b: b["script"].update(title="x" * 41), "text_too_long"),
            (lambda b: b["script"].update(title="a\u200bb c"), "forbidden_character"),
            (lambda b: b["script"].update(title="ask @someone now"), None),
            (lambda b: b["script"].update(loop="yes"), "bad_loop"),
            (lambda b: b.update(script=[]), "not_object")):
        bad = copy.deepcopy(beats)
        mutate(bad)
        if code is None:
            assert _edl.check_beats(bad, edl, VOCAB)["mentions"]               # a mention in the title is listed with the other texts
            continue
        assert refused(_edl.check_beats, bad, edl, VOCAB).code == code, code
    v1 = copy.deepcopy(VOCAB)
    v1["version"] = 1
    del v1["script"]
    assert refused(_edl.check_beats, beats, edl, v1).code in ("bad_role", "bad_emphasis")
    only_script = copy.deepcopy(build(K.POST)[1])
    only_script["script"] = {"title": "three words here"}
    assert refused(_edl.check_beats, only_script, edl, v1).code == "script_without_vocabulary"


def test_the_required_keys_of_a_beats_file_and_its_entries_are_unchanged():
    edl, beats = build(v2_post())
    bad = copy.deepcopy(beats)
    del bad["unmatched"]
    assert refused(_edl.check_beats, bad, edl, VOCAB).code == "missing_key"
    bad = copy.deepcopy(beats)
    del bad["overlays"][0]["score"]
    assert refused(_edl.check_beats, bad, edl, VOCAB).code == "missing_key"
    ok = copy.deepcopy(beats)
    del ok["script"]
    for e in ok["overlays"] + ok["layouts"]:
        e.pop("role", None), e.pop("emphasis", None)
    assert _edl.check_beats(ok, edl, VOCAB)["texts"]


# ---------------------------------------------------------------- the checker that align runs, isolated

def test_the_checker_align_runs_reads_the_header_and_the_roles(tmp_path):
    post = tmp_path / "post.md"
    post.write_text(v2_post(), encoding="utf-8")
    verdict = A.run_checker(str(K.CHECKER), str(post), str(K.VOCABULARY), "reel")
    assert verdict["ok"] is True and verdict["mode"] == "v2" and verdict["header"]["title"] == "quick story about money"
    assert [b["role"] for b in verdict["beats"]] == ROLES
    bad = tmp_path / "bad.md"
    bad.write_text(v2_post().replace("cta_kind: save\n", ""), encoding="utf-8")
    err = refused(A.run_checker, str(K.CHECKER), str(bad), str(K.VOCABULARY), "reel")
    assert err.code == "script_refused" and any(p["code"] == "missing_header" and p["field"] == "cta_kind" for p in err.problems)
    bad.write_text(v2_post().replace("role: payoff", "role: point"), encoding="utf-8")
    assert any(p["code"] == "no_payoff" for p in refused(A.run_checker, str(K.CHECKER), str(bad), str(K.VOCABULARY), "reel").problems)
    post.write_text(K.POST, encoding="utf-8")
    legacy = A.run_checker(str(K.CHECKER), str(post), str(K.VOCABULARY), "reel")
    assert legacy["ok"] is True and legacy["mode"] == "legacy"                 # the fixture post of version 1 still passes


# ---------------------------------------------------------------- the align verb, end to end

def test_the_align_verb_writes_the_roles_and_the_script_object_into_beats_json(tmp_path):
    post = tmp_path / "post.md"
    post.write_text(v2_post(), encoding="utf-8")
    tr = K.write_json(tmp_path / "t.json", K.build_transcript())
    rc, out, err = K.run_verb("align", "--post", post, "--transcript", tr, "--checker", K.CHECKER, "--vocabulary", K.VOCABULARY, "--out", tmp_path / "b.json")
    assert rc == 0, err
    assert out["unmatched"] == [] and out["overlays"] == 4 and out["layouts"] == 2
    beats = json.loads((tmp_path / "b.json").read_text())
    assert beats["script"] == {"title": "quick story about money", "loop": True}
    assert [r["role"] for r in beats["report"]] == ROLES and beats["report"][2]["emphasis"] == "punch"
    assert {e["id"]: e["role"] for e in beats["overlays"] + beats["layouts"]} == {"b3": "point", "b4": "point", "b5": "proof", "b6": "proof", "b7": "setup", "b8": "payoff"}
    text = json.dumps(beats)
    assert '"hook_type"' not in text and '"cta_kind"' not in text and '"send_to"' not in text      # the rest of the header stays in the post file


def test_a_version_1_post_gives_the_beats_file_it_always_gave(tmp_path):
    post = tmp_path / "post.md"
    post.write_text(K.POST, encoding="utf-8")
    tr = K.write_json(tmp_path / "t.json", K.build_transcript())
    rc, out, err = K.run_verb("align", "--post", post, "--transcript", tr, "--checker", K.CHECKER, "--vocabulary", K.VOCABULARY, "--out", tmp_path / "b.json")
    assert rc == 0, err
    beats = json.loads((tmp_path / "b.json").read_text())
    assert set(beats) == _edl.BEATS_REQUIRED and all("role" not in r and "emphasis" not in r for r in beats["report"])


def test_a_post_the_checker_refuses_stops_the_verb_before_anything_is_written(tmp_path):
    post = tmp_path / "post.md"
    post.write_text(v2_post().replace("role: payoff", "role: point"), encoding="utf-8")
    tr = K.write_json(tmp_path / "t.json", K.build_transcript())
    rc, out, err = K.run_verb("align", "--post", post, "--transcript", tr, "--checker", K.CHECKER, "--vocabulary", K.VOCABULARY, "--out", tmp_path / "b.json")
    assert rc == 1 and err.startswith("refused: script_refused") and "no_payoff" in err and not (tmp_path / "b.json").exists()
