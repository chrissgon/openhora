"""Guard of scripts/tests/pinned_hashes.json, the one place of every hash the test suite pins.

The file holds `pins` (key -> sha256) and `notes` (key -> what is hashed and why it is pinned). The tests below keep it that way: every pin has a note and a reader, no test file
holds a pinned value as a literal, and every reader loads this file. Offline; standard library and pytest only.

Run: uv run --with pytest pytest scripts/tests/test_pinned_hashes.py
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PINNED_FILE = REPO / "scripts" / "tests" / "pinned_hashes.json"
THIS_FILE = Path(__file__).resolve()
LOOKUP = "PINNED_" + "HASHES["      # built here so that this file never names a lookup itself


def load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def doc():
    return json.loads(PINNED_FILE.read_text(encoding="utf-8"))


def all_test_files():
    found = []
    for folder in load("test_dirs").test_dirs(str(REPO)):
        found.extend(sorted((REPO / folder).glob("test_*.py")))
    assert found, "the test folders were not found"
    return found


def test_every_pin_is_a_sha256_with_a_note():
    data = doc()
    assert set(data) == {"pins", "notes"}
    assert set(data["pins"]) == set(data["notes"]) and data["pins"]
    for key, value in data["pins"].items():
        assert re.fullmatch(r"[0-9a-f]{64}", value), key
        note = data["notes"][key]
        assert isinstance(note, str) and note.strip(), key
        assert "guards a security table or policy" in note or "a review tripwire" in note, key


def test_every_pin_is_read_by_a_test():
    texts = [p.read_text(encoding="utf-8") for p in all_test_files() if p.resolve() != THIS_FILE]
    for key in doc()["pins"]:
        needle = f'{LOOKUP}"{key}"]'
        assert any(needle in text for text in texts), f"no test reads {key}"


def test_no_test_file_holds_a_pinned_value_as_a_literal():
    values = list(doc()["pins"].values())
    for path in all_test_files():
        text = path.read_text(encoding="utf-8")
        for value in values:
            assert value not in text, f"{path.relative_to(REPO)} holds a pinned value; read it from scripts/tests/pinned_hashes.json"


def test_every_reader_loads_this_file():
    for path in all_test_files():
        if path.resolve() == THIS_FILE:
            continue
        text = path.read_text(encoding="utf-8")
        if LOOKUP in text:
            assert '"pinned_hashes.json"' in text, f"{path.relative_to(REPO)} reads a pin without loading pinned_hashes.json"


def canonical(data):
    """The one form of the file (HOT-1): keys sorted at every level, two spaces, non-ASCII kept, one newline at the end. A new pin lands at its own sorted place."""
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def test_the_file_is_in_its_canonical_form():
    assert PINNED_FILE.read_text(encoding="utf-8") == canonical(doc())


def test_vacuity_an_unsorted_copy_or_one_without_the_final_newline_is_not_canonical():
    data = doc()
    unsorted_pins = {"pins": dict(reversed(list(data["pins"].items()))), "notes": data["notes"]}
    assert json.loads(canonical(unsorted_pins)) == json.loads(json.dumps(unsorted_pins)), "the same content"
    assert json.dumps(unsorted_pins, indent=2, ensure_ascii=False) + "\n" != canonical(data), "an unsorted copy fails the text test"
    assert canonical(data).rstrip("\n") != canonical(data)
    assert canonical({"b": 1, "a": 2}) == '{\n  "a": 2,\n  "b": 1\n}\n'
