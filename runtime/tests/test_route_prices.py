"""runtime/prices.json against runtime/interpreter_routes.json (package PRICES-CACHE): every route of the interpreter has a price for each
kind of token a call of it can report, so that the cost of a cached call can be recomputed and is not null. The oracle reads the two raw
JSON files with its own literals, not the price module's lookup. Offline; the usage numbers are invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_route_prices.py
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "runtime"))
import prices  # noqa: E402

KINDS = ("input", "output", "cache_read", "cache_write")


def read(name):
    return json.loads((REPO / "runtime" / name).read_text(encoding="utf-8"))


def missing(routes_doc, table_doc):
    """[(route id, kind)] of every kind a route needs and its row of the table does not price with a number of 0 or more.
    A route that asks for a cache breakpoint writes a cache, so it needs cache_write; every route needs the other three kinds."""
    models = table_doc["models"]
    out = []
    for route in routes_doc["routes"]:
        row = models.get(route["model"])
        if row is None:
            out.append((route["id"], "row"))
            continue
        for kind in KINDS:
            if kind == "cache_write" and not route.get("cache_breakpoint"):
                continue
            value = row.get(kind + "_usd_per_mtok")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                out.append((route["id"], kind))
    return out


def test_every_route_of_the_interpreter_has_its_prices():
    routes = read("interpreter_routes.json")
    assert len(routes["routes"]) >= 3
    assert missing(routes, read("prices.json")) == []


def test_the_anthropic_routes_ask_for_a_cache_and_price_both_cache_kinds():
    routes = read("interpreter_routes.json")["routes"]
    models = read("prices.json")["models"]
    anthropic = [r for r in routes if r["model"].startswith("openrouter/anthropic/")]
    assert {r["id"] for r in anthropic} == {"or-claude-haiku-4.5", "or-claude-sonnet-5.5"}
    for route in anthropic:
        assert route["cache_breakpoint"] is True
        row = models[route["model"]]
        assert row["cache_read_usd_per_mtok"] > 0 and row["cache_write_usd_per_mtok"] > 0, route["id"]


def test_a_call_with_cached_tokens_is_priced_on_every_route():
    table = prices.load(str(REPO / "runtime" / "prices.json"))
    usage = {"input": 1000, "output": 200, "cache_read": 5000}
    for route in read("interpreter_routes.json")["routes"]:
        row = prices.price_of(table, [route["model"]])
        assert row is not None, route["id"]
        cost = prices.expected_cost(usage, row)
        assert cost is not None and cost > 0, route["id"]
    # a call that writes a cache is priced on the routes that ask for a cache breakpoint
    written = dict(usage, cache_write=3000)
    for route in read("interpreter_routes.json")["routes"]:
        if route["cache_breakpoint"]:
            assert prices.expected_cost(written, prices.price_of(table, [route["model"]])) is not None, route["id"]


def test_vacuity_a_route_without_a_cache_price_is_found():
    routes = read("interpreter_routes.json")
    table = read("prices.json")
    for kind in KINDS:
        broken = json.loads(json.dumps(table))
        del broken["models"]["openrouter/anthropic/claude-haiku-4.5"][kind + "_usd_per_mtok"]
        assert missing(routes, broken) == [("or-claude-haiku-4.5", kind)], kind
    gone = json.loads(json.dumps(table))
    del gone["models"]["openrouter/deepseek/deepseek-v4.1-flash"]
    assert missing(routes, gone) == [("or-deepseek-v4.1-flash", "row")]
    text = json.loads(json.dumps(table))
    text["models"]["openrouter/anthropic/claude-sonnet-5.5"]["cache_read_usd_per_mtok"] = "0.1"
    assert missing(routes, text) == [("or-claude-sonnet-5.5", "cache_read")]
