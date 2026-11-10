"""The post file's script block: the skill's own checker, the beats, and their alignment to the transcript's words."""
from __future__ import annotations

import json

import pytest

import renderer_kit as K
import _align as A
from _text import Refusal
from _vocab import load_vocabulary

VOCAB = load_vocabulary(str(K.VOCABULARY))


def mk(text):
    out, t = [], 0.0
    for k, tok in enumerate(text.split()):
        out.append({"index": k, "text": tok, "start": t, "end": t + 0.2})
        t += 0.25
    return out


def align(line, speech, threshold=0.6):
    w = mk(speech)
    r = A.align_line(line, A.flatten_words(w), threshold)
    if r["matched"]:
        r["word_from"], r["word_to"] = A.expand_digit_words(w, r["word_from"], r["word_to"])
    return r, w


def test_an_exact_line_is_found_inside_longer_speech():
    r, w = align("name every dollar", "so the first rule is simple name every dollar and that is it")
    assert r["matched"] and [w[r["word_from"]]["text"], w[r["word_to"]]["text"]] == ["name", "dollar"] and r["score"] == pytest.approx(1.0)


def test_normalisation_is_nfkc_casefold_and_punctuation():
    assert align("Don't WAIT, act now!", "dont wait act now")[0]["score"] == pytest.approx(1.0)
    assert align("café ＯＫ", "CAFÉ ok")[0]["matched"]       # fullwidth folds, the combining accent composes


def test_fast_speech_with_dropped_and_misrecognised_words_still_matches():
    r, w = align("then do three things each week review adjust and celebrate", "um then do three thing each week review adjust celebrate right")
    assert r["matched"] and r["score"] > 0.7 and w[r["word_to"]]["text"] == "celebrate"


def test_an_ad_lib_inside_the_line_costs_little():
    r, w = align("small steps beat big plans", "small steps honestly really beat big plans")
    assert r["matched"] and r["score"] < 1.0 and [w[r["word_from"]]["text"], w[r["word_to"]]["text"]] == ["small", "plans"]


def test_an_unmatched_line_is_reported_not_guessed():
    assert not align("quarterly revenue forecast", "name every dollar and keep going")[0]["matched"]


def test_a_retake_wins_a_tie_but_a_much_better_early_take_wins():
    r, _ = align("name every dollar", "name every dollar uh sorry name every dollar now")
    assert (r["word_from"], r["word_to"]) == (5, 7)
    r, _ = align("name every dollar", "name every dollar uh sorry name a dollar now")
    assert r["word_from"] == 0


def test_figures_are_excluded_from_scoring_and_a_neighbouring_figure_is_included():
    assert align("that habit saved me 340 dollars in one month", "that habit saved me three hundred forty dollars in one month")[0]["matched"]
    r, w = align("that habit saved me 340 dollars in one month", "that habit saved me 340 dollars in one month")
    assert r["score"] == pytest.approx(1.0) and w[r["word_to"]]["text"] == "month"
    r, w = align("it grew by", "it grew by 30")
    assert w[r["word_to"]]["text"] == "30"
    assert not align("2024", "in 2024 we grew")[0]["matched"]


def test_the_threshold_and_the_order_check():
    assert not align("one two three four five six", "one two zzz yyy xxx six", threshold=0.9)[0]["matched"]
    w = mk("alpha beta gamma delta epsilon zeta eta theta")
    res = A.align_beats(w, [{"line": "epsilon zeta eta"}, {"line": "alpha beta gamma"}])
    assert not res[0]["reordered"] and res[1]["reordered"] and res[1]["matched"]


def test_alignment_ignores_dropped_words_and_keeps_transcript_indices():
    live = [w for w in mk("noise noise first line of the story") if w["index"] >= 2]
    r = A.align_line("first line of the story", A.flatten_words(live))
    assert (r["word_from"], r["word_to"]) == (2, 6)


# ---------------------------------------------------------------- the checker and the post file

def test_the_checker_runs_isolated_and_a_post_it_refuses_is_refused(tmp_path):
    post = tmp_path / "post.md"
    post.write_text(K.POST, encoding="utf-8")
    assert A.run_checker(str(K.CHECKER), str(post), str(K.VOCABULARY), "reel")["ok"] is True
    bad = tmp_path / "bad.md"
    bad.write_text(K.POST.replace("preset: keyword", "preset: confetti"), encoding="utf-8")
    with pytest.raises(Refusal) as e:
        A.run_checker(str(K.CHECKER), str(bad), str(K.VOCABULARY), "reel")
    assert e.value.code == "script_refused" and any(p["code"] == "unknown_preset" for p in e.value.problems)
    assert "confetti" not in str(e.value) and "confetti" not in json.dumps(e.value.problems)
    with pytest.raises(Refusal) as e:
        A.run_checker(str(tmp_path / "nope.py"), str(post), str(K.VOCABULARY), "reel")
    assert e.value.code == "checker_missing"


def test_the_checker_is_started_with_isolation_flags_and_a_scrubbed_environment(tmp_path, monkeypatch):
    seen = {}

    class Done:
        returncode, stdout, stderr = 0, json.dumps({"ok": True, "problems": []}), ""

    def fake_run(argv, **kw):
        seen.update(argv=argv, env=kw["env"], cwd=kw["cwd"])
        return Done()

    monkeypatch.setenv("SOME_SECRET_TOKEN", "must-not-pass")
    monkeypatch.setattr(A.subprocess, "run", fake_run)
    checker = tmp_path / "check.py"
    checker.write_text("")
    A.run_checker(str(checker), "post.md", "v.json", "reel")
    assert seen["argv"][1:4] == ["-I", "-E", "-s"] and set(seen["env"]) == {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL"}
    assert seen["cwd"] != str(tmp_path)


def test_the_beats_of_the_fixture_post_are_read_with_the_main_parameter_under_its_own_name():
    rows = A.read_beats(K.POST, VOCAB)
    assert [r["preset"] for r in rows] == [None, None, "keyword", "list", "number", "quote", "cutaway", "pip", None]
    assert rows[2]["params"] == {"text": "Name every dollar", "icon": "coin"}
    assert rows[3]["params"]["items"] == "Review | Adjust | Celebrate"
    assert rows[6]["params"] == {"label": "My dashboard", "fit": "cover"} and "asset" in rows[6]["slots"]


def test_a_post_that_is_not_a_video_format_is_refused_by_the_verb(tmp_path):
    post = tmp_path / "carousel.md"
    post.write_text(K.POST.replace("Format: reel", "Format: carousel"), encoding="utf-8")
    tr = K.write_json(tmp_path / "t.json", K.build_transcript())
    rc, out, err = K.run_verb("align", "--post", post, "--transcript", tr, "--checker", K.CHECKER, "--vocabulary", K.VOCABULARY, "--out", tmp_path / "b.json")
    assert rc == 1 and err.startswith("refused: post_format")
    post.write_text(K.POST.replace("- Format: reel\n", ""), encoding="utf-8")
    rc, out, err = K.run_verb("align", "--post", post, "--transcript", tr, "--checker", K.CHECKER, "--vocabulary", K.VOCABULARY, "--out", tmp_path / "b.json")
    assert rc == 1 and err.startswith("refused: post_format")          # never assumed


def test_a_failing_post_stops_the_verb_before_anything_is_written(tmp_path):
    post = tmp_path / "bad.md"
    post.write_text(K.POST.replace("on-screen: Name every dollar", "on-screen: " + "x" * 80), encoding="utf-8")
    tr = K.write_json(tmp_path / "t.json", K.build_transcript())
    rc, out, err = K.run_verb("align", "--post", post, "--transcript", tr, "--checker", K.CHECKER, "--vocabulary", K.VOCABULARY, "--out", tmp_path / "b.json")
    assert rc == 1 and err.startswith("refused: script_refused") and "text_too_long" in err and not (tmp_path / "b.json").exists()
    assert "xxxxx" not in err


def test_the_align_verb_writes_beats_with_scores_slots_and_only_indices_and_typed_values(tmp_path):
    post = tmp_path / "post.md"
    post.write_text(K.POST, encoding="utf-8")
    tr = K.write_json(tmp_path / "t.json", K.build_transcript())
    rc, out, err = K.run_verb("align", "--post", post, "--transcript", tr, "--checker", K.CHECKER, "--vocabulary", K.VOCABULARY, "--out", tmp_path / "b.json")
    assert rc == 0, err
    assert out["overlays"] == 4 and out["layouts"] == 2 and out["unmatched"] == [] and out["slots"] == ["beat7", "beat8"]
    beats = json.loads((tmp_path / "b.json").read_text())
    assert [e["preset"] for e in beats["overlays"]] == ["keyword", "list", "number", "quote"]
    assert beats["layouts"][0]["params"]["asset"] == "beat7" and beats["slots"][0]["description"].startswith("a screenshot")
    assert all(set(e) == {"id", "beat", "preset", "params", "word_from", "word_to", "score"} for e in beats["overlays"] + beats["layouts"])
    text = json.dumps(beats["overlays"] + beats["layouts"])
    assert "screenshot" not in text and "start" not in text      # no description and no time inside an entry
    assert oct((tmp_path / "b.json").stat().st_mode & 0o777) == "0o600"


def test_a_beat_that_was_not_said_is_reported_unmatched_and_gets_no_overlay(tmp_path):
    post = tmp_path / "post.md"
    post.write_text(K.POST.replace("line: The first rule is simple: name every dollar.", "line: Quarterly revenue forecasts always disappoint auditors."), encoding="utf-8")
    tr = K.write_json(tmp_path / "t.json", K.build_transcript())
    rc, out, err = K.run_verb("align", "--post", post, "--transcript", tr, "--checker", K.CHECKER, "--vocabulary", K.VOCABULARY, "--out", tmp_path / "b.json")
    assert rc == 0 and out["unmatched"] == [3]
    beats = json.loads((tmp_path / "b.json").read_text())
    assert "keyword" not in [e["preset"] for e in beats["overlays"]]
    assert next(r for r in beats["report"] if r["beat"] == 3)["matched"] is False


def test_an_empty_slot_falls_back_as_the_person_chose(tmp_path):
    post = tmp_path / "post.md"
    post.write_text(K.POST, encoding="utf-8")
    tr = K.write_json(tmp_path / "t.json", K.build_transcript())
    rc, out, err = K.run_verb("align", "--post", post, "--transcript", tr, "--checker", K.CHECKER, "--vocabulary", K.VOCABULARY, "--out", tmp_path / "b.json",
                              "--empty-slot", "7=keyword", "--empty-slot", "beat8=none")
    assert rc == 0, err
    beats = json.loads((tmp_path / "b.json").read_text())
    assert beats["layouts"] == [] and beats["slots"] == []
    assert [e["preset"] for e in beats["overlays"]][-1] == "keyword" and beats["overlays"][-1]["params"] == {"text": "My dashboard"}
    assert {(f["beat"], f["to"]) for f in beats["fallbacks"]} == {(7, "keyword"), (8, "none")}
    rc, out, err = K.run_verb("align", "--post", post, "--transcript", tr, "--checker", K.CHECKER, "--vocabulary", K.VOCABULARY, "--out", tmp_path / "c.json", "--empty-slot", "7=maybe")
    assert rc == 2
