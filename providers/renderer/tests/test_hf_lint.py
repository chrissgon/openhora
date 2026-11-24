"""The reduced escape lint of an admitted page: every rule has a planted snippet it refuses and a near miss it passes, every category refuses with
`block_lint` and names the rule and the file:line, and a clean fictional component passes. Offline."""
from __future__ import annotations

import pytest

import hf_second_kit as H
import _hf_host
import _hf_lint
from _text import Refusal

CATEGORIES = {"frames", "links", "remote", "storage", "top-layer", "markup-from-data", "network", "media", "workers", "fonts", "gpu"}


def test_every_rule_refuses_its_planted_snippet_and_passes_its_near_miss():
    _hf_lint.self_test()
    assert {cat for cat, _r, _p, _f in _hf_lint.RULES} == CATEGORIES
    for rule, bad, good in _hf_lint.PLANTED:
        assert rule in {r for _c, r, _l in _hf_lint.scan("x", bad)}, rule
        assert _hf_lint.scan("x", good) == [], rule


def test_the_table_covers_the_rules_one_for_one_and_a_loosened_rule_stops_the_check(monkeypatch):
    assert sorted(r for r, _b, _g in _hf_lint.PLANTED) == sorted(r for _c, r, _p, _f in _hf_lint.RULES)
    monkeypatch.setattr(_hf_lint, "_COMPILED", [(c, r, __import__("re").compile("never-matches-anything")) for c, r, _x in _hf_lint._COMPILED])
    with pytest.raises(RuntimeError):
        _hf_lint.self_test()
    with pytest.raises(Refusal) as e:
        _hf_lint.check({"a.html": "<p>x</p>"})
    assert e.value.code == "block_lint" and e.value.field == "self_test"


@pytest.mark.parametrize("rule,snippet", [(r, b) for r, b, _g in _hf_lint.PLANTED])
def test_a_file_with_a_rules_snippet_is_refused_with_the_rule_the_file_and_the_line(rule, snippet):
    with pytest.raises(Refusal) as e:
        _hf_lint.check({"page.html": "<div>\n<p>fine</p>\n" + snippet + "\n</div>\n"})
    assert e.value.code == "block_lint"
    name, file, line = e.value.field.split(":")
    assert file == "page.html" and int(line) in (3, 4, 5) and name in {r for _c, r, _p, _f in _hf_lint.RULES}


def test_a_clean_component_passes_and_a_computed_key_does_too_which_is_why_the_policy_is_the_wall():
    def served(variant):
        return _hf_host.apply_edits({H.FILE: H.component(variant).encode()}, ["E1", "E2:Inter"], {"Inter": "oh-text"})
    _hf_lint.check(served("clean"))
    _hf_lint.check(served("computed_fetch"))            # evadable by design: the page policy and the interception hold it
    with pytest.raises(Refusal):
        _hf_lint.check(served("fontface"))
    with pytest.raises(Refusal) as e:                    # before the edit the CDN line is a remote script
        _hf_lint.check({H.FILE: H.component("clean")})
    assert e.value.field.startswith("url:")
    with pytest.raises(Refusal) as e:
        _hf_lint.check({"x.js": b"\xff\xfe"})
    assert e.value.field.startswith("encoding:x.js")
