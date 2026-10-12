"""Tests of the local task board (providers/issue-tracker/local.py) beyond the contract: the form of its item file,
an item a person wrote by hand, and its command line. Offline.

Run: uv run --with pytest==9.1.1 pytest providers/issue-tracker/tests/test_issue_tracker_local.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "local.py"


def run(*argv):
    done = subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True, text=True, timeout=60)
    return done.returncode, done.stdout, done.stderr


def board(tmp_path) -> tuple:
    folder = tmp_path / "board"
    folder.mkdir()
    config = tmp_path / "task_board.json"
    config.write_text(json.dumps({"provider": "local", "dir": str(folder)}), encoding="utf-8")
    return folder, str(config)


def test_the_item_file_has_the_documented_form(tmp_path):
    folder, config = board(tmp_path)
    item = tmp_path / "item.json"
    item.write_text(json.dumps({"title": "Brand strategy", "text": "Write the strategy.", "state": "ready",
                                "shown": {"task": "4", "pending": "none"}}), encoding="utf-8")
    code, out, err = run("upsert", "--config-file", config, "--item-file", str(item), "--idempotency-key", "k1",
                         "--confirmed")
    assert code == 0, err
    assert json.loads(out)["id"] == "t1"
    assert (folder / "t1.md").read_text(encoding="utf-8") == (
        "# Brand strategy\n\nState: ready\n\nWrite the strategy.\n\n## Comments\n\n## Runtime\n\n"
        "- pending: none\n- task: 4\n")
    assert json.loads((folder / ".keys.json").read_text(encoding="utf-8")) == {"k1": "t1"}
    code, out, _ = run("upsert", "--config-file", config, "--item-file", str(item), "--idempotency-key", "k2",
                       "--confirmed")
    assert json.loads(out)["id"] == "t2"  # the smallest positive number not in use


def test_a_file_a_person_wrote_by_hand_with_no_state_line_is_a_requested_item(tmp_path):
    folder, config = board(tmp_path)
    (folder / "logo-question.md").write_text("# Is the logo final?\n\nAsk the designer first.\n\n## Comments\n\n"
                                              "- I think so.\n", encoding="utf-8")
    (folder / ".hidden.md").write_text("# not an item\n", encoding="utf-8")
    (folder / "notes.txt").write_text("not an item\n", encoding="utf-8")
    code, out, err = run("get", "--config-file", config, "--id", "logo-question")
    assert code == 0, err
    got = json.loads(out)
    assert (got["title"], got["text"], got["state"]) == ("Is the logo final?", "Ask the designer first.", "requested")
    assert [c["text"] for c in got["comments"]] == ["I think so."]
    assert [i["id"] for i in json.loads(run("list", "--config-file", config)[1])["items"]] == ["logo-question"]
    item = tmp_path / "item.json"
    item.write_text(json.dumps({"state": "ready"}), encoding="utf-8")
    run("upsert", "--config-file", config, "--id", "logo-question", "--item-file", str(item), "--idempotency-key", "k",
        "--confirmed")
    got = json.loads(run("get", "--config-file", config, "--id", "logo-question")[1])
    assert (got["title"], got["text"], got["state"]) == ("Is the logo final?", "Ask the designer first.", "ready")
    assert [c["text"] for c in got["comments"]] == ["I think so."]


def test_the_script_prints_its_help_and_refuses_an_unknown_call(tmp_path):
    code, out, _ = run("--help")
    assert code == 0 and "integration:issue-tracker" in out
    code, out, err = run("--no-such-flag")
    assert code == 2 and out == "" and "Traceback" not in err
    assert run()[0] == 2
    _, config = board(tmp_path)
    relative = tmp_path / "relative.json"
    relative.write_text(json.dumps({"provider": "local", "dir": "board"}), encoding="utf-8")
    assert run("list", "--config-file", str(relative))[0] == 2
    assert run("get", "--config-file", config, "--id", "t9")[0] == 1
    assert run("list")[0] == 2
