"""`check`: the schema, the bounds, the text hardening, colours, fonts, credential shapes and mentions."""
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
INSTAGRAM = json.loads(K.INSTAGRAM.read_text())
ALLOW = {"fixture-800": {"id": "fixture-800"}}


def make(post=K.POST, transcript=None):
    doc = transcript or K.build_transcript()
    analysis = {"facts": {"duration": doc["duration"], "sha256": "c" * 64, "width": 1080, "height": 1920, "has_audio": True}, "silences": None}
    edl, _ = _edl.build_base(doc, analysis, DATA, ALLOW)
    rows = [r for r in A.read_beats(post, VOCAB) if r["preset"]]
    tr = T.check_transcript(doc, DATA["limits"])
    words, _ = T.normalise_words(tr["words"], tr["segments"], tr["duration"])
    beats = A.build_beats(rows, A.align_beats([w for w in words if not w["dropped"]], rows), VOCAB, 0.6, {})
    return edl, beats


def check(edl, beats, platform=None):
    first = _edl.check_edl(edl, DATA, VOCAB, ALLOW, platform)
    second = _edl.check_beats(beats, edl, VOCAB)
    return first, second


def code(edl, beats, platform=None):
    with pytest.raises(Refusal) as e:
        check(edl, beats, platform)
    return e.value


def test_the_lists_code_builds_pass_their_own_check():
    edl, beats = make()
    first, second = check(edl, beats, INSTAGRAM)
    assert first["mentions"] == [] and second["texts"]


def test_every_object_is_closed_and_every_key_is_required():
    edl, beats = make()
    for path in (("extra",), ("source", "path"), ("captions", "x"), ("theme", "css")):
        bad = copy.deepcopy(edl)
        node = bad
        for k in path[:-1]:
            node = node[k]
        node[path[-1]] = "x"
        assert code(bad, beats).code == "unknown_key"
    bad = copy.deepcopy(edl)
    del bad["kept"]
    assert code(bad, beats).code == "missing_key"
    for bucket in ("overlays", "layouts"):
        bad = copy.deepcopy(beats)
        bad[bucket].append(copy.deepcopy(bad["overlays"][0] if bucket == "overlays" else bad["layouts"][0]))
        bad[bucket][-1]["start"] = 1.5                       # a time in an entry
        assert code(edl, bad).code == "unknown_key"
    bad = copy.deepcopy(beats)
    bad["overlays"][0]["params"]["filter"] = "drawtext=text=x"
    assert code(edl, bad).code == "undeclared_param"
    assert code(edl, dict(beats, extra=1)).code == "unknown_key"


def test_the_schema_file_lists_the_same_keys_as_the_checks():
    schema = json.loads((K.RENDERER / "edl.schema.json").read_text())["$defs"]
    assert set(schema["edl"]["properties"]) == _edl.EDL_KEYS
    assert set(schema["edl"]["properties"]["source"]["properties"]) == _edl.SOURCE_KEYS
    assert set(schema["beats"]["properties"]) == _edl.BEATS_KEYS
    assert set(schema["entry"]["properties"]) == _edl.ENTRY_KEYS
    assert set(schema["beats"]["properties"]["slots"]["items"]["properties"]) == _edl.SLOT_KEYS


def test_the_bounds_on_ranges_words_and_beats():
    edl, beats = make()
    cases = []
    bad = copy.deepcopy(edl); bad["kept"][1][0] = bad["kept"][0][1] - 1; cases.append((bad, "bad_kept"))         # overlapping ranges
    bad = copy.deepcopy(edl); bad["kept"][0] = [10, 5]; cases.append((bad, "bad_kept"))
    bad = copy.deepcopy(edl); bad["kept"][-1][1] += 5000; cases.append((bad, "bad_kept"))                       # past the recording
    bad = copy.deepcopy(edl); bad["out_frames"] += 1; cases.append((bad, "bad_out_frames"))
    bad = copy.deepcopy(edl); bad["words"][3]["index"] = bad["words"][2]["index"]; cases.append((bad, "word_index"))
    bad = copy.deepcopy(edl); bad["words"][3]["end"] = bad["words"][3]["start"] - 1; cases.append((bad, "word_time"))
    bad = copy.deepcopy(edl); bad["captions"]["chunks"][0] = [9999, 10000]; cases.append((bad, "bad_chunks"))
    bad = copy.deepcopy(edl); bad["fps"] = 120; cases.append((bad, "bad_fps"))
    bad = copy.deepcopy(edl); bad["size"] = [1920, 1080]; cases.append((bad, "bad_size"))
    for bad, expected in cases:
        assert code(bad, beats).code == expected, expected
    for mutate, expected in (
            (lambda b: b["overlays"][0].update(word_to=99999), "bad_word_range"),
            (lambda b: b["overlays"][0].update(word_from=b["overlays"][0]["word_to"] + 1), "bad_word_range"),
            (lambda b: b["overlays"][0].update(score=1.5), "bad_score"),
            (lambda b: b["overlays"][0].update(preset="pip"), "bad_preset"),                      # a layout preset in the overlay bucket
            (lambda b: b["overlays"][0].update(preset="explode"), "bad_preset"),
            (lambda b: b["overlays"].append(dict(b["overlays"][0])), "bad_id"),
            (lambda b: b["layouts"][0]["params"].update(asset="../x"), "bad_slot"),
            (lambda b: b["slots"].clear(), "slot_without_description"),
            (lambda b: b.update(overlays=b["overlays"] * 1 + [dict(b["overlays"][0], id="x%d" % k) for k in range(20)]), "too_many_beats")):
        bad = copy.deepcopy(beats)
        mutate(bad)
        assert code(edl, bad).code == expected, expected


def test_the_output_must_fit_the_platform_and_its_fps():
    edl, beats = make()
    short = copy.deepcopy(INSTAGRAM)
    short["video"]["max_seconds"] = 5
    assert code(edl, beats, short).code == "longer_than_platform"
    text_only = {"post": {"shape": "text_with_images"}, "video": {}}
    assert code(edl, beats, text_only).code == "platform_has_no_video"
    big = copy.deepcopy(edl)
    big["out_frames"] = DATA["limits"]["frames_max"] + 1
    assert code(big, beats).code in ("bad_out_frames", "bad_kept")


def test_an_output_longer_than_ninety_seconds_is_not_refused_when_the_platform_allows_it():
    """A real recording came out at 2 to 3 minutes: the limit is the platform file's maximum, never a fixed 90 s."""
    transcript = K.build_transcript([(1.0, "word " * 3 + "number %d." % k) for k in range(60)])
    edl, beats = make(transcript=transcript)
    assert edl["out_frames"] / edl["fps"] > 90
    _edl.check_edl(edl, DATA, VOCAB, ALLOW, INSTAGRAM)
    tiktok = json.loads(K.TIKTOK.read_text())
    _edl.check_edl(edl, DATA, VOCAB, ALLOW, tiktok)


def test_colours_are_rrggbb_and_fonts_come_from_the_allow_list():
    edl, beats = make()
    for bad in ("red", "#FFF", "rgba(0,0,0,.5)", "#12345G", "accent", "#FFFFFF;background:url(x)"):
        broken = copy.deepcopy(edl)
        broken["theme"]["colors"]["accent"] = bad
        assert code(broken, beats).code == "bad_color", bad
    broken = copy.deepcopy(edl)
    broken["theme"]["colors"]["extra"] = "#FFFFFF"
    assert code(broken, beats).code == "bad_theme"
    broken = copy.deepcopy(edl)
    broken["theme"]["fonts"]["display"]["id"] = "comic-sans"
    assert code(broken, beats).code == "font_not_allowed"
    ok = copy.deepcopy(edl)
    ok["theme"]["fonts"]["display"]["id"] = "fixture-800"
    check(ok, beats)
    broken = copy.deepcopy(edl)
    broken["theme"]["fonts"]["text"]["weight"] = 450
    assert code(broken, beats).code == "bad_font_weight"


def test_base_takes_colours_as_rrggbb_and_a_font_outside_the_list_falls_back_and_is_named():
    doc = K.build_transcript()
    analysis = {"facts": {"duration": doc["duration"], "sha256": "c" * 64, "width": 1080, "height": 1920, "has_audio": True}, "silences": None}
    for bad in ("red", "#FFF", "url(x)"):
        with pytest.raises(Refusal) as e:
            _edl.build_base(doc, analysis, DATA, ALLOW, colors={"accent": bad})
        assert e.value.code == "bad_color"
    with pytest.raises(Refusal) as e:
        _edl.build_base(doc, analysis, DATA, ALLOW, colors={"nope": "#FFFFFF"})
    assert e.value.code == "unknown_token"
    edl, notes = _edl.build_base(doc, analysis, DATA, ALLOW, colors={"accent": "#07b6f0"}, font_flags={"display": ("acme-brand", 800), "text": ("fixture-800", 500)})
    assert edl["theme"]["colors"]["accent"] == "#07B6F0"
    assert edl["theme"]["fonts"]["display"]["id"] == "default" and edl["theme"]["fonts"]["text"]["id"] == "fixture-800"
    assert notes == [{"role": "display", "asked": "acme-brand", "used": "default", "reason": "not in the font allow-list"}]


SECRETS = ["sk-" + "a1" * 16, "ghp_" + "Ab3" * 12, "AKIA" + "ABCDEFGHIJKLMNOP", "xoxb-" + "1234567890-abcdefghij",
           "api" + "_key = 'abcd1234efgh5678'", "Bearer " + "abcdefghij0123456789xyz", "https://user:" + "hunter2pass@host.example/x"]


@pytest.mark.parametrize("secret", SECRETS)
def test_a_credential_shaped_text_is_refused_and_never_echoed(secret):
    edl, beats = make()
    bad = copy.deepcopy(edl)
    bad["words"][4]["text"] = secret.split()[0] if " " not in secret else secret.replace(" ", "")[:40]
    # a whole secret split over words is caught by the joined scan; a one-word secret by the word scan
    if " " in secret:
        for k, part in enumerate(secret.split()):
            bad["words"][4 + k]["text"] = part
    err = code(bad, beats)
    assert err.code == "credential_shaped" and secret[:12] not in str(err)
    bad_beats = copy.deepcopy(beats)
    bad_beats["overlays"][0]["params"]["text"] = secret[:24] if " " not in secret else "x"
    if " " not in secret and len(secret) <= 24:
        err = code(edl, bad_beats)
        assert err.code == "credential_shaped" and secret[:12] not in str(err)


def test_the_check_verb_never_prints_the_matched_text(tmp_path):
    edl, beats = make()
    edl["words"][4]["text"] = "ghp_" + "Ab3" * 12
    K.write_json(tmp_path / "e.json", edl)
    K.write_json(tmp_path / "b.json", beats)
    rc, out, err = K.run_verb("check", "--edl", tmp_path / "e.json", "--beats", tmp_path / "b.json", "--vocabulary", K.VOCABULARY)
    assert rc == 1 and err.startswith("refused: credential_shaped") and "ghp_" not in err and out["ok"] is False and "ghp_" not in json.dumps(out)


def test_mentions_are_listed_separately():
    edl, beats = make()
    edl["words"][1]["text"] = "@maria.souza"
    beats["overlays"][0]["params"]["text"] = "ask @joao_x"
    first, second = check(edl, beats)
    assert first["mentions"] == ["@maria.souza"] and second["mentions"] == ["@joao_x"]


def test_text_in_a_list_must_be_hardened_whatever_its_source():
    edl, beats = make()
    for ch in ("\u202e", "\u200b", "\u2028", "\n"):
        bad = copy.deepcopy(edl)
        bad["words"][2]["text"] = "x" + ch + "y"
        assert code(bad, beats).code == "forbidden_character"
        bad_beats = copy.deepcopy(beats)
        bad_beats["overlays"][0]["params"]["text"] = "x" + ch + "y"
        assert code(edl, bad_beats).code == "forbidden_character"
    bad = copy.deepcopy(edl)
    bad["words"][2]["text"] = "é"
    assert code(bad, beats).code == "text_not_clean"          # not NFC
    bad_beats = copy.deepcopy(beats)
    bad_beats["slots"][0]["description"] = "a chart\u202e"
    assert code(edl, bad_beats).code == "forbidden_character"


def test_the_check_verb_prints_counts_and_exits_one_on_a_refusal(tmp_path):
    edl, beats = make()
    K.write_json(tmp_path / "e.json", edl)
    K.write_json(tmp_path / "b.json", beats)
    rc, out, err = K.run_verb("check", "--edl", tmp_path / "e.json", "--beats", tmp_path / "b.json", "--vocabulary", K.VOCABULARY, "--platform-file", K.INSTAGRAM)
    assert rc == 0 and out["ok"] and out["overlays"] == 4 and out["layouts"] == 2
    edl["kept"][0] = [5, 1]
    K.write_json(tmp_path / "e.json", edl)
    rc, out, err = K.run_verb("check", "--edl", tmp_path / "e.json", "--beats", tmp_path / "b.json", "--vocabulary", K.VOCABULARY)
    assert rc == 1 and out["code"] == "bad_kept" and err.startswith("refused: bad_kept")
