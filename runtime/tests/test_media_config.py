"""Tests of the key `media` of runtime.json (runtime/project_config.py, package V1b2-1): the language and the transcriber's model of a new video, each
optional, checked against the transcriber's own rules. The engine is a fake; nothing is called and every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_media_config.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from media_kit import POST, add, ops, ops_core, ops_step_seams, run_task, world  # noqa: F401
import standin_tree as st

project_config = st.load("project_config")
REPO = Path(__file__).resolve().parents[2]
SHA = "a" * 64
MODELS = {"models": [{"name": "small", "sha256": SHA}, {"name": "medium", "sha256": "b" * 64}, {"name": "tiny", "sha256": None}]}


def set_media(world, value, models=MODELS):
    root = Path(json.loads((Path(world["path"]) / "docs/workbench/runtime.json").read_text())["workbench"])
    (root / "providers" / "transcriber").mkdir(parents=True, exist_ok=True)
    (root / "providers" / "transcriber" / "models.json").write_text(json.dumps(models), encoding="utf-8")
    (root / "providers" / "renderer").mkdir(parents=True, exist_ok=True)
    for name in ("ffmpeg.py", "hyperframes.py"):
        (root / "providers" / "renderer" / name).write_text("", encoding="utf-8")
    path = Path(world["path"]) / "docs/workbench/runtime.json"
    raw = json.loads(path.read_text())
    raw["media"] = value
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def accept(world):
    ops.accept_config(world["path"], project_config.load(world["path"])["sha256"])


def transcribe_args(world):
    task = add(world)
    run_task(world, task)
    return world["engine"].of("transcribe")[-1]["args"]


def flag(args, name):
    return args[args.index(name) + 1]


def test_a_project_that_names_the_language_and_the_model_transcribes_with_them(world):
    set_media(world, {"language": "en", "transcriber_model": "medium"})
    assert project_config.load(world["path"])["media"] == {"language": "en", "transcriber_model": "medium"}
    accept(world)
    store = ops_step_seams.MediaStore(ops_core.context(world["path"]))
    assert store.setting("language") == "en" and store.setting("transcriber_model") == "medium"
    args = transcribe_args(world)
    assert flag(args, "--language") == "en" and flag(args, "--model") == "medium"


def test_a_project_with_no_media_key_gets_the_step_kinds_defaults(world):
    assert project_config.load(world["path"])["media"] is None
    args = transcribe_args(world)
    assert flag(args, "--language") == "pt" and flag(args, "--model") == "small"


@pytest.mark.parametrize("value, sentence", [
    ([], "must be an object with the keys language, transcriber_model and renderer"),
    ({"engine": "x"}, "must be an object with the keys language, transcriber_model and renderer"),
    ({"renderer": "heygen"}, "media.renderer must be auto or one of ffmpeg, hyperframes"),
    ({"renderer": 5}, "media.renderer must be auto or one of ffmpeg, hyperframes"),
    ({"renderer": ""}, "media.renderer must be auto or one of ffmpeg, hyperframes"),
    ({"renderer": None}, "media.renderer must be auto or one of ffmpeg, hyperframes"),
    ({"language": "pt-BR"}, "media.language must be a language code"),
    ({"language": "PT"}, "media.language must be a language code"),
    ({"language": ""}, "media.language must be a language code"),
    ({"language": 5}, "media.language must be a language code"),
    ({"transcriber_model": "huge"}, "media.transcriber_model must be one of small, medium"),
    ({"transcriber_model": ["small"]}, "media.transcriber_model must be one of small, medium"),
])
def test_a_media_key_that_is_not_valid_is_refused_with_its_sentence(world, value, sentence):
    set_media(world, value)
    with pytest.raises(project_config.ConfigError) as caught:
        project_config.load(world["path"])
    assert sentence in str(caught.value)


def test_an_empty_object_loads_and_gives_an_empty_object_and_auto_is_a_language(world):
    set_media(world, {})
    assert project_config.load(world["path"])["media"] == {}
    set_media(world, {"language": "auto"})
    assert project_config.load(world["path"])["media"] == {"language": "auto"}


def test_the_language_pattern_is_the_transcribers(world):
    text = (REPO / "providers" / "transcriber" / "whispercpp.py").read_text(encoding="utf-8")
    found = re.search(r'^LANGUAGE = re\.compile\(r"([^"]+)"\)', text, re.M)
    assert found and project_config.MEDIA_LANGUAGE.pattern == found.group(1)


def test_a_model_that_is_not_pinned_is_refused_and_an_empty_list_says_so(world):
    set_media(world, {"transcriber_model": "tiny"})
    with pytest.raises(project_config.ConfigError) as caught:
        project_config.load(world["path"])
    assert "must be one of small, medium" in str(caught.value) and "tiny" not in str(caught.value)
    set_media(world, {"transcriber_model": "small"}, models={"models": []})
    with pytest.raises(project_config.ConfigError) as caught:
        project_config.load(world["path"])
    assert "none is listed" in str(caught.value)


@pytest.mark.parametrize("name", ["auto", "ffmpeg", "hyperframes"])
def test_the_renderer_key_loads_auto_and_each_shipped_implementation(world, name):
    set_media(world, {"renderer": name})
    assert project_config.load(world["path"])["media"] == {"renderer": name}


def test_the_store_names_the_renderer_unless_it_is_absent_or_auto(world):
    for value, expected in (({}, None), ({"renderer": "auto"}, None), ({"renderer": "ffmpeg"}, "ffmpeg"), ({"renderer": "hyperframes"}, "hyperframes")):
        set_media(world, value)
        accept(world)
        assert ops_step_seams.MediaStore(ops_core.context(world["path"])).renderer() == expected
