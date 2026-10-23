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


def http_only(routes_doc):
    """The rows of kind http: a call of an account route is paid by the subscription, not per call, so it has no price (ACCT-C)."""
    return {"routes": [r for r in routes_doc["routes"] if r["kind"] == "http"]}


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
    routes = http_only(read("interpreter_routes.json"))
    assert len(routes["routes"]) >= 1
    assert missing(routes, read("prices.json")) == []


def test_the_shipped_route_asks_no_cache_breakpoint_and_prices_the_cache_it_reads():
    """ACCT-B: the two routes that asked for a cache breakpoint (a Claude model through a metered key) are gone; the one left reads a cache (its
    provider caches by itself) and writes none."""
    routes = http_only(read("interpreter_routes.json"))["routes"]
    models = read("prices.json")["models"]
    assert [r["id"] for r in routes] == ["or-deepseek-v4.1-flash"]
    assert routes[0]["cache_breakpoint"] is False
    assert models[routes[0]["model"]]["cache_read_usd_per_mtok"] > 0


def test_a_call_with_cached_tokens_is_priced_on_every_route():
    table = prices.load(str(REPO / "runtime" / "prices.json"))
    usage = {"input": 1000, "output": 200, "cache_read": 5000}
    for route in http_only(read("interpreter_routes.json"))["routes"]:
        row = prices.price_of(table, [route["model"]])
        assert row is not None, route["id"]
        cost = prices.expected_cost(usage, row)
        assert cost is not None and cost > 0, route["id"]
    # a call that writes a cache is priced on the routes that ask for a cache breakpoint
    written = dict(usage, cache_write=3000)
    for route in http_only(read("interpreter_routes.json"))["routes"]:
        if route["cache_breakpoint"]:
            assert prices.expected_cost(written, prices.price_of(table, [route["model"]])) is not None, route["id"]


def test_vacuity_a_route_without_a_price_is_found():
    routes = http_only(read("interpreter_routes.json"))
    table = read("prices.json")
    row = "openrouter/deepseek/deepseek-v4.1-flash"
    for kind in ("input", "output", "cache_read"):
        broken = json.loads(json.dumps(table))
        del broken["models"][row][kind + "_usd_per_mtok"]
        assert missing(routes, broken) == [("or-deepseek-v4.1-flash", kind)], kind
    gone = json.loads(json.dumps(table))
    del gone["models"][row]
    assert missing(routes, gone) == [("or-deepseek-v4.1-flash", "row")]
    text = json.loads(json.dumps(table))
    text["models"][row]["cache_read_usd_per_mtok"] = "0.1"
    assert missing(routes, text) == [("or-deepseek-v4.1-flash", "cache_read")]
    # a route that asks for a cache breakpoint writes a cache, so it needs a cache_write price, which this row does not have
    asking = {"routes": [dict(routes["routes"][0], cache_breakpoint=True)]}
    assert missing(asking, table) == [("or-deepseek-v4.1-flash", "cache_write")]


def test_an_account_route_is_not_priced_per_call_and_the_oracle_would_see_it_if_it_were_read():
    """The account rows are left out on purpose; read as http rows they have no row of the table (they carry no cache_breakpoint either)."""
    everything = read("interpreter_routes.json")
    accounts = [r["id"] for r in everything["routes"] if r["kind"] == "account"]
    assert accounts == ["acct-claude-sonnet-5.5", "acct-claude-haiku-4.5"]
    assert {r["id"] for r in http_only(everything)["routes"]}.isdisjoint(accounts)
    assert [id_ for id_, kind in missing(everything_as_http(everything), read("prices.json")) if kind == "row"] == accounts


def everything_as_http(doc):
    return {"routes": [dict(r, cache_breakpoint=False) for r in doc["routes"]]}
