"""Retakes by rule (`_retakes.detect_retakes`): the table of shapes, the properties and the constants block. Fictional text only."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import pytest

import renderer_kit as K  # noqa: F401  (puts the renderer's folder on the path)
import _retakes as R
from _vocab import load_data

DATA = load_data()
CFG = DATA["retakes"]
PAUSE = re.compile(r"/([0-9.]+)/")


def words_of(text: str, language: str = "pt") -> list:
    """Each token of `text` is a word of 0.25 s, 0.05 s after the previous one; a token `/P/` adds a pause of P seconds and is not a word."""
    out, t = [], 0.0
    for tok in text.split():
        m = PAUSE.fullmatch(tok)
        if m:
            t += float(m.group(1))
            continue
        out.append({"index": len(out), "text": tok, "start": round(t, 3), "end": round(t + 0.25, 3), "segment": 0, "estimated": False, "dropped": False})
        t += 0.3
    return out


def detect(text: str, language: str = "pt") -> tuple:
    words = words_of(text, language)
    return words, R.detect_retakes(words, language, CFG)


def kept(words: list, proposals: list) -> str:
    gone = {i for p in proposals if p["default"] == "cut" for i in range(p["word_from"], p["word_to"] + 1)}
    return " ".join(w["text"] for w in words if w["index"] not in gone)


HOOK = "Você está gastando errado."  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken: a retake case must hold the words as said
FILLER_60 = " ".join("palavra%s" % "".join(chr(97 + (k // 26 ** d) % 26) for d in range(3)) for k in range(60))
CASE5 = "a primeira regra é que você precisa /0.7/ a primeira regra é simples: anote cada gasto."  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken: a retake case must hold the words as said

# (row, language, text, kept text or None for unchanged, expected [(kind, default, reason)])
ROWS = [
    (1, "pt", "hoje eu quero falar sobre hoje eu quero falar sobre dinheiro.", "hoje eu quero falar sobre dinheiro.", [("repeat", "cut", "continues")]),
    (2, "pt", "a gente... a gente passa por isso todo dia.", "a gente passa por isso todo dia.", [("restart", "cut", "cut_off")]),  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken: a retake case must hold the words as said
    (3, "pt", "e a gente a gente passa por isso.", "e a gente passa por isso.", [("restart", "cut", "continues")]),  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken: a retake case must hold the words as said
    (4, "pt", "o primeiro passo é ahn o primeiro passo é anotar tudo.", "o primeiro passo é anotar tudo.", [("repeat", "cut", "hesitation")]),
    (5, "pt", CASE5, "a primeira regra é simples: anote cada gasto.", [("repeat", "cut", "abandoned")]),
    (6, "en", "the first rule is that you need to /0.7/ the first rule is simple: write down every expense.",
     "the first rule is simple: write down every expense.", [("repeat", "cut", "abandoned")]),
    (7, "pt", "Hoje eu vou contar uma história. /1.5/ Hoje eu vou contar uma história.", "Hoje eu vou contar uma história.", [("repeat", "cut", "pause")]),
    (8, "pt", "Seja forte e corajoso. /0.3/ Seja forte e corajoso.", None, [("repeat", "keep", "complete")]),
    (9, "pt", "Eu passei por situações, sofrimento, amor e recomeço.", None, []),  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken: a retake case must hold the words as said
    (10, "pt", "A gente precisa de fé, a gente precisa de amor, a gente precisa de esperança.", None, [("repeat", "keep", "complete")] * 2),  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken: a retake case must hold the words as said
    (11, "pt", "O amor nunca falha. Ele sempre volta. O amor nunca falha.", None, [("repeat", "keep", "complete")]),
    (12, "pt", "Eu economizei dez por cento ahn eu economizei doze por cento.", "eu economizei doze por cento.", [("near", "cut", "hesitation")]),
    (13, "pt", "Eu economizei dez por cento. Eu economizei doze por cento.", None, [("near", "keep", "complete")]),
    (14, "pt", "a primeira regra a primeira regra é a primeira regra é simples.", "a primeira regra é simples.", [("repeat", "cut", "continues")] * 2),
    (15, "en", "I want to show you I want to show you my budget.", "I want to show you my budget.", [("repeat", "cut", "continues")]),
    (16, "en", "so the first rule is uh sorry the first rule is simple name every dollar", "so the first rule is simple name every dollar",
     [("repeat", "cut", "hesitation")]),
    (17, "en", "Never give up. Never give up.", None, [("repeat", "keep", "complete")]),
    (18, "pt", "eu eu acho que sim.", None, []),
    (19, "pt", "vamos pa- passar pelo básico.", "vamos passar pelo básico.", [("restart", "cut", "cut_off")]),
    (20, "pt", "a primeira regra é que você sempre anota tudo e guarda bem cada nota /0.9/ a primeira regra é simples.", None, [("repeat", "keep", "far")]),  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken: a retake case must hold the words as said
    (21, "pt", "%s %s /6.0/ %s" % (HOOK, FILLER_60, HOOK), None, []),
    (22, "pt", " ".join(t if PAUSE.fullmatch(t) else t.replace(".", "").replace(":", "") for t in CASE5.split()), None, [("repeat", "keep", "complete")]),
]
IDS = ["row%d" % r[0] for r in ROWS]


def check_row(text, language, expected_kept, expected, transform=lambda s: s):
    words, props = detect(transform(text), language)
    assert [(p["kind"], p["default"], p["reason"]) for p in props] == expected
    want = transform(expected_kept if expected_kept is not None else " ".join(t for t in text.split() if not PAUSE.fullmatch(t)))
    assert kept(words, props) == want
    return words, props


@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_the_table_of_shapes(row):
    _, language, text, expected_kept, expected = row
    check_row(text, language, expected_kept, expected)


@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_every_row_again_with_every_word_upper_cased(row):
    _, language, text, expected_kept, expected = row
    check_row(text, language, expected_kept, expected, transform=str.upper)


def test_an_accent_the_transcriber_wrote_differently_in_the_later_take_is_folded():
    text = "Hoje eu vou contar uma história. /1.5/ Hoje eu vou contar uma historia."
    words, props = detect(text, "pt")
    assert [(p["kind"], p["default"], p["reason"]) for p in props] == [("repeat", "cut", "pause")]
    assert kept(words, props) == "Hoje eu vou contar uma historia."


def test_a_spans_of_chained_takes_and_the_numbers_of_the_hesitation_row():
    _, props = detect(ROWS[13][2], "pt")
    assert [(p["word_from"], p["word_to"], p["keep_from"]) for p in props] == [(0, 2, 3), (3, 6, 7)]
    _, props = detect(ROWS[15][2], "en")
    (p,) = props
    assert (p["word_from"], p["word_to"], p["keep_from"]) == (1, 6, 7) and p["seconds"] == pytest.approx(1.75)
    assert p["id"] == "retake-1" and p["confirmed"] is False


# ---------------------------------------------------------------- properties

def all_texts():
    return [(r[1], r[2]) for r in ROWS]


def test_the_output_is_the_same_over_three_calls_and_with_the_input_copied():
    for language, text in all_texts():
        words = words_of(text, language)
        first = R.detect_retakes(words, language, CFG)
        again = R.detect_retakes([dict(w) for w in words], language, CFG)
        assert first == again == R.detect_retakes(words, language, CFG) == R.detect_retakes(words, language, CFG)


def test_ids_order_overlap_and_the_kinds_of_values():
    for language, text in all_texts():
        words = words_of(text, language)
        props = R.detect_retakes(words, language, CFG)
        assert [p["id"] for p in props] == ["retake-%d" % (k + 1) for k in range(len(props))]
        assert len(props) <= CFG["proposals_max"]
        assert [p["word_from"] for p in props] == sorted(p["word_from"] for p in props)
        for a, b in zip(props, props[1:]):
            assert a["word_to"] < b["word_from"]
        for p in props:
            assert p["keep_from"] > p["word_to"] >= p["word_from"]
            assert p["kind"] in R.KINDS and p["default"] in ("cut", "keep") and p["reason"] in R.REASONS
            assert isinstance(p["seconds"], float) and isinstance(p["confirmed"], bool)
            assert all(isinstance(p[k], int) and not isinstance(p[k], bool) for k in ("word_from", "word_to", "keep_from"))
            assert all(isinstance(v, (str, int, float, bool)) for v in p.values())


def test_an_unknown_language_uses_the_universal_list_only():
    text = "o primeiro passo é ahn o primeiro passo é anotar tudo."
    words = words_of(text, "xx")
    props = R.detect_retakes(words, "xx", CFG)
    assert R.detect_retakes(words, None, CFG) == props
    # `ahn` is a Portuguese hesitation: with "*" only it is a content word, so the take is no longer cut for a hesitation
    assert [(p["default"], p["reason"]) for p in props] != [("cut", "hesitation")]
    words2 = words_of("hmm the first rule hmm the first rule is simple", "xx")
    assert any(p["reason"] == "hesitation" for p in R.detect_retakes(words2, "xx", CFG))


def test_the_presets_block_has_exactly_the_keys_and_clean_lists():
    expected = {"window_seconds", "run_min", "restart_min", "fragment_min_chars", "tail_propose_max", "tail_cut_max", "cut_seconds_max",
                "retake_pause", "phrase_pause", "near_min_tokens", "near_head_tokens", "near_ratio", "near_edits_max", "near_gap_max",
                "punctuation_min_share", "proposals_max", "words"}
    assert set(CFG) == expected
    bounds = {"run_min": (3, 4), "restart_min": (2, 3), "tail_cut_max": (4, 8), "cut_seconds_max": (6, 15), "retake_pause": (0.9, 1.5),
              "phrase_pause": (0.5, 0.8), "near_ratio": (0.75, 0.9)}
    for key, (lo, hi) in bounds.items():
        assert lo <= CFG[key] <= hi, key
    for language, block in CFG["words"].items():
        assert set(block) == {"hesitation", "filler", "cue"}
        seen = {}
        for cls, entries in block.items():
            for entry in entries:
                assert entry == unicodedata.normalize("NFC", entry).casefold(), (language, entry)
                assert entry not in seen, (language, entry, seen.get(entry), cls)
                seen[entry] = cls


def test_the_proposals_bound_is_the_one_of_the_check():
    text = (Path(__file__).resolve().parents[1] / "_edl.py").read_text(encoding="utf-8")
    assert re.search(r"len\(props\) > (\d+)", text).group(1) == str(CFG["proposals_max"]) == "100"


def test_the_many_proposals_are_bounded():
    text = " ".join("w%da w%db w%dc w%dd. w%da w%db w%dc w%dd." % ((k,) * 8) for k in range(150))
    words = words_of(text, "en")
    assert len(R.detect_retakes(words, "en", CFG)) <= CFG["proposals_max"]


def test_no_words_no_proposals():
    assert R.detect_retakes([], "pt", CFG) == []


def test_a_long_silence_inside_a_stretched_word_counts_as_a_pause():
    # the transcriber stretched the last word of the first take over 1.5 s; the audio is silent for 1.3 s inside it
    text = "Hoje eu vou contar uma história. Hoje eu vou contar uma história."
    words = words_of(text, "pt")
    words[5]["end"] = words[5]["start"] + 1.5
    for w in words[6:]:
        w["start"] += 1.25
        w["end"] += 1.25
    assert [(p["default"], p["reason"]) for p in R.detect_retakes(words, "pt", CFG)] == [("keep", "complete")]
    silence = [(words[5]["start"] + 0.1, words[5]["start"] + 1.4)]
    assert [(p["default"], p["reason"]) for p in R.detect_retakes(words, "pt", CFG, silence)] == [("cut", "pause")]


def test_the_module_is_standard_library_only():
    src = (Path(__file__).resolve().parents[1] / "_retakes.py").read_text(encoding="utf-8")
    imports = set(re.findall(r"^(?:from|import) (\w+)", src, re.M))
    assert imports <= {"__future__", "bisect", "difflib", "unicodedata", "_align"}


def test_the_presets_file_is_valid_json_with_the_block():
    assert "retakes" in json.loads((Path(__file__).resolve().parents[1] / "renderer-presets.json").read_text(encoding="utf-8"))
