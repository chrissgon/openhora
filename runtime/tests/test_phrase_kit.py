"""T8-0a: the phrase kit (runtime/tests/phrase_kit.py) says what it says.

Every oracle here is a literal of this file, over a small table of this file's own (swapped in for `phrases.TABLE`), so the kit is not
checked against the wording it will be used on. One test reads the real table, and checks the kit against `str.format` (the way the table's
own function writes a sentence), for every key of both languages. The planted-wrong cases at the end are the vacuity of the rest: a `said` that
ignores the fields, a `said` that ignores the language, and a `which` that always answers the first key, each makes the check that guards it fail.
"""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import phrase_kit as pk  # noqa: E402
import phrases  # noqa: E402

EN = {"language": "en"}
PT = {"language": "pt-BR"}
FR = {"language": "fr"}

# Fictional sentences; the second language has no accented letter on purpose (the repository's English check reads this file).
TABLE = {
    "en": {
        "GREET": "Hello {name}, you have {n} messages.",
        "BYE": "Goodbye.",
        "RANGE": "From {day} to {day}.",
        "SHORT": "{who}: {what}",
        "TWO_LINES": "First line of {name}.\nSecond line.",
        "ONLY_EN": "Only in English {x}",
        "DOTTED": "Price (net) is {amount}.",
    },
    "pt-BR": {
        "GREET": "Ola {name}, voce tem {n} mensagens.",
        "BYE": "Tchau.",
        "RANGE": "De {day} ate {day}.",
        "SHORT": "{who} diz: {what}",
        "TWO_LINES": "Primeira linha de {name}.\nSegunda linha.",
        "DOTTED": "O preco (liquido) e {amount}.",
    },
}


@pytest.fixture(autouse=True)
def own_table(monkeypatch):
    monkeypatch.setattr(phrases, "TABLE", TABLE)


def field_checks(said):
    """What a `said` must do with fields; run on the real one, and (below) on planted wrong ones."""
    text = "Hello Ana, you have 3 messages."
    assert said(text, "GREET", EN, name="Ana", n=3)                 # every field given and equal
    assert said(text, "GREET", EN, name="Ana")                      # a field not given matches anything
    assert said(text, "GREET", EN)                                  # no field given at all
    assert not said(text, "GREET", EN, name="Ana", n=4)             # a field that differs
    assert not said(text, "GREET", EN, name="Bia")                  # the other field that differs
    assert said(text, "GREET", EN, n="3")                           # a value is compared as text
    assert not said("Hello Ana, you have 3 message.", "GREET", EN)  # the fixed words differ


def language_checks(said):
    assert said("Hello Ana, you have 3 messages.", "GREET", EN, name="Ana", n=3)
    assert said("Ola Ana, voce tem 3 mensagens.", "GREET", PT, name="Ana", n=3)
    assert not said("Ola Ana, voce tem 3 mensagens.", "GREET", EN)  # a key's sentence of the other language fails
    assert not said("Hello Ana, you have 3 messages.", "GREET", PT)
    assert said("Hello Ana, you have 3 messages.", "GREET", None, name="Ana")   # no cfg: English
    assert said("Hello Ana, you have 3 messages.", "GREET", FR, name="Ana")     # a language with no table says English


def test_said_follows_the_fields():
    field_checks(pk.said)


def test_said_follows_the_language():
    language_checks(pk.said)


def test_a_language_that_lacks_a_key_says_the_english_sentence_as_the_table_does():
    assert phrases.text("ONLY_EN", PT, x="1") == "Only in English 1"      # the table's own rule
    assert pk.said("Only in English 1", "ONLY_EN", PT, x=1)
    assert not pk.said("Only in English 2", "ONLY_EN", PT, x=1)


def test_a_line_of_a_longer_text_or_the_whole_text_is_enough():
    assert pk.said("Goodbye.", "BYE", EN)
    assert pk.said("Header\nGoodbye.\nFooter", "BYE", EN)
    assert not pk.said("Header\nGoodbye. Really.\nFooter", "BYE", EN)    # a line is the whole sentence, not a part of one
    assert not pk.said("Goodbye.!", "BYE", EN)
    assert pk.said("Header\nHello Ana, you have 3 messages.", "GREET", EN, name="Ana", n="3")
    assert not pk.said(None, "BYE", EN) and not pk.said(7, "BYE", EN)


def test_a_sentence_of_two_lines_is_matched_whole_or_line_by_line():
    assert pk.said("First line of Ana.\nSecond line.", "TWO_LINES", EN, name="Ana")
    assert pk.said("Intro\nFirst line of Ana.\nSecond line.\nOutro", "TWO_LINES", EN, name="Ana")
    assert not pk.said("First line of Ana.\nSecond line", "TWO_LINES", EN)
    assert not pk.said("Intro\nFirst line of Ana.\nOther line.", "TWO_LINES", EN)
    assert pk.said("Primeira linha de Ana.\nSegunda linha.", "TWO_LINES", PT, name="Ana")


def test_a_field_may_hold_a_new_line_only_when_the_whole_text_is_the_sentence():
    assert pk.said("Ana\nBia: said\nhello", "SHORT", EN, who="Ana\nBia", what="said\nhello")
    assert pk.said("Ana: said\nhello", "SHORT", EN, who="Ana", what="said\nhello")
    assert pk.said("Ana: ok\nmore text", "SHORT", EN, who="Ana", what="ok")         # the line "Ana: ok" is the sentence
    assert pk.said("Ana: ok\nmore text", "SHORT", EN, who="Ana", what="ok\nmore text")   # and so is the whole text, with a field that spans lines
    assert not pk.said("Ana: ok\nmore text", "SHORT", EN, who="Ana", what="ok\nmore")    # but not a part of it


def test_a_repeated_field_holds_one_value():
    assert pk.said("From 21/10 to 21/10.", "RANGE", EN, day="21/10")
    assert pk.said("From 21/10 to 21/10.", "RANGE", EN)
    assert not pk.said("From 21/10 to 22/10.", "RANGE", EN)                   # the template repeats {day}: two values are not it
    assert not pk.said("From 21/10 to 22/10.", "RANGE", EN, day="21/10")


def literal_checks(said):
    assert said("Price (net) is 3.50.", "DOTTED", EN, amount="3.50")
    assert not said("Price net is 3.50.", "DOTTED", EN)                       # the parentheses are text
    assert not said("Price (net) is 3x50.", "DOTTED", EN, amount="3.50")      # the point of a value is a point
    assert said("Price (net) is a+b*(c).", "DOTTED", EN, amount="a+b*(c)")


def test_the_characters_of_a_template_and_of_a_value_are_literal_not_a_pattern():
    literal_checks(pk.said)


def naming_checks(which):
    assert which("Hello Ana, you have 3 messages.", EN) == ("GREET", {"name": "Ana", "n": "3"})
    assert which("Ola Ana, voce tem 3 mensagens.", PT) == ("GREET", {"name": "Ana", "n": "3"})
    assert which("Ola Ana, voce tem 3 mensagens.", EN) == ("GREET", {"name": "Ana", "n": "3"})    # the other language is looked for too
    assert which("Header\nTchau.\nFooter", PT) == ("BYE", {})                                   # the first line that is a sentence
    assert which("Something nobody wrote", EN) is None
    assert which(None, EN) is None


def test_a_field_may_be_called_text_key_or_cfg(monkeypatch):
    monkeypatch.setattr(phrases, "TABLE", {"en": {"ODD": "{text} {key} {cfg}"}})
    assert pk.said("a b c", "ODD", EN, text="a", key="b", cfg="c")
    assert not pk.said("a b c", "ODD", EN, text="a", key="b", cfg="d")
    pk.assert_said("a b c", "ODD", EN, text="a")


def test_which_names_the_key_and_the_fields_in_both_languages():
    naming_checks(pk.which)


def test_which_tries_the_template_with_the_most_fixed_words_first():
    # "{who}: {what}" would match anything with a colon; the exact template wins.
    assert pk.which("Hello Ana, you have 3 messages.", EN)[0] == "GREET"
    assert pk.which("Ana: hi", EN) == ("SHORT", {"who": "Ana", "what": "hi"})
    assert pk.which("Ana: Hello Bia, you have 3 messages.", EN)[0] == "SHORT"


def test_assert_said_passes_on_a_sentence_and_names_the_failure_otherwise():
    pk.assert_said("Hello Ana, you have 3 messages.", "GREET", EN, name="Ana", n=3)
    with pytest.raises(AssertionError) as raised:
        pk.assert_said("Hello Ana, you have 3 messages.", "GREET", EN, name="Ana", n=4)
    message = str(raised.value)
    assert "does not say GREET (en)" in message
    assert "expected: Hello Ana, you have 4 messages." in message
    assert "got:      Hello Ana, you have 3 messages." in message
    assert "field 'n' is '3', not '4'" in message                                   # the nearest: the same key, another value


def test_assert_said_shows_a_field_not_given_as_a_placeholder_and_the_other_language():
    with pytest.raises(AssertionError) as raised:
        pk.assert_said("Ola Ana, voce tem 3 mensagens.", "GREET", EN, name="Ana")
    message = str(raised.value)
    assert "expected: Hello Ana, you have {n} messages." in message
    assert "the text is the sentence of GREET in pt-BR, not in en" in message


def test_assert_said_names_the_key_the_text_does_say_and_the_nearest_when_none():
    with pytest.raises(AssertionError) as raised:
        pk.assert_said("Goodbye.", "GREET", EN)
    assert "the text is the sentence of BYE (en) with fields {}" in str(raised.value)
    with pytest.raises(AssertionError) as raised:
        pk.assert_said("Hello Ana, you have three messages", "GREET", EN)
    message = str(raised.value)
    assert "no sentence of the table equals the text; the nearest is GREET (en): 'Hello {name}, you have {n} messages.'" in message
    with pytest.raises(AssertionError) as raised:
        pk.assert_said("zzzz qqqq", "GREET", EN)
    assert "no sentence of the table equals the text, and none is near it" in str(raised.value)


def test_a_long_text_is_quoted_short_and_on_one_line():
    with pytest.raises(AssertionError) as raised:
        pk.assert_said("x\n" * 400, "BYE", EN)
    got = [line for line in str(raised.value).splitlines() if line.startswith("  got:")]
    assert len(got) == 1 and got[0].endswith("...") and len(got[0]) < 330 and "\\n" in got[0]


def test_a_key_the_table_lacks_and_a_field_the_key_lacks_are_errors_not_failures():
    with pytest.raises(KeyError) as raised:
        pk.said("x", "NO_SUCH_KEY", EN)
    assert "NO_SUCH_KEY" in str(raised.value)
    with pytest.raises(ValueError) as raised:
        pk.said("Goodbye.", "BYE", EN, name="Ana")
    assert "BYE has no field 'name'" in str(raised.value)
    with pytest.raises(ValueError):
        pk.assert_said("Goodbye.", "BYE", EN, name="Ana")


def test_the_real_table_round_trips_for_every_key_in_both_languages(monkeypatch):
    monkeypatch.undo()                                     # the real table, not this file's
    import string
    seen = 0
    for language, table in phrases.TABLE.items():
        cfg = {"language": language}
        for key, template in table.items():
            names = [n for _lit, n, _spec, _conv in string.Formatter().parse(template) if n is not None]
            fields = {n: f"v{i}" for i, n in enumerate(dict.fromkeys(names))}
            sentence = template.format(**fields)           # the oracle: str.format, as phrases.text writes it
            assert pk.said(sentence, key, cfg, **fields), (language, key)
            if fields:
                wrong = {**fields, next(iter(fields)): "other"}
                assert not pk.said(sentence, key, cfg, **wrong), (language, key)
            seen += 1
    assert seen == sum(len(t) for t in phrases.TABLE.values()) and seen >= 1700


def test_which_on_the_real_table_gives_a_key_whose_sentence_is_the_text(monkeypatch):
    monkeypatch.undo()
    import string
    for language in phrases.TABLE:
        cfg = {"language": language}
        for key in sorted(phrases.TABLE[language])[::40]:
            template = phrases.TABLE[language][key]
            names = [n for _lit, n, _spec, _conv in string.Formatter().parse(template) if n is not None]
            sentence = template.format(**{n: "v" for n in names})
            found = pk.which(sentence, cfg)
            assert found is not None, (language, key)
            key2, fields = found
            assert phrases.TABLE[language][key2].format(**fields) == sentence, (language, key, key2)


def _parts():
    """(package, language, {key: sentence}) of every file of runtime/phrases_parts/ (the part files are the oracle: their own sentences)."""
    import json
    out = []
    for path in sorted((HERE.parent / "phrases_parts").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        language = "pt-BR" if path.name.endswith(".pt-BR.json") else "en"
        out.append((data["package"], language, data["table"]))
    return out


def parts_checks(said):
    import string
    seen = 0
    for _package, language, table in _parts():
        for key, template in table.items():
            names = [n for _lit, n, _spec, _conv in string.Formatter().parse(template) if n is not None]
            fields = {n: f"v{i}" for i, n in enumerate(dict.fromkeys(names))}
            assert said(template.format(**fields), key, {"language": language}, **fields), (language, key)
            seen += 1
    assert seen > 0, "no part file was read"


def test_a_sentence_of_a_part_is_covered_like_one_of_the_core(monkeypatch):
    monkeypatch.undo()                                     # the real table: the core and the parts, as phrases.py builds it
    assert _parts(), "there is no part file to check"
    parts_checks(pk.said)


# --- vacuity: a planted wrong `said` or `which` makes the check that guards it fail ---


def test_a_said_that_ignores_the_fields_fails_the_field_checks():
    def ignores_fields(text, key, cfg=None, **fields):
        return pk.said(text, key, cfg)
    with pytest.raises(AssertionError):
        field_checks(ignores_fields)


def test_a_said_that_ignores_the_language_fails_the_language_checks():
    def always_english(text, key, cfg=None, **fields):
        return pk.said(text, key, EN, **fields)
    with pytest.raises(AssertionError):
        language_checks(always_english)


def test_a_said_that_treats_the_template_as_a_pattern_fails_the_literal_checks():
    import re

    def as_pattern(text, key, cfg=None, **fields):
        return re.fullmatch(TABLE["en"][key].replace("{amount}", ".*"), text) is not None
    with pytest.raises(AssertionError):
        literal_checks(as_pattern)


def test_a_which_that_answers_the_first_key_fails_the_naming_checks():
    def first_key(text, cfg=None):
        return "GREET", {}
    with pytest.raises(AssertionError):
        naming_checks(first_key)


def test_a_table_without_the_parts_fails_the_parts_checks(monkeypatch):
    monkeypatch.undo()
    keys = {language: set() for language in ("en", "pt-BR")}
    for _package, language, table in _parts():
        keys[language] |= set(table)
    core_only = {language: {k: v for k, v in table.items() if k not in keys[language]} for language, table in phrases.TABLE.items()}
    monkeypatch.setattr(phrases, "TABLE", core_only)
    with pytest.raises(KeyError):
        parts_checks(pk.said)
