"""The Notion task board tells an unsafe credentials directory from a missing token (T34). Offline: no network, no real
credential; every folder is a temporary one.

Run: uv run --with pytest==9.1.1 pytest providers/issue-tracker/tests/test_notion_unsafe_dir.py
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "notion.py"
PLANTED_VALUE = "zz-not-a-real-value-41"


def load_module():
    spec = importlib.util.spec_from_file_location("notion_board_provider_unsafe", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("NOTION_TOKEN", "CREDENTIALS_DIRECTORY"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_notion_an_unsafe_credentials_directory_says_unsafe_and_names_the_chmod(tmp_path, clean_env):
    folder = tmp_path / "credentials"
    folder.mkdir()
    folder.chmod(0o755)
    (folder / "NOTION_TOKEN").write_text(PLANTED_VALUE, encoding="utf-8")
    (folder / "NOTION_TOKEN").chmod(0o644)
    clean_env.setenv("OPENHORA_CREDENTIALS_DIR", str(folder))
    module = load_module()
    with pytest.raises(module.ProviderError) as caught:
        module.load_token(True)
    assert caught.value.code == 3
    said = str(caught.value)
    assert "unsafe" in said and "chmod" in said and "nothing was sent" in said
    assert "no Notion token" not in said and PLANTED_VALUE not in said


def test_notion_a_missing_token_keeps_its_message(tmp_path, clean_env):
    folder = tmp_path / "credentials"
    folder.mkdir()
    folder.chmod(0o700)
    clean_env.setenv("OPENHORA_CREDENTIALS_DIR", str(folder))
    module = load_module()
    with pytest.raises(module.ProviderError) as caught:
        module.load_token(True)
    assert caught.value.code == 3 and "no Notion token" in str(caught.value)


def test_notion_a_safe_credentials_directory_still_gives_the_token(tmp_path, clean_env):
    folder = tmp_path / "credentials"
    folder.mkdir()
    folder.chmod(0o700)
    (folder / "NOTION_TOKEN").write_text(PLANTED_VALUE + "\n", encoding="utf-8")
    (folder / "NOTION_TOKEN").chmod(0o600)
    clean_env.setenv("OPENHORA_CREDENTIALS_DIR", str(folder))
    assert load_module().load_token(True) == PLANTED_VALUE


def test_notion_data_home_is_named_openhora():
    assert load_module().data_home().name == "openhora"
