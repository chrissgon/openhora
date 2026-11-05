"""Offline tests of the account route in the interpreter's evidence and status (ACCT-D; SPEC-ACCT-ROUTE sections 3.4 and 4): a Claude model
is measured on the maintainer's own account, so an event that names one cannot be `metered`, no cost is stated under an event that is
not metered, and the account reference is judged on accuracy only while latency and cost stay required of the route that runs daily.
Every expected value is the test's own literal (a model id, a hash computed once offline, a band, a cost worked by hand); each
invariant has a vacuity case that fails on a planted wrong result. The models and routes are fixtures. No model is called."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

import interpreter_fixtures as fx
# Every pinned hash of the test suite is in scripts/tests/pinned_hashes.json, with what it hashes and why it is pinned.
PINNED_HASHES = json.loads((Path(__file__).resolve().parents[2] / "scripts" / "tests" / "pinned_hashes.json").read_text(encoding="utf-8"))["pins"]

REPO = Path(__file__).resolve().parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


el = load("evidence_lines_account_status_test", "evals/evidence_lines.py")
ist = load("interpreter_status_account_status_test", "evals/interpreter_status.py")
es = load("eval_status_account_status_test", "evals/eval_status.py")

T1, T2, T3, T4 = fx.TEST_IDS[:4]

# --- the test's own literals ------------------------------------------------------------------------------------------------------

ACCT_ID = "fx-acct-ref"
ACCT_MODEL = "claude-sonnet-5-5"
ACCT = {"id": ACCT_ID, "kind": "account", "model": ACCT_MODEL, "upstream_model": ACCT_MODEL, "lab_model": ACCT_MODEL,
        "pin": "anthropic", "params": {"max_tokens": 2000, "reasoning": "low", "temperature": None}, "deadline_ms": 60000,
        "runner_version": "fx-1", "runner_sha256": fx.H["a"], "envelope_sha256": fx.H["b"], "reference": True,
        "retention": "A fictional account route: sent under a fictional subscription."}
# The sha256 of the canonical JSON of ACCT without `retention` and `reference` (sorted keys, compact separators), computed once offline.
ACCT_SHA = PINNED_HASHES["route_account_status_test_row"]
DEEPSEEK_SHA = PINNED_HASHES["route_or_deepseek_v4_1_flash"]  # SPEC-ACCT-ROUTE 0.7: the committed DeepSeek row
CHEAP = {**fx.route_row("fx-cheap", "example/cheap-1", "cheap/cheap-1", "hostone"), "kind": "http"}
ROUTES = {"v": 1, "routes": [CHEAP, ACCT]}
PRICES = {"version": 1, "models": {"anthropic/claude-sonnet-5-5": {
    "aliases": ["claude-sonnet-5-5"], "input_usd_per_mtok": 2, "output_usd_per_mtok": 10, "cache_read_usd_per_mtok": 0.2,
    "cache_write_usd_per_mtok": 2.5, "source": "https://prices.example/models", "accessed": "2030-10-01"}}}
LATENCY_NOTE = "not a condition on an account route"
PRICE_NOTE = "proxy, not paid, not a go input"
# The usage of fx.item's default line (900 input, 40 output tokens) at the prices above: 900*2/1e6 + 40*10/1e6 = 0.0022 USD.
DEFAULT_LINE_USD = 0.0022


def checkout(root, routes=ROUTES, prices=PRICES):
    """The fixture checkout (its hashes are those of the default routes, which the routes file does not enter), then the routes file of
    this test: a metered http route and an account reference."""
    hs = fx.checkout(root)
    fx.put(root, "runtime/interpreter_routes.json", routes)
    if prices is not None:
        fx.put(root, "runtime/prices.json", prices)
    hs["route_sha256:" + ACCT_ID] = ACCT_SHA
    return hs


def acct_event(test, hs, **change):
    return fx.event(test, hs, **{"route": ACCT_ID, "model": ACCT_MODEL, "billing": "subscription", **change})


def acct_lines(test, plan=None, latency=9000, **change):
    return fx.lines_of(test, fx.corpus(100, plan), cost=None, latency=latency, upstream="anthropic", **change)


def account_run(root, plan=None, latency=9000, sequential=True, prices=PRICES):
    """The account reference with one complete event (100 items in each of six languages, two runs), every call taking `latency` ms."""
    hs = checkout(root, prices=prices)
    fx.write_file(root, acct_event(T1, hs, sequential=sequential), acct_lines(T1, plan, latency))
    return hs


def go_fixture(root, cheap_plan=None, acct_plan=None, latency=9000):
    """The account reference (p95 9000 ms), the metered http route that runs daily, and a current-pipeline run that is worse than both."""
    hs = checkout(root)
    fx.write_file(root, acct_event(T1, hs), acct_lines(T1, acct_plan, latency))
    fx.write_file(root, fx.event(T2, hs), fx.lines_of(T2, fx.corpus(100, cheap_plan), cost=0.001))
    fx.write_file(root, fx.current_event(T3, hs), fx.lines_of(T3, fx.corpus(100, {("en", n): "missed" for n in range(1, 61)}), cost=None))
    return hs


def rows_of(root, route):
    return {r["lang"]: r for r in ist.status(str(root))["rows"] if r["route"] == route}


def overall_of(root, route=ACCT_ID):
    inputs = ist.load_inputs(str(root))
    row = next(r for r in inputs["routes"] if r["id"] == route)
    return ist.route_status(row, inputs, ist.read_events(str(root)), inputs["prices"])["overall"]


# =============================================================================================================================
# Guard 4: the evidence lines
# =============================================================================================================================

def event_problems(model, billing, **change):
    return el.interpreter_event_problems(fx.event(T1, checkout_hashes(), model=model, billing=billing, **change))


def checkout_hashes():
    return {"protocol_sha256": fx.H["a"], "prompt_sha256": fx.H["b"], "catalog_sha256": fx.H["c"], "corpus_sha256": fx.H["d"],
            "taxonomy_sha256": fx.H["e"], "thresholds_sha256": fx.H["f"], "harness_sha256": fx.H["0"], "route_sha256:fx-cheap": fx.H["1"]}


METERED_CLAUDE = ["openrouter/anthropic/claude-sonnet-5.5", "claude-sonnet-5-5", "claude-haiku-4-5", "ANTHROPIC/model-1", "x/Claude-mini",
                  "vendor/anthropic-like"]


@pytest.mark.parametrize("model", METERED_CLAUDE)
def test_a_metered_event_that_names_a_claude_model_is_refused(model):
    found = event_problems(model, "metered")
    assert len(found) == 1 and "metered" in found[0] and "account" in found[0], found


def test_the_same_models_on_the_account_and_a_deepseek_model_metered_are_valid():
    for model in ("claude-sonnet-5-5", "claude-haiku-4-5", "openrouter/anthropic/claude-sonnet-5.5"):
        assert event_problems(model, "subscription") == [], model
    assert event_problems("openrouter/deepseek/deepseek-v4.1-flash", "metered") == []
    assert event_problems("example/cheap-1", "metered") == []


def test_the_current_pipeline_arm_names_no_model_and_is_not_metered():
    event = fx.current_event(T1, checkout_hashes())
    assert event["model"] is None and event["billing"] == "none" and el.interpreter_event_problems(event) == []


def test_billing_gains_subscription_and_no_other_word():
    assert sorted(el.IX_BILLING) == ["metered", "none", "subscription"]
    for word in ("free", "paid", "Subscription", "", None, True, 1):
        assert any("billing" in p for p in el.interpreter_event_problems({**fx.event(T1, checkout_hashes()), "billing": word})), word


def refuses_metered_claude(problems_of):
    """The oracle of the guard, over an event-problems function: every literal Claude model is refused when metered and accepted on the
    account, and a DeepSeek model is accepted metered."""
    def run(model, billing):
        return problems_of(fx.event(T1, checkout_hashes(), model=model, billing=billing))
    return (all(run(m, "metered") for m in METERED_CLAUDE) and not any(run(m, "subscription") for m in METERED_CLAUDE)
            and not run("openrouter/deepseek/deepseek-v4.1-flash", "metered"))


def test_vacuity_the_claude_oracle_catches_a_guard_that_is_off(monkeypatch):
    assert refuses_metered_claude(el.interpreter_event_problems)
    monkeypatch.setattr(el, "IX_METERED_FORBIDDEN", ())  # the planted fault: the guard's word list emptied
    assert not refuses_metered_claude(el.interpreter_event_problems)
    monkeypatch.setattr(el, "IX_METERED_FORBIDDEN", ("claude",))  # a guard that knows one of the two words misses the vendor's name
    assert not refuses_metered_claude(el.interpreter_event_problems)


def cost_cases(item_problems):
    """(label, whether the item line is refused) for a cost of 0.001 and a null cost under each billing word."""
    out = {}
    for billing in ("metered", "subscription", "none"):
        event = fx.event(T1, checkout_hashes(), billing=billing)
        out[(billing, 0.001)] = bool(item_problems(fx.item(T1, 1, "en", "correct", cost=0.001), event))
        out[(billing, None)] = bool(item_problems(fx.item(T1, 1, "en", "correct", cost=None), event))
    return out


def test_a_cost_under_an_event_that_is_not_metered_is_refused():
    got = cost_cases(el.interpreter_item_problems)
    assert got == {("metered", 0.001): False, ("metered", None): False, ("subscription", 0.001): True, ("subscription", None): False,
                   ("none", 0.001): True, ("none", None): False}
    found = el.interpreter_item_problems(fx.item(T1, 1, "en", "correct", cost=0.001), fx.event(T1, checkout_hashes(), billing="subscription"))
    assert found == ["cost_usd must be null in an event that is not metered"]


def test_vacuity_the_cost_oracle_catches_a_check_that_only_knows_none():
    def old(line, event=None):  # the planted fault: the earlier rule, which refused a cost under `none` alone
        found = el.interpreter_item_problems(line, event)
        if event is not None and event.get("billing") == "subscription":
            found = [p for p in found if "not metered" not in p]
        return found
    assert cost_cases(old)[("subscription", 0.001)] is False  # the planted function lets it through: the test above would fail on it


def test_a_whole_account_file_is_valid_and_a_cost_in_it_makes_it_invalid(tmp_path):
    hs = checkout_hashes()
    event = acct_event(T1, {**hs, "route_sha256:" + ACCT_ID: ACCT_SHA}, items=2)
    items = [fx.item(T1, n, "en", "correct", run=r, cost=None, upstream="anthropic") for n in (1, 2) for r in (1, 2)]
    good = fx.write_file(tmp_path / "good", event, items)
    assert el.interpreter_file_problems(str(good)) == []
    items[1] = {**items[1], "cost_usd": 0.0005}
    bad = fx.write_file(tmp_path / "bad", event, items)
    assert any("line 3" in p and "cost_usd must be null" in p for p in el.interpreter_file_problems(str(bad)))
    leaked = fx.write_file(tmp_path / "leaked", {**event, "billing": "metered"}, [{**i, "cost_usd": 0.0005} for i in items])
    assert any("line 1" in p and "metered" in p for p in el.interpreter_file_problems(str(leaked)))


def test_the_committed_evidence_files_still_validate():
    folder = REPO / "evals" / "interpreter" / "evidence"
    files = sorted(p for p in folder.iterdir() if p.suffix == ".jsonl")
    assert "ix-20261021T025640Z-4cbd16f0.jsonl" in [p.name for p in files]
    for path in files:
        assert el.interpreter_file_problems(str(path)) == [], path.name
    assert "20261021T025640Z-4cbd16f0" in [e[0]["test"] for e in ist.read_events(str(REPO))]


def test_vacuity_a_planted_cost_in_a_copy_of_the_committed_file_is_refused(tmp_path):
    source = (REPO / "evals" / "interpreter" / "evidence" / "ix-20261021T025640Z-4cbd16f0.jsonl").read_text().splitlines()
    event = json.loads(source[0])
    assert event["billing"] == "none"
    first = json.loads(source[1])
    assert first["cost_usd"] is None
    first["cost_usd"] = 0.25
    copy = tmp_path / "ix-20261021T025640Z-4cbd16f0.jsonl"
    copy.write_text("\n".join([source[0], json.dumps(first, sort_keys=True)] + source[2:]) + "\n")
    assert any("line 2" in p and "cost_usd must be null" in p for p in el.interpreter_file_problems(str(copy)))


# =============================================================================================================================
# Section 4: the status judges the account reference on accuracy only
# =============================================================================================================================

def test_the_route_hashes_are_the_literals():
    assert ist.route_sha256(ACCT) == ACCT_SHA
    assert ist.route_sha256({**ACCT, "reference": False, "retention": "another text"}) == ACCT_SHA  # neither key is hashed
    assert ist.route_sha256({**ACCT, "params": {**ACCT["params"], "reasoning": "high"}}) != ACCT_SHA
    deepseek = next(r for r in json.loads((REPO / "runtime" / "interpreter_routes.json").read_text())["routes"] if r["id"] == "or-deepseek-v4.1-flash")
    assert ist.route_sha256(deepseek) == DEEPSEEK_SHA
    assert ist.route_sha256(CHEAP) == ist.route_sha256({k: v for k, v in CHEAP.items() if k != "kind"})  # `kind` is not hashed for http


def test_the_account_reference_is_reliable_on_accuracy_with_a_p95_of_9000_ms(tmp_path):
    account_run(tmp_path)
    rows = rows_of(tmp_path, ACCT_ID)
    assert {lang: r["band"] for lang, r in rows.items()} == {lang: "reliable" for lang in fx.LANGS}
    assert rows["en"]["cause"] == "every condition holds" and rows["en"]["items"] == 100
    overall = overall_of(tmp_path)
    assert overall["band"] == "reliable" and overall["p95_latency_ms"] == 9000 and overall["p95_latency_note"] == LATENCY_NOTE
    assert [c["name"] for c in overall["checks"]] == [
        "wrong_effect_unconfirmed", "wrong_card Wilson upper bound", "wrong_read Wilson upper bound",
        "wrong_reminder_reading Wilson upper bound", "wrong_item_binding Wilson upper bound", "clarify_rate"]
    assert overall["median_cost_usd"] is None


def test_the_same_latency_on_an_http_route_is_below_the_gate(tmp_path):
    hs = checkout(tmp_path)
    fx.write_file(tmp_path, fx.event(T1, hs), fx.lines_of(T1, fx.corpus(100), cost=0.001, latency=9000))
    rows = rows_of(tmp_path, "fx-cheap")
    assert {r["band"] for r in rows.values()} == {"below the gate"} and rows["en"]["cause"] == "p95_latency_ms is 9000, over 4000"


def test_the_account_route_needs_no_sequential_event_and_an_http_route_does(tmp_path):
    account_run(tmp_path, sequential=False)
    assert {r["band"] for r in rows_of(tmp_path, ACCT_ID).values()} == {"reliable"}
    overall = overall_of(tmp_path)
    assert overall["p95_latency_ms"] is None and overall["sequential"]["calls"] == 0 and overall["p95_latency_note"] == LATENCY_NOTE
    hs = checkout(tmp_path / "http")
    fx.write_file(tmp_path / "http", fx.event(T1, hs, sequential=False), fx.lines_of(T1, fx.corpus(100), cost=0.001))
    assert rows_of(tmp_path / "http", "fx-cheap")["en"]["cause"] == "no sequential run (the latency and the cost are measured on one call at a time)"


@pytest.mark.parametrize("name,plan,fall,cause", [
    ("wrong_effect_unconfirmed", {("en", 1): "wrong_effect_unconfirmed"}, set(fx.LANGS), "wrong_effect_unconfirmed is 1, over the limit 0"),
    ("wrong_card overall", {(lang, n): "wrong_card" for lang in ("pt-BR", "en", "es", "fr") for n in (1, 2, 3)}, set(fx.LANGS),
     "wrong_card Wilson upper bound"),
    ("wrong_card in one language", {("en", n): "wrong_card" for n in range(1, 5)}, {"en"}, "en wrong_card rate is 0.04, over 0.03"),
    ("clarify", {(lang, n): "clarify" for lang in ("pt-BR", "en", "es") for n in range(1, 41)}, set(fx.LANGS), "clarify_rate is"),
    ("correct_direct", {("de", n): "missed" for n in range(1, 31)}, {"de"}, "de correct_direct is 0.7, under 0.75"),
], ids=["wrong_effect_unconfirmed", "wrong_card_overall", "wrong_card_one_language", "clarify", "correct_direct"])
def test_accuracy_still_decides_the_account_route(tmp_path, name, plan, fall, cause):
    account_run(tmp_path, plan)
    rows = rows_of(tmp_path, ACCT_ID)
    assert {lang for lang, r in rows.items() if r["band"] == "below the gate"} == fall, name
    assert cause in next(r["cause"] for r in rows.values() if r["band"] == "below the gate")


def test_the_account_route_does_not_count_unless_its_row_hash_is_the_events(tmp_path):
    hs = checkout(tmp_path)
    fx.write_file(tmp_path, acct_event(T1, hs, route_sha256=fx.H["0"]), acct_lines(T1))
    row = rows_of(tmp_path, ACCT_ID)["en"]
    assert row["band"] == "needs a run" and "route_sha256" in row["cause"]


def test_vacuity_a_status_that_does_not_know_the_account_kind_is_caught(tmp_path, monkeypatch):
    account_run(tmp_path)
    monkeypatch.setattr(ist, "is_account", lambda route: False)  # the planted fault: the account row is read as an http row
    assert {r["band"] for r in rows_of(tmp_path, ACCT_ID).values()} == {"needs a run"}  # the tests above assert `reliable`


# --- the go -----------------------------------------------------------------------------------------------------------------

def test_go_via_the_deepseek_fixture_route_and_the_languages_it_does_not_serve_are_off(tmp_path):
    go_fixture(tmp_path, cheap_plan={("de", n): "missed" for n in range(1, 31)})
    status = ist.status(str(tmp_path))
    assert {r["band"] for r in rows_of(tmp_path, ACCT_ID).values()} == {"reliable"}
    assert overall_of(tmp_path)["p95_latency_ms"] == 9000
    got = status["go"]
    assert got["go"] is True and got["route"] == "fx-cheap" and got["model"] == "example/cheap-1"
    assert got["languages"] == ["pt-BR", "en", "es", "fr", "de", "it"]  # the reference's reliable languages
    assert got["route_languages"] == ["pt-BR", "en", "es", "fr", "it"]
    assert got["off_languages"] == ["de"]


def test_go_with_a_daily_route_that_serves_every_language_has_none_off(tmp_path):
    go_fixture(tmp_path)
    got = ist.status(str(tmp_path))["go"]
    assert got["go"] is True and got["route"] == "fx-cheap" and got["off_languages"] == []
    assert got["route_languages"] == got["languages"] == fx.LANGS


def test_a_language_the_reference_does_not_pass_is_neither_served_nor_off(tmp_path):
    go_fixture(tmp_path, acct_plan={("fr", n): "missed" for n in range(1, 41)})
    got = ist.status(str(tmp_path))["go"]
    assert got["go"] is True and got["languages"] == ["pt-BR", "en", "es", "de", "it"]
    assert got["route_languages"] == got["languages"] and got["off_languages"] == []


def test_go_is_no_when_the_reference_account_route_is_not_reliable_anywhere(tmp_path):
    go_fixture(tmp_path, acct_plan={(lang, n): "wrong_effect_unconfirmed" for lang in fx.LANGS for n in (1, 2)})
    got = ist.status(str(tmp_path))["go"]
    assert got["go"] is False and got["off_languages"] == [] and "reference route is not reliable in any language" in got["cause"]


def test_the_account_route_is_never_the_daily_route(tmp_path):
    hs = checkout(tmp_path, routes={"v": 1, "routes": [ACCT]})
    fx.write_file(tmp_path, acct_event(T1, hs), acct_lines(T1))
    fx.write_file(tmp_path, fx.current_event(T3, hs), fx.lines_of(T3, fx.corpus(100, {("en", n): "missed" for n in range(1, 61)}), cost=None))
    got = ist.status(str(tmp_path))["go"]
    assert got["go"] is False and got["route"] is None and got["route_languages"] == [] and got["cause"] == "no route"


def test_go_does_not_depend_on_the_latency_of_the_account_route(tmp_path):
    results = []
    for latency in (100, 9000, 60000):
        go_fixture(tmp_path / str(latency), latency=latency)
        results.append(ist.status(str(tmp_path / str(latency)))["go"])
    assert results[0]["go"] is True and results[0]["route"] == "fx-cheap" and results[0] == results[1] == results[2]


def test_vacuity_a_go_that_ignores_the_account_kind_would_price_it_and_lose_the_route_languages(tmp_path, monkeypatch):
    """With the account row read as an http row the account reference has no band, so the go has no languages: the tests above assert
    otherwise."""
    go_fixture(tmp_path)
    monkeypatch.setattr(ist, "is_account", lambda route: False)
    got = ist.status(str(tmp_path))["go"]
    assert got["go"] is False and got["languages"] == []


# --- evidence the status will not read ----------------------------------------------------------------------------------------

def test_an_account_event_billed_as_metered_is_not_evidence(tmp_path):
    hs = checkout(tmp_path)
    fx.write_file(tmp_path, acct_event(T1, hs, billing="metered"), acct_lines(T1))
    assert rows_of(tmp_path, ACCT_ID)["en"]["band"] == "needs a run"


def test_an_account_item_with_a_cost_is_not_evidence(tmp_path):
    hs = checkout(tmp_path)
    lines = acct_lines(T1)
    lines[0] = {**lines[0], "cost_usd": 0.001}
    fx.write_file(tmp_path, acct_event(T1, hs), lines)
    assert rows_of(tmp_path, ACCT_ID)["en"]["band"] == "needs a run"


def test_vacuity_the_same_run_without_the_faults_is_evidence(tmp_path):
    hs = checkout(tmp_path)
    fx.write_file(tmp_path, acct_event(T1, hs), acct_lines(T1))
    assert rows_of(tmp_path, ACCT_ID)["en"]["band"] == "reliable"


# --- the published figures ------------------------------------------------------------------------------------------------------

def test_the_list_price_equivalent_is_published_with_its_source_and_its_label(tmp_path):
    account_run(tmp_path)
    price = overall_of(tmp_path)["list_price_equivalent"]
    assert price["median_usd"] == pytest.approx(DEFAULT_LINE_USD) and price["calls"] == 1200
    assert price["model"] == "anthropic/claude-sonnet-5-5" and price["source"] == "https://prices.example/models"
    assert price["accessed"] == "2030-10-01" and price["note"] == PRICE_NOTE
    assert overall_of(tmp_path)["deviations"] == "reasoning low, temperature as the CLI sends it"


def test_without_a_price_table_the_equivalent_is_unknown_and_the_band_is_the_same(tmp_path):
    account_run(tmp_path, prices=None)
    price = overall_of(tmp_path)["list_price_equivalent"]
    assert price["median_usd"] is None and price["model"] is None and price["note"] == PRICE_NOTE
    assert {r["band"] for r in rows_of(tmp_path, ACCT_ID).values()} == {"reliable"}


def test_the_list_price_is_the_median_of_calls_priced_from_their_usage():
    lines = [{"usage": {"input": 1000, "output": 100, "cache_read": 0, "cache_write": 0}},       # 0.002 + 0.001 = 0.003
             {"usage": {"input": 500, "output": 50, "cache_read": 1000, "cache_write": 0}},      # 0.001 + 0.0005 + 0.0002 = 0.0017
             {"usage": {"input": 2000, "output": 200, "cache_read": 0, "cache_write": 400}},     # 0.004 + 0.002 + 0.001 = 0.007
             {"usage": None}]                                                                     # left out
    got = ist.list_price_equivalent(ACCT, lines, PRICES)
    assert got["calls"] == 3 and got["median_usd"] == pytest.approx(0.003)
    trimmed = {"models": {"anthropic/claude-sonnet-5-5": {k: v for k, v in PRICES["models"]["anthropic/claude-sonnet-5-5"].items()
                                                         if k != "cache_write_usd_per_mtok"}}}
    # a kind of token the entry leaves out is unknown: the call that uses it is left out, the others are priced
    assert ist.list_price_equivalent(ACCT, lines, trimmed)["calls"] == 2
    assert ist.list_price_equivalent(ACCT, lines, trimmed)["median_usd"] == pytest.approx((0.003 + 0.0017) / 2)
    assert ist.list_price_equivalent({**ACCT, "pin": "other", "model": "claude-sonnet-5-5"}, lines, PRICES)["model"] == "anthropic/claude-sonnet-5-5"  # by alias
    assert ist.list_price_equivalent({**ACCT, "model": "unknown-model"}, lines, PRICES)["median_usd"] is None


def test_the_deviations_are_the_row_s_own_settings():
    assert ist.account_deviations(ACCT) == "reasoning low, temperature as the CLI sends it"
    assert ist.account_deviations({**ACCT, "params": {"max_tokens": 300, "reasoning": "off", "temperature": None}}) == \
        "reasoning off, temperature as the CLI sends it"
    assert ist.account_deviations({**ACCT, "params": {"max_tokens": 300, "reasoning": "off", "temperature": 0}}) == "reasoning off, temperature 0"


def test_the_table_and_the_json_say_what_each_figure_is(tmp_path, capsys):
    go_fixture(tmp_path, cheap_plan={("de", n): "missed" for n in range(1, 31)})
    lines = ist.table(ist.status(str(tmp_path)))
    text = "\n".join(lines)
    assert "  fx-acct-ref: account route, judged on accuracy only; reasoning low, temperature as the CLI sends it" in lines
    assert "  fx-acct-ref: p95 latency 9000 ms of 1200 sequential calls (not a condition on an account route)" in lines
    assert ("  fx-acct-ref: list-price equivalent, median per call, 0.00220 USD of 1200 calls (proxy, not paid, not a go input; "
            "anthropic/claude-sonnet-5-5, https://prices.example/models, accessed 2030-10-01)") in lines
    assert lines[-1] == "  go: yes via fx-cheap for pt-BR, en, es, fr, it (off: de)"
    assert "example/cheap-1 | fx-cheap | de | below the gate | de correct_direct is 0.7, under 0.75" in text
    assert es.main(["interpreter", "--json"], root=str(tmp_path)) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["go"]["off_languages"] == ["de"] and out["accounts"][0]["route"] == ACCT_ID
    assert out["accounts"][0]["p95_latency_note"] == LATENCY_NOTE and out["accounts"][0]["list_price_equivalent"]["note"] == PRICE_NOTE


def test_an_http_route_publishes_no_account_figure(tmp_path):
    hs = checkout(tmp_path, routes={"v": 1, "routes": [CHEAP]})
    fx.write_file(tmp_path, fx.event(T1, hs), fx.lines_of(T1, fx.corpus(100), cost=0.001))
    status = ist.status(str(tmp_path))
    assert status["accounts"] == []
    overall = overall_of(tmp_path, "fx-cheap")
    assert "list_price_equivalent" not in overall and "p95_latency_note" not in overall and overall["median_cost_usd"] == 0.001
    assert not any("account route" in line for line in ist.table(status))


# --- the billing words other than `metered` (ACCT-C): a Claude model is valid under `subscription` alone ---------------------------------

@pytest.mark.parametrize("model", METERED_CLAUDE)
def test_a_claude_model_with_billing_none_is_refused_and_with_subscription_is_valid(model):
    found = event_problems(model, "none")
    assert len(found) == 1 and "account" in found[0] and "subscription" in found[0], found
    assert event_problems(model, "subscription") == []      # vacuity: the one billing word that is accepted


def test_a_model_that_is_not_claude_is_valid_under_none_and_the_word_list_is_what_refuses(monkeypatch):
    assert event_problems("example/cheap-1", "none") == []
    monkeypatch.setattr(el, "IX_METERED_FORBIDDEN", ())          # the planted fault: the guard's word list emptied
    assert event_problems("claude-sonnet-5-5", "none") == []


def test_the_go_of_an_input_that_is_missing_carries_the_two_language_lists_as_empty(tmp_path):
    """The early return of status(): a checkout with no thresholds file still returns a go with `route_languages` and `off_languages`."""
    root = tmp_path / "checkout"
    (root / "runtime").mkdir(parents=True)
    (root / "runtime" / "interpreter_routes.json").write_text(json.dumps(ROUTES))
    out = ist.status(str(root))
    assert out["missing"] and out["go"]["go"] is False
    assert out["go"]["route_languages"] == [] and out["go"]["off_languages"] == [] and out["go"]["languages"] == []
