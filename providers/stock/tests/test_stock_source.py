"""The source data file, the licence tuple, the query rule and the admission of a licence (providers/stock/_stock.py)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import stock_kit as kit
from stock_kit import source, write_source

import _stock

COMMITTED = Path(__file__).resolve().parents[1] / "sources" / "pexels.json"


def load(tmp_path, data, today=kit.TODAY, impl="pexels"):
    return _stock.read_source(write_source(tmp_path, data), today, impl)


def refused(tmp_path, data, today=kit.TODAY):
    with pytest.raises(_stock.Refusal) as stop:
        load(tmp_path, data, today)
    return stop.value


def test_the_licence_tuples_are_the_decided_ones():
    assert _stock.LICENCES_ACCEPTED == ("pexels-license", "pixabay-content-license", "cc0-1.0", "pdm-1.0", "cc-by-4.0", "cc-by-3.0", "cc-by-2.5", "cc-by-2.0")
    assert _stock.LICENCES_CREDIT == ("cc-by-4.0", "cc-by-3.0", "cc-by-2.5", "cc-by-2.0")
    assert set(_stock.LICENCES_CREDIT) <= set(_stock.LICENCES_ACCEPTED)
    for refused_id in ("cc-by-sa-4.0", "cc-by-nc-4.0", "cc-by-nd-4.0", "editorial", "cc-by", "unverified"):
        assert refused_id not in _stock.LICENCES_ACCEPTED
    assert _stock.TIERS == ("library", "per-item", "unverified")


def test_the_committed_source_file_holds_no_value_a_maintainer_fills():
    data = json.loads(COMMITTED.read_text(encoding="utf-8"))
    assert list(data) == list(_stock.SOURCE_KEYS)
    assert (data["source"], data["licence_tier"], data["licence"], data["kinds"], data["cache_seconds"]) == ("pexels", "library", "pexels-license", ["image", "clip"], 0)
    for key in ("licences", "licence_url", "terms_read_on", "secret", "secret_in", "credit_line"):
        assert data[key] is None, key
    assert data["media_hosts"] == [] and data["redirect_hosts"] == []
    for block in ("api", "path_patterns", "rendition"):
        assert all(v is None for v in data[block].values()), block


def test_the_committed_source_file_is_refused_with_every_field_it_lacks():
    with pytest.raises(_stock.Refusal) as stop:
        _stock.read_source(str(COMMITTED), kit.TODAY, "pexels")
    assert stop.value.code == "source_not_ready" and stop.value.exit_code == 3
    for field in ("licence_url", "terms_read_on", "secret_in", "api.host", "media_hosts", "path_patterns.preview", "rendition.clip"):
        assert field in stop.value.fields


def test_a_filled_source_file_loads_and_compiles_its_patterns(tmp_path):
    data = load(tmp_path, source())
    assert data["source"] == "pexels" and set(data["_patterns"]) == {"preview", "image", "clip"}


NULLABLE = [("licence", ["licence"]), ("licence_url", ["licence_url"]), ("terms_read_on", ["terms_read_on"]), ("secret", ["secret"]),
            ("secret_in", ["secret_in"]), ("media_hosts", ["media_hosts"]), ("kinds", ["kinds"])]


@pytest.mark.parametrize("field,named", NULLABLE)
def test_every_field_a_library_source_needs_is_refused_when_null_or_empty(tmp_path, field, named):
    data = source()
    data[field] = [] if field in ("media_hosts", "kinds") else None
    stop = refused(tmp_path, data)
    assert stop.code == "source_not_ready" and set(named) <= set(stop.fields)


@pytest.mark.parametrize("block,key", [("api", k) for k in _stock.API_KEYS] + [("path_patterns", k) for k in _stock.KIND_KEYS]
                         + [("rendition", k) for k in _stock.KIND_KEYS])
def test_every_nested_field_is_refused_when_null(tmp_path, block, key):
    data = source()
    data[block][key] = None
    stop = refused(tmp_path, data)
    assert stop.code == "source_not_ready" and "%s.%s" % (block, key) in stop.fields


def test_a_kind_the_source_does_not_serve_needs_none_of_its_fields(tmp_path):
    data = source(kinds=["image"])
    data["api"]["search_clip"] = data["api"]["item_clip"] = None
    data["path_patterns"]["clip"] = data["rendition"]["clip"] = None
    assert load(tmp_path, data)["kinds"] == ["image"]


def test_the_tiers_each_need_what_they_need_and_nothing_else(tmp_path):
    # library: one licence, no table
    assert refused(tmp_path, source(licences={"x": "cc0-1.0"})).fields == ["licences"]
    # per-item: a table and a credit line, no single licence
    per = dict(licence_tier="per-item", licence=None, licences={"by 4.0": "cc-by-4.0", "cc0": "cc0-1.0"}, credit_line="credit")
    assert load(tmp_path, source(**per))["licence_tier"] == "per-item"
    assert refused(tmp_path, source(**dict(per, licence="cc0-1.0"))).fields == ["licence"]
    assert "licences" in refused(tmp_path, source(**dict(per, licences=None))).fields
    assert "licences" in refused(tmp_path, source(**dict(per, licences={}))).fields
    assert "credit_line" in refused(tmp_path, source(**dict(per, credit_line=None))).fields
    # unverified: neither
    un = dict(licence_tier="unverified", licence=None, licences=None)
    assert load(tmp_path, source(**un))["licence_tier"] == "unverified"
    assert refused(tmp_path, source(**dict(un, licence="cc0-1.0"))).fields == ["licence"]
    assert refused(tmp_path, source(**dict(un, licences={"a": "cc0-1.0"}))).fields == ["licences"]
    assert refused(tmp_path, source(licence_tier="open")).fields[0] == "licence_tier"


def test_secret_in_none_takes_no_secret_and_a_header_or_query_takes_one(tmp_path):
    assert load(tmp_path, source(secret_in="none", secret=None))["secret_in"] == "none"
    assert refused(tmp_path, source(secret_in="none")).fields == ["secret"]
    assert refused(tmp_path, source(secret_in="header", secret=None)).fields == ["secret"]
    assert refused(tmp_path, source(secret_in="query", secret="not a name")).fields == ["secret"]
    assert load(tmp_path, source(secret_in="query"))["secret_in"] == "query"
    assert refused(tmp_path, source(secret_in="cookie")).fields == ["secret_in"]


def test_a_library_licence_outside_the_tuple_is_refused_at_load(tmp_path):
    for bad in ("cc-by-sa-4.0", "cc-by-nc-4.0", "cc-by-nd-4.0", "editorial-only", "cc-by", "unverified"):
        stop = refused(tmp_path, source(licence=bad))
        assert stop.code == "licence_refused", bad
    for good in _stock.LICENCES_ACCEPTED:
        assert load(tmp_path, source(licence=good))["licence"] == good


def test_a_licences_value_outside_the_tuple_is_refused_at_load(tmp_path):
    base = dict(licence_tier="per-item", licence=None, credit_line="credit")
    assert refused(tmp_path, source(**dict(base, licences={"by-sa 4.0": "cc-by-sa-4.0"}))).code == "licence_refused"
    assert refused(tmp_path, source(**dict(base, licences={"by 4.0": "cc-by-4.0", "nd": "cc-by-nd-4.0"}))).code == "licence_refused"
    assert load(tmp_path, source(**dict(base, licences={"by 3.0": "cc-by-3.0"})))["licences"] == {"by 3.0": "cc-by-3.0"}


def test_the_terms_are_stale_after_365_days_and_not_before(tmp_path):
    data = source(terms_read_on="2025-11-10")          # exactly 365 days before 2026-11-10
    assert load(tmp_path, data)["terms_read_on"] == "2025-11-10"
    stop = refused(tmp_path, source(terms_read_on="2025-11-09"))      # 366 days
    assert stop.code == "terms_stale" and stop.exit_code == 3
    assert refused(tmp_path, source(terms_read_on="2026-11-11")).fields == ["terms_read_on"]       # in the future
    assert refused(tmp_path, source(terms_read_on="10/11/2026")).fields == ["terms_read_on"]


@pytest.mark.parametrize("today", [None, "", "yesterday", "20261110", "2026-13-40"])
def test_a_missing_or_malformed_today_is_refused(tmp_path, today):
    assert refused(tmp_path, source(), today=today).fields == ["today"]


def test_unknown_missing_and_wrong_keys_and_another_implementation_are_refused(tmp_path):
    data = source()
    data["extra"] = 1
    assert refused(tmp_path, data).fields == ["extra"]
    data = source()
    del data["api"]
    assert refused(tmp_path, data).fields == ["api"]
    with pytest.raises(_stock.Refusal) as stop:
        load(tmp_path, source(source="other"), impl="pexels")
    assert stop.value.fields == ["source"]
    bad = Path(tmp_path) / "bad.json"
    bad.write_text("not json")
    with pytest.raises(_stock.Refusal) as stop:
        _stock.read_source(str(bad), kit.TODAY)
    assert stop.value.fields == ["file"]


def test_hosts_patterns_and_paths_are_checked_for_shape(tmp_path):
    assert refused(tmp_path, source(media_hosts=["IMG.stock.example"])).fields == ["media_hosts"]
    assert refused(tmp_path, source(media_hosts=["10.0.0.1"])).fields == ["media_hosts"]
    assert refused(tmp_path, source(redirect_hosts=["cdn.example."])).fields == ["redirect_hosts"]
    data = source()
    data["path_patterns"]["image"] = "(unclosed"
    assert refused(tmp_path, data).fields == ["path_patterns.image"]
    data = source()
    data["path_patterns"]["image"] = "a" * 201
    assert refused(tmp_path, data).fields == ["path_patterns.image"]
    data = source()
    data["api"]["item_image"] = "/v1/photos/none"          # a path template holds {item} once
    assert refused(tmp_path, data).fields == ["api.item_image"]
    data = source()
    data["api"]["host"] = "https://api.stock.example"
    assert refused(tmp_path, data).fields == ["api.host"]
    assert refused(tmp_path, source(cache_seconds=-1)).fields == ["cache_seconds"]
    assert refused(tmp_path, source(cache_seconds=True)).fields == ["cache_seconds"]


GOOD_QUERIES = ["mountain lake", "a", "forest", "city street at night", "it's cold", "slow-motion waves", "one two three four five six", "ab"]


@pytest.mark.parametrize("query", [q for q in GOOD_QUERIES if len(q) >= 2])
def test_the_query_rule_accepts_one_to_six_words_of_letters(query):
    assert _stock.check_query(query) == query


@pytest.mark.parametrize("query", ["a", "", " lake", "lake ", "one two three four five six seven", "lake 2", "me@home", "a.b", "a/b", "a:b", "café au lait",
                                   "x" * 61, None, 7, "-lake", "'lake", "lake\nview"])
def test_the_query_rule_refuses_everything_else(query):
    with pytest.raises(_stock.Refusal) as stop:
        _stock.check_query(query)
    assert stop.value.code == "query_refused" and stop.value.exit_code == 2


def test_the_search_pattern_is_the_decided_one():
    assert _stock.SEARCH.pattern == r"[A-Za-z][A-Za-z' -]{1,59}"


def test_admission_of_a_licence():
    ok = _stock.admit_licence
    assert ok("library", "pexels-license", "Aster Lane") and ok("library", "pexels-license", "")
    assert ok("per-item", "cc0-1.0", "") and ok("per-item", "pdm-1.0", "")
    assert ok("per-item", "cc-by-4.0", "Aster Lane") and ok("per-item", "cc-by-3.0", "Aster Lane")
    assert ok("per-item", "cc-by-2.5", "Aster Lane") and ok("per-item", "cc-by-2.0", "Aster Lane")
    assert not ok("per-item", "cc-by-4.0", "") and not ok("per-item", "cc-by-3.0", "")
    assert not ok("per-item", "cc-by-2.5", "") and not ok("per-item", "cc-by-2.0", "")        # a credit licence with no author to credit
    assert not ok("per-item", "cc-by-sa-4.0", "Aster Lane") and not ok("per-item", None, "Aster Lane")
    assert not ok("unverified", "unverified", "Aster Lane")                              # refused unless the project turned the tier on
    assert ok("unverified", "unverified", "Aster Lane", allow_unverified=True)
    assert not ok("library", "unverified", "Aster Lane", allow_unverified=True)          # only a source of that tier can carry it


def test_third_party_text_is_kept_as_data_only():
    assert _stock.clean_text("  Aster \x00 Lane\n\t", 120) == "Aster Lane"
    assert _stock.clean_text("x" * 500, 120) == "x" * 120 and _stock.clean_text(5, 120) == "" and _stock.clean_text(None, 9) == ""
    assert _stock.clean_page("https://page.stock.example/a?b=1") == "https://page.stock.example/a?b=1"
    for bad in ("http://page.stock.example/a", "https://user@page.stock.example/", "https://10.0.0.1/a", "javascript:alert(1)", "https://a b.example/x",
                "https://page.stock.example/" + "x" * 300, 5):
        assert _stock.clean_page(bad) == ""


def test_the_map_of_a_per_item_licence():
    table = {"by 4.0": "cc-by-4.0"}
    assert _stock.map_licence(table, "by 4.0") == "cc-by-4.0" and _stock.map_licence(table, "by-sa 4.0") is None and _stock.map_licence(table, None) is None
