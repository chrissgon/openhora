"""Tests of the task board on Notion (providers/issue-tracker/notion.py) beyond the contract, against the stand-in
service (providers/documents/tests/fake_notion.py). Offline: no network, no real credential.

Run: uv run --with pytest==9.1.1 pytest providers/issue-tracker/tests/test_issue_tracker_notion.py
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SCRIPT = REPO / "providers" / "issue-tracker" / "notion.py"
sys.path.insert(0, str(HERE))
import board_harness  # noqa: E402


class Board:
    def __init__(self, tmp_path: Path, **config):
        self.harness = board_harness.NotionBoard()
        self.fake = None
        cfg = self.harness.config(tmp_path)
        self.fake = self.harness.fake
        self.config = tmp_path / "task_board.json"
        self.config.write_text(json.dumps({**cfg, **config}), encoding="utf-8")
        self.tmp = tmp_path
        self.count = 0

    def run(self, *argv, env=None):
        done = subprocess.run([sys.executable, str(SCRIPT), *argv] + ([] if "--config-file" in argv else ["--config-file", str(self.config)]),
                              capture_output=True, text=True, timeout=60,
                              env={**os.environ, **self.harness.env(), **(env or {})})
        try:
            out = json.loads(done.stdout) if done.stdout.strip() else None
        except ValueError:
            out = None
        return done.returncode, out, done.stdout + done.stderr

    def upsert(self, item: dict, key: str, ident=None, mode="--confirmed"):
        self.count += 1
        item_file = self.tmp / f"item-{self.count}.json"
        item_file.write_text(json.dumps(item), encoding="utf-8")
        return self.run("upsert", "--item-file", str(item_file), "--idempotency-key", key, mode,
                        *(["--id", ident] if ident else []))

    def rows(self) -> int:
        return sum(1 for p in self.fake.pages.values() if p["parent"].get("data_source_id") == self.harness.base)


def test_the_token_is_never_printed_and_a_redirect_is_refused(tmp_path):
    board = Board(tmp_path)
    made = board.upsert({"title": "Strategy", "state": "ready"}, key="k1")[1]
    board.fake.redirect_next = True
    code, out, said = board.run("get", "--id", made["id"])
    assert code == 1 and out is None and "redirect" in said and board.fake.redirected == 0
    assert board.fake.token not in said
    code, _, said = board.run("get", "--id", made["id"], env={"NOTION_TOKEN": "fake-wrong-token"})
    assert code == 3 and "401" in said and "fake-wrong-token" not in said
    for argv in (("list",), ("get", "--id", made["id"]), ("--check",)):
        code, _, said = board.run(*argv)
        assert code == 0 and board.fake.token not in said
    code, out, said = board.upsert({"state": "done"}, key="k2", ident=made["id"], mode="--dry-run")
    assert code == 0 and out["dry_run"] is True and board.fake.token not in said


def test_the_provider_names_itself_openhora_in_the_user_agent(tmp_path):
    board = Board(tmp_path)
    before = len(board.fake.user_agents)
    assert board.run("--check")[0] == 0
    assert board.fake.user_agents[before:] and set(board.fake.user_agents[before:]) == {"openhora-issue-tracker-notion"}


def test_a_base_address_that_is_not_loopback_is_refused(tmp_path):
    board = Board(tmp_path)
    before = len(board.fake.requests)
    for address in ("https://api.notion.example", "http://10.0.0.1:8080"):
        env = {"INTEGRATION_ISSUE_TRACKER_NOTION_API_BASE": address}
        for argv in (("--check",), ("list",)):
            code, out, said = board.run(*argv, env=env)
            assert code == 2 and out is None and "loopback" in said and board.fake.token not in said
    assert len(board.fake.requests) == before


def test_an_option_the_states_map_does_not_know_is_read_as_null(tmp_path):
    board = Board(tmp_path, states={"done": "Complete", "ready": "To do"})
    made = board.upsert({"title": "Voice", "state": "done"}, key="k1")[1]
    status = board.fake.pages[made["id"]]["properties"]["Status"]
    assert status["status"]["name"] == "Complete"
    assert board.run("get", "--id", made["id"])[1]["state"] == "done"
    for option, state in (("Done", None), ("done", None), ("To do", "ready"), ("planned", "planned"), (None, "requested")):
        board.fake.person_sets(made["id"], "Status", option)
        assert board.run("get", "--id", made["id"])[1]["state"] == state, option
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"provider": "notion", "base": board.harness.base, "states": {"done": "ready"}}),
                   encoding="utf-8")
    assert board.run("list", "--config-file", str(bad))[0] == 2  # two states on one option


def test_a_creation_with_an_unknown_outcome_blocks_its_key_until_resolve(tmp_path):
    board = Board(tmp_path)
    board.fake.fail_next("create_page", 502, carried_out=True)
    code, _, said = board.upsert({"title": "Guidelines"}, key="plan-1-guidelines")
    assert code == 1 and "502" in said and board.rows() == 1
    made = next(i for i, p in board.fake.pages.items() if p["parent"].get("data_source_id") == board.harness.base)
    creations = board.fake.count("create_page")
    for mode in ("--confirmed", "--dry-run"):
        code, _, said = board.upsert({"title": "Guidelines"}, key="plan-1-guidelines", mode=mode)
        assert code == 1 and "pending" in said and "resolve" in said
    assert board.fake.count("create_page") == creations and board.rows() == 1
    code, out, said = board.run("resolve", "--idempotency-key", "plan-1-guidelines", "--id", made, "--confirmed")
    assert code == 0 and out["resolved"] is True, said
    code, out, said = board.upsert({"title": "Guidelines", "state": "ready"}, key="plan-1-guidelines")
    assert code == 0 and out["created"] is False and out["id"] == made and board.rows() == 1, said
    # A refusal (a 4xx that is not 408 or 429) sent nothing: the key is released at once.
    board.fake.fail_next("create_page", 400)
    assert board.upsert({"title": "Name"}, key="plan-1-name")[0] == 1
    code, out, _ = board.upsert({"title": "Name"}, key="plan-1-name")
    assert code == 0 and out["created"] is True and board.rows() == 2
    # Too many requests is an unknown outcome too, and is never retried inside the verb.
    board.fake.fail_next("create_page", 429)
    calls = board.fake.count("create_page")
    code, _, said = board.upsert({"title": "Voice"}, key="plan-1-voice")
    assert code == 1 and "429" in said and "Retry-After" in said and board.fake.count("create_page") == calls + 1
    assert "pending" in board.upsert({"title": "Voice"}, key="plan-1-voice")[2]


def test_the_board_never_retries_a_429_or_a_5xx(tmp_path):
    """The board's rule (notion.py, "a verb never retries"): too many requests or a server error ends the verb with exit
    1 and the status, after exactly one request of that call, for a read and for a write alike; the runtime's next sync
    is the retry."""
    board = Board(tmp_path)
    made = board.upsert({"title": "Identity", "state": "planned"}, key="k1")[1]
    reads = (("retrieve_page", ("get", "--id", made["id"])), ("query_base", ("list",)))
    for status in (429, 500, 503):
        for name, argv in reads:
            board.fake.fail_next(name, status)
            calls = board.fake.count(name)
            code, out, said = board.run(*argv)
            assert code == 1 and out is None and str(status) in said, (name, status, said)
            assert board.fake.count(name) == calls + 1, (name, status)
    for n, status in enumerate((429, 502)):
        board.fake.fail_next("update_page", status)
        calls = board.fake.count("update_page")
        code, _, said = board.upsert({"title": "Identity", "state": "ready"}, key=f"w{n}", ident=made["id"])
        assert code == 1 and str(status) in said and board.fake.count("update_page") == calls + 1, (status, said)


def test_a_write_of_values_already_on_the_row_sends_no_change(tmp_path):
    board = Board(tmp_path)
    made = board.upsert({"title": "Identity", "text": "Design the look.", "state": "planned",
                         "shown": {"task": "4"}}, key="k1")[1]
    before = board.fake.count("update_page") + board.fake.count("append_children") + board.fake.count("delete_block")
    code, out, said = board.upsert({"title": "Identity", "text": "Design the look.", "state": "planned",
                                    "shown": {"task": "4"}}, key="k2", ident=made["id"])
    assert code == 0 and out["version"] == made["version"], said
    after = board.fake.count("update_page") + board.fake.count("append_children") + board.fake.count("delete_block")
    assert after == before
    code, out, _ = board.upsert({"shown": {"task": "4", "run": "2"}}, key="k3", ident=made["id"])
    sent = board.fake.requests[-2]
    assert code == 0 and sent[0] == "PATCH" and list(sent[2]["properties"]) == ["Runtime"]
    assert board.run("get", "--id", made["id"])[1]["text"] == "Design the look."


def test_the_task_board_loads_only_the_block_helper_from_the_documents_folder(tmp_path, monkeypatch):
    board = Board(tmp_path)
    made = board.upsert({"title": "Strategy", "text": "The why."}, key="k1")[1]
    for name, value in board.harness.env().items():
        monkeypatch.setenv(name, value)
    before, opened = set(sys.modules), []
    real = importlib.util.spec_from_file_location

    def recording(name, location, *args, **kwargs):
        opened.append(Path(location).resolve())
        return real(name, location, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "spec_from_file_location", recording)
    spec = importlib.util.spec_from_file_location("issue_tracker_notion_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = module.main(["get", "--id", made["id"], "--config-file", str(board.config)])
    assert code == 0 and json.loads(out.getvalue())["text"] == "The why.", err.getvalue()
    providers = REPO / "providers"
    files = [Path(getattr(sys.modules[n], "__file__", None) or "/").resolve() for n in set(sys.modules) - before]
    loaded = {f.relative_to(providers).as_posix() for f in files + opened if f.is_relative_to(providers)}
    assert "documents/notion_blocks.py" in {f.relative_to(providers).as_posix() for f in opened
                                            if f.is_relative_to(providers)}
    other = {p for p in loaded if not p.startswith(("issue-tracker/", "secrets/"))}
    assert other == {"documents/notion_blocks.py"}
    source = SCRIPT.read_text(encoding="utf-8")
    assert source.count('"documents"') == 1 and "spec_from_file_location" in source


def test_a_comment_on_one_block_of_the_body_is_read_with_the_item(tmp_path):
    # Measured on the live service (README.md, N4): a comment on a block is listed under that block, not the page's.
    board = Board(tmp_path)
    made = board.upsert({"title": "Voice", "text": "First paragraph.\n\nSecond paragraph."}, key="k1")[1]
    block = board.fake.children[made["id"]][1]
    board.fake.comment(made["id"], "On the row.")
    board.fake.comment(block, "On the second paragraph.")
    got = board.run("get", "--id", made["id"])[1]
    assert [c["text"] for c in got["comments"]] == ["On the row.", "On the second paragraph."]


def test_a_row_in_the_trash_is_got_as_archived_with_no_body(tmp_path):
    # Measured on the live service (README.md, N8): the body of a trashed row cannot be listed (404).
    board = Board(tmp_path)
    made = board.upsert({"title": "Voice", "text": "A body.", "state": "ready"}, key="k1")[1]
    board.fake.person_trashes(made["id"])
    code, out, said = board.run("get", "--id", made["id"])
    assert code == 0, said
    assert (out["archived"], out["title"], out["text"], out["comments"], out["state"]) == (True, "Voice", "", [], "ready")
    assert made["id"] not in [i["id"] for i in board.run("list")[1]["items"]]


def test_comments_is_one_listing_of_the_rows_own_comments_and_a_comment_does_not_move_the_version(tmp_path):
    # Measured on the live service (README.md, N3): a comment does not move the version, so the runtime lists the
    # row's own comments at every pull with this one call (WP-3.15); the comments on the body's blocks come with get.
    board = Board(tmp_path)
    made = board.upsert({"title": "Voice", "text": "First paragraph.\n\nSecond paragraph."}, key="k1")[1]
    before = board.run("get", "--id", made["id"])[1]["version"]
    board.fake.comment(made["id"], "On the row.")
    board.fake.comment(board.fake.children[made["id"]][1], "On the second paragraph.")
    assert board.run("list")[1]["items"][0]["version"] == before
    listed = board.fake.count("list_comments")
    code, out, said = board.run("comments", "--id", made["id"])
    assert code == 0, said
    assert [c["text"] for c in out["comments"]] == ["On the row."]
    assert board.fake.count("list_comments") == listed + 1
