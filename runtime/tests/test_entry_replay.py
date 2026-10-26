"""The entry replay (package S41-1; PLAN-BRAIN section 4 step 1): the outcome of every scenario of `entry_corpus.jsonl` must be the outcome recorded in `entry_golden.jsonl`, field by field.

WHAT THIS HOLDS. The golden was recorded ONCE, on the tree as it was before any package of step 1 moved the order of the claimers (the commit is in its header). Every later package that
changes who takes a line first (S41-2 and S41-3: one table of order, S41-8: one frame dispatcher) runs this file and must leave every outcome as it is: the claimer trace, the operations
called, the messages sent, the ledger records added, the drafts and plans left, the conversation rows stored, the jobs started, and the counts of model and provider calls. A difference
fails with the scenario, the field and both values (the corpus is fictional data); it is never recorded again by the package that meets it. A change of the golden is a reviewed decision.

NO CALLS. The model is the stand-in of entry_kit.StandInModel, the messenger and the calendar writer run in this process, and a provider process or a connection raises (see entry_kit.py).
The replay asserts it: the number of model calls of every scenario is the golden's, and no provider was started.

SENSITIVITY. A comparator that cannot see a change proves nothing, so the last tests change the order on purpose, in the test and nowhere else: a claimer that is disabled (it never takes
a line) or two that swap places must change at least one scenario's outcome. They also say where the corpus does NOT see a change (a claimer no scenario depends on is reported).

Run (the whole replay, the default: about 1,000 scenarios, in SHARDS tests that may run in parallel):
  uv run --with pytest==9.1.1 --with pytest-xdist==3.8.0 pytest -q -n 4 runtime/tests/test_entry_replay.py
  WB_FULL_FUZZ=1 ...        every line of the sampled corpora is also replayed, with the invariants (no call, a trace) and not against a golden: runtime/README.md, "The entry replay"
Record (once, on the unchanged tree): python3 runtime/tests/entry_corpus_build.py --record
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

import pytest

import entry_corpus_build as build
import entry_kit as ek
import standin_tree as st

bridge = st.load("messaging_bridge")
ops_natural = st.load("ops_natural")

SHARDS = 4
RECORDING = os.environ.get("WB_ENTRY_RECORD") == "1"
FULL = os.environ.get("WB_FULL_FUZZ") == "1"
MAX_SHOWN = 12


def corpus() -> list:
    return ek.read_jsonl(ek.CORPUS_FILE)


def golden() -> tuple:
    """(header, {id: outcome}) of the committed golden."""
    rows = ek.read_jsonl(ek.GOLDEN_FILE)
    return rows[0], {row["id"]: row["outcome"] for row in rows[1:]}


def shard_of(scenarios: list, shard: int) -> list:
    return [s for index, s in enumerate(scenarios) if index % SHARDS == shard]


def replay(scenario: dict, tmp_path: Path, hooks=None) -> dict:
    """The outcome of one scenario in a world of its own: a scratch folder, a fresh set of patches, undone at the end, and the folder removed. `hooks(monkeypatch)` patches the code under
    test once the pre-state is built and before the line is delivered: a claimer disabled for the line only, so that the pre-state is the one the golden was recorded in."""
    folder = tmp_path / "w"
    folder.mkdir()
    try:
        with pytest.MonkeyPatch.context() as mp:
            return ek.run_scenario(scenario, folder, mp, line_hook=hooks)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def differences(expected: dict, found: dict) -> list:
    """[(field, expected, found)] for each field of the outcome that is not the golden's."""
    return [(field, expected.get(field), found.get(field)) for field in ek.OUTCOME_FIELDS if expected.get(field) != found.get(field)]


def describe(scenario: dict, diffs: list) -> str:
    shown = json.dumps({k: v for k, v in scenario.items() if k != "id"}, ensure_ascii=False)
    return f"{scenario['id']} {shown}\n" + "".join(f"    {field}\n      golden:   {json.dumps(want, ensure_ascii=False)[:600]}\n      replayed: {json.dumps(got, ensure_ascii=False)[:600]}\n"
                                                    for field, want, got in diffs)


# --- recording (once) ---------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.skipif(not RECORDING, reason="the golden is recorded once, by entry_corpus_build.py --record, on the unchanged tree")
@pytest.mark.parametrize("shard", range(SHARDS))
def test_record_the_golden(shard, tmp_path):
    out = Path(os.environ["WB_ENTRY_RECORD_DIR"]) / f"shard-{shard}.jsonl"
    rows, times = [], []
    only = os.environ.get("WB_ENTRY_ONLY")      # a regular expression on the ids: an exploratory record of part of the corpus (the builder's --record never sets it)
    for scenario in shard_of(corpus(), shard):
        if only is None or re.search(only, scenario["id"]):
            started = time.monotonic()
            rows.append({"id": scenario["id"], "outcome": replay(scenario, tmp_path)})
            times.append({"id": scenario["id"], "seconds": round(time.monotonic() - started, 3)})
    out.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    out.with_name(f"meta-{shard}.json").write_text(json.dumps({"answers_sha256": ek.answers_sha256()}), encoding="utf-8")
    out.with_name(f"times-{shard}.jsonl").write_text("".join(json.dumps(row) + "\n" for row in times), encoding="utf-8")      # what each scenario cost (the builder does not read it)


# --- the replay ---------------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.skipif(RECORDING, reason="recording")
@pytest.mark.parametrize("shard", range(SHARDS))
def test_every_scenario_has_the_outcome_of_the_golden(shard, tmp_path):
    _, recorded = golden()
    bad, calls = [], 0
    scenarios = shard_of(corpus(), shard)
    for scenario in scenarios:
        found = replay(scenario, tmp_path)
        calls += found["model_calls"]
        diffs = differences(recorded[scenario["id"]], found)
        if diffs:
            bad.append(describe(scenario, diffs))
    assert not bad, f"{len(bad)} of {len(scenarios)} scenarios of shard {shard} differ from the golden:\n" + "\n".join(bad[:MAX_SHOWN])
    assert calls == sum(recorded[s["id"]]["model_calls"] for s in scenarios), "the stand-in model was asked as many times as the golden records"


@pytest.mark.skipif(RECORDING, reason="recording")
def test_no_model_and_no_provider_call_was_made(tmp_path):
    """The scenarios that call the stand-in model, one in six of them: the number of calls is the golden's and no provider process or connection was started."""
    _, recorded = golden()
    chosen = [s for s in corpus() if recorded[s["id"]]["model_calls"] > 0][::6]
    assert len(chosen) >= 20, "the corpus holds scenarios that reach the model route"
    asked = started = 0
    for scenario in chosen:
        found = replay(scenario, tmp_path)
        asked += found["model_calls"]
        started += found["provider_calls"]
    assert asked == sum(recorded[s["id"]]["model_calls"] for s in chosen) > 0
    assert started == 0 and all(row["provider_calls"] == 0 for row in recorded.values()), "no provider was started, when the golden was recorded and now"


@pytest.mark.skipif(RECORDING, reason="recording")
def test_the_golden_matches_the_corpus():
    header, recorded = golden()
    scenarios = corpus()
    assert [s["id"] for s in scenarios] == list(recorded), "the golden holds the scenarios of the corpus, in its order"
    assert header["corpus_sha256"] == ek.corpus_sha256(), "the corpus is the one the golden was recorded from"
    assert header["answers_sha256"] == ek.answers_sha256(), "the recorded answers the stand-in model reads (entry_kit.ANSWER_FILES and OVERRIDES) are the ones the golden was recorded with"
    assert header["count"] == len(scenarios) and header["commit"] and len(header["commit"]) >= 7
    assert [s["id"] for s in scenarios] == [s["id"] for s in build.generate(False)[0]], "the corpus is what entry_corpus_build.py writes"


@pytest.mark.skipif(RECORDING, reason="recording")
def test_every_scenario_is_well_formed_and_every_claimer_has_a_row_in_the_table():
    for scenario in corpus():
        assert ek.check_scenario(scenario) == [], scenario["id"]
    assert set(build.CLAIMERS) == set(ek.CLAIMER_NAMES), "the table of authored scenarios has one entry for every claimer name of the kit"
    assert len(ek.CLAIMER_NAMES) == len(set(ek.CLAIMER_NAMES)) == 31 + 3 + 15


@pytest.mark.skipif(RECORDING, reason="recording")
def test_every_claimer_takes_at_least_one_scenario():
    _, recorded = golden()
    seen = {name for row in recorded.values() for name in row["trace"]}
    assert set(ek.CLAIMER_NAMES) - seen == set(), "every claimer of the kit is the first to take a line in at least one scenario of the golden"


@pytest.mark.skipif(RECORDING, reason="recording")
def test_every_authored_take_is_taken_and_every_near_miss_is_not():
    """The corpus says, for every claimer, five lines it takes and five that must go elsewhere (entry_corpus_build.CLAIMERS): the golden agrees. A claimer that takes none of its own lines is
    the finding (the line, the state or the claimer was misread), not a failure to hide."""
    _, recorded = golden()
    _, expectations = build.generate(False)
    taken = {name: 0 for name in build.CLAIMERS}
    wrong = []
    for claimer, role, scenario_id in expectations:
        names = recorded[scenario_id]["trace"]
        if role == "take":
            taken[claimer] += claimer in names
            if claimer not in names:
                wrong.append(f"{scenario_id}: authored as taken by {claimer}, the trace is {names}")
        elif claimer in names:
            wrong.append(f"{scenario_id}: authored as a near-miss of {claimer}, the trace is {names}")
    short = {name: count for name, count in taken.items() if count < 5}
    assert not short, f"claimers with fewer than five lines they take: {short}"
    assert not wrong, f"{len(wrong)} authored scenarios whose trace is not as authored:\n" + "\n".join(wrong[:MAX_SHOWN * 3])


@pytest.mark.skipif(RECORDING, reason="recording")
def test_the_replay_is_deterministic(tmp_path):
    """Thirty scenarios replayed twice give the same outcome: nothing of the order the threads finish in, of the hash seed or of the clock reaches the outcome."""
    scenarios = corpus()
    for scenario in scenarios[:: max(1, len(scenarios) // 30)][:30]:
        assert replay(scenario, tmp_path) == replay(scenario, tmp_path), scenario["id"]


@pytest.mark.skipif(RECORDING, reason="recording")
def test_the_corpus_and_the_golden_hold_no_machine_path_no_real_address_and_no_token():
    """Fictional data only (the review of the package checks it by hand too): no path of a machine, every address on an invented domain (`.example`, `example.com`, or a bot suffix of a
    command), no string the scan reads as a credential."""
    import re
    for path in (ek.CORPUS_FILE, ek.GOLDEN_FILE):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"/Users/|/private/|/var/folders|/tmp/|/home/", text), f"{path.name} names a path of a machine"
        for address in re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+", text):
            assert address.split("@")[1] in ("bot", "example.com") or address.endswith(".example"), f"{path.name} holds the address {address}"
        assert not re.search(r"sk-[A-Za-z0-9_-]{10,}|gh[pousr]_[A-Za-z0-9]{10,}|AKIA[A-Z0-9]{8,}|xox[a-z]-[A-Za-z0-9-]{10,}", text), f"{path.name} holds what reads as a key"


@pytest.mark.skipif(RECORDING, reason="recording")
def test_the_messenger_called_in_this_process_answers_as_the_provider_process(tmp_path, monkeypatch):
    """`FastMessenger` saves a process start per message, and only that: the capabilities, the id of a sent message and what is recorded of it are those of the stand-in provider run as a
    process, through the real resolver, the way the bridge's other tests run it."""
    import shutil
    standin = st.REPO / "runtime" / "tests" / "fixtures" / "messenger_standin.py"
    root = tmp_path / "bench"
    (root / "providers" / "messenger").mkdir(parents=True)
    shutil.copy(st.REPO / "providers" / "resolve.py", root / "providers" / "resolve.py")
    shutil.copy(standin, root / "providers" / "messenger" / "standin.py")
    providers = st.load("messaging_provider")
    seen = {}
    for name in ("process", "here"):
        folder = tmp_path / name
        folder.mkdir()
        monkeypatch.setenv("STANDIN_DIR", str(folder))
        messenger = providers.Messenger("telegram", root=str(root))
        if name == "here":
            messenger._call = ek.FastMessenger()
        (folder / "caps.json").write_text(json.dumps({"buttons": False, "actions_need_reply": True}))
        message = {"text": "Pick one.", "actions": [{"id": "1:plan-yes", "label": "Yes"}], "link": None, "document": None}
        seen[name] = (messenger.capabilities(), str(messenger.send("5511", message)), str(messenger.send("5511", dict(message, text="Again."))),
                      [json.loads(line) for line in (folder / "sent.jsonl").read_text().splitlines()])
    assert seen["process"] == seen["here"]


# --- sensitivity: the comparator is not blind ----------------------------------------------------------------------------------------------------------


def never(owner, name, result):
    """A hook that makes `owner.name` claim nothing: it returns `result` (False, or None) without looking at the line."""
    def hook(mp):
        mp.setattr(owner, name, lambda *a, **k: result)
    return hook


def disabled(hooks_for: list):
    def hook(mp):
        for item in hooks_for:
            item(mp)
    return hook


def scenarios_of(claimer: str, limit: int = 8) -> list:
    """The scenarios of the corpus whose golden trace names the claimer (the lines it takes), at most `limit`, in the order of the corpus."""
    _, recorded = golden()
    return [s for s in corpus() if claimer in recorded[s["id"]]["trace"]][:limit]


def changed_by(hook, scenarios: list, tmp_path) -> list:
    """The ids of the scenarios whose outcome is not the golden's once `hook` is in force."""
    _, recorded = golden()
    return [s["id"] for s in scenarios if differences(recorded[s["id"]], replay(s, tmp_path, hook))]


@pytest.mark.skipif(RECORDING, reason="recording")
def test_vacuity_a_changed_claim_order_is_seen(tmp_path):
    """The three the spec names: with `Bridge.plan_line` and `Bridge.word_line` made to take nothing, and `ops_natural.take` made to answer None, at least one scenario differs from the golden."""
    for claimer, hook in (("plan-confirm-word", never(bridge.Bridge, "plan_line", False)), ("card-word", never(bridge.Bridge, "word_line", False)),
                          ("tier-1-form", never(ops_natural, "take", None))):
        lines = scenarios_of(claimer)
        assert lines, f"the corpus holds lines {claimer} takes"
        assert changed_by(hook, lines, tmp_path), f"disabling {claimer} changes at least one scenario, or the comparator is blind"


DISABLED = [("plan-confirm-word", bridge.Bridge, "plan_line", False), ("card-word", bridge.Bridge, "word_line", False), ("research-stop", bridge.Bridge, "research_stop_line", False),
            ("card-revise", bridge.Bridge, "revise_line", False), ("project-switch", bridge.Bridge, "project_line", False),
            ("reminder-draft-answer", bridge.remind.Reminders, "answer", False), ("reminder-expired-yes", bridge.remind.Reminders, "late", False),
            ("write-draft-answer", bridge.Bridge, "write_answers", False), ("attachment-line", bridge.attach.Attachments, "line", False),
            ("reminder-form", bridge.remind.Reminders, "natural", False)]


@pytest.mark.skipif(RECORDING, reason="recording")
@pytest.mark.parametrize("claimer, owner, name, result", DISABLED, ids=[row[0] for row in DISABLED])
def test_sensitivity_disabling_a_claimer_changes_at_least_one_scenario(claimer, owner, name, result, tmp_path):
    lines = scenarios_of(claimer)
    assert lines, f"the corpus holds lines {claimer} takes"
    assert changed_by(never(owner, name, result), lines, tmp_path), f"nothing in the corpus depends on {claimer}"


@pytest.mark.skipif(RECORDING, reason="recording")
def test_sensitivity_two_claimers_that_swap_places_change_a_scenario(tmp_path):
    """`research_stop_line` stands after `word_line` so that a "não" with a card as the last message rejects the card and leaves the search alone (L64, BL2b). Swapped, the same line stops the
    search and leaves the card open: the scenario where a search runs and a card is last (`research_and_card`) must see it."""
    def swapped(mp):
        original_stop, original_word = bridge.Bridge.research_stop_line, bridge.Bridge.word_line
        mp.setattr(bridge.Bridge, "word_line", lambda self, update, intent, project, listed, sender, chat: False)
        mp.setattr(bridge.Bridge, "research_stop_line", lambda self, update, intent, kind, project, listed, chat: original_stop(self, update, intent, kind, project, listed, chat) or
                   original_word(self, update, intent, project, listed, str(update.get("sender")), chat))
    lines = [s for s in corpus() if s["prestate"] == "research_and_card" and s["text"] in ("não", "no", "sim", "pare")]
    assert lines, "the corpus holds a search that runs with a card last"
    assert changed_by(swapped, lines, tmp_path), "the order of the card words and the research brake is seen by the corpus"


# --- the full fuzz: every line, with the invariants ---------------------------------------------------------------------------------------------------


@pytest.mark.skipif(RECORDING or not FULL, reason="WB_FULL_FUZZ=1: every line of the sampled corpora")
@pytest.mark.parametrize("shard", range(SHARDS))
def test_full_fuzz_every_line_makes_a_trace_and_no_call(shard, tmp_path):
    _, recorded = golden()
    known = set(recorded)
    scenarios = [s for s in build.generate(True)[0] if s["id"] not in known]
    bad = []
    for scenario in shard_of(scenarios, shard):
        found = replay(scenario, tmp_path)
        if found["provider_calls"] or not found["trace"] or found["model_calls"] > 1:
            bad.append(f"{scenario['id']}: trace {found['trace']}, provider {found['provider_calls']}, model {found['model_calls']}")
    assert not bad, "\n".join(bad[:MAX_SHOWN])
