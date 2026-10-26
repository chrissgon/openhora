"""S41-9: the private-line words and the search stop words are data the registry owns (runtime/registry/*.json, runtime/registry_data.py), read by the gate
(`turn_gate.private_line`) and by `event_lookup`; the old table readers are the oracles.

What is proven here, each with its vacuity:

  * The search sets (`stop_words`, `brands`, `nouns`, `leads`, `cal_words`, `plural`) EQUAL what `event_lookup` computed from the language tables at commit 2fb497d (the frozen copies
    below). Vacuity: one stop word dropped from a copy of the data -> the equality fails.
  * The private detector flags every line `natural.private` flags, on every corpus (the three natural corpora, the interpreter's dev sets, the entry corpus) and on a seeded
    differential fuzz of generated and mutated lines. Vacuity: one phrase a corpus line needs dropped from a copy of the data -> the superset fails. The lines only the new detector flags
    are counted per corpus (OPEN-41-10); on the entry corpus and the three natural corpora there are none, so that no stored row or outage route of the entry replay can change.
  * Both files are well formed (header, version, folded, sorted, without repeat) and equal what scripts/registry_build.py makes from the tables while the tables exist.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_registry_data.py
"""
from __future__ import annotations

import copy
import json
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
import registry_build  # noqa: E402
import registry_data  # noqa: E402
import turn_gate  # noqa: E402

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
    return [(i, x) for i, x in lines if natural.private(x) and not turn_gate.private_line(x)]


@pytest.mark.parametrize("name", sorted(CORPORA))
def test_private_words_flag_a_superset(name):
    """Every line `natural.private` flags on the corpus, `turn_gate.private_line` flags (the oracle stays in runtime/natural.py until S41-11)."""
    lines = corpus_lines(name)
    assert len(lines) >= 40
    assert superset_failures(lines) == []
    if name in NO_NEW:
        assert [(i, x) for i, x in lines if turn_gate.private_line(x) and not natural.private(x)] == []


def test_the_corpora_have_private_lines_in_them():
    """Not vacuous: the oracle flags many lines of the corpora the superset is asked over."""
    flagged = {name: sum(1 for _, x in corpus_lines(name) if natural.private(x)) for name in CORPORA}
    assert flagged["natural_corpus"] > 100 and flagged["natural_writes_corpus"] > 100 and flagged["natural_writes_mail_corpus"] > 100
    assert flagged["interpreter_ix_test_v1"] > 20 and flagged["entry_corpus"] > 100


def test_one_dropped_phrase_breaks_the_superset(data_copy):
    """Vacuity: a copy of the data without a phrase the natural corpus needs fails the superset; the real data passes (the control)."""
    lines = corpus_lines("natural_writes_corpus") + corpus_lines("natural_corpus")
    assert superset_failures(lines) == []
    data = json.loads((data_copy / "private_words.json").read_text(encoding="utf-8"))
    data["languages"]["en"]["lead"].remove("add to my calendar")
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
        heads = triggers["remind"] + triggers["note"] + triggers["calendar"] + triggers["calendar_verb"] + triggers["calendar_loose"] + triggers["calendar_noun"]
        pool = []
        for family, keys in (("calendar", ("change_verbs", "cancel_verbs", "rename")), ("mail", ("send_verbs", "reply_verbs", "draft_verbs", "archive_verbs", "move_verbs", "mark_verbs", "trash_verbs")),
                             ("files", ("create_verbs", "replace_verbs", "save_verbs"))):
            for key in keys:
                heads += writes[family][key]
            for value in writes[family].values():
                if isinstance(value, list):
                    pool += value
        pool += writes["articles"] + writes["polite"] + writes["service_in"] + table["remind_nouns"] + table["polite"] + table["connectors"] + table["edge_words"]
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


@pytest.mark.parametrize("seed", [101, 102])
def test_private_words_flag_a_superset_of_generated_and_mutated_lines(seed):
    """A seeded differential fuzz (generated from the tables' own phrases, and corpus lines with words dropped, added, swapped, upper-cased or with a time or a polite word added): the
    oracle's flags are all kept. A few thousand lines, deterministic."""
    rng = random.Random(seed)
    lines, pools, times = generated(rng, 4000)
    lines += mutated(rng, 4000, pools, times)
    flagged = [x for x in lines if natural.private(x)]
    assert len(flagged) > 1500
    assert [x for x in flagged if not turn_gate.private_line(x)] == []


def test_a_typed_command_and_a_blank_or_odd_line_are_not_private():
    for line in ("/remind 15:00 call Maria", "/reminder", "   ", "", None, 5, ["remind me"]):
        assert turn_gate.private_line(line) is False
        assert natural.private(line) is False


def test_private_lines_in_both_languages():
    private = ["remind me to call Maria tomorrow at 9", "me lembra de ligar pra Maria amanha as 9h", "please schedule a reminder to water the plants", "marca na agenda dentista sexta 15h",  # validate: allow english-only -- the closed words of the languages a line may be written in, copied as they were
               "send an email to maria@mail.example saying the report is ready", "responde o email 3 dizendo que ok", "cancel event 4", "archive the latest email",
               "cria uma nota chamada ideias.txt dizendo comprar tinta azul", "save this pdf to my drive", "9h dentista"]
    plain = ["what is the weather in Lisbon", "summarize the quarterly report", "write a poem about the sea", "como esta o projeto", "o que tem na minha agenda amanha",
             "list my reminders", "quais lembretes eu tenho", "cancel the deploy", "send me the file", "oi tudo bem"]
    for line in private:
        assert turn_gate.private_line(line), line
        assert natural.private(line), line
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
    assert not natural.private(line)
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


def test_the_files_equal_what_the_builder_makes_from_the_tables():
    """While the tables exist (until S41-11 deletes them and the builder), the committed files equal the builder's output; the commit name is not compared."""
    built = registry_build.build("x")
    for name, data in built.items():
        have = json.loads((FOLDER / name).read_text(encoding="utf-8"))
        have["made_from"] = "x"
        assert have == data, name
    assert subprocess.run([sys.executable, str(REPO / "scripts/registry_build.py"), "--check"], capture_output=True, text=True).returncode == 0


def test_the_builder_is_deterministic_and_has_help(tmp_path):
    first = registry_build.build("abc1234")
    assert registry_build.render(first["private_words.json"]) == registry_build.render(registry_build.build("abc1234")["private_words.json"])
    out = subprocess.run([sys.executable, str(REPO / "scripts/registry_build.py"), "--made-from", "abc1234", "--out", str(tmp_path)], capture_output=True, text=True)
    assert out.returncode == 0
    assert (tmp_path / "private_words.json").read_text(encoding="utf-8") == registry_build.render(registry_build.build("abc1234")["private_words.json"])
    assert (tmp_path / "search_stop_words.json").read_text(encoding="utf-8") == registry_build.render(registry_build.build("abc1234")["search_stop_words.json"])
    helped = subprocess.run([sys.executable, str(REPO / "scripts/registry_build.py"), "--help"], capture_output=True, text=True)
    assert helped.returncode == 0 and "registry" in helped.stdout.lower()
    assert subprocess.run([sys.executable, str(REPO / "scripts/registry_build.py"), "--check", "--out", str(tmp_path)], capture_output=True, text=True).returncode == 0
