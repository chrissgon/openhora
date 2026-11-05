"""Builds the set of (reminder question, reply line) pairs of CANDIDATE-OUT PR 1 (runtime/tests/reply_guard_lines.jsonl). Not a test file.

What the set is for: the reminder question engine (`natural.complete`) must tell a reply that ANSWERS the open question from a line that starts a request of its own. Until PR 1 it asked
`natural.candidate`; the guard `turn_gate.new_request` replaces it. The set measures that change with no model call: each pair is one question the person was shown and one line they wrote.

Every pair holds:
  id          "rg-" + the first 8 hex digits of sha256(lang|need|line): stable, never a counter
  lang        "pt-BR" | "en": the language of the question the person saw (and of the line)
  need        the question kind: time | reading | weekday | text | kind | confirm | again | forget (the `need` of the draft the engine keeps)
  draft_seed  "<recipe>:<n>": one fixed recipe of this file that makes the draft with the engine at REPLAY_CLOCK, in the zone ZONE; `make_draft` asserts its `need`
  line        what the person wrote
  source      where the line comes from (entry | test-literal | corpus:<file>:<family> | authored:answer | authored:amend | authored:giveup | authored:request:<family>)
  split       "dev" (40 of 100 by sha256 of the LINE) or "test" (the other 60); the guard is never tuned on a test row
  gold        "answer" | "new" | "unclear", written by a blind labeller who saw only the question sentence and the line; null until the labels are applied
  old         "answer" | "retry" | "new": what `natural.complete` with the real `natural.candidate` did with the pair, recorded on the base commit before any product edit

Run (from the repository root, one command at a time; none reads the keychain, a model or the network):
  python3 runtime/tests/reply_guard_build.py --write                      assemble the pairs (keeps the gold and the old outcome of an id already in the file)
  python3 runtime/tests/reply_guard_build.py --record-old                 fill `old` on the checkout it runs on (run it on the base, before the product edit)
  python3 runtime/tests/reply_guard_build.py --emit-labels <path>         write the pairs WITHOUT gold, old, source or seed, shuffled, for the labeller
  python3 runtime/tests/reply_guard_build.py --apply-labels <labels.jsonl> fill `gold` from {"id", "gold"} lines
  python3 runtime/tests/reply_guard_build.py --counts                     the counts per question kind, family and language

Sources: the lines of the entry rows that hold an open reminder question; the reply literals the natural-layer tests pass to `complete`/`short_answer`; request lines drawn (seeded) from
evals/interpreter/dev-relabelled.jsonl, tier1-cover-v1.jsonl and the entry corpus, 10 per family per language where the corpus has them; and runtime/tests/reply_guard_authored.json.
"""
from __future__ import annotations

import argparse
import ast
import copy
import datetime
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

LINES = HERE / "reply_guard_lines.jsonl"
AUTHORED = HERE / "reply_guard_authored.json"
REPLAY_CLOCK = "2026-10-18T14:00"      # the clock of the world of every pair: Sunday 2026-10-18 14:00 (the entry replay's clock, pinned by a test)
ZONE = "America/Sao_Paulo"
SEED = "candidate-out-20261029"
DEV_PERCENT = 40
LANGS = ("pt-BR", "en")
NEEDS = ("time", "reading", "weekday", "text", "kind", "confirm", "again", "forget")
DRAWN_PER_FAMILY = 10
REQUEST_NEEDS = ("time", "text", "confirm")      # every request line (and every reply literal of a test) meets these three questions
GIVEUP_NEEDS = ("time", "text", "confirm", "kind")
FAMILIES = ("reminders-list", "forget", "restore", "new-reminder", "calendar-create", "calendar-read", "mail", "file", "brake", "decision")
CORPUS_OPS = {
    "reminders-list": [("tier1", "reminders")],
    "forget": [("tier1", "reminder-forget")],
    "new-reminder": [("tier1", "remind")],
    "calendar-create": [("dev", "event-create"), ("tier1", "event-create")],
    "mail": [("dev", "mail-send"), ("dev", "mail-draft"), ("dev", "mail-reply"), ("dev", "mail-mark"), ("dev", "mail-archive"), ("dev", "mail-trash"), ("dev", "mail-move"),
             ("tier1", "mail-send"), ("tier1", "mail-draft"), ("tier1", "mail-reply"), ("tier1", "mail-mark"), ("tier1", "mail-archive"), ("tier1", "mail-trash"), ("tier1", "mail-move")],
    "file": [("dev", "file-create"), ("dev", "file-save"), ("dev", "file-replace"), ("tier1", "file-create"), ("tier1", "file-save")],
    "brake": [("tier1", "stop-task"), ("tier1", "routine-pause"), ("tier1", "cancel"), ("tier1", "routine-cancel")],
}
CORPUS_FILES = {"dev": "dev-relabelled.jsonl", "tier1": "tier1-cover-v1.jsonl"}
ENTRY_PRESTATES = ("reminder_draft", "reminder_and_write_draft", "reminder_and_expired")
TEST_FILES = ("test_natural_review3", "test_natural_review4", "test_natural_review5", "test_natural_dialogues", "test_natural_reminders", "natural_kit")
TOPICS = {
    "pt-BR": ["ligar para a Ana", "pagar o aluguel", "regar as plantas", "buscar a encomenda"],
    "en": ["call Ana", "pay the rent", "water the plants", "pick up the parcel"],
}
SEEDS = {
    "time": ("time_day", "time_open"),
    "reading": ("reading_nine",),
    "weekday": ("weekday_next",),
    "text": ("text_tomorrow",),
    "kind": ("kind_bare",),
    "confirm": ("confirm_plain",),
    "again": ("again_after_confirm",),
    "forget": ("forget_one", "forget_many"),
}
KIND_WORDS = {
    "time": "asks at what time (the day may already be given)",
    "reading": "asks which of two readings of an ambiguous hour is meant",
    "weekday": "asks which weekday of next week",
    "text": "asks what the reminder should say",
    "kind": "asks whether it is a reminder here in the chat or an event in the calendar",
    "confirm": "shows the reminder as understood and asks to confirm it (yes / another time)",
    "again": "asks for a new day and time",
    "forget": "asks whether to cancel the reminder(s) shown (yes / no)",
}
# Words that make a line Portuguese when it has no diacritic; a line with neither a diacritic nor one of these is English. A line of digits, hours and a slash command is neutral (both languages).
PT_WORDS = {"sim", "nao", "outra", "hora", "sexta", "hoje", "amanha", "segunda", "terca", "quarta", "quinta", "sabado", "domingo", "contrato", "aluguel", "oi", "descarta", "claro", "lembrete",
            "agenda", "mas", "do", "da", "de", "para", "um", "uma", "aprova", "rejeita", "recusa", "cancela", "apaga", "esquece", "pode", "isso", "certo", "ok"}  # validate: allow english-only -- Portuguese words of the recipes and of the language guess: data of the reply set, invented lines
NEUTRAL = re.compile(r"^(?:/\S*|[\d\s:./hH]+|[\d\s:.]+\s?(?:am|pm))$")

RUBRIC = ("Labels are written by a blind labeller who sees only the question sentence the person was shown and the line they wrote: answer = the line gives, confirms, refuses, amends or gives up "
          "what the question asked; new = the line starts something else (a request of its own); unclear = it cannot be told from these two alone, and it is left out of the bars (and counted). "
          "A yes that changes the hour is an answer. A line that is both is unclear.")


RULINGS = ("The labeller's rulings on ambiguity: a full reminder request that gives the asked slot is an answer (after a confirm question only when it matches the shown reminder); a bare undo is unclear; "
           "a cancel by name that may be the pending reminder is unclear; 'and another one at 8pm' and single words such as reminder or agenda after a question that is not the kind question are unclear; "
           "calendar-shaped content after the question of what to remind is new; a slash command is new. Unclear pairs are left out of both bars and counted.")


def load_modules():
    """(natural, phrases, standin_tree): the modules loaded the way every test loads them."""
    import standin_tree as st
    return st.load("natural"), st.load("phrases"), st


def now_clock() -> datetime.datetime:
    return datetime.datetime.fromisoformat(REPLAY_CLOCK).replace(tzinfo=ZoneInfo(ZONE))


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pair_id(lang: str, need: str, line: str) -> str:
    return "rg-" + digest(f"{lang}|{need}|{line}")[:8]


def split_of(line: str) -> str:
    """The split of a pair, by its LINE (the same line is never in both): the first 8 hex digits of sha256(line) modulo 100, under DEV_PERCENT is dev."""
    return "dev" if int(digest(line)[:8], 16) % 100 < DEV_PERCENT else "test"


def pick(key: str, count: int) -> int:
    return int(digest(f"{SEED}|{key}")[:8], 16) % count


def make_draft(natural, phrases, seed: str, lang: str) -> dict:
    """The draft a recipe makes at REPLAY_CLOCK, in the language `lang`; asserts that its need is the recipe's own. Run inside a phrases scope for the forget recipes (their sentence is kept in the draft)."""
    recipe, _, index = seed.partition(":")
    topic = TOPICS[lang][int(index) % len(TOPICS[lang])]
    now = now_clock()
    pt = lang == "pt-BR"
    if recipe == "time_day":
        got, need = natural.understand(f"{topic} " + ("amanhã" if pt else "tomorrow"), now, "command"), "time"  # validate: allow english-only -- Portuguese words of the recipes and of the language guess: data of the reply set, invented lines
    elif recipe == "time_open":
        got, need = natural.understand(topic, now, "command"), "time"
    elif recipe == "reading_nine":
        got, need = natural.understand(f"{topic} " + ("às 9" if pt else "at 9"), now, "command"), "reading"
    elif recipe == "weekday_next":
        got, need = natural.understand(f"{topic} " + ("semana que vem" if pt else "next week"), now, "command"), "weekday"
    elif recipe == "text_tomorrow":
        got, need = natural.understand("amanhã às 10h" if pt else "tomorrow at 10am", now, "command"), "text"  # validate: allow english-only -- Portuguese words of the recipes and of the language guess: data of the reply set, invented lines
    elif recipe == "kind_bare":
        got, need = natural.understand(f"{topic} " + ("amanhã às 10h" if pt else "tomorrow at 10am"), now, "bare"), "kind"  # validate: allow english-only -- Portuguese words of the recipes and of the language guess: data of the reply set, invented lines
    elif recipe in ("confirm_plain", "again_after_confirm"):
        got, need = natural.understand(f"{topic} " + ("amanhã às 10h" if pt else "tomorrow at 10am"), now, "command"), "confirm"  # validate: allow english-only -- Portuguese words of the recipes and of the language guess: data of the reply set, invented lines
    elif recipe in ("forget_one", "forget_many"):
        today = now.date()
        first = {"human": {**natural.info_of("2026-10-19", "10:00", today), "zone": ZONE}, "preview": {"id": 3, "text": topic}}
        second = {"human": {**natural.info_of("2026-10-20", "09:00", today), "zone": ZONE}, "preview": {"id": 7, "text": TOPICS[lang][(int(index) + 1) % len(TOPICS[lang])]}}
        with phrases.scope(lang):
            sentence, draft = natural.forget_question([first] if recipe == "forget_one" else [first, second], None, True)
        assert draft["need"] == "forget"
        return draft
    else:
        raise ValueError(f"no recipe {seed!r}")
    draft = got["ask"]
    assert draft["need"] == need, (seed, lang, draft["need"])
    if recipe == "again_after_confirm":
        draft = natural.complete(draft, "outra hora" if pt else "another time", now)["ask"]
        assert draft["need"] == "again", (seed, lang, draft["need"])
    return draft


def question_of(natural, phrases, draft: dict, lang: str) -> str:
    with phrases.scope(lang):
        return natural.question(draft, None, True, draft.get("how", "trigger"))[0]


def seed_for(lang: str, need: str, line: str) -> str:
    """The recipe of a pair, fixed by its own key: the recipe of the need and the topic number."""
    recipes = SEEDS[need]
    key = f"{lang}|{need}|{line}"
    return f"{recipes[pick(key + '|recipe', len(recipes))]}:{pick(key + '|topic', len(TOPICS[lang]))}"


def old_outcome(natural, draft: dict, line: str, now) -> str:
    """What the engine on this tree did with the pair: None is a new line, the same draft asked once more is a retry, anything else an answer."""
    got = natural.complete(copy.deepcopy(draft), line, now)
    if got is None:
        return "new"
    ask = got.get("ask") if isinstance(got, dict) else None
    if ask is not None and ask == {**draft, "retries": draft.get("retries", 0) + 1}:
        return "retry"
    return "answer"


def language_of(line: str) -> list:
    """The languages a line is paired in: neutral lines (hours, digits, a slash command) in both, else the one its words say."""
    if NEUTRAL.match(line.strip()):
        return list(LANGS)
    if any(ord(ch) > 127 for ch in line):
        return ["pt-BR"]
    words = set(re.findall(r"[a-z]+", line.lower()))
    return ["pt-BR"] if words & PT_WORDS else ["en"]


def entry_lines() -> list:
    """The lines of the entry rows that hold an open reminder question (the corpus and the packages' extension rows), in the order they are written."""
    rows = [json.loads(line) for line in (HERE / "entry_corpus.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    for path in sorted((HERE / "entry_ext").glob("*.scenarios.jsonl")):
        rows += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r["text"] for r in rows if r.get("prestate") in ENTRY_PRESTATES and isinstance(r.get("text"), str) and r["text"].strip()]


def test_literals() -> list:
    """The reply literals the natural-layer tests pass to `complete`, `completed` and `short_answer` at a call site (read from the source, never run)."""
    found = []
    for name in TEST_FILES:
        tree = ast.parse((HERE / f"{name}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            args = node.args
            if called in ("complete", "completed") and len(args) >= 2 and isinstance(args[1], ast.Constant) and isinstance(args[1].value, str):
                found.append(args[1].value)
            elif called == "short_answer" and args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
                found.append(args[0].value)
    return sorted({line for line in found if line.strip()})


def corpus_requests() -> dict:
    """{family: {lang: [lines]}}: up to DRAWN_PER_FAMILY lines per family and language, drawn by the seed from the interpreter corpora (the lines only) and, for the decision words, the entry corpus."""
    natural, _phrases, _st = load_modules()
    pools = {}
    for kind, name in CORPUS_FILES.items():
        pools[kind] = [json.loads(line) for line in (REPO / "evals" / "interpreter" / name).read_text(encoding="utf-8").splitlines() if line.strip()]
    drawn = {}
    for family, sources in CORPUS_OPS.items():
        drawn[family] = {}
        for lang in LANGS:
            lines = sorted({r["line"] for kind, op in sources for r in pools[kind] if r["gold"].get("op") == op and r["lang"] == lang and r["line"].strip() and not r["line"].startswith("/")})
            lines.sort(key=lambda line: digest(f"{SEED}|{family}|{lang}|{line}"))
            drawn[family][lang] = lines[:DRAWN_PER_FAMILY]
    rows = [json.loads(line) for line in (HERE / "entry_corpus.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    for path in sorted((HERE / "entry_ext").glob("*.scenarios.jsonl")):
        rows += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    decisions = sorted({r["text"] for r in rows if isinstance(r.get("text"), str) and natural.decision(r["text"]) is not None})
    drawn["decision"] = {lang: [] for lang in LANGS}
    for line in sorted(decisions, key=lambda line: digest(f"{SEED}|decision|{line}")):
        for lang in language_of(line):
            if lang in LANGS and len(drawn["decision"][lang]) < DRAWN_PER_FAMILY:
                drawn["decision"][lang].append(line)
    return drawn


def assemble() -> list:
    """The pairs, as {lang, need, line, source}, in a fixed order, a (lang, need, line) once (the first source wins)."""
    authored = json.loads(AUTHORED.read_text(encoding="utf-8"))
    found = {}

    def add(lang, need, line, source):
        found.setdefault((lang, need, line), source)

    for line in entry_lines():
        for lang in language_of(line):
            add(lang, "time", line, "entry")
    for line in test_literals():
        for lang in language_of(line):
            for need in REQUEST_NEEDS:
                add(lang, need, line, "test-literal")
    for family, per_lang in corpus_requests().items():
        for lang, lines in per_lang.items():
            for line in lines:
                for need in REQUEST_NEEDS:
                    add(lang, need, line, f"corpus:{family}")
    for need, per_lang in authored["answers"].items():
        for lang, lines in per_lang.items():
            for line in lines:
                add(lang, need, line, "authored:answer")
    for lang, lines in authored["amend"].items():
        for line in lines:
            add(lang, "confirm", line, "authored:amend")
    for lang, lines in authored["giveups"].items():
        for line in lines:
            for need in GIVEUP_NEEDS:
                add(lang, need, line, "authored:giveup")
    for family, per_lang in authored["requests"].items():
        for lang, lines in per_lang.items():
            for line in lines:
                for need in REQUEST_NEEDS:
                    add(lang, need, line, f"authored:request:{family}")
    return [{"lang": lang, "need": need, "line": line, "source": source} for (lang, need, line), source in sorted(found.items(), key=lambda item: (item[0][0], item[0][1], pair_id(*item[0])))]


def base_commit() -> str:
    got = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    return got.stdout.strip() if got.returncode == 0 else ""


def read_rows() -> tuple:
    """(the header row, the pairs) of the file, or ({}, [])."""
    if not LINES.exists():
        return {}, []
    items = [json.loads(line) for line in LINES.read_text(encoding="utf-8").splitlines() if line.strip()]
    return (items[0], items[1:]) if items and items[0].get("header") else ({}, items)


def write_rows(header: dict, rows: list) -> None:
    out = [json.dumps(header, ensure_ascii=False)] + [json.dumps(r, ensure_ascii=False) for r in rows]
    LINES.write_text("\n".join(out) + "\n", encoding="utf-8")


def do_write() -> None:
    kept_header, kept = read_rows()
    header = kept_header
    by_id = {r["id"]: r for r in kept}
    natural, phrases, _st = load_modules()
    rows = []
    for pair in assemble():
        ident = pair_id(pair["lang"], pair["need"], pair["line"])
        seed = seed_for(pair["lang"], pair["need"], pair["line"])
        make_draft(natural, phrases, seed, pair["lang"])      # asserts the recipe's need
        old = by_id.get(ident, {})
        rows.append({"id": ident, "lang": pair["lang"], "need": pair["need"], "draft_seed": seed, "line": pair["line"], "source": pair["source"],
                     "split": split_of(pair["line"]), "gold": old.get("gold"), "old": old.get("old")})
    header = {"header": True, "set": "reply_guard_lines", "clock": REPLAY_CLOCK, "zone": ZONE, "seed": SEED, "split_rule": f"sha256(line)[:8] as hex, modulo 100, under {DEV_PERCENT} is dev, else test",
              "rubric": RUBRIC, "base_commit": header.get("base_commit", ""), "count": len(rows)}
    if "labeller_rulings" in kept_header:
        header["labeller_rulings"] = kept_header["labeller_rulings"]
    write_rows(header, rows)


def do_record_old() -> None:
    header, rows = read_rows()
    natural, phrases, _st = load_modules()
    now = now_clock()
    for row in rows:
        draft = make_draft(natural, phrases, row["draft_seed"], row["lang"])
        row["old"] = old_outcome(natural, draft, row["line"], now)
    header["base_commit"] = base_commit()
    write_rows(header, rows)


def do_emit_labels(path: Path) -> None:
    _header, rows = read_rows()
    natural, phrases, _st = load_modules()
    out = []
    for row in sorted(rows, key=lambda r: digest(f"label|{r['id']}")):
        draft = make_draft(natural, phrases, row["draft_seed"], row["lang"])
        out.append({"id": row["id"], "language": row["lang"], "question_kind": KIND_WORDS[row["need"]], "question": question_of(natural, phrases, draft, row["lang"]), "line": row["line"]})
    path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in out) + "\n", encoding="utf-8")


def do_apply_labels(path: Path) -> None:
    header, rows = read_rows()
    labels = {}
    for text in path.read_text(encoding="utf-8").splitlines():
        if text.strip():
            item = json.loads(text)
            labels[item["id"]] = item["gold"]
    missing = [r["id"] for r in rows if r["id"] not in labels]
    wrong = {k: v for k, v in labels.items() if v not in ("answer", "new", "unclear")}
    if missing or wrong:
        raise SystemExit(f"labels: {len(missing)} pairs without a label, {len(wrong)} labels outside answer/new/unclear")
    header["labeller_rulings"] = RULINGS
    for row in rows:
        row["gold"] = labels[row["id"]]
    write_rows(header, rows)


def group_of(source: str) -> str:
    """The group a pair is counted in: request:<family> for a drawn or authored request line, else the source itself."""
    if source.startswith("authored:request:"):
        return "request:" + source.split(":", 2)[2]
    if source.startswith("corpus:"):
        return "request:" + source.split(":", 1)[1]
    return source


def counts() -> dict:
    _header, rows = read_rows()
    out = {"total": len(rows), "by_need": {}, "by_lang": {}, "by_group": {}, "by_need_lang": {}, "by_split": {}, "by_group_lang": {}}
    for row in rows:
        group = group_of(row["source"])
        for bucket, key in (("by_need", row["need"]), ("by_lang", row["lang"]), ("by_group", group), ("by_need_lang", f"{row['need']}/{row['lang']}"),
                            ("by_split", row["split"]), ("by_group_lang", f"{group}/{row['lang']}")):
            out[bucket][key] = out[bucket].get(key, 0) + 1
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build the (reminder question, reply line) set of CANDIDATE-OUT PR 1; see the module text.")
    parser.add_argument("--write", action="store_true", help="assemble the pairs")
    parser.add_argument("--record-old", action="store_true", help="fill the old outcome on this checkout")
    parser.add_argument("--emit-labels", metavar="PATH", help="write the unlabelled pairs for the labeller")
    parser.add_argument("--apply-labels", metavar="PATH", help="fill gold from a labels.jsonl")
    parser.add_argument("--counts", action="store_true", help="print the counts")
    args = parser.parse_args(argv)
    if args.write:
        do_write()
    if args.record_old:
        do_record_old()
    if args.emit_labels:
        do_emit_labels(Path(args.emit_labels))
    if args.apply_labels:
        do_apply_labels(Path(args.apply_labels))
    if args.counts:
        print(json.dumps(counts(), indent=1, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
