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
# The test modules the kit builds its world from, named here as well: scripts/select_tests.py follows the importers of a changed test file, and a kit between them hides this replay from it
# (the oracle test_select_tests_oracle.py found it for test_service.py). A change to one of them selects the replay.
import test_ask  # noqa: F401
import test_calendar_write  # noqa: F401
import test_channel_email_reply  # noqa: F401
import test_file_read  # noqa: F401
import test_messaging_ask  # noqa: F401
import test_ops_natural  # noqa: F401
import test_research  # noqa: F401
import test_service  # noqa: F401
import test_sources_mail  # noqa: F401

bridge = st.load("messaging_bridge")
ops_turn = st.load("ops_turn")

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
        time.tzset()      # the world pinned TZ; the patch is undone, the process zone follows
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


COMPOSITES = ("expired_and_write_draft", "reminder_and_write_draft", "reminder_and_expired", "plan_and_write_draft", "plan_and_file_held")
EDGES = ("reply_to_a_question_of_another_project", "delete_from_a_sender_who_may_not_talk", "forwarded_file_with_a_reminder_draft_open")


@pytest.mark.skipif(RECORDING, reason="recording")
def test_every_composite_pre_state_and_every_edge_input_is_in_the_corpus_with_its_yes_and_its_sim():
    """S41-1b. The single-state corpus was blind to a row whose effect needs two states live at once or an uncommon input: each composite pre-state (two questions open, a plan and a question, a
    plan and a held file) has at least five scenarios, among them the "sim" and the "yes" that every pending question reads; each edge input has at least five; a plan that is last with a captioned
    file is covered; and each is in the golden, recorded on the order of its day."""
    _, recorded = golden()
    scenarios = corpus()
    for name in COMPOSITES:
        assert name in ek.PRESTATES, name
        rows = [s for s in scenarios if s["prestate"] == name]
        assert len(rows) >= 5, f"{name}: {len(rows)} scenarios"
        assert {"sim", "yes"} <= {s["text"] for s in rows if s["kind"] == "text"}, f"{name} holds the sim and the yes"
        assert all(s["id"] in recorded for s in rows)
    captioned = [s for s in scenarios if s["prestate"] in ("plan_last", "plan_not_last") and s["kind"] == "attachment" and s["text"] in ("sim", "yes")]
    assert len(captioned) >= 2, "a plan that is last, and a file captioned sim or yes"
    assert "question_of_other_project" in ek.PRESTATES and len([s for s in scenarios if s["prestate"] == "question_of_other_project"]) >= 5
    for name in EDGES:
        rows = [s for s in scenarios if s["id"].startswith(f"edge.{name}.")]
        assert len(rows) >= 5, f"{name}: {len(rows)} scenarios"
        assert all(s["id"] in recorded for s in rows)
    dropped = [s for s in scenarios if s["id"].startswith("edge.reply_to_a_question_of_another_project.") and s["prestate"] == "question_of_other_project"]
    assert dropped and all(recorded[s["id"]]["trace"][-1] in ("reply", "pending-typed") for s in dropped), "a reply to a question of another project is the reply branch's, and is dropped"
    delete = [s for s in scenarios if s["id"].startswith("edge.delete_from_a_sender_who_may_not_talk.") and s["id"].rsplit(".", 1)[1] in ("01", "02", "03", "04", "05")]
    assert delete and all("delete-refusal-before-queue" not in recorded[s["id"]]["trace"] for s in delete), "a sender who may not talk is never told the file cannot be deleted from a message"


OPS_GROUPS = ("router_question_and_a_state_line", "write_draft_and_a_state_line", "write_draft_and_a_tier_1_form", "plan_not_last_and_a_greeting_that_is_a_yes",
              "plan_last_and_a_greeting_that_is_a_yes", "interpreter_sender_without_talk", "mcp_and_chat_shells", "a_page_line_queued_while_a_run_is_busy", "a_queued_answer_to_the_choice_of_a_file")


@pytest.mark.skipif(RECORDING, reason="recording")
def test_the_operations_composites_the_interpreter_sender_without_talk_and_the_mcp_chat_and_queue_shells_are_in_the_corpus():
    """S41-1c. The review of S41-3 found orders and guards of the operations layer that no scenario reached. Each group has at least five scenarios with its "sim" and its "yes" and is in the golden;
    the pre-states `route_busy` and `route_busy_ask_choice`, the sender `reader_interpret` (holds `interpret` and a read group, not `talk`) on the bridge and on `ops`, the shells `mcp` and `chat`, and
    the drain of the queue (`route_queued`) are all named and used."""
    _, recorded = golden()
    scenarios = corpus()
    in_corpus = {build.key_of(s) for s in scenarios}      # a scenario that two groups both want is written once, under the first group's id: the group is read from what was authored
    for name in OPS_GROUPS:
        authored = build.OPS_GROUPS[name]
        assert len(authored) >= 5, f"{name}: {len(authored)} scenarios"
        assert {"sim", "yes"} <= {s["text"] for s in authored}, f"{name} holds the sim and the yes"
        assert all(build.key_of(s) in in_corpus for s in authored), name
        assert all(s["id"] in recorded for s in scenarios if s["id"].startswith(f"opscomp.{name}."))
    assert {"route_busy", "route_busy_ask_choice"} <= set(ek.PRESTATES) and {"mcp", "chat"} <= set(ek.CHANNELS) and "reader_interpret" in ek.SENDERS
    viewer = [s for s in scenarios if s["sender"] == "reader_interpret"]
    assert {s["channel"] for s in viewer} == {"messaging", "ops"} and len(viewer) >= 10
    assert "talk-refusal" in {n for s in viewer if s["channel"] == "ops" for n in recorded[s["id"]]["trace"]}, "a sender with no talk meets the refusal of the operations layer, and no model is asked"
    assert all(recorded[s["id"]]["model_calls"] == 0 for s in viewer)
    for channel in ("mcp", "chat"):
        assert len([s for s in scenarios if s["channel"] == channel]) >= 5, channel
    drained = [s for s in scenarios if s["prestate"] in ("route_busy", "route_busy_ask_choice") and any(row["to"].endswith("-drain") and row["flags"].get("routed") == "line" for row in recorded[s["id"]]["sent"])]
    assert len(drained) >= 5, "lines queued while a run is busy, answered by the drain of the queue"


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


def row_never(name):
    """A hook that makes the row `name` of the stage `ops` (runtime/ops_turn.py) take nothing."""
    def hook(mp):
        mp.setitem(ops_turn.ROWS, name, lambda *a, **k: None)
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
    """The three the spec names: with `Bridge.plan_line` and `Bridge.word_line` made to take nothing, and the row `tier-1-form` of `ops_turn` (S41-3: what `ops_natural.take` ended with) made to take nothing, at least one scenario differs from the golden."""
    for claimer, hook in (("plan-confirm-word", never(bridge.Bridge, "plan_line", False)), ("card-word", never(bridge.Bridge, "word_line", False)),
                          ("tier-1-form", row_never("tier-1-form"))):
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


# --- the guard of `--record-added` (BL7-4) ----------------------------------------------------------------------------------------------------------------------
# A scenario may bring a model text of its own into `entry_kit.OVERRIDES`, keyed by its own line, and then the hash of the table of answers in the golden's header moves; but the table taken
# WITHOUT the added scenarios' own keys must still hash to the header's old `answers_sha256`. A change to an existing recorded answer or override is refused: a recorded row may then be stale,
# and the golden is never re-recorded by a package. The oracle is this file's own literals (a planted override, a planted answer); the added scenarios are the four BL7-4 rows of the corpus.


def added() -> list:
    return [row for row in build.read_rows(build.CORPUS_FILE) if row["id"].startswith("bl74.")]


def header_before_the_additions() -> dict:
    return {"answers_sha256": ek.answers_sha256_without([row["text"] for row in added()])}


def test_the_four_added_scenarios_are_found_and_their_texts_are_overrides():
    assert [row["id"] for row in added()] == ["bl74.deadline.01", "bl74.plan_no.01", "bl74.plan_none.01", "bl74.draft_route.01"]
    assert all(ek.collapse(row["text"]) in ek.OVERRIDES for row in added())


def test_the_table_without_the_added_texts_is_the_table_the_header_hashes():
    assert build.answers_problem(header_before_the_additions(), added()) is None
    assert ek.answers_sha256_without([row["text"] for row in added()]) != ek.answers_sha256()          # the added texts do move the hash of the whole table


def test_a_changed_existing_override_is_refused(monkeypatch):
    header = header_before_the_additions()
    key = ek.collapse(ek.RESEARCH_LINE)
    assert key in ek.OVERRIDES
    monkeypatch.setitem(ek.OVERRIDES, key, json.dumps({"v": 1, "kind": "none"}))          # the planted change to a recorded override
    assert "stop and review" in build.answers_problem(header, added())


def test_a_changed_recorded_answer_is_refused(monkeypatch):
    header = header_before_the_additions()
    table = dict(ek.answers())
    key = next(iter(table))
    table[key] = table[key] + " "
    monkeypatch.setattr(ek, "answers", lambda: table)
    assert "stop and review" in build.answers_problem(header, added())


def test_vacuity_a_change_to_an_added_scenarios_own_text_is_not_a_refusal(monkeypatch):
    header = header_before_the_additions()
    monkeypatch.setitem(ek.OVERRIDES, ek.collapse(added()[0]["text"]), json.dumps({"v": 1, "kind": "route"}))
    assert build.answers_problem(header, added()) is None          # the guard looks only at what is not new
