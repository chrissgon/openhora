"""Tests of the project key language (LANGUAGE, skills part): the language artifacts are written in. A tag of two lower-case
letters and, optionally, a hyphen and two upper-case letters; absent means English. Today the loader only checks it; a wrong
case is refused with the right form. Offline: the stand-in tree (runtime/tests/standin_tree.py).

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_project_config_language.py
"""
from __future__ import annotations

import json

import pytest

import standin_tree as st

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
project_config = st.load("project_config")


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    return built


def configure(tree, **extra) -> str:
    path = str(tree["project"])
    file = project_config.path(path)
    with open(file, encoding="utf-8") as f:
        good = json.load(f)
    good.pop("language", None)
    with open(file, "w", encoding="utf-8") as f:
        json.dump({**good, **extra}, f)
    return path


def test_language_is_a_known_key_and_absent_means_none(tree):
    assert "language" in project_config.TASK_RUNTIME_KEYS
    assert project_config.load(configure(tree))["language"] is None


def test_language_accepts_simple_tags(tree):
    for tag in ("en", "pt", "pt-BR", "en-US", "es", "fr", "de"):
        assert project_config.load(configure(tree, language=tag))["language"] == tag


def test_language_refuses_what_is_not_a_simple_tag(tree):
    for bad in ("", " ", "portuguese", "pt_BR", "pt-br-x", "es-419", "zh-Hant-TW", "eng", "p", "pt-B", 5, True, ["en"], {"a": 1}):
        path = configure(tree, language=bad)
        with pytest.raises(project_config.ConfigError) as raised:
            project_config.load(path)
        assert "runtime.json language must be a language tag" in str(raised.value), bad


def test_a_tag_in_the_wrong_case_is_refused_with_the_right_form(tree):
    for bad, right in (("PT-br", "pt-BR"), ("pt-br", "pt-BR"), ("EN", "en"), ("En-us", "en-US"), ("pt_BR", "pt-BR")):
        path = configure(tree, language=bad)
        with pytest.raises(project_config.ConfigError) as raised:
            project_config.load(path)
        assert f"did you mean {right}?" in str(raised.value), bad


def test_a_file_with_the_key_is_accepted_through_accept_config_like_every_key(tree):
    path = configure(tree, language="pt-BR")
    digest = project_config.load(path)["sha256"]
    out = ops.accept_config(path, digest)
    assert out["accepted"] == digest
    assert ops.status(path)["config"]["sha256"] == digest
    # changing the key changes the hash: the person accepts the new file again
    path = configure(tree, language="en")
    assert project_config.load(path)["sha256"] != digest
