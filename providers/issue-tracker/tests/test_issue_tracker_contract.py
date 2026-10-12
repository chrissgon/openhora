"""The contract of integration:issue-tracker (providers/CONTRACT.md, "Verbs per class"), tested on every
implementation the resolver lists: a new implementation is tested by adding its harness to board_harness.py and
nothing else. Offline: no network, no real credential.

Run: uv run --with pytest==9.1.1 pytest providers/issue-tracker/tests
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
import board_harness  # noqa: E402

spec = importlib.util.spec_from_file_location("provider_resolve_for_board", REPO / "providers" / "resolve.py")
resolve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resolve)
IMPLEMENTATIONS = resolve.implementations("integration:issue-tracker", root=REPO)


class Board:
    """One implementation, one fresh board: run(verb...) runs the script and returns (exit code, JSON or None,
    stderr)."""

    def __init__(self, name: str, tmp_path: Path):
        self.harness = board_harness.HARNESSES[name]()
        self.script = REPO / "providers" / "issue-tracker" / f"{name}.py"
        self.config = tmp_path / "task_board.json"
        self.config.write_text(json.dumps(self.harness.config(tmp_path)), encoding="utf-8")
        self.tmp = tmp_path
        self.count = 0

    def run(self, *argv, config=True):
        env = {**os.environ, **self.harness.env()}
        args = [sys.executable, str(self.script), *argv] + (["--config-file", str(self.config)] if config else [])
        done = subprocess.run(args, capture_output=True, text=True, timeout=60, env=env)
        try:
            out = json.loads(done.stdout) if done.stdout.strip() else None
        except ValueError:
            out = None
        return done.returncode, out, done.stderr

    def upsert(self, item: dict, ident=None, key=None, mode="--confirmed"):
        self.count += 1
        item_file = self.tmp / f"item-{self.count}.json"
        item_file.write_text(json.dumps(item), encoding="utf-8")
        argv = ["upsert", "--item-file", str(item_file), "--idempotency-key", key or f"key-{self.count}", mode]
        return self.run(*(argv + (["--id", ident] if ident else [])))

    def get(self, ident: str) -> dict:
        code, out, err = self.run("get", "--id", ident)
        assert code == 0, err
        return out


@pytest.fixture(params=IMPLEMENTATIONS)
def board(request, tmp_path):
    assert request.param in board_harness.HARNESSES, f"{request.param} has no harness in board_harness.py"
    return Board(request.param, tmp_path)


def test_every_implementation_has_a_harness():
    assert IMPLEMENTATIONS and set(IMPLEMENTATIONS) <= set(board_harness.HARNESSES)


def test_an_item_that_was_created_is_read_back_with_its_title_text_and_state(board):
    code, out, err = board.upsert({"title": "Brand strategy", "text": "Write the strategy.\n\nTwo lines.",
                                   "state": "ready"})
    assert code == 0 and out["created"] is True, err
    got = board.get(out["id"])
    assert (got["title"], got["text"], got["state"], got["archived"]) == (
        "Brand strategy", "Write the strategy.\n\nTwo lines.", "ready", False)
    assert got["version"] == out["version"] and got["comments"] == [] and got["url"]


def test_the_version_changes_when_a_person_edits_the_title_the_text_or_the_state_and_not_otherwise(board):
    # The version covers the content (WP-3.15): a comment may or may not move it, so nothing here asserts either.
    ident = board.upsert({"title": "Name", "text": "Check the name.", "state": "planned"})[1]["id"]
    seen = [board.get(ident)["version"]]
    assert board.get(ident)["version"] == seen[-1]  # reading changes nothing
    code, out, _ = board.upsert({"state": "planned"}, ident=ident)
    assert code == 0 and board.get(ident)["version"] == seen[-1]  # the same value written again
    for change in ({"title": "Name, renamed"}, {"text": "Check it twice."}, {"state": "cancelled"}):
        board.harness.person_edits(ident, **change)
        seen.append(board.get(ident)["version"])
    assert len(set(seen)) == len(seen)
    board.harness.person_comments(ident, "Shorter, please.")
    got = board.get(ident)
    assert [c["text"] for c in got["comments"]] == ["Shorter, please."] and got["comments"][0]["id"]


def test_comments_lists_an_items_open_comments_whatever_its_version(board):
    ident = board.upsert({"title": "Name", "text": "Check the name.", "state": "planned"})[1]["id"]
    code, out, err = board.run("comments", "--id", ident)
    assert code == 0 and out == {"id": ident, "comments": []}, err
    board.harness.person_comments(ident, "Shorter, please.")
    board.harness.person_comments(ident, "Keep the blue.")
    code, out, err = board.run("comments", "--id", ident)
    assert code == 0 and [c["text"] for c in out["comments"]] == ["Shorter, please.", "Keep the blue."], err
    assert all(c["id"] and set(c) >= {"id", "author", "created_at", "text"} for c in out["comments"])
    assert [c["id"] for c in out["comments"]] == [c["id"] for c in board.get(ident)["comments"]]


def test_a_write_of_the_state_alone_keeps_the_title_and_the_text_a_person_edited(board):
    ident = board.upsert({"title": "Identity", "text": "Design the look.", "state": "planned"})[1]["id"]
    board.harness.person_edits(ident, title="Identity, warmer", text="Design a warmer look.")
    board.harness.person_comments(ident, "Keep the blue.")
    code, _, err = board.upsert({"state": "ready", "shown": {"task": "7"}}, ident=ident)
    assert code == 0, err
    got = board.get(ident)
    assert (got["title"], got["text"], got["state"]) == ("Identity, warmer", "Design a warmer look.", "ready")
    assert [c["text"] for c in got["comments"]] == ["Keep the blue."]


def test_list_names_every_item_with_its_version_and_an_item_a_person_created(board):
    made = board.upsert({"title": "Voice", "state": "planned"})[1]
    by_hand = board.harness.person_creates("Ask about the logo", "Is the logo final?")
    code, out, err = board.run("list")
    assert code == 0 and out["truncated"] is False, err
    listed = {i["id"]: i for i in out["items"]}
    assert set(listed) == {made["id"], by_hand}
    assert listed[made["id"]]["version"] == board.get(made["id"])["version"] and not listed[by_hand]["archived"]
    assert board.get(by_hand)["title"] == "Ask about the logo"


def test_the_same_idempotency_key_creates_one_item(board):
    first = board.upsert({"title": "Guidelines"}, key="plan-1-guidelines")[1]
    second = board.upsert({"title": "Guidelines", "state": "ready"}, key="plan-1-guidelines")[1]
    assert first["created"] is True and second["created"] is False and second["id"] == first["id"]
    assert len(board.run("list")[1]["items"]) == 1
    code, out, _ = board.run("resolve", "--idempotency-key", "plan-1-guidelines", "--not-created", "--dry-run")
    assert code == 0 and out["dry_run"] is True
    assert board.upsert({"title": "Guidelines"}, key="plan-1-guidelines")[1]["created"] is False  # the dry run kept it
    code, out, err = board.run("resolve", "--idempotency-key", "plan-1-guidelines", "--not-created", "--confirmed")
    assert code == 0, err
    assert board.upsert({"title": "Guidelines"}, key="plan-1-guidelines")[1]["created"] is True


def test_a_write_without_confirmation_is_refused_and_a_dry_run_changes_nothing(board):
    ident = board.upsert({"title": "Strategy", "state": "planned"})[1]["id"]
    before = board.get(ident)
    code, out, _ = board.upsert({"state": "ready"}, ident=ident, mode="--dry-run")
    assert code == 0 and out["dry_run"] is True and out["would"]
    assert board.get(ident) == before
    code, out, _ = board.upsert({"title": "Nothing written"}, mode="--dry-run")
    assert code == 0 and out["would"]["create"] is True and len(board.run("list")[1]["items"]) == 1
    item = board.tmp / "bare.json"
    item.write_text(json.dumps({"state": "ready"}), encoding="utf-8")
    code, out, _ = board.run("upsert", "--id", ident, "--item-file", str(item), "--idempotency-key", "k")
    assert code == 2 and out is None and board.get(ident) == before
    for bad in (["--id", "Not An Id"], ["--id", "../escape"]):
        assert board.run("get", *bad)[0] == 2
    item.write_text(json.dumps({"state": "someday"}), encoding="utf-8")
    assert board.run("upsert", "--id", ident, "--item-file", str(item), "--idempotency-key", "k", "--confirmed")[0] == 2


def test_a_state_the_board_holds_that_is_not_one_of_the_nine_is_read_as_null(board):
    ident = board.upsert({"title": "Name", "state": "planned"})[1]["id"]
    board.harness.person_edits(ident, state="someday")
    assert board.get(ident)["state"] is None


def test_the_shown_fields_are_written_and_never_read_back(board):
    ident = board.upsert({"title": "Strategy", "text": "The why.", "state": "ready",
                          "shown": {"task": "12", "run": "3", "pending": "review 5"}})[1]["id"]
    got = board.get(ident)
    assert got["text"] == "The why." and "12" not in json.dumps({k: got[k] for k in ("title", "text", "comments")})
    assert set(got) >= {"id", "version", "title", "text", "state", "archived", "comments", "url"}


def test_check_says_not_configured_with_exit_3_and_prints_no_secret(board):
    code, out, err = board.run("--check")
    assert code == 0 and out == {"ok": True}, err
    missing = board.tmp / "missing.json"
    missing.write_text(json.dumps({"provider": "local", "dir": str(board.tmp / "no-such-folder")}), encoding="utf-8")
    code, out, err = board.run("--check", "--config-file", str(missing), config=False)
    assert code == 3 and out is None and err.strip()
    code, out, err = board.run("--check", "--config-file", str(board.tmp / "absent.json"), config=False)
    assert code == 3 and err.strip()
    for value in board.harness.env().values():
        assert value not in err
