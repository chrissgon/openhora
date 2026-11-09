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


def words_of(text: str, language: str = "pt", dur: float = 0.25, gap: float = 0.05) -> list:
    """Each token of `text` is a word of 0.25 s, 0.05 s after the previous one; a token `/P/` adds a pause of P seconds and is not a word."""
    out, t = [], 0.0
    for tok in text.split():
        m = PAUSE.fullmatch(tok)
        if m:
            t += float(m.group(1))
            continue
        out.append({"index": len(out), "text": tok, "start": round(t, 3), "end": round(t + dur, 3), "segment": 0, "estimated": False, "dropped": False})
        t += dur + gap
    return out


def detect(text: str, language: str = "pt", **timing) -> tuple:
    words = words_of(text, language, **timing)
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
                "redo_words_max", "redo_seconds_max", "redo_later_share", "retake_pause", "phrase_pause", "near_min_tokens", "near_head_tokens", "near_ratio", "near_edits_max", "near_gap_max",
                "punctuation_min_share", "proposals_max", "words"}
    assert set(CFG) == expected
    bounds = {"run_min": (3, 4), "restart_min": (2, 3), "tail_cut_max": (4, 8), "cut_seconds_max": (6, 15), "retake_pause": (0.9, 1.5),
              "redo_words_max": (30, 60), "redo_seconds_max": (12, 20),
              "phrase_pause": (0.5, 0.8), "near_ratio": (0.75, 0.9)}
    for key, (lo, hi) in bounds.items():
        assert lo <= CFG[key] <= hi, key
    for language, block in CFG["words"].items():
        assert set(block) == {"hesitation", "filler", "cue", "connector"}
        seen = {}
        for cls, entries in block.items():
            for entry in entries:
                assert entry == unicodedata.normalize("NFC", entry).casefold(), (language, entry)
                if cls == "connector":          # a connector may also be a filler ("so"): it is only looked up before a redo's earlier take
                    continue
                assert entry not in seen, (language, entry, seen.get(entry), cls)
                seen[entry] = cls
        assert block["connector"] == sorted(set(block["connector"]), key=block["connector"].index)


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


# ---------------------------------------------------------------- the whole-sentence redo (real check of V3e)

A_FIRST = "Quando a gente guarda dinheiro todo mês durante vários anos seguidos, a pessoa consegue comprar uma casa pequena perto da família inteira."  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken
A_REDO = "Quando a gente guarda um pouco de cada salário com paciência e disciplina, em poucos anos nasce a entrada para o primeiro lar."  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken
B_FIRST = ("When I first started tracking every single expense in a small notebook, I noticed that the biggest leaks were never the large purchases "
           "but the tiny daily habits that nobody ever questions or even remembers.")
B_REDO = ("When I first started tracking all of my spending, the real surprise came from the coffee, the snacks and the small subscriptions "
          "that I had completely forgotten about.")
ANAPHORA = " ".join("Eu quero ver %s." % tail for tail in (  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken
    "a cidade crescer com paciência e cuidado em cada bairro pequeno do interior",
    "as famílias vivendo melhor depois de tanto trabalho duro nas lavouras vizinhas",  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken
    "os jovens estudando sem medo do futuro que ainda vai chegar para todos nós"))  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken
LONG_50 = " ".join("w%d" % k for k in range(50))
LONG_70 = " ".join("v%d" % k for k in range(70))

REDO_ROWS = [
    # (name, language, text, timing, expected [(kind, default, reason)], expected kept text or None for unchanged)
    ("shape-a", "pt", A_FIRST + " " + A_REDO, {}, [("repeat", "cut", "redo")], A_REDO),
    ("shape-b", "en", B_FIRST + " " + B_REDO, {}, [("repeat", "cut", "redo")], B_REDO),
    ("filler-pt", "pt", A_FIRST + " é… " + A_REDO, {}, [("repeat", "cut", "redo")], A_REDO),  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken
    ("filler-en", "en", B_FIRST + " um " + B_REDO, {}, [("repeat", "cut", "redo")], B_REDO),
    ("anaphora", "pt", ANAPHORA, {}, [("repeat", "keep", "far")] * 2, None),
    ("emphatic", "en", "We will never quit this fight. We will never quit this fight.", {}, [("repeat", "keep", "complete")], None),
    # an earlier take over redo_words_max words is kept as `far`; a take so long that no proposal is made at all is kept too
    ("too-long-50", "en", "Once upon a time " + LONG_50 + ". Once upon a time again z1 z2 z3 z4 z5 z6.", {"dur": 0.08, "gap": 0.02},
     [("repeat", "keep", "far")], None),
    ("too-long-70", "en", "Once upon a time " + LONG_70 + ". Once upon a time again z1 z2 z3 z4 z5 z6.", {"dur": 0.08, "gap": 0.02}, [], None),
    ("long-pause", "pt", A_FIRST + " /3.0/ " + A_REDO, {}, [("repeat", "cut", "redo")], A_REDO),
]


@pytest.mark.parametrize("row", REDO_ROWS, ids=[r[0] for r in REDO_ROWS])
def test_the_whole_sentence_redo_shapes(row):
    _, language, text, timing, expected, expected_kept = row
    words, props = detect(text, language, **timing)
    assert [(p["kind"], p["default"], p["reason"]) for p in props] == expected
    want = expected_kept if expected_kept is not None else " ".join(t for t in text.split() if not PAUSE.fullmatch(t))
    assert kept(words, props) == want


def test_the_redo_sentences_have_the_sizes_the_real_shapes_had():
    assert 20 <= len(A_FIRST.split()) <= 24 and 30 <= len(B_FIRST.split()) <= 36 and len(LONG_50.split()) == 50 and len(LONG_70.split()) == 70
    assert A_FIRST.split()[:4] == A_REDO.split()[:4] and A_FIRST.split()[4] != A_REDO.split()[4]
    assert B_FIRST.split()[:5] == B_REDO.split()[:5] and B_FIRST.split()[5] != B_REDO.split()[5]


def test_a_redo_is_not_cut_when_another_sentence_lies_between_the_takes():
    middle = "Isso foi o que eu aprendi no ano passado com muito esforço."  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken
    _, props = detect(A_FIRST + " " + middle + " " + A_REDO, "pt")
    assert all(p["reason"] != "redo" for p in props)


def test_a_shorter_summary_said_after_a_long_sentence_is_not_a_redo():
    _, props = detect(ROWS[19][2], "pt")        # row 20: a 13-word sentence, then a four-word summary of it
    assert [(p["default"], p["reason"]) for p in props] == [("keep", "far")]


# ---------------------------------------------------------------- the earlier take after a connector (a clause, "..., but <take>")

PT_LEAD = "Nós sabemos que tudo muda com o tempo,"  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken
PT_EARLIER = "nós vamos continuar juntos nesta caminhada longa e bonita cheia de desafios e alegrias na nossa vida."  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken
PT_LATER = "Nós vamos continuar juntos nesta jornada, porque cada passo pequeno constrói algo muito maior do que imaginamos."  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken
EN_LEAD = "We all know that things change over time,"
EN_EARLIER = "we will keep walking together on this long and lovely road full of small challenges and joys in our life."
EN_LATER = "We will keep walking together on this winding path, because every small step builds something far bigger than we imagine."
CROSSING = ("Nós vamos continuar juntos nesta caminhada longa e bonita. Isso é o que eu aprendo todo dia com muita gente boa e humilde. "  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken
            + PT_LATER)

CONNECTOR_ROWS = [
    ("mas", "pt", PT_LEAD + " mas " + PT_EARLIER + " " + PT_LATER, [("repeat", "cut", "redo")], PT_LEAD + " mas " + PT_LATER),
    ("mas-no-comma", "pt", PT_LEAD.rstrip(",") + " mas " + PT_EARLIER + " " + PT_LATER, [("repeat", "cut", "redo")], PT_LEAD.rstrip(",") + " mas " + PT_LATER),
    ("but", "en", EN_LEAD + " but " + EN_EARLIER + " " + EN_LATER, [("repeat", "cut", "redo")], EN_LEAD + " but " + EN_LATER),
    ("crosses-a-sentence-end", "pt", CROSSING, [("repeat", "keep", "far")], None),
    ("connector-not-in-the-list", "pt", PT_LEAD + " depois " + PT_EARLIER + " " + PT_LATER, [("repeat", "keep", "far")], None),
    ("no-connector-no-phrase-start", "en", EN_LEAD + " " + EN_EARLIER + " " + EN_LATER, [("repeat", "keep", "far")], None),
]


@pytest.mark.parametrize("row", CONNECTOR_ROWS, ids=[r[0] for r in CONNECTOR_ROWS])
def test_the_earlier_take_may_follow_a_connector_but_never_cross_a_sentence_end(row):
    _, language, text, expected, expected_kept = row
    words, props = detect(text, language)
    assert [(p["kind"], p["default"], p["reason"]) for p in props] == expected
    assert kept(words, props) == (expected_kept if expected_kept is not None else " ".join(text.split()))


def test_a_connector_is_matched_after_folding_and_a_two_word_connector_counts():
    cfg = json.loads(json.dumps(CFG))
    cfg["words"]["pt"]["connector"] = ["s\u00f3 que"]
    words = words_of(PT_LEAD + " só que " + PT_EARLIER + " " + PT_LATER, "pt")  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken
    assert [(p["default"], p["reason"]) for p in R.detect_retakes(words, "pt", cfg)] == [("cut", "redo")]
    words = words_of(PT_LEAD + " so que " + PT_EARLIER + " " + PT_LATER, "pt")
    assert [(p["default"], p["reason"]) for p in R.detect_retakes(words, "pt", cfg)] == [("cut", "redo")]      # accents are folded on both sides
