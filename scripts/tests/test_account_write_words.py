"""The vocabulary the writes to the person's own accounts arrived with (package FND): the side-effect words `calendar`, `mailbox`, `files` and (CB-5) `tasks` (the validator's
list and the table of contracts/environment.md, which a test elsewhere holds equal), and the runtime-only provider role `writer` of providers/resolve.py
(`writer:calendar`, `writer:mailbox`, `writer:files`, the folder providers/writer/). The words arrive with the runtime, not with a skill: nothing here makes a
skill declare them. Offline.

Run: uv run --with pytest scripts/tests/test_account_write_words.py
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validate = load("validate_for_account_words", REPO / "scripts" / "validate.py")
resolve = load("resolve_for_account_words", REPO / "providers" / "resolve.py")

WORDS = ("calendar", "mailbox", "files", "tasks")
CLASSES = ("writer:calendar", "writer:mailbox", "writer:files", "writer:tasks")


def test_the_account_words_are_in_the_validators_list_after_write_and_in_the_contract_table_in_the_same_order():
    assert validate.SIDE_EFFECTS[-4:] == WORDS and "write" in validate.SIDE_EFFECTS[:-4]
    text = (REPO / "contracts" / "environment.md").read_text(encoding="utf-8")
    assert tuple(row[0] for row in validate.markdown_table(text, "Word")) == validate.SIDE_EFFECTS


def test_the_contract_says_the_words_arrived_with_the_runtime_and_no_skill_declares_them():
    text = (REPO / "contracts" / "environment.md").read_text(encoding="utf-8")
    assert "`calendar`, `mailbox` and `files`" in text and "not with a skill" in text and "a fixed phrase written by code" in text and "never the person's words" in text and "RUNTIME_ONLY_EFFECTS" in text
    declared = []
    for skill in sorted((REPO / "skills").glob("*/SKILL.md")):
        front = skill.read_text(encoding="utf-8").split("---", 2)[1]
        found = re.search(r"^\s*side_effects:\s*\[([^\]]*)\]", front, re.M)
        if found and set(w.strip() for w in found.group(1).split(",")) & set(WORDS):
            declared.append(skill.parent.name)
    assert declared == [], "a skill declares a word of the runtime's account writes"


def test_the_validator_refuses_a_skill_that_declares_a_word_the_runtime_alone_has_and_accepts_the_words_of_a_skill(tmp_path, monkeypatch):
    """The four words (write, calendar, mailbox, files) are in the list the contract names, and no skill declares one: an error of the vocabulary rule."""
    helpers = load("validate_rules_for_account_words", REPO / "scripts" / "tests" / "test_validate_rules.py")
    monkeypatch.setattr(helpers.validate, "ROOT", str(tmp_path))
    monkeypatch.setattr(helpers.validate, "SKILLS", str(tmp_path / "skills"))
    monkeypatch.setattr(helpers.validate, "AGENTS", str(tmp_path / "agents"))
    body = "# Demo\n\nText.\n\n## Confirmation gate\n\nAsk first.\n"
    assert validate.RUNTIME_ONLY_EFFECTS == ("write",) + WORDS and set(validate.SKILL_EFFECTS) == set(validate.SIDE_EFFECTS) - set(validate.RUNTIME_ONLY_EFFECTS)
    for word in validate.SKILL_EFFECTS:
        helpers.add_skill(tmp_path, meta={"side_effects": f"[{word}]"}, body=body)
        assert helpers.run_skill(tmp_path, classes=["search:web"]).errors == [], word
    for word in validate.RUNTIME_ONLY_EFFECTS + ("teleport",):
        helpers.add_skill(tmp_path, meta={"side_effects": f"[{word}]"}, body=body)
        report = helpers.run_skill(tmp_path, classes=["search:web"])
        flagged = [e["message"] for e in report.errors if e.get("rule") == "side-effects-vocabulary"]
        assert len(flagged) == 1 and f"side_effects {word}" in flagged[0], word
        assert ("no skill declares it" in flagged[0]) == (word != "teleport")


def test_the_writer_role_is_runtime_only_in_the_resolver_and_in_neither_the_listed_classes_nor_the_contract_table():
    assert "writer" in resolve.ROLES and not any(c.startswith("writer:") for c in resolve.LISTED)
    env = (REPO / "contracts" / "environment.md").read_text(encoding="utf-8")
    assert "writer:" not in env and "providers/writer" not in env
    contract = (REPO / "providers" / "CONTRACT.md").read_text(encoding="utf-8")
    assert "`writer:calendar`, `writer:mailbox`, `writer:files`" in contract and "providers/writer/" in contract and "never `auto`" in contract


@pytest.mark.parametrize("cls", CLASSES)
def test_a_writer_class_maps_to_the_writer_folder_and_its_two_variables(cls):
    target = cls.split(":")[1]
    assert resolve.split_class(cls) == ("writer", target) and resolve.folder(cls) == "writer"
    assert resolve.variables(cls) == [f"WRITER_{target.upper()}_PROVIDER", "WRITER_PROVIDER"]
    assert resolve.platform_of(cls) is None, "the target is part of the class and is handed to no implementation"


def test_with_no_writer_shipped_nothing_resolves_and_a_named_one_resolves_only_when_it_is_shipped(tmp_path):
    root = tmp_path / "wb"
    (root / "providers").mkdir(parents=True)
    assert resolve.implementations("writer:calendar", root=root) == []
    with pytest.raises(resolve.Unresolved):
        resolve.resolve("writer:calendar", root=root, env={})
    (root / "providers" / "writer").mkdir()
    (root / "providers" / "writer" / "google-calendar.py").write_text("SERVES = 'writer:calendar'\n", encoding="utf-8")
    got = resolve.resolve("writer:calendar", root=root, env={}, implementation="google-calendar")
    assert got["implementation"] == "google-calendar" and got["source"] == "configuration"
    with pytest.raises(resolve.Unresolved):      # a name that is not shipped is never used as a path
        resolve.resolve("writer:calendar", root=root, env={}, implementation="../elsewhere")
    with pytest.raises(resolve.UnknownClass):
        resolve.resolve("writer", root=root, env={})
    with pytest.raises(resolve.UnknownClass):
        resolve.resolve("author:calendar", root=root, env={})
