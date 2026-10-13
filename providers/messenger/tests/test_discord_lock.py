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


def header_of(text: str) -> str:
    return text.split('"""', 1)[0]


def header_pins(script_text: str) -> dict:
    deps = re.search(r"^# dependencies = \[(.*)\]$", header_of(script_text), re.M).group(1)
    return dict(re.findall(r'"([A-Za-z0-9_.-]+)==([^"]+)"', deps))


def lock_packages(lock_text: str) -> dict:
    blocks = lock_text.split("[[package]]\n")[1:]
    return {re.search(r'^name = "([^"]+)"', b, re.M).group(1): b for b in blocks}


def problems(script_text: str, lock_text) -> list:
    """What is wrong with the lock for this script: empty when it is good."""
    if lock_text is None:
        return ["discord.py.lock is missing: run uv lock --script providers/messenger/discord.py"]
    found = []
    pins = header_pins(script_text)
    packages = lock_packages(lock_text)
    for name, version in pins.items():
        if name not in packages or not re.search(rf'^version = "{re.escape(version)}"$', packages[name], re.M):
            found.append(f"the lock does not lock {name}=={version}")
        if f'{{ name = "{name}", specifier = "=={version}" }}' not in lock_text:
            found.append(f"the lock's manifest does not require {name}=={version}")
    python = re.search(r'^# requires-python = "(.*)"$', header_of(script_text), re.M).group(1)
    if f'requires-python = "{python}"' not in lock_text:
        found.append("the lock names another requires-python")
    for name, block in packages.items():
        if 'source = { registry = "https://pypi.org/simple" }' not in block:
            found.append(f"{name} does not come from the default registry")
        if not re.search(r'hash = "sha256:[0-9a-f]{64}"', block):
            found.append(f"{name} has no hash")
    if "websockets" in packages and len(re.findall(r'hash = "sha256:[0-9a-f]{64}"', packages["websockets"])) < 10:
        found.append("websockets has too few hashes")
    return found


def current():
    return SCRIPT.read_text(encoding="utf-8"), (LOCK.read_text(encoding="utf-8") if LOCK.is_file() else None)


def test_the_lock_exists_names_the_header_versions_and_hashes_every_package():
    script, lock = current()
    assert set(header_pins(script)) == {"keyring", "websockets"}
    assert problems(script, lock) == []


def test_a_missing_lock_is_flagged():
    script, _ = current()
    assert problems(script, None)


def test_a_lock_for_another_version_than_the_header_is_flagged():
    script, lock = current()
    version = header_pins(script)["websockets"]
    assert problems(script.replace(f"websockets=={version}", "websockets==99.0"), lock)
    assert problems(script, lock.replace(f'name = "websockets"\nversion = "{version}"', 'name = "websockets"\nversion = "99.0"'))


def test_a_lock_with_a_removed_hash_or_another_registry_is_flagged():
    script, lock = current()
    assert problems(script, re.sub(r'hash = "sha256:[0-9a-f]{64}"', 'size = 1', lock, count=1000))
    assert problems(script, lock.replace("https://pypi.org/simple", "https://mirror.example/simple"))
    assert problems(script, lock.replace('requires-python = ">=3.10"', 'requires-python = ">=3.11"'))
