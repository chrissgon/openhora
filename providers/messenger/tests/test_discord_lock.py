"""The dependencies of providers/messenger/discord.py are hash-locked, not only version-pinned: `discord.py.lock`
(written by `uv lock --script providers/messenger/discord.py`) sits next to the script, `uv run` honours it, and
providers/resolve.py starts the script with `uv run --locked`, which refuses a lock that disagrees with the header.

These tests read both files as text and run offline. After a change to the header's dependencies, run
`uv lock --script providers/messenger/discord.py` and commit the new lock.
"""
from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
SCRIPT = HERE / "discord.py"
LOCK = HERE / "discord.py.lock"


def header_pins() -> dict:
    header = SCRIPT.read_text(encoding="utf-8").split('"""', 1)[0]
    deps = re.search(r"^# dependencies = \[(.*)\]$", header, re.M).group(1)
    return dict(re.findall(r'"([A-Za-z0-9_.-]+)==([^"]+)"', deps))


def lock_packages() -> dict:
    text = LOCK.read_text(encoding="utf-8")
    blocks = text.split("[[package]]\n")[1:]
    return {re.search(r'^name = "([^"]+)"', b, re.M).group(1): b for b in blocks}


def test_the_lock_exists_next_to_the_script():
    assert LOCK.is_file(), "run: uv lock --script providers/messenger/discord.py"


def test_the_lock_names_the_same_versions_as_the_header_and_the_same_python():
    pins = header_pins()
    assert set(pins) == {"keyring", "websockets"}
    packages = lock_packages()
    for name, version in pins.items():
        assert re.search(rf'^version = "{re.escape(version)}"$', packages[name], re.M), \
            f"discord.py.lock does not lock {name}=={version}: run uv lock --script providers/messenger/discord.py"
    text = LOCK.read_text(encoding="utf-8")
    header = SCRIPT.read_text(encoding="utf-8").split('"""', 1)[0]
    assert re.search(r'^# requires-python = "(.*)"$', header, re.M).group(1) in text
    for name, version in pins.items():
        assert f'{{ name = "{name}", specifier = "=={version}" }}' in text


def test_every_locked_package_has_hashes_and_comes_from_the_default_registry():
    for name, block in lock_packages().items():
        assert 'source = { registry = "https://pypi.org/simple" }' in block, name
        hashes = re.findall(r'hash = "sha256:[0-9a-f]{64}"', block)
        assert hashes, f"{name} has no hash in the lock"
    assert len(re.findall(r'hash = "sha256:[0-9a-f]{64}"', lock_packages()["websockets"])) >= 10
