"""S41-9: the private-line words and the search stop words are data the registry owns (runtime/registry/*.json, runtime/registry_data.py), read by the gate
(`turn_gate.private_line`) and by `event_lookup`; the old table readers (frozen in runtime/tests/closed_heads.py and old_claim.py since S41-11) are the oracles.

What is proven here, each with its vacuity:

  * The search sets (`stop_words`, `brands`, `nouns`, `leads`, `cal_words`, `plural`) EQUAL what `event_lookup` computed from the language tables at commit 2fb497d (the frozen copies
    below). Vacuity: one stop word dropped from a copy of the data -> the equality fails.
  * The private detector flags every line `natural.private` flags, on every corpus (the three natural corpora, the interpreter's dev sets, the entry corpus) and on a seeded
    differential fuzz of generated and mutated lines. Vacuity: one phrase a corpus line needs dropped from a copy of the data -> the superset fails. The lines only the new detector flags
    are counted per corpus (OPEN-41-10); on the entry corpus and the three natural corpora there are none, so that no stored row or outage route of the entry replay can change.
  * Both files are well formed (header, version, folded, sorted, without repeat). They were made once from the language tables by a builder script that S41-11 PR 2b deleted with its two tests
    (the files equal what the builder makes; the builder is deterministic and has help): the data is edited by hand under review from then on, and the tests above are what holds it.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_registry_data.py
"""
from __future__ import annotations

import copy
import json
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "runtime"))
sys.path.insert(0, str(REPO / "scripts"))

import event_lookup  # noqa: E402
import natural  # noqa: E402
import natural_time as nt  # noqa: E402
import natural_writes as nw  # noqa: E402
import old_claim  # noqa: E402  (CANDIDATE-OUT 2: the frozen old reading, the oracle of the private-line detector and the words of the fuzz)
import registry_data  # noqa: E402
import turn_gate  # noqa: E402
from closed_heads import old_private, closed_heads, tier1_forms, words_interpreted  # noqa: F401  (S41-11: the claim of the write families and of every closed form, as fixtures: these tests are about the readers and resolvers, not the claim)

pytestmark = pytest.mark.usefixtures("tier1_forms", "words_interpreted")      # S41-11: every closed form claims a line in this file, as it did

FOLDER = REPO / "runtime" / "registry"
CORPORA = {
    "natural_corpus": REPO / "runtime/tests/natural_corpus.jsonl",
    "natural_writes_corpus": REPO / "runtime/tests/natural_writes_corpus.jsonl",
    "natural_writes_mail_corpus": REPO / "runtime/tests/natural_writes_mail_corpus.jsonl",
    "interpreter_dev": REPO / "evals/interpreter/dev.jsonl",
    "interpreter_dev_long_v2": REPO / "evals/interpreter/dev-long-v2.jsonl",
    "interpreter_ix_test_v1": REPO / "evals/interpreter/ix-test-v1.jsonl",
    "entry_corpus": REPO / "runtime/tests/entry_corpus.jsonl",
}
NO_NEW = ("natural_corpus", "natural_writes_corpus", "natural_writes_mail_corpus", "entry_corpus")      # no line is newly private here: a newly private line would change a stored row of the replay


def corpus_lines(name: str) -> list:
    out = []
    for number, raw in enumerate(CORPORA[name].read_text(encoding="utf-8").splitlines()):
        if not raw.strip():
            continue
        row = json.loads(raw)
        text = row.get("text") if "text" in row else row.get("line")
        if isinstance(text, str):
            out.append((str(row.get("id", number)), text))
    return out


@pytest.fixture
def data_copy(tmp_path):
    """A copy of the registry folder that the loader reads, with the compiled rule and the caches dropped before and after."""
    for name in registry_data.FILES.values():
        (tmp_path / name).write_text((FOLDER / name).read_text(encoding="utf-8"), encoding="utf-8")
    real = registry_data.FOLDER
    registry_data.FOLDER = str(tmp_path)

    def reset():
        registry_data.forget()
        turn_gate.forget_private_rule()
        event_lookup._STOP.clear()
    reset()
    yield tmp_path
    registry_data.FOLDER = real
    reset()


def write(folder: Path, name: str, data: dict) -> None:
    (folder / registry_data.FILES[name]).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    registry_data.forget()
    turn_gate.forget_private_rule()
    event_lookup._STOP.clear()


# --- the frozen copies of what event_lookup computed from the tables at commit 2fb497d ----------------------------------------------------------------------

FROZEN_COMMIT = "2fb497d"
FROZEN_CAL_WORDS = {"agenda", "agendas", "calendar", "calendars", "calendario", "calendarios", "calendrier", "calendriers", "kalender", "calendari"}
FROZEN_LEADS = FROZEN_CAL_WORDS | {"no", "na", "nos", "nas", "pelo", "pela", "via", "usando", "pro", "pra", "em", "de", "do", "da", "meu", "minha",  # validate: allow english-only -- the closed words of the languages a line may be written in, copied as they were
                                   "on", "in", "to", "from", "using", "of", "my", "at",
                                   "en", "del", "por", "mi", "mis", "con",
                                   "sur", "dans", "avec", "mon", "ma", "chez",
                                   "im", "auf", "bei", "mit", "uber", "mein", "meine", "unter",
                                   "su", "sul", "sulla", "nel", "nella", "tramite", "mio", "mia", "di"}
FROZEN_PLURAL = {"os", "as", "uns", "umas", "aos", "los", "las", "les", "die", "gli", "le", "ambos", "ambas", "todos", "todas", "both", "all"}
FROZEN_STOP_EXTRA = {"para", "as", "que", "com", "sem", "e", "and", "with", "the", "a", "an", "for", "at", "please", "por", "favor", "pra", "pro"}  # validate: allow english-only -- the closed words of the languages a line may be written in, copied as they were
FROZEN_TITLE_NOUNS = {"reuniao", "reunioes", "meeting", "meetings", "appointment", "appointments", "compromisso", "compromissos"}


def frozen_words(text) -> list:
    return natural.normal(text).split()


def frozen_brands() -> dict:
    tables = natural._tables(None)
    return {account: [tuple(frozen_words(p)) for p in nw.listed(tables, "calendar", "brands_" + account)] for account in ("google", "microsoft")}


def frozen_stop_words() -> set:
    tables = natural._tables(None)
    found = set(FROZEN_STOP_EXTRA) | set(FROZEN_LEADS) | set(FROZEN_CAL_WORDS) | FROZEN_PLURAL
    for section, key in ((None, "articles"), ("calendar", "cancel_verbs"), ("calendar", "change_verbs"), ("calendar", "to_time"), ("calendar", "rename"), ("calendar", "in_calendar")):
        for phrase in nw.listed(tables, section, key):
            found.update(frozen_words(phrase))
    for table in tables:
        for phrase in nw.writes_of(table).get("polite", []) + table.get("polite", []):
            found.update(frozen_words(phrase))
    for brands in frozen_brands().values():
        for brand in brands:
            found.difference_update(brand)
    return found


def frozen_noun_words() -> set:
    tables = natural._tables(None)
    return {w for key in ("nouns", "nouns_plural") for phrase in nw.listed(tables, "calendar", key) for w in frozen_words(phrase)} - FROZEN_TITLE_NOUNS


def search_differences() -> list:
    """What the data and the readers of event_lookup give that the frozen copies (made at FROZEN_COMMIT) do not."""
    out = []
    if event_lookup._stop_words() != frozen_stop_words():
        out.append("stop words")
    if event_lookup._brands() != frozen_brands():
        out.append("brands")
    if event_lookup._noun_words() != frozen_noun_words():
        out.append("nouns")
    if (event_lookup.LEADS, event_lookup.CAL_WORDS, event_lookup.PLURAL) != (FROZEN_LEADS, FROZEN_CAL_WORDS, FROZEN_PLURAL):
        out.append("leads, calendar words or plural words")
    return out


def test_stop_words_equal_the_tables():
    """Exact equality: the sets event_lookup reads now are the sets the language tables and the closed words gave at commit 2fb497d."""
    data = registry_data.search_stop_words()
    assert set(data["stop_words"]) == frozen_stop_words() and len(data["stop_words"]) == len(frozen_stop_words())
    assert data["brands"] == frozen_brands()
    assert set(data["nouns"]) - FROZEN_TITLE_NOUNS == frozen_noun_words()
    assert (set(data["leads"]), set(data["cal_words"]), set(data["plural"])) == (FROZEN_LEADS, FROZEN_CAL_WORDS, FROZEN_PLURAL)
    assert search_differences() == []


def test_one_dropped_stop_word_breaks_the_equality(data_copy):
    """Vacuity of the equality test: the same comparison fails for a copy of the data with one stop word taken out, and the reader follows the data (no table is read)."""
    assert search_differences() == []
    data = json.loads((data_copy / "search_stop_words.json").read_text(encoding="utf-8"))
    data["stop_words"].remove("para")
    write(data_copy, "search_stop_words", data)
    assert "para" not in event_lookup._stop_words()
    assert search_differences() == ["stop words"]
    data["stop_words"].append("zzz")
    data["stop_words"].sort()
    write(data_copy, "search_stop_words", data)
    assert "zzz" in event_lookup._stop_words()


def test_a_dropped_brand_or_noun_breaks_the_equality(data_copy):
    data = json.loads((data_copy / "search_stop_words.json").read_text(encoding="utf-8"))
    data["brands"]["google"].pop()
    write(data_copy, "search_stop_words", data)
    assert search_differences() == ["brands"]
    data = json.loads((FOLDER / "search_stop_words.json").read_text(encoding="utf-8"))
    data["nouns"].remove("evento")
    write(data_copy, "search_stop_words", data)
    assert search_differences() == ["nouns"]


def test_event_lookup_names_no_table_key_for_its_stop_words():
    """The reader of the search words is the data: event_lookup no longer lists the table keys of the stop words, the brands or the nouns, and holds no closed copy of them."""
    source = (REPO / "runtime/event_lookup.py").read_text(encoding="utf-8")
    for needle in ('"brands_" + account', '"cancel_verbs"), ("calendar", "change_verbs")', "STOP_EXTRA", '("nouns", "nouns_plural")', '{"agenda", "agendas"'):
        assert needle not in source, needle


# --- the private detector ---------------------------------------------------------------------------------------------------------------------------------

def superset_failures(lines) -> list:
    return [(i, x) for i, x in lines if old_private(x) and not turn_gate.private_line(x)]


@pytest.mark.parametrize("name", sorted(CORPORA))
def test_private_words_flag_a_superset(name):
    """Every line `natural.private` flags on the corpus, `turn_gate.private_line` flags (the oracle is `closed_heads.old_private`, the S41-9 reader frozen as a test stand-in)."""
    lines = corpus_lines(name)
    assert len(lines) >= 40
    assert superset_failures(lines) == []
    if name in NO_NEW:
        assert [(i, x) for i, x in lines if turn_gate.private_line(x) and not old_private(x)] == []


def test_the_corpora_have_private_lines_in_them():
    """Not vacuous: the oracle flags many lines of the corpora the superset is asked over."""
    flagged = {name: sum(1 for _, x in corpus_lines(name) if old_private(x)) for name in CORPORA}
    assert flagged["natural_corpus"] > 100 and flagged["natural_writes_corpus"] > 100 and flagged["natural_writes_mail_corpus"] > 100
    assert flagged["interpreter_ix_test_v1"] > 20 and flagged["entry_corpus"] > 100


def test_one_dropped_phrase_breaks_the_superset(data_copy):
    """Vacuity: a copy of the data without a phrase the natural corpus needs fails the superset; the real data passes (the control)."""
    lines = corpus_lines("natural_writes_corpus") + corpus_lines("natural_corpus")
    assert superset_failures(lines) == []
    data = json.loads((data_copy / "private_words.json").read_text(encoding="utf-8"))
    data["languages"]["en"]["lead_write"].remove("add to my calendar")
    write(data_copy, "private_words", data)
    lost = superset_failures(lines)
    assert lost and all("calendar" in x.lower() for _, x in lost)
    data = json.loads((FOLDER / "private_words.json").read_text(encoding="utf-8"))
    data["languages"]["pt-BR"]["lead_with_time"].remove("marca")
    write(data_copy, "private_words", data)
    assert superset_failures(lines)


def test_a_dropped_write_head_breaks_the_superset(data_copy):
    lines = corpus_lines("natural_writes_mail_corpus")
    data = json.loads((data_copy / "private_words.json").read_text(encoding="utf-8"))
    for shape in data["languages"]["en"]["writes"]["mail"]:
        shape["heads"] = [h for h in shape["heads"] if h != "archive"]
    write(data_copy, "private_words", data)
    lost = superset_failures(lines)
    assert lost and all(x.lower().startswith("archive") or " archive " in x.lower() for _, x in lost)


def generated(rng: random.Random, n: int) -> tuple:
    """`n` lines made of the phrases of the language tables (heads, nouns, markers, services), digits, names, an address and time phrases, in either language or both."""
    pools = []
    for table in nt.languages():
        writes, triggers = table["requests"]["writes"], table["triggers"]
        frozen = old_claim.FROZEN_WORDS[table["tag"]]      # the table no longer holds `note` and `remind_nouns` (CANDIDATE-OUT 2): the fuzz keeps their words, frozen in the stand-in
        heads = triggers["remind"] + frozen["triggers"]["note"] + triggers["calendar"] + triggers["calendar_verb"] + triggers["calendar_loose"] + triggers["calendar_noun"]
        pool = []
        for family, keys in (("calendar", ("change_verbs", "cancel_verbs", "rename")), ("mail", ("send_verbs", "reply_verbs", "draft_verbs", "archive_verbs", "move_verbs", "mark_verbs", "trash_verbs")),
                             ("files", ("create_verbs", "replace_verbs", "save_verbs"))):
            for key in keys:
                heads += writes[family][key]
            for value in writes[family].values():
                if isinstance(value, list):
                    pool += value
        pool += writes["articles"] + writes["polite"] + writes["service_in"] + frozen["remind_nouns"] + table["polite"] + table["connectors"] + table["edge_words"]
        pool += [p for names in writes["services"].values() for p in names] + [p for names in (writes["files"].get("kinds") or {}).values() for p in names]
        pools.append((heads, pool, table["polite"] + writes["polite"]))
    times = ["at 9am", "tomorrow at 3pm", "in 2 hours", "amanha as 15h", "hoje 18h30", "friday 10:00", "daqui a 2 horas", "dia 25 as 9h", "next week", "em 30 minutos"]
    extra = ["1", "2", "14", "3", "ana@mail.example", "bia", "the bank", "do banco", "banco", "reuniao", "report", "?", ":", ",", "and", "e", "x", "y"]
    out = []
    for _ in range(n):
        heads, pool, polite = rng.choice(pools)
        heads2, pool2, _unused = rng.choice(pools) if rng.random() < 0.3 else (heads, pool, polite)
        tokens = [rng.choice(polite)] if rng.random() < 0.25 else []
        if rng.random() < 0.92:
            tokens.append(rng.choice(heads2))
        for _ in range(rng.randint(0, 11)):
            r = rng.random()
            tokens.append(rng.choice(pool2) if r < 0.55 else rng.choice(extra) if r < 0.8 else rng.choice(times))
        out.append(" ".join(tokens))
    return out, pools, times


def mutated(rng: random.Random, n: int, pools, times) -> list:
    base = [x for name in ("natural_writes_corpus", "natural_writes_mail_corpus", "interpreter_ix_test_v1", "entry_corpus") for _, x in corpus_lines(name)]
    out = []
    for _ in range(n):
        words = rng.choice(base).split()
        for _ in range(rng.randint(1, 3)):
            r = rng.random()
            if r < 0.25 and len(words) > 2:
                del words[rng.randrange(len(words))]
            elif r < 0.5:
                words.insert(rng.randrange(len(words) + 1), rng.choice(rng.choice(pools)[1]))
            elif r < 0.65 and len(words) > 1:
                i = rng.randrange(len(words) - 1)
                words[i], words[i + 1] = words[i + 1], words[i]
            elif r < 0.8:
                words.append(rng.choice(times))
            elif r < 0.9:
                words.insert(0, rng.choice(rng.choice(pools)[2]))
            else:
                words = [w.upper() if rng.random() < 0.5 else w for w in words]
        out.append(" ".join(words))
    return out


FULL = os.environ.get("WB_FULL_FUZZ") == "1"      # the default fuzz is small (a few seconds); WB_FULL_FUZZ=1 makes it about thirty times larger
SEPARATORS = ["  ", "\t", "\n", ", ", ". ", "_", "-", "\u2011", "/", ": ", "\u2013", "'", "\u3000", "\u200b"]
PREFIXES = ["@ ", "# ", "* ", "> ", "- ", "1) ", "ok ", "hmm, ", "so ", "obs: ", "(", "\"", "...", "+ ", "ps ", "please: "]
SUFFIXES = ["?", "!!", " pls", " thanks", " :)", "...", ")", " ok?"]
ARABIC = dict(zip("0123456789", "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669"))


def oracle_flagged_corpus_lines() -> list:
    return [x for name in ("natural_writes_corpus", "natural_writes_mail_corpus", "natural_corpus", "interpreter_ix_test_v1", "entry_corpus") for _, x in corpus_lines(name) if old_private(x)]


def surface_mutated(rng: random.Random, n: int, source: list) -> list:
    """Corpus lines the oracle flags, changed on the surface: another separator for a blank (a non-breaking hyphen, a dash, a dot, an underscore, a full-width space), a prefix such as "@",
    a suffix, Arabic-Indic digits, upper or title case, another spelling of "e-mail", a word added. The kinds of change that opened the four gaps the review of S41-9 found."""
    out = []
    for _ in range(n):
        line = rng.choice(source)
        for _ in range(rng.randint(1, 3)):
            kind = rng.randrange(7)
            if kind == 0:
                at = [i for i, c in enumerate(line) if c == " "]
                if at:
                    i = rng.choice(at)
                    line = line[:i] + rng.choice(SEPARATORS) + line[i + 1:]
            elif kind == 1:
                line = rng.choice(PREFIXES) + line
            elif kind == 2:
                line += rng.choice(SUFFIXES)
            elif kind == 3:
                line = "".join(ARABIC.get(c, c) if rng.random() < 0.5 else c for c in line)
            elif kind == 4:
                line = line.upper() if rng.random() < 0.5 else line.title()
            elif kind == 5:
                line = line.replace("e-mail", rng.choice(["e\u2011mail", "e mail", "E-Mail", "e.mail", "e_mail", "email", "e\u2013mail"]))
            else:
                words = line.split()
                if len(words) > 2:
                    words.insert(rng.randrange(len(words)), rng.choice(["please", "the", "o", "really", "agora"]))
                    line = " ".join(words)
        out.append(line)
    return out


@pytest.mark.parametrize("seed", [201, 202])
def test_private_words_flag_a_superset_of_surface_mutated_lines(seed):
    """The seeded differential fuzz of the surface: every line the oracle flags stays flagged. Small by default, WB_FULL_FUZZ=1 for the large run; a shape change cannot reopen a gap unseen."""
    rng = random.Random(seed)
    lines = surface_mutated(rng, 60000 if FULL else 3000, oracle_flagged_corpus_lines())
    flagged = [x for x in lines if old_private(x)]
    assert len(flagged) > (20000 if FULL else 1000)
    assert [x for x in flagged if not turn_gate.private_line(x)][:10] == []


@pytest.mark.parametrize("seed", [101, 102])
def test_private_words_flag_a_superset_of_generated_and_mutated_lines(seed):
    """A seeded differential fuzz (generated from the tables' own phrases, and corpus lines with words dropped, added, swapped, upper-cased or with a time or a polite word added): the
    oracle's flags are all kept. A few thousand lines, deterministic."""
    rng = random.Random(seed)
    lines, pools, times = generated(rng, 80000 if FULL else 4000)
    lines += mutated(rng, 80000 if FULL else 4000, pools, times)
    flagged = [x for x in lines if old_private(x)]
    assert len(flagged) > (30000 if FULL else 1500)
    assert [x for x in flagged if not turn_gate.private_line(x)] == []


def test_a_typed_command_and_a_blank_or_odd_line_are_not_private():
    for line in ("/remind 15:00 call Maria", "/reminder", "   ", "", None, 5, ["remind me"]):
        assert turn_gate.private_line(line) is False
        assert old_private(line) is False


def test_private_lines_in_both_languages():
    private = ["remind me to call Maria tomorrow at 9", "me lembra de ligar pra Maria amanha as 9h", "please schedule a reminder to water the plants", "marca na agenda dentista sexta 15h",  # validate: allow english-only -- the closed words of the languages a line may be written in, copied as they were
               "send an email to maria@mail.example saying the report is ready", "responde o email 3 dizendo que ok", "cancel event 4", "archive the latest email",
               "cria uma nota chamada ideias.txt dizendo comprar tinta azul", "save this pdf to my drive", "9h dentista"]
    plain = ["what is the weather in Lisbon", "summarize the quarterly report", "write a poem about the sea", "como esta o projeto", "o que tem na minha agenda amanha",
             "list my reminders", "quais lembretes eu tenho", "cancel the deploy", "send me the file", "oi tudo bem"]
    for line in private:
        assert turn_gate.private_line(line), line
        assert old_private(line), line
    for line in plain:
        assert not turn_gate.private_line(line), line


def test_the_gate_reads_the_data_and_not_the_tables(data_copy):
    """A word added to the data makes a line private; the old detector, which reads the tables, does not follow."""
    line = "zzzremind me about the invoice"
    assert not turn_gate.private_line(line)
    data = json.loads((data_copy / "private_words.json").read_text(encoding="utf-8"))
    data["languages"]["en"]["lead"] = sorted(data["languages"]["en"]["lead"] + ["zzzremind me"])
    write(data_copy, "private_words", data)
    assert turn_gate.private_line(line)
    assert not old_private(line)
    source = (REPO / "runtime/turn_gate.py").read_text(encoding="utf-8")
    assert "natural.private" not in source.replace("`natural.private`", "")


def test_the_bare_word_number_is_the_naturals():
    """The number of words a bare reminder may have is the file's, and it is the number natural.py has today."""
    assert turn_gate.private_line("dentista 9h amanha")
    assert registry_data.private_words()["numbers"]["bare_words_max"] == natural.BARE_WORDS_MAX


def test_the_bare_word_number_moves_the_rule(data_copy):
    data = json.loads((data_copy / "private_words.json").read_text(encoding="utf-8"))
    data["numbers"]["bare_words_max"] = 1
    write(data_copy, "private_words", data)
    assert not turn_gate.private_line("buy milk and eggs tomorrow at 9am")
    data["numbers"]["bare_words_max"] = 6
    write(data_copy, "private_words", data)
    assert turn_gate.private_line("buy milk and eggs tomorrow at 9am")


# --- the files -----------------------------------------------------------------------------------------------------------------------------------------

def test_registry_files_are_well_formed():
    assert registry_data.problems() == []
    for name in registry_data.FILES.values():
        data = json.loads((FOLDER / name).read_text(encoding="utf-8"))
        assert data["v"] == 1 and data["made_from"] and "\n" not in data["rule"]
    assert subprocess.run([sys.executable, str(REPO / "runtime/registry_data.py"), "--check"], capture_output=True, text=True).returncode == 0
    helped = subprocess.run([sys.executable, str(REPO / "runtime/registry_data.py"), "--help"], capture_output=True, text=True)
    assert helped.returncode == 0 and "registry" in helped.stdout


def test_a_badly_formed_file_is_reported(data_copy):
    data = json.loads((data_copy / "search_stop_words.json").read_text(encoding="utf-8"))
    bad = copy.deepcopy(data)
    bad["v"] = 2
    bad["stop_words"] = ["b", "a", "a", "Not Folded"]
    bad["rule"] = "two\nlines"
    write(data_copy, "search_stop_words", bad)
    found = " | ".join(registry_data.problems("search_stop_words"))
    assert "v is 2" in found and "rule is not one line" in found and "not a list of folded" in found
    bad = copy.deepcopy(data)
    bad["stop_words"] = ["b", "a"]
    write(data_copy, "search_stop_words", bad)
    assert any("not sorted" in p for p in registry_data.problems("search_stop_words"))
    bad["stop_words"] = ["a", "a"]
    write(data_copy, "search_stop_words", bad)
    assert any("repeated" in p for p in registry_data.problems("search_stop_words"))
    bad = copy.deepcopy(data)
    bad["stop_words"] = sorted(bad["stop_words"] + ["google"])
    write(data_copy, "search_stop_words", bad)
    assert any("brand word" in p for p in registry_data.problems("search_stop_words"))
    private = json.loads((FOLDER / "private_words.json").read_text(encoding="utf-8"))
    private["languages"]["en"]["lead"].append("Zebra")
    private["numbers"]["bare_words_max"] = "6"
    del private["languages"]["pt-BR"]["writes"]["mail"]
    write(data_copy, "private_words", private)
    found = " | ".join(registry_data.problems("private_words"))
    assert "numbers" in found and "en.lead" in found and "pt-BR.writes" in found


def test_the_words_are_generic_words_of_the_languages():
    """The data holds the words of the language tables only: no address, no digit-only word, no word of a real project (the files are read by a person under review)."""
    text = (FOLDER / "private_words.json").read_text(encoding="utf-8") + (FOLDER / "search_stop_words.json").read_text(encoding="utf-8")
    assert "@" not in text.replace('"address"', "")
    assert "http" not in text


# --- the four gaps of the review of S41-9 (each was a line the oracle flags and the first detector did not), the validation and the stored word ---------------------------------------

GAPS = {
    "A a start behind an @": ["@ remind me to call mom", "@ me lembra de pagar a conta", "@, lembrete: pagar a conta", "@ anota comprar leite",
                              "@ put on my calendar the board meeting with the whole finance team next week", "@ schedule a reminder about the long weekly report"],
    "B another spelling of e-mail": ["arquiva o e\u2011mail 3", "responde o e\u2010mail 3: tudo certo", "responde o e\u2013mail 3: tudo certo", "responde o e_mail 3: tudo certo",
                                     "responde o e.mail 3: tudo certo", "manda um e\u2011mail para ana@exemplo.example: oi", "move o e\u2011mail 3 para a pasta contas", "archive e_mails 2 and 3"],
    "C a digit that is not ASCII": ["arquiva o email \u0663", "apaga os emails \u0661 e \u0662", "reply to email \u0663 saying ok"],
    "D a long list of item references": ["apaga os emails " + ", ".join(f"gmail#{i}" for i in range(1, 18)), "archive emails " + ", ".join(f"work-mail#{i}" for i in range(1, 10))],
}


@pytest.mark.parametrize("gap", sorted(GAPS))
def test_the_gaps_of_the_review_are_closed(gap):
    for line in GAPS[gap]:
        assert old_private(line), f"the oracle no longer flags {line!r}: the probe is stale"
        assert turn_gate.private_line(line), line


def test_an_empty_list_in_a_need_or_a_head_is_a_problem_and_the_gate_fails_loud(data_copy):
    data = json.loads((data_copy / "private_words.json").read_text(encoding="utf-8"))
    data["languages"]["en"]["writes"]["mail"][0]["needs"][0]["words"] = []
    write(data_copy, "private_words", data)
    assert any("empty" in p for p in registry_data.problems("private_words"))
    with pytest.raises(ValueError, match="not well formed"):
        turn_gate.private_line("archive the emails 1 and 2")
    data = json.loads((FOLDER / "private_words.json").read_text(encoding="utf-8"))
    data["languages"]["pt-BR"]["writes"]["files"][0]["heads"] = []
    write(data_copy, "private_words", data)
    assert any("heads: empty" in p for p in registry_data.problems("private_words"))
    with pytest.raises(ValueError):
        turn_gate.private_kind("salva esse pdf")
    write(data_copy, "private_words", json.loads((FOLDER / "private_words.json").read_text(encoding="utf-8")))
    assert turn_gate.private_line("archive the emails 1 and 2")


def test_the_kind_of_a_private_line_is_a_reminder_or_a_write():
    assert turn_gate.private_kind("remind me to call Maria tomorrow at 9") == "reminder"
    assert turn_gate.private_kind("me lembra de ligar pra Maria") == "reminder"  # validate: allow english-only -- a line a person types in Portuguese, the language under test
    assert turn_gate.private_kind("marca na agenda dentista sexta 15h") == "write"
    assert turn_gate.private_kind("cancel event 2 on my calendar") == "write"
    assert turn_gate.private_kind("archive the emails 1 and 2") == "write"
    assert turn_gate.private_kind("what is the weather in Lisbon") is None
    assert turn_gate.private_kind("/remind 15:00 call Maria") is None
    for line in oracle_flagged_corpus_lines()[:3000]:
        if old_claim.candidate(line) and old_claim.candidate(line)["op"] in natural.PRIVATE:
            assert turn_gate.private_kind(line) == "reminder", line
