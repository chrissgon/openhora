"""The entry corpus replayed once with five observers (package SLOW-1; docs/decisions/2026-10-28-slow-1-one-observed-replay.md).

WHAT THIS HOLDS. Five properties of the entry path are checked over every scenario of the corpus (the base and the scenarios of every package of `entry_ext/`). Each used to replay the whole corpus
by itself (four replays of about 1,000 scenarios, and a fifth over 188 of them); each only OBSERVES: it wraps a function, calls the real one and returns its result, and no two wrap the same
attribute. So the corpus is replayed ONCE with all five installed, in this order: claims, operations trace, bridge trace, reads, envelope, and each check runs over the rows its observer collected.
The observers and the comparisons stay in the files that own them; this file only composes them:

  * `test_ops_turn.py` (3): `recording_claims` and `claims_problems` (`code_claims` is the frozen expression of `say`'s queue decision, on every call);
  * `test_ops_turn.py` (7): `ops_trace_hook` and `ops_trace_problems` (the row of the stage `ops` that took a line is the claimer the golden records);
  * `test_turn_order.py` (5): `bridge_trace_hook` and `bridge_trace_problems` (the rows of the bridge stages are the claimers the golden records);
  * `test_turn_gate_refresh.py`: `Reads` and `reads_problems` (no source is read twice in a line, no two mail lookups, no read outside a turn);
  * `test_frame_dispatch.py` (5): `envelope_hook` and `envelope_problems` (no record of one message is read twice in a dispatch, at most two messages are read).

The problems of every check are joined under a label that names its owner (`test_ops_turn (3) code_claims: ...`); every check runs even when an earlier one found problems. The outcome of each scenario
with the observers is also compared with the golden: a difference there says an observer changed the outcome (or the golden test is failing too).

NOT HERE. The golden comparison itself stays apart, replayed with no observer attached (`test_entry_replay.py`: it is the one comparison the others are measured against); `applying`
(test_frame_dispatch.py) calls every kind's `applies`, which reads ledger records the envelope observer counts; and every hook that changes behaviour (a claimer disabled, two swapped, the memo taken away).

THE OBSERVERS DO NOT DISTURB EACH OTHER. Argued from the code (each returns the real result; the attributes they patch are disjoint), proved once on every scenario of the corpus when this file was written (the
numbers are in the decision entry), and kept by `test_the_observers_do_not_see_each_other` on six scenarios that make each observer record something.

NO CALLS. The scenarios are replayed by test_entry_replay.py's own functions, with the stand-ins of entry_kit.py: no model, no provider process. The golden is never recorded here.

Run: uv run --with pytest==9.1.1 --with pytest-xdist pytest -q -n 4 runtime/tests/test_entry_observed.py
"""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

import standin_tree as st
import test_entry_replay as rp
import test_frame_dispatch as fd
import test_ops_turn as ot
import test_turn_gate_refresh as tg
import test_turn_order as to

messaging_bridge = st.load("messaging_bridge")
messaging_turn = st.load("messaging_turn")
ops_sources = st.load("ops_sources")
ops_turn = st.load("ops_turn")

OBSERVED_SHARDS = 8
OBSERVERS = ("claims", "ops", "bridge", "reads", "envelope")      # the order they are installed in
LABELS = {"claims": "test_ops_turn (3) code_claims", "ops": "test_ops_turn (7) table trace", "bridge": "test_turn_order (5) table trace",
          "reads": "test_turn_gate_refresh corpus reads", "envelope": "test_frame_dispatch (5) envelope"}
OUTCOME_LABEL = "an observer changed the outcome"
MAX_SHOWN = 12


def shard_of(scenarios: list, shard: int) -> list:
    return [s for index, s in enumerate(scenarios) if index % OBSERVED_SHARDS == shard]


def together(hooks):
    """One hook that installs each of `hooks`, in order."""
    def hook(mp):
        for item in hooks:
            item(mp)
    return hook


def observe(scenario, tmp_path, observers=OBSERVERS, before=()):
    """Replay `scenario` once with the named observers installed (in the order of OBSERVERS) after the hooks of `before` (a defect planted by a test). Returns the outcome and what each observer saw."""
    lock = threading.Lock()
    seen = SimpleNamespace(claims=[], ops=[], bridge=[], reads=[], envelope=[])
    builders = {"claims": lambda: ot.recording_claims(seen.claims, lock), "ops": lambda: ot.ops_trace_hook(seen.ops, lock), "bridge": lambda: to.bridge_trace_hook(seen.bridge),
                "reads": lambda: (lambda mp: seen.reads.append(tg.Reads(mp, through=True))), "envelope": lambda: fd.envelope_hook(seen.envelope)}
    hooks = list(before) + [builders[name]() for name in OBSERVERS if name in observers]
    outcome = rp.replay(scenario, tmp_path, hooks=together(hooks))
    seen.reads = seen.reads[0] if seen.reads else None
    return outcome, seen


def signature(seen, name):
    """What one observer saw, as plain data that two runs can be compared on."""
    if name == "reads":
        return None if seen.reads is None else (list(seen.reads.sources), list(seen.reads.outside), seen.reads.mail_grants)
    return list(getattr(seen, name))


def observed_problems(scenarios, tmp_path, before=()) -> list:
    """Replay each scenario once with the five observers and run the five checks over what they saw: the problems, each under the label of its owner. Every check runs."""
    _, recorded = rp.golden()
    envelope_ids = {s["id"] for s in fd.envelope_scenarios()}
    rows, changed = [], []
    for scenario in scenarios:
        outcome, seen = observe(scenario, tmp_path, before=before)
        rows.append((scenario, seen))
        diffs = rp.differences(recorded[scenario["id"]], outcome)
        if diffs:
            changed.append(rp.describe(scenario, diffs))
    checks = {"claims": ot.claims_problems([(s["id"], seen.claims) for s, seen in rows]),
              "ops": ot.ops_trace_problems([(s, seen.ops) for s, seen in rows], recorded),
              "bridge": to.bridge_trace_problems([(s, seen.bridge) for s, seen in rows], recorded),
              "reads": tg.reads_problems([(s, seen.reads) for s, seen in rows]),
              "envelope": fd.envelope_problems([(s, seen.envelope) for s, seen in rows], envelope_ids)}
    found = [f"{LABELS[name]}: {line}" for name in OBSERVERS for line in checks[name]]
    return found + [f"{OUTCOME_LABEL}: {text}" for text in changed]


@pytest.mark.parametrize("shard", range(OBSERVED_SHARDS))
def test_the_corpus_observed_once(shard, tmp_path):
    scenarios = shard_of(rp.corpus(), shard)
    assert scenarios
    problems = observed_problems(scenarios, tmp_path)
    assert not problems, f"{len(problems)} problems in {len(scenarios)} scenarios of shard {shard}:\n" + "\n".join(problems[:MAX_SHOWN])


# --- the partition ----------------------------------------------------------------------------------------------------------------------------------


def partition_problems(parts, corpus) -> list:
    """What is wrong with `parts` (the shards, in order) as a partition of `corpus`: a scenario in two shards, a scenario in none, the interleaving of the corpus (scenario i in shard i modulo the count)."""
    ids = [s["id"] for part in parts for s in part]
    found = []
    if len(ids) != len(set(ids)):
        found.append("a scenario is in two shards")
    missing = [s["id"] for s in corpus if s["id"] not in set(ids)]
    if missing:
        found.append(f"{len(missing)} scenarios are in no shard, the first is {missing[0]}")
    if not missing and not found:
        found += [f"scenario {index} is not in its place" for index, s in enumerate(corpus) if parts[index % len(parts)][index // len(parts)]["id"] != s["id"]][:1]
    return found


def test_the_shards_are_disjoint_and_their_union_is_the_corpus():
    corpus = rp.corpus()
    assert len(corpus) >= 1089 and len({s["id"] for s in corpus}) == len(corpus)
    assert partition_problems([shard_of(corpus, n) for n in range(OBSERVED_SHARDS)], corpus) == []
    assert OBSERVED_SHARDS == 8 and rp.SHARDS == 8
    assert partition_problems([rp.shard_of(corpus, n) for n in range(rp.SHARDS)], corpus) == [], "the golden's own shards are a partition too"


def test_vacuity_a_partition_that_drops_a_shard_or_repeats_a_scenario_is_seen():
    corpus = [{"id": f"p.{n}"} for n in range(20)]
    shards = [[s for index, s in enumerate(corpus) if index % 4 == n] for n in range(4)]
    assert partition_problems(shards, corpus) == []
    assert len(partition_problems(shards[:3], corpus)) == 1 and "in no shard" in partition_problems(shards[:3], corpus)[0], "seven shards of eight would lose a scenario in eight"
    assert partition_problems([shards[0] + shards[1][:1]] + shards[1:], corpus) == ["a scenario is in two shards"]
    assert partition_problems([shards[1], shards[0], shards[2], shards[3]], corpus) == ["scenario 0 is not in its place"]


# --- each check bites, on planted rows (no replay) --------------------------------------------------------------------------------------------------


def test_vacuity_each_check_reports_one_problem_for_one_planted_defect():
    """The oracle of each check is its own literals: a row it must refuse is planted among rows it must accept, and it names exactly one problem."""
    claims = [("a1", [("sim", "messaging", False, True, True), ("oi", "page", False, False, False)])]
    assert ot.claims_problems(claims) == []
    assert len(ot.claims_problems(claims + [("a2", [("pare", "page", True, False, True)])])) == 1, "old != new"
    assert len(ot.claims_problems([("a3", [("sim", "page", False, True, True)])])) == 1, "one answer and one shell only: the check could not see a change"
    assert ot.claims_problems([("a4", [])]) == ["the corpus makes `say` ask the queue decision"]

    recorded = {"o.1": {"trace": ["greeting"]}, "o.2": {"trace": ["delete-file"]}}
    first, second = {"id": "o.1", "channel": "page"}, {"id": "o.2", "channel": "page"}
    assert ot.ops_trace_problems([(first, ["greeting"]), (second, ["delete-file"])], recorded) == []
    assert len(ot.ops_trace_problems([(first, ["greeting"]), (second, ["greeting"])], recorded)) == 1, "a table name that is not the kit's"
    assert len(ot.ops_trace_problems([(first, []), (second, [])], recorded)) == 3, "no row seen: the two lines are wrong, and the dispatch is not seen"

    bridge = {"b.1": {"trace": ["project-switch"]}, "b.2": {"trace": ["attachment-line"]}}
    one, two = {"id": "b.1", "channel": "messaging"}, {"id": "b.2", "channel": "messaging"}
    assert to.bridge_trace_problems([(one, [("project-switch", False)]), (two, [("attachment-line", False)])], bridge) == []
    assert len(to.bridge_trace_problems([(one, [("project-switch", False)]), (two, [("project-switch", False)])], bridge)) == 1, "a table name that is not the kit's"
    assert len(to.bridge_trace_problems([(one, [("project-switch", True)]), (two, [("attachment-line", False)])], bridge)) == 1, "a rewrite the kit does not record as a reply to a card"
    assert to.bridge_trace_problems([({"id": "b.3", "channel": "page"}, [])], bridge) == ["no messaging scenario was seen"]

    def reads(sources=(), outside=(), mail=0):
        planted = object.__new__(tg.Reads)
        planted.sources, planted.outside, planted.mail_grants = list(sources), list(outside), mail
        return planted
    clean = {"id": "r.1"}
    assert tg.reads_problems([(clean, reads(["agenda", "inbox"], mail=1))]) == []
    assert len(tg.reads_problems([(clean, reads(["agenda", "agenda"]))])) == 1, "a source read twice"
    assert len(tg.reads_problems([(clean, reads(["agenda"], outside=["agenda"]))])) == 1, "a read outside a turn"
    assert len(tg.reads_problems([(clean, reads(mail=2))])) == 1, "two mail lookups"

    ids = {"e.1", "e.2"}
    one, other = {"id": "e.1"}, {"id": "e.2"}
    assert fd.envelope_problems([(one, [("1", "m1")]), (other, [("1", "m1"), ("1", "m2")])], ids) == []
    assert len(fd.envelope_problems([(one, [("1", "m1"), ("1", "m1")])], ids)) == 1, "one message read twice"
    assert len(fd.envelope_problems([(one, [("1", "m1"), ("1", "m2"), ("1", "m3")])], ids)) == 1, "three messages read"
    assert len(fd.envelope_problems([(one, [])], ids)) == 1, "the spy saw nothing"
    assert fd.envelope_problems([({"id": "x"}, [("1", "m1"), ("1", "m1")]), (one, [("1", "m1")])], ids) == [], "a scenario outside the set is not judged"


# Three scenarios whose line makes `say` ask the queue decision (`code_claims` is called): two page lines and a messaging line that is a reply to a card.
CLAIMS_SCENARIOS = ("command.take.08", "router-question.near.04", "reply-to-card.take.03")


def negated(mp):
    """A planted defect: `ops_turn.code_claims` answers the negation of the real one."""
    real = ops_turn.code_claims
    mp.setattr(ops_turn, "code_claims", lambda *a, **k: not real(*a, **k))


def a_row_that_takes_nothing(name):
    """A planted defect: the row `name` of the stage `ops` takes nothing, so the table's trace names the row that takes the line instead of the claimer the golden records."""
    return rp.row_never(name)


def reminder_form_that_takes_nothing(mp):
    """A planted defect: the bridge row `reminder-form` takes nothing (S41-11: it reads only `/remind <free words>`), so the table's trace names the row that takes the line instead of the claimer the
    golden records."""
    mp.setitem(messaging_turn.ROWS, "reminder-form", lambda bridge, turn: False)


def a_second_read_of_every_message(mp):
    """A planted defect: the turn's memo of the envelope is gone, so each kind that asks for a record reads it again."""
    mp.setattr(messaging_turn.Turn, "record", lambda self, message_id: self.bridge.ledger.by_message(self.chat, message_id) if message_id else None)


def a_read_outside_a_turn(mp):
    """A planted defect: a provider read of a source is made as the bridge begins to handle the line, before any turn is open (the observer counts it, wherever it was installed)."""
    real = messaging_bridge.Bridge._handle

    def handle(self, update):
        try:
            ops_sources.source_refresh("demo", "agenda")
        except Exception:      # noqa: BLE001 - the read itself may refuse: it was counted when it was asked
            pass
        return real(self, update)
    mp.setattr(messaging_bridge.Bridge, "_handle", handle)


def with_a_reply():
    ids = {s["id"] for s in fd.envelope_scenarios()}
    return [s for s in rp.corpus() if s["id"] in ids and s["reply_to"] is not None]


# (the owner's name in LABELS, the planted hook, the scenarios, a part of the text the owner's problems have when it sees the defect: the lines of coverage are not that)
PLANTED = {
    "claims": (negated, lambda: [s for s in rp.corpus() if s["id"] in CLAIMS_SCENARIOS], "the frozen expression says"),
    "ops": (a_row_that_takes_nothing("greeting"), lambda: rp.scenarios_of("greeting", 2), ": table "),
    "bridge": (reminder_form_that_takes_nothing, lambda: to.lines_of("reminder-form", 2), ": table "),
    "reads": (a_read_outside_a_turn, lambda: [s for s in rp.corpus() if s["channel"] == "messaging"][:2], "outside a turn"),
    "envelope": (a_second_read_of_every_message, lambda: with_a_reply()[:3], "read twice"),
}


@pytest.mark.parametrize("owner", OBSERVERS)
def test_vacuity_a_defect_in_each_observed_property_is_reported_by_the_observed_test_itself_under_its_owner(owner, tmp_path):
    """End to end, through the function the real test calls, on real scenarios: with the defect planted before the observers are installed, the owner's check reports it under its label (a real scenario, no
    planted row). The same scenarios without it give no such problem. No cache stands between the patch and the result: every call computes its own scenario."""
    hook, chosen, part = PLANTED[owner]
    scenarios = chosen()
    assert len(scenarios) >= 2, f"the corpus holds scenarios for the defect of {owner}"
    seen = lambda found: [p for p in found if p.startswith(LABELS[owner] + ": ") and part in p]
    assert seen(observed_problems(scenarios, tmp_path)) == [], "control: the same scenarios, unplanted, give no such problem"
    planted = observed_problems(scenarios, tmp_path, before=[hook])
    assert seen(planted), planted[:3]


# --- the observers do not disturb each other ---------------------------------------------------------------------------------------------------------

# Six scenarios picked so that four observers record something on at least one of them: a reply to a card (the envelope, the bridge trace, the claims), a page line with claims calls, an operations
# dispatch, a card word, a line the bridge says, a line that goes to the planning agent (the model route). The reads observer records nothing on any scenario of the corpus: it holds no stale source
# (test_turn_gate_refresh.py: the corpus proves that nothing in it breaks the budget; the reads themselves are the scripted tests), so for it the test shows that it changes no outcome and sees nothing.
TRANSPARENCY_SCENARIOS = ("reply-to-card.take.03", "command.take.08", "router-question.take.02", "card-word.take.08", "say.take.06", "drop-invalid-attachments.near.04")


def transparency_problems(scenarios, tmp_path, before_composed=()) -> list:
    """For each scenario: the outcome with no observer, with the five together (after the hooks of `before_composed`, a defect planted for the test) and with each alone; what each observer sees alone and
    together; the problems, and the observers that recorded nothing on every scenario."""
    _, recorded = rp.golden()
    found, seen_something = [], {name: False for name in OBSERVERS}
    for scenario in scenarios:
        sid = scenario["id"]
        bare = rp.replay(scenario, tmp_path)
        outcome, composed = observe(scenario, tmp_path, before=before_composed)
        if outcome != bare:
            found.append(f"{sid}: the five observers together changed the outcome")
        if rp.differences(recorded[sid], outcome):
            found.append(f"{sid}: the outcome with the observers is not the golden's")
        for name in OBSERVERS:
            alone_outcome, alone = observe(scenario, tmp_path, observers=(name,))
            if alone_outcome != bare:
                found.append(f"{sid}: the observer {name} changed the outcome")
            if signature(alone, name) != signature(composed, name):
                found.append(f"{sid}: {name} sees something else when the others are installed")
            seen_something[name] = seen_something[name] or signature(composed, name) not in ([], ([], [], 0))
    return found + [f"{name}: nothing recorded on any of the scenarios" for name in OBSERVERS if name != "reads" and not seen_something[name]]


def test_the_observers_do_not_see_each_other(tmp_path):
    """Each observer installed alone records what it records in the composed run, and the composed outcome is the outcome with no observer (and the golden's); four of the five record something."""
    scenarios = [s for s in rp.corpus() if s["id"] in TRANSPARENCY_SCENARIOS]
    assert len(scenarios) == len(TRANSPARENCY_SCENARIOS) == 6
    assert transparency_problems(scenarios, tmp_path) == []


def test_vacuity_a_hook_that_acts_only_when_the_observers_are_together_is_seen_by_the_transparency_test(tmp_path):
    """The comparison above can fail: a defect planted for the composed run only (the negated `code_claims`) makes the claims record, and the outcome of the scenarios that ask the queue decision, differ
    from the run of the observer alone; and a set of scenarios that no observer records anything on is reported."""
    scenarios = [s for s in rp.corpus() if s["id"] in CLAIMS_SCENARIOS]
    found = transparency_problems(scenarios, tmp_path, before_composed=[negated])
    assert any("claims sees something else" in line for line in found), found[:4]
    quiet = [s for s in rp.corpus() if s["id"] == "drop-unlisted.take.01"]
    assert transparency_problems(quiet, tmp_path) == [f"{name}: nothing recorded on any of the scenarios" for name in ("claims", "ops", "envelope")], "a scenario the observers see nothing on shows nothing"
