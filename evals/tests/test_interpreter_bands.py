"""Offline tests of the interpreter's bands and the go computation (evals/interpreter_status.py). The checkouts are small folders
written from the test's own literal data (interpreter_fixtures.py); every expected band and cause below is the test's own literal, not a
computation of the code under test. No model is called."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

import interpreter_fixtures as fx

REPO = Path(__file__).resolve().parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ist = load("interpreter_status_bands_test", "evals/interpreter_status.py")

T1, T2, T3, T4 = fx.TEST_IDS[:4]


def scenario(root, plan=None, later=None, route="fx-cheap", model="example/cheap-1", test=T1, sequential=True, cost=0.001, mutate=None,
             **event_change):
    """A checkout with one complete test event of `route`: 100 items in each of the six languages, two runs, all `correct` but `plan`."""
    hs = fx.checkout(root)
    cells = fx.corpus(100, plan)
    lines = fx.lines_of(test, cells, later_runs=later, cost=cost)
    if mutate:
        mutate(lines)
    fx.write_file(root, fx.event(test, hs, route=route, model=model, sequential=sequential, **event_change), lines)
    return hs


def rows_of(root, route="fx-cheap"):
    return {r["lang"]: r for r in ist.status(str(root))["rows"] if r["route"] == route}


def bands(root, route="fx-cheap"):
    return {lang: r["band"] for lang, r in rows_of(root, route).items()}


# --- the Wilson upper bound, against literal values ------------------------------------------------------------------------

@pytest.mark.parametrize("k,n,expected", [(0, 800, 0.004779), (16, 800, 0.032240), (3, 100, 0.084521), (0, 188, 0.020025), (0, 189, 0.019921)])
def test_wilson_upper_matches_the_literal_values(k, n, expected):
    assert round(ist.wilson_upper(k, n, 1.96), 6) == expected


def test_a_two_percent_point_rate_fails_the_two_percent_bound():
    assert ist.wilson_upper(16, 800, 1.96) > 0.02  # 16 of 800 is a 2% point rate: the bound is 3.2%
    assert ist.wilson_upper(0, 800, 1.96) < 0.02


# --- a reliable route, and the bands that are not --------------------------------------------------------------------------

def test_every_condition_holding_gives_reliable_in_every_language(tmp_path):
    scenario(tmp_path)
    assert bands(tmp_path) == {lang: "reliable" for lang in fx.LANGS}
    assert rows_of(tmp_path)["en"]["items"] == 100
    # the other route has no run: needs a run, and the cause says so
    other = rows_of(tmp_path, "fx-ref")
    assert {r["band"] for r in other.values()} == {"needs a run"} and other["en"]["cause"] == "no test run of this route"


def test_an_exact_point_rate_at_the_maximum_passes(tmp_path):
    scenario(tmp_path, {("en", n): "wrong_card" for n in (1, 2, 3)})  # 3 of 100 is the 3% maximum, not over it
    assert bands(tmp_path)["en"] == "reliable"


ALONE = [
    # name, the cells that go wrong, the languages that fall, the cause starts with
    ("wrong_effect_unconfirmed", {("en", 1): "wrong_effect_unconfirmed"}, set(fx.LANGS), "wrong_effect_unconfirmed"),
    ("clarify_rate", {**{("pt-BR", n): "clarify" for n in range(1, 11)}, **{("en", n): "clarify" for n in range(1, 11)},
                      **{(lang, n): "clarify" for lang, k in (("es", 20), ("fr", 20), ("de", 16), ("it", 16)) for n in range(1, k + 1)}},
     set(fx.LANGS), "clarify_rate"),
    ("es correct_direct", {("es", n): "missed" for n in range(1, 27)}, {"es"}, "es correct_direct"),
] + [
    (f"{cat} Wilson upper bound", {(lang, n): cat for lang in fx.LANGS for n in (1, 2)}, set(fx.LANGS), f"{cat} Wilson upper bound")
    for cat in ("wrong_card", "wrong_read", "wrong_reminder_reading", "wrong_item_binding")
] + [
    (f"en {cat} rate", {("en", n): cat for n in (1, 2, 3, 4)}, {"en"}, f"en {cat} rate")
    for cat in ("wrong_card", "wrong_read", "wrong_reminder_reading", "wrong_item_binding")
]


@pytest.mark.parametrize("name,plan,fall,cause", ALONE, ids=[a[0] for a in ALONE])
def test_each_threshold_failing_alone_gives_below_the_gate_with_its_cause(tmp_path, name, plan, fall, cause):
    scenario(tmp_path, plan)
    rows = rows_of(tmp_path)
    for lang in fx.LANGS:
        if lang in fall:
            assert rows[lang]["band"] == "below the gate", (name, lang)
            assert rows[lang]["cause"].startswith(cause), (name, lang, rows[lang]["cause"])
        else:
            assert rows[lang]["band"] == "reliable", (name, lang, rows[lang]["cause"])


def test_the_p95_latency_failing_alone(tmp_path):
    def slow(lines):  # a tenth of the calls take 5 seconds: the p95 is over the 4 seconds allowed
        for line in lines[::10]:
            line["latency_ms"] = 5000
    scenario(tmp_path, mutate=slow)
    rows = rows_of(tmp_path)
    assert {r["band"] for r in rows.values()} == {"below the gate"}
    assert all(r["cause"].startswith("p95_latency_ms is 5000") for r in rows.values())


def test_a_zero_count_is_reported_by_the_rule_of_three(tmp_path):
    hs = fx.checkout(tmp_path, per_lang=20)  # 20 items in each language: even no error cannot reach the 2% bound (3.84 / 123.84 = 3.1%)
    fx.write_file(tmp_path, fx.event(T1, hs, items=120), fx.lines_of(T1, fx.corpus(20)))
    cause = rows_of(tmp_path)["de"]["cause"]
    assert cause == "wrong_card Wilson upper bound is 0.0310, over 0.02 (0 of 120: < 3/120 by the rule of three)"
    # twelve errors of 600: the same words, with the count
    scenario(tmp_path / "other", {(lang, n): "wrong_card" for lang in fx.LANGS for n in (1, 2)})
    assert rows_of(tmp_path / "other")["de"]["cause"].startswith("wrong_card Wilson upper bound is 0.0346, over 0.02 (12 of 600)")


def test_the_item_takes_the_worst_category_of_its_runs(tmp_path):
    scenario(tmp_path, later={("en", 1): "wrong_card"})  # run 1 correct, run 2 wrong_card: the item is wrong_card
    assert bands(tmp_path)["en"] == "reliable"  # one wrong item of 600 stays inside every bound
    inputs = ist.load_inputs(str(tmp_path))
    status = ist.route_status(next(r for r in inputs["routes"] if r["id"] == "fx-cheap"), inputs, ist.read_events(str(tmp_path)))
    assert status["overall"]["measures"]["counts"] == {"correct": 599, "wrong_card": 1}
    # a best-of-runs reading would pass this one: 13 items wrong in their second run only fall below the gate
    scenario(tmp_path / "many", later={(lang, n): "wrong_card" for lang in fx.LANGS for n in (1, 2)})
    assert set(bands(tmp_path / "many").values()) == {"below the gate"}


# --- needs a run -----------------------------------------------------------------------------------------------------------

def test_an_item_with_fewer_runs_than_the_thresholds_ask_needs_a_run(tmp_path):
    hs = fx.checkout(tmp_path)
    lines = fx.lines_of(T1, fx.corpus(100), cost=0.001)
    lines = [l for l in lines if not (l["item"] == "test-en-00007" and l["run"] == 2)]
    fx.write_file(tmp_path, fx.event(T1, hs), lines)
    row = rows_of(tmp_path)["en"]
    assert row["band"] == "needs a run" and row["cause"] == "item test-en-00007 has 1 run(s), fewer than 2"


def test_fewer_items_than_the_event_states_needs_a_run(tmp_path):
    hs = fx.checkout(tmp_path)
    cells = {k: v for k, v in fx.corpus(100).items() if k != ("it", 100)}
    fx.write_file(tmp_path, fx.event(T1, hs), fx.lines_of(T1, cells))
    assert rows_of(tmp_path)["it"]["cause"] == "599 of 600 items have a run"


def test_no_sequential_event_needs_a_run(tmp_path):
    scenario(tmp_path, sequential=False)
    assert {r["cause"] for r in rows_of(tmp_path).values()} == {"no sequential run (the latency and the cost are measured on one call at a time)"}
    # a second event, sequential, completes the set: the runs of the first still count
    hs = fx.hashes(tmp_path)
    fx.write_file(tmp_path, fx.event(T2, hs, sequential=True), fx.lines_of(T2, fx.corpus(100)))
    assert set(bands(tmp_path).values()) == {"reliable"}


def test_runs_of_two_events_pool_when_each_has_one_run(tmp_path):
    hs = fx.checkout(tmp_path)
    for test in (T1, T2):
        fx.write_file(tmp_path, fx.event(test, hs, runs=1), fx.lines_of(test, fx.corpus(100), runs=1))
    assert set(bands(tmp_path).values()) == {"reliable"}


# --- a change of an input empties the current set --------------------------------------------------------------------------

def _edit_json(root, rel, change):
    path = Path(root) / rel
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")


INVALIDATIONS = [
    ("prompt", lambda r: (Path(r) / "runtime/interpreter_prompt.txt").write_text("A changed prompt.\n"), "prompt_sha256"),
    ("protocol", lambda r: _edit_json(r, "runtime/interpreter_protocol.json", lambda d: d["params"].update(max_tokens=301)), "protocol_sha256"),
    ("route", lambda r: _edit_json(r, "runtime/interpreter_routes.json", lambda d: d["routes"][0].update(pin="hostthree")), "route_sha256"),
    ("model", lambda r: _edit_json(r, "runtime/interpreter_routes.json", lambda d: d["routes"][0].update(model="example/cheap-2")), "model"),
    ("taxonomy", lambda r: _edit_json(r, "evals/interpreter/taxonomy.json", lambda d: d.update(v=2)), "taxonomy_sha256"),
    ("thresholds", lambda r: _edit_json(r, "evals/interpreter/thresholds.json", lambda d: d.update(statements=["a new statement"])),
     "thresholds_sha256"),
    ("test split", lambda r: _edit_json(r, "evals/interpreter/test-split.json", lambda d: d.update(frozen="2030-11-01")), "corpus_sha256"),
]


@pytest.mark.parametrize("name,change,field", INVALIDATIONS, ids=[i[0] for i in INVALIDATIONS])
def test_a_change_of_an_input_empties_the_current_set(tmp_path, name, change, field):
    scenario(tmp_path)
    assert set(bands(tmp_path).values()) == {"reliable"}
    change(tmp_path)
    after = rows_of(tmp_path)
    assert {r["band"] for r in after.values()} == {"needs a run"}, name
    assert after["en"]["cause"].startswith("changed since the newest test run") and field in after["en"]["cause"], after["en"]["cause"]


def test_a_new_catalog_epoch_empties_the_current_set_and_a_pending_one_does_not(tmp_path):
    scenario(tmp_path)
    h2 = fx.sha(fx.CATALOG_2)
    # the catalog changed and its epoch waits for a rerun: the served catalog is still the old one, so the run still counts
    fx.put(tmp_path, "evals/interpreter/epochs.json", fx.epochs(fx.sha(fx.CATALOG), (h2, "pending-rerun")))
    assert set(bands(tmp_path).values()) == {"reliable"}
    # the new catalog is served: the old run was made on a catalog that is no longer the served one
    fx.put(tmp_path, "runtime/interpreter_catalog.json", fx.CATALOG_2)
    fx.put(tmp_path, "evals/interpreter/epochs.json", {"v": 1, "served": h2, "epochs": [
        {"catalog_sha256": fx.sha(fx.CATALOG), "date": "2030-10-01", "state": "retired"},
        {"catalog_sha256": h2, "date": "2030-10-03", "state": "served"}]})
    after = rows_of(tmp_path)
    assert {r["band"] for r in after.values()} == {"needs a run"} and "catalog_sha256" in after["en"]["cause"]


def test_a_served_file_that_differs_from_the_epoch_gives_needs_a_run_naming_the_file(tmp_path):
    scenario(tmp_path)
    fx.put(tmp_path, "runtime/interpreter_catalog.json", fx.CATALOG_2)  # changed, and the epochs file was not
    row = rows_of(tmp_path)["en"]
    assert row["band"] == "needs a run" and row["cause"].startswith("runtime/interpreter_catalog.json")


@pytest.mark.parametrize("rel", ["runtime/interpreter_protocol.json", "runtime/interpreter_prompt.txt", "evals/interpreter/taxonomy.json",
                                 "evals/interpreter/thresholds.json", "evals/interpreter/test-split.json",
                                 "evals/interpreter/epochs.json"])
def test_a_missing_input_gives_needs_a_run_and_the_cause_names_the_file(tmp_path, rel):
    scenario(tmp_path)
    (tmp_path / rel).unlink()
    rows = [r for r in ist.status(str(tmp_path))["rows"]]
    assert rows and {r["band"] for r in rows} == {"needs a run"}
    assert all(rel in r["cause"] for r in rows), (rel, rows[0]["cause"])


def test_without_a_routes_file_there_are_no_rows(tmp_path):
    scenario(tmp_path)
    (tmp_path / "runtime/interpreter_routes.json").unlink()
    assert ist.status(str(tmp_path))["rows"] == []


def test_a_dev_event_never_counts(tmp_path):
    hs = fx.checkout(tmp_path)
    cells = fx.corpus(100)
    fx.write_file(tmp_path, fx.event(T1, hs, split="dev"), fx.lines_of(T1, cells, split="dev"))
    assert {r["cause"] for r in rows_of(tmp_path).values()} == {"no test run of this route"}


# --- local aggregates demote and never promote -----------------------------------------------------------------------------

def _local(root, test, lang, n=100, hs=None, **counts):
    hs = hs or fx.hashes(root)
    fx.write_file(root, fx.event(test, hs, split="local", runs=1, items=n), [fx.aggregate(test, lang, n, **counts)])


def test_a_newer_local_aggregate_over_a_point_rate_demotes_that_language_only(tmp_path):
    scenario(tmp_path)
    _local(tmp_path, T2, "en", wrong_card=4)  # 4 of 100 is over the 3% point maximum
    got = rows_of(tmp_path)
    assert got["en"]["band"] == "below the gate" and got["en"]["cause"] == "local lines"
    assert {l for l, r in got.items() if r["band"] == "reliable"} == set(fx.LANGS) - {"en"}


def test_a_local_wrong_effect_demotes_every_language(tmp_path):
    scenario(tmp_path)
    _local(tmp_path, T2, "fr", wrong_effect_unconfirmed=1)
    assert set(bands(tmp_path).values()) == {"below the gate"}


def test_a_local_aggregate_inside_the_bounds_does_not_demote_and_does_not_promote(tmp_path):
    scenario(tmp_path, {("es", n): "missed" for n in range(1, 27)})  # es is below the gate on its own
    _local(tmp_path, T2, "es", wrong_card=0)
    got = bands(tmp_path)
    assert got["es"] == "below the gate" and got["en"] == "reliable"
    scenario(tmp_path / "empty")  # nothing run on the cheap route's tests: needs a run stays
    (tmp_path / "empty/evals/interpreter/evidence").joinpath(f"ix-{T1}.jsonl").unlink()
    _local(tmp_path / "empty", T2, "es", wrong_card=0)
    assert set(bands(tmp_path / "empty").values()) == {"needs a run"}


def test_an_older_local_aggregate_and_one_of_another_prompt_do_not_count(tmp_path):
    scenario(tmp_path, test=T3)
    _local(tmp_path, T2, "en", wrong_card=9)  # older than the newest test event
    hs = fx.hashes(tmp_path)
    _local(tmp_path, T4, "de", hs={**hs, "prompt_sha256": fx.H["a"]}, wrong_card=9)  # another prompt: not this checkout's
    assert set(bands(tmp_path).values()) == {"reliable"}


# --- the go computation ----------------------------------------------------------------------------------------------------

def both_routes(root, cheap_cost=0.001, ref_cost=0.0015, cheap_plan=None, ref_plan=None, current_plan=None, current=True):
    hs = fx.checkout(root)
    for test, route, model, cost, plan in ((T1, "fx-cheap", "example/cheap-1", cheap_cost, cheap_plan),
                                           (T2, "fx-ref", "example/strong-1", ref_cost, ref_plan)):
        fx.write_file(root, fx.event(test, hs, route=route, model=model), fx.lines_of(test, fx.corpus(100, plan), cost=cost))
    if current:
        plan = {("en", n): "missed" for n in range(1, 11)} if current_plan is None else current_plan
        fx.write_file(root, fx.current_event(T3, hs), fx.lines_of(T3, fx.corpus(100, plan), cost=None))
    return hs


def go(root):
    return ist.status(str(root))["go"]


def test_go_chooses_the_cheapest_route_that_meets_everything(tmp_path):
    both_routes(tmp_path)
    got = go(tmp_path)
    assert got["go"] is True and got["route"] == "fx-cheap" and got["languages"] == fx.LANGS
    assert got["versus_current"]["correct_direct"][0] == 1.0 and got["versus_current"]["correct_direct"][1] < 1.0
    assert got["versus_current"]["wrong_card"] == [0.0, 0.0]


def test_go_languages_are_those_where_the_reference_route_is_reliable(tmp_path):
    both_routes(tmp_path, ref_plan={("de", n): "missed" for n in range(1, 40)})
    got = go(tmp_path)
    assert got["go"] is True and got["languages"] == ["pt-BR", "en", "es", "fr", "it"]


def test_go_is_no_when_the_reference_route_is_not_reliable_anywhere(tmp_path):
    both_routes(tmp_path, ref_plan={(lang, n): "wrong_effect_unconfirmed" for lang in fx.LANGS for n in (1, 2)})
    got = go(tmp_path)
    assert got["go"] is False and got["languages"] == [] and "reference route" in got["cause"]


def test_go_is_no_when_the_median_cost_is_over_the_limit(tmp_path):
    both_routes(tmp_path, cheap_cost=0.003, ref_cost=0.0025)
    got = go(tmp_path)
    assert got["go"] is False and "fx-cheap: median cost 0.00300 over 0.002 in every language it is reliable in" in got["cause"] and "fx-ref" in got["cause"]


def test_go_falls_to_the_next_route_when_the_cheapest_is_not_better_than_the_current_pipeline(tmp_path):
    # the cheap route makes one wrong card: it is no worse in correct_direct (0.998 > 0.9833) but its wrong_card rate is greater
    both_routes(tmp_path, cheap_plan={("en", 1): "wrong_card"}, current_plan={("en", n): "missed" for n in range(1, 11)})
    got = go(tmp_path)
    assert got["go"] is True and got["route"] == "fx-ref"  # the dearer route has no wrong card


def test_go_is_no_when_the_current_pipeline_is_as_good(tmp_path):
    both_routes(tmp_path, current_plan={})
    got = go(tmp_path)
    assert got["go"] is False and "correct_direct is not greater" in got["cause"]


def test_go_is_no_without_a_run_of_the_current_pipeline(tmp_path):
    both_routes(tmp_path, current=False)
    assert go(tmp_path)["cause"] == "no run of the current pipeline on this test split"


def test_go_is_no_when_no_route_reported_a_cost(tmp_path):
    both_routes(tmp_path, cheap_cost=None, ref_cost=None)
    assert "reported a cost" in go(tmp_path)["cause"]


def test_the_current_pipeline_must_be_run_on_the_same_corpus(tmp_path):
    hs = both_routes(tmp_path, current=False)
    fx.write_file(tmp_path, fx.current_event(T3, hs, corpus_sha256=fx.H["a"]), fx.lines_of(T3, fx.corpus(100), cost=None))
    assert go(tmp_path)["cause"] == "no run of the current pipeline on this test split"


# --- the table, and a vacuity case for the thresholds ----------------------------------------------------------------------

def test_the_table_has_a_line_for_each_route_and_language(tmp_path):
    both_routes(tmp_path)
    lines = ist.table(ist.status(str(tmp_path)))
    assert lines[0].startswith("Interpreter") and len(lines) == 1 + 12 + 1
    assert "  example/strong-1 | fx-ref (reference) | de | reliable | every condition holds" in lines
    assert lines[-1].startswith("  go: yes via fx-cheap for pt-BR, en, es, fr, de, it")


def test_the_command_line_prints_the_table_and_the_go_exit_code(tmp_path, capsys):
    both_routes(tmp_path)
    assert ist.main(["status", "--root", str(tmp_path)]) == 0
    assert "fx-cheap" in capsys.readouterr().out
    assert ist.main(["go", "--root", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["go"] is True
    assert ist.main(["status", "--nope"]) == 2


@pytest.mark.parametrize("name,plan,fall,cause", [a for a in ALONE], ids=[a[0] for a in ALONE])
def test_vacuity_a_band_that_ignores_one_threshold_is_caught(tmp_path, monkeypatch, name, plan, fall, cause):
    """The tests above would fail on a band function that skips this threshold: with it skipped, the planted fault leaves the band
    `reliable`, which is not what they assert."""
    real_overall, real_language = ist.overall_checks, ist.language_checks
    drop = lambda checks: [c for c in checks if not c["name"].startswith(cause)]
    monkeypatch.setattr(ist, "overall_checks", lambda *a: drop(real_overall(*a)))
    monkeypatch.setattr(ist, "language_checks", lambda *a: drop(real_language(*a)))
    scenario(tmp_path, plan)
    assert set(bands(tmp_path).values()) == {"reliable"}


def test_vacuity_a_best_of_runs_reading_is_caught(tmp_path, monkeypatch):
    real = ist.worst_per_item
    def best(items, severity):  # the planted fault: the best category of an item's runs
        return real(items, list(reversed(severity)))
    monkeypatch.setattr(ist, "worst_per_item", best)
    scenario(tmp_path, later={(lang, n): "wrong_card" for lang in fx.LANGS for n in (1, 2)})
    assert set(bands(tmp_path).values()) == {"reliable"}  # the worst-of-runs test above asserts "below the gate"


# --- the status script's command and section -------------------------------------------------------------------------------

es = load("eval_status_interpreter_bands_test", "evals/eval_status.py")


def test_the_interpreter_command_prints_the_table_the_json_and_the_go_exit_code(tmp_path, capsys):
    both_routes(tmp_path)
    assert es.main(["interpreter"], root=str(tmp_path)) == 0
    out = capsys.readouterr().out
    assert out.startswith("Interpreter") and "example/cheap-1 | fx-cheap | en | reliable" in out
    assert es.main(["interpreter", "--json"], root=str(tmp_path)) == 0
    assert json.loads(capsys.readouterr().out)["go"]["route"] == "fx-cheap"
    assert es.main(["interpreter", "--go"], root=str(tmp_path)) == 0
    assert json.loads(capsys.readouterr().out)["go"] is True
    both_routes(tmp_path / "no", cheap_cost=0.003, ref_cost=0.003)
    assert es.main(["interpreter", "--go"], root=str(tmp_path / "no")) == 1


def test_the_flags_of_the_interpreter_command_belong_to_it_alone(tmp_path):
    for argv in (["status", "--go"], ["evidence", "--json"], ["interpreter", "--write"], ["interpreter", "--skill", "core-demo"]):
        with pytest.raises(SystemExit) as stop:
            es.main(argv, root=str(tmp_path))
        assert stop.value.code == 2, argv


def test_status_adds_an_interpreter_section_after_the_skills(tmp_path, capsys):
    both_routes(tmp_path)
    shutil_gate = REPO / "evals" / "eval-gate.json"
    (tmp_path / "evals").mkdir(exist_ok=True)
    (tmp_path / "evals" / "eval-gate.json").write_text(shutil_gate.read_text())
    assert es.main(["status"], root=str(tmp_path)) == 0
    out = json.loads(capsys.readouterr().out)
    assert list(out)[-1] == "interpreter" and out["skills"] == []
    assert out["interpreter"]["go"]["go"] is True and len(out["interpreter"]["rows"]) == 12


def test_the_interpreter_never_moves_a_skill_band(tmp_path, capsys):
    """A skill's row is computed from skills/ alone: the same skill rows with and without interpreter evidence."""
    (tmp_path / "evals").mkdir()
    (tmp_path / "evals" / "eval-gate.json").write_text((REPO / "evals" / "eval-gate.json").read_text())
    skill = tmp_path / "skills" / "core-demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: core-demo\n---\n# demo\n")
    es.main(["status"], root=str(tmp_path))
    before = json.loads(capsys.readouterr().out)
    both_routes(tmp_path)
    es.main(["status"], root=str(tmp_path))
    after = json.loads(capsys.readouterr().out)
    assert before["skills"] == after["skills"] and before["counts"] == after["counts"] and before["causes"] == after["causes"]
    assert before["interpreter"]["rows"] == [] and len(after["interpreter"]["rows"]) == 12


# --- the review of #493: the cases of its probes ---------------------------------------------------------------------------

def missed_from(per_lang, last_good, langs=fx.LANGS):
    """Every cell correct up to `last_good` in each of `langs`, `missed` after it."""
    return {(lang, n): "missed" for lang in langs for n in range(last_good + 1, per_lang + 1)}


def test_p1_a_route_reliable_in_no_language_never_carries_go(tmp_path):
    hs = fx.checkout(tmp_path)
    fx.write_file(tmp_path, fx.event(T1, hs), fx.lines_of(T1, fx.corpus(100, missed_from(100, 70)), cost=0.001))  # correct_direct 0.70 everywhere
    fx.write_file(tmp_path, fx.event(T2, hs, route="fx-ref", model="example/strong-1"), fx.lines_of(T2, fx.corpus(100), cost=0.009))
    fx.write_file(tmp_path, fx.current_event(T3, hs), fx.lines_of(T3, fx.corpus(100, missed_from(100, 50)), cost=None))
    assert set(bands(tmp_path).values()) == {"below the gate"}
    got = go(tmp_path)
    assert got["go"] is False and got["route"] is None
    assert "fx-cheap: reliable in no language where the reference route is reliable" in got["cause"]
    assert "fx-ref: median cost 0.00900 over 0.002 in every language it is reliable in" in got["cause"]


def test_p1_a_route_reliable_only_where_the_reference_is_not_does_not_qualify(tmp_path):
    hs = fx.checkout(tmp_path)
    fx.write_file(tmp_path, fx.event(T1, hs), fx.lines_of(T1, fx.corpus(100, missed_from(100, 60, ("pt-BR", "en", "es", "fr"))), cost=0.001))
    fx.write_file(tmp_path, fx.event(T2, hs, route="fx-ref", model="example/strong-1"),
                  fx.lines_of(T2, fx.corpus(100, missed_from(100, 60, ("de", "it"))), cost=0.009))
    fx.write_file(tmp_path, fx.current_event(T3, hs), fx.lines_of(T3, fx.corpus(100, missed_from(100, 50)), cost=None))
    assert {l for l, b in bands(tmp_path).items() if b == "reliable"} == {"de", "it"}              # the cheap route, only here
    assert {l for l, b in bands(tmp_path, "fx-ref").items() if b == "reliable"} == {"pt-BR", "en", "es", "fr"}
    got = go(tmp_path)
    assert got["go"] is False and got["languages"] == ["pt-BR", "en", "es", "fr"]
    assert "fx-cheap: reliable in no language where the reference route is reliable" in got["cause"]


def test_p1_the_cost_bound_is_checked_in_each_language_the_route_serves(tmp_path):
    both_routes(tmp_path, cheap_cost=0.001, ref_cost=0.0015)
    # the cheap route is dear in Italian only: it serves five languages, and Italian runs on the reference route
    path = tmp_path / "evals/interpreter/evidence" / f"ix-{T1}.jsonl"
    lines = [json.loads(l) for l in path.read_text().splitlines()]
    for line in lines[1:]:
        if line["lang"] == "it":
            line["cost_usd"] = 0.01
    path.write_text("".join(json.dumps(l, sort_keys=True) + "\n" for l in lines))
    got = go(tmp_path)
    assert got["go"] is True and got["route"] == "fx-cheap" and got["languages"] == fx.LANGS
    assert got["route_languages"] == ["pt-BR", "en", "es", "fr", "de"]


def test_p2_the_clarify_rate_leaves_out_the_items_whose_gold_is_clarify(tmp_path):
    hs = fx.checkout(tmp_path)
    cells, golds = {}, {}
    for lang in fx.LANGS:  # 15 gold-clarify items answered by nothing (missed), 14 clarifications of an op, 71 correct
        for n in range(1, 101):
            cells[(lang, n)] = "missed" if n <= 15 else "clarify" if n <= 29 else "correct"
            if n <= 15:
                golds[(lang, n)] = "clarify"
    fx.write_file(tmp_path, fx.event(T1, hs), fx.lines_of(T1, cells, golds=golds))
    inputs = ist.load_inputs(str(tmp_path))
    overall = ist.route_status(inputs["routes"][0], inputs, ist.read_events(str(tmp_path)))["overall"]
    assert abs(overall["measures"]["clarify_rate"] - 84 / 510) < 1e-9  # 14 / 85 in each language: 0.1647, not 84 / 600 = 0.14
    assert overall["band"] == "below the gate" and overall["cause"].startswith("clarify_rate is 0.1647")


def test_the_correct_direct_denominator_leaves_out_the_clarify_gold(tmp_path):
    hs = fx.checkout(tmp_path)
    cells = {(l, n): "correct" for l in fx.LANGS for n in range(1, 101)}
    golds = {(l, n): "clarify" for l in fx.LANGS for n in range(1, 21)}  # 20 correct clarifications per language
    cells.update({("en", n): "missed" for n in range(21, 34)})            # 13 of the 80 direct items missed: 67 / 80 = 0.8375
    fx.write_file(tmp_path, fx.event(T1, hs), fx.lines_of(T1, cells, golds=golds))
    row = rows_of(tmp_path)["en"]
    assert row["band"] == "below the gate" and row["cause"].startswith("en correct_direct is 0.8375")
    assert rows_of(tmp_path)["fr"]["band"] == "reliable" and rows_of(tmp_path)["fr"]["correct_direct"] == 1.0


def test_p3_a_current_pipeline_run_that_is_a_fragment_cannot_decide_go(tmp_path):
    hs = both_routes(tmp_path, current=False)
    fx.write_file(tmp_path, fx.current_event(T3, hs), fx.lines_of(T3, {(l, 1): "missed" for l in fx.LANGS}, runs=1, cost=None))
    cause = go(tmp_path)["cause"]
    assert cause == "needs a run of the current pipeline: 6 of 600 items have a run"
    # a stated-and-held run with one run per item is not enough either (thresholds.runs is 2)
    hs2 = fx.checkout(tmp_path / "b")
    fx.write_file(tmp_path / "b", fx.event(T1, hs2), fx.lines_of(T1, fx.corpus(100), cost=0.001))
    fx.write_file(tmp_path / "b", fx.event(T2, hs2, route="fx-ref", model="example/strong-1"), fx.lines_of(T2, fx.corpus(100), cost=0.001))
    fx.write_file(tmp_path / "b", fx.current_event(T3, hs2), fx.lines_of(T3, fx.corpus(100), runs=1, cost=None))
    assert go(tmp_path / "b")["cause"] == "needs a run of the current pipeline: item test-de-00001 has 1 run(s), fewer than 2"


def test_p3_the_current_pipeline_must_carry_the_same_taxonomy_thresholds_and_catalog(tmp_path):
    for field in ("taxonomy_sha256", "thresholds_sha256", "catalog_sha256"):
        root = tmp_path / field
        hs = both_routes(root, current=False)
        fx.write_file(root, fx.current_event(T3, hs, **{field: fx.H["a"]}), fx.lines_of(T3, fx.corpus(100, missed_from(100, 50)), cost=None))
        assert go(root)["cause"] == "no run of the current pipeline on this test split", field


def test_p4_a_local_wrong_effect_demotes_the_overall_band_and_go_does_not_use_the_route(tmp_path):
    hs = both_routes(tmp_path, ref_cost=0.0015)
    _local(tmp_path, T4, "pt-BR", n=50, hs=hs, wrong_effect_unconfirmed=3, wrong_card=10)
    inputs = ist.load_inputs(str(tmp_path))
    events = ist.read_events(str(tmp_path))
    cheap = ist.route_status(inputs["routes"][0], inputs, events)
    assert cheap["overall"]["band"] == "below the gate" and cheap["overall"]["cause"] == "local lines"
    assert {r["band"] for r in cheap["rows"]} == {"below the gate"}
    got = go(tmp_path)
    assert got["go"] is True and got["route"] == "fx-ref"  # the cheap route no longer qualifies; the reference does


def test_p5_a_sampled_run_of_the_test_split_is_not_the_split(tmp_path):
    hs = fx.checkout(tmp_path)  # the split has 600 items
    fx.write_file(tmp_path, fx.event(T1, hs, items=300), fx.lines_of(T1, fx.corpus(50), cost=0.001))
    row = rows_of(tmp_path)["en"]
    assert row["band"] == "needs a run"
    assert row["cause"] == f"event {T1} states 300 items and the test split has 600: a sample of the split is not the split"


def test_a_run_that_states_the_split_but_holds_other_items_per_language_needs_a_run(tmp_path):
    hs = fx.checkout(tmp_path)
    cells = {k: v for k, v in fx.corpus(100).items() if k[0] != "it"}
    cells.update({("en", n): "correct" for n in range(101, 201)})  # 600 items, but 200 in English and none in Italian
    fx.write_file(tmp_path, fx.event(T1, hs), fx.lines_of(T1, cells))
    assert rows_of(tmp_path)["it"]["cause"] == "200 items of language en have a run, and the test split has 100"


def test_a_test_split_without_its_counts_gives_needs_a_run_naming_the_file(tmp_path):
    scenario(tmp_path)
    fx.put(tmp_path, "evals/interpreter/test-split.json", {"v": 1, "file": "x.jsonl"})
    row = rows_of(tmp_path)["en"]
    assert row["band"] == "needs a run" and row["cause"].startswith("evals/interpreter/test-split.json does not state its items")


def test_the_rows_publish_the_per_language_wilson_bound_and_the_sequential_sample(tmp_path):
    scenario(tmp_path)
    row = rows_of(tmp_path)["en"]
    assert round(row["wilson"]["wrong_card"], 4) == 0.037  # 0 of 100: 3.8416 / 103.8416
    inputs = ist.load_inputs(str(tmp_path))
    overall = ist.route_status(inputs["routes"][0], inputs, ist.read_events(str(tmp_path)))["overall"]
    assert overall["sequential"] == {"calls": 1200, "items": 600, "of": 600}


def test_vacuity_a_go_that_ignores_the_route_languages_is_caught(tmp_path, monkeypatch):
    """With the per-route language check removed, the P1 setup says go: the test above asserts that it does not."""
    real = ist.go_of
    def blind(inputs, statuses, events):
        for _, status in statuses:  # the planted fault: treat every row as reliable where the reference is
            for row in status["rows"]:
                row["band"] = "reliable"
            status["overall"]["band"] = "reliable"
        return real(inputs, statuses, events)
    monkeypatch.setattr(ist, "go_of", blind)
    hs = fx.checkout(tmp_path)
    fx.write_file(tmp_path, fx.event(T1, hs), fx.lines_of(T1, fx.corpus(100, missed_from(100, 70)), cost=0.001))
    fx.write_file(tmp_path, fx.event(T2, hs, route="fx-ref", model="example/strong-1"), fx.lines_of(T2, fx.corpus(100), cost=0.009))
    fx.write_file(tmp_path, fx.current_event(T3, hs), fx.lines_of(T3, fx.corpus(100, missed_from(100, 50)), cost=None))
    assert go(tmp_path)["go"] is True
