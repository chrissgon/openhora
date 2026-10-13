"""The operations of the media store through the terminal (media-in, media-list, media-purge), the store's place outside the
project, and the retention run by a dispatcher round with no model call. The stand-in tree of standin_tree.py; ffmpeg makes
the tiny synthetic video (the tests that need it are skipped where it is not installed).

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_media_ops.py
"""
from __future__ import annotations

import datetime
import json
import os

import pytest

import standin_tree as st
from media_fixtures import make_mov, needs_ffmpeg, png
from test_file_drop import planned

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
cli = st.load("cli")
media = st.load("media")
operations = st.load("operations")
UTC = datetime.timezone.utc


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    project = str(built["project"])
    ops.accept_config(project, ops.project_config.load(project)["sha256"])
    hand = tmp_path / "hand"
    hand.mkdir()
    return {**built, "hand": hand}


@pytest.fixture
def mov(tmp_path):
    return make_mov(tmp_path / "hand-clip.mov") if media.ffprobe_path() else None


def run(tree, *argv):
    return cli.run([*argv[:1], "--project", str(tree["project"]), *argv[1:]])


def test_the_store_lies_under_the_data_folder_and_never_under_the_project(tree):
    project = os.path.realpath(tree["project"])
    listed = run(tree, "media-list")
    assert listed["recordings"] == [] and listed["limits"]["max_seconds"] == 300
    root = media.root_of(str(tree["data"]))
    assert not os.path.realpath(root).startswith(project + os.sep) and not os.path.realpath(str(tree["data"])).startswith(project + os.sep)
    assert media.root_of(ops.config(str(tree["project"]))["data_dir"]) == root


@needs_ffmpeg
def test_media_in_takes_a_file_from_disk_through_the_same_checks_and_issues_the_id(tree, mov):
    done = run(tree, "media-in", "--file", str(mov))
    rid = done["recording"]
    assert media.ID.fullmatch(rid) and done["type"] == "mov" and done["name"] == "hand-clip.mov"
    shown = run(tree, "media-list")
    assert [r["id"] for r in shown["recordings"]] == [rid] and shown["recordings"][0]["raw"]["sha256"] == done["sha256"]
    assert run(tree, "media-list", "--recording", rid)["recordings"][0]["status"] == "open"
    with pytest.raises(ops.OpsError, match="never replaced"):
        run(tree, "media-in", "--recording", rid, "--file", str(mov))


@needs_ffmpeg
def test_media_in_attaches_to_a_recording_issued_by_code_and_an_asset_to_its_slot(tree, mov, tmp_path):
    data = str(tree["data"])
    record = media.create(data, posts={"instagram": "docs/marketing/posts/launch.md"})
    done = run(tree, "media-in", "--recording", record["id"], "--file", str(mov))
    assert done["recording"] == record["id"]
    media.register_slots(data, record["id"], [{"key": "b1", "description": "a picture of the shelf"}])
    sid = media.slot_id(record["id"], "b1")
    picture = tmp_path / "hand" / "shelf.png"
    picture.write_bytes(png(20, 10))
    asset = run(tree, "media-in", "--recording", record["id"], "--slot", sid, "--file", str(picture))
    assert asset["kind"] == "asset" and asset["facts"] == {"width": 20, "height": 10}


def test_media_in_refuses_a_link_a_folder_a_missing_file_and_a_file_that_is_not_media(tree, tmp_path):
    hand = tree["hand"]
    (hand / "note.txt").write_text("not a video, only some words that are long enough to be sniffed")
    os.symlink(hand / "note.txt", hand / "link.mov")
    for target in (hand / "link.mov", hand, hand / "missing.mov"):
        with pytest.raises(ops.OpsError) as caught:
            run(tree, "media-in", "--file", str(target))
        assert caught.value.code == 2
    with pytest.raises(ops.OpsError, match="MP4 or MOV") as caught:
        run(tree, "media-in", "--file", str(hand / "note.txt"))
    assert caught.value.code == 1 and caught.value.kind == "type"
    assert run(tree, "media-list")["recordings"] == []
    with pytest.raises(ops.OpsError, match="no recording"):
        run(tree, "media-list", "--recording", "0" * 16)
    with pytest.raises(ops.OpsError):
        run(tree, "media-list", "--recording", "../x")


def ended(tree, status, days):
    now = datetime.datetime.now(UTC)
    then = now - datetime.timedelta(days=days)
    record = media.create(str(tree["data"]), now=then)
    folder = os.path.join(str(tree["data"]), "media", record["id"])
    open(os.path.join(folder, "raw.mov"), "wb").write(b"x")
    open(os.path.join(folder, "transcript.json"), "w").write("{}")
    if status != "open":
        media.mark(str(tree["data"]), record["id"], status, now=then)
    return record["id"], folder


def test_media_purge_removes_the_edit_tasks_run_folders_with_the_recording(tree):
    project = str(tree["project"])
    ids = planned(tree)
    ran = ops.run_next(project)                          # the stand-in adapter runs the first task: its run folder exists
    run_dir = ran["run_dir"]
    assert os.path.isdir(os.path.join(run_dir, "outputs"))
    os.makedirs(os.path.join(run_dir, "failed-1", "outputs"))
    rid, folder = ended(tree, "cancelled", 8)
    media.bind_tasks(str(tree["data"]), rid, {"edit": ran["ran"]})
    done = run(tree, "media-purge")
    assert done["removed"] == [{"recording": rid, "what": "all", "run_dirs": 1}]
    assert not os.path.exists(folder) and not os.path.exists(run_dir)
    assert ids["market"] == ran["ran"]


def test_media_purge_leaves_the_folders_of_a_task_that_is_still_running(tree):
    project = str(tree["project"])
    planned(tree)
    ran = ops.run_next(project)
    rid, folder = ended(tree, "cancelled", 8)
    media.bind_tasks(str(tree["data"]), rid, {"edit": ran["ran"]})
    conn = ops_core.context(project)
    store = conn["store"]
    # a run row still `running`: the purge waits for it
    rows = store.task_runs_list(conn["conn"], ran["ran"])
    assert rows and rows[0]["run_dir"] == ran["run_dir"]
    import ops_media
    seen = ops_media._run_dirs_of(conn)({"tasks": {"edit": ran["ran"]}})
    assert seen == [ran["run_dir"]]
    conn["conn"].execute("UPDATE task_runs SET status = 'running' WHERE task_id = ?", (ran["ran"],))
    conn["conn"].commit()
    assert ops_media._run_dirs_of(conn)({"tasks": {"edit": ran["ran"]}}) is None
    done = run(tree, "media-purge")
    assert done["removed"] == [] and "still going" in done["skipped"][0] and os.path.exists(folder)


def test_media_purge_by_id_removes_that_recording_whatever_its_age(tree):
    rid, folder = ended(tree, "open", 0)
    other, other_folder = ended(tree, "open", 0)
    assert run(tree, "media-purge", "--recording", rid)["removed"][0]["recording"] == rid
    assert not os.path.exists(folder) and os.path.exists(other_folder)
    with pytest.raises(ops.OpsError):
        run(tree, "media-purge", "--recording", "9" * 16)


def test_a_dispatcher_round_runs_the_retention_with_no_model_call(tree):
    rid, folder = ended(tree, "published", 40)
    young, young_folder = ended(tree, "published", 2)
    done = ops.dispatch(str(tree["project"]), wait=False)
    assert done["stopped"] == "no area agent is configured"                   # no agent, no model: the round still purges
    assert done["media_purged"] == [{"recording": rid, "what": "all", "run_dirs": 0}]
    assert not os.path.exists(folder) and os.path.exists(young_folder)
    assert not os.path.isfile(os.path.join(str(tree["adapter"]), "calls.txt"))
    assert "media_purged" not in ops.dispatch(str(tree["project"]), wait=False)  # nothing left to remove: the key is absent


def test_the_media_rows_never_reach_the_model_clients_and_the_cli_flags_are_the_tables():
    for name, channels in (("media-in", ("terminal", "page")), ("media-list", ("terminal", "page")), ("media-purge", ("terminal",))):
        assert operations.by_name(name)["channels"] == channels and operations.by_name(name)["model"] is False
    assert {"media-in", "media-list", "media-purge"} <= set(operations.terminal_verbs())
    assert operations.GROUPS["media"] == {"operations": ("media-in",), "kind": None}
    assert "media-list" in operations.GROUPS["read"]["operations"]
    assert not any(name.startswith("media") for name in operations.permissions("mcp", None) + operations.permissions("messaging", None))
    assert not any(row["name"].startswith("media") for row in operations.OPERATIONS if "chat" in row["channels"])


def test_media_purge_by_id_refuses_a_scheduled_recording_unless_the_flag_is_given(tree):
    rid, folder = ended(tree, "scheduled", 0)
    with pytest.raises(ops.OpsError, match="--include-scheduled") as caught:
        run(tree, "media-purge", "--recording", rid)
    assert caught.value.code == 1 and os.path.exists(folder)
    with pytest.raises(ops.OpsError):
        run(tree, "media-purge", "--include-scheduled")                      # the flag goes with a recording id
    assert run(tree, "media-purge", "--recording", rid, "--include-scheduled")["removed"][0]["recording"] == rid
    assert not os.path.exists(folder)
    old, old_folder = ended(tree, "scheduled", 400)
    assert run(tree, "media-purge")["removed"] == [] and os.path.exists(old_folder), "a scheduled recording is never purged by age"


def test_an_open_post_whose_task_still_waits_or_runs_is_not_abandoned_and_a_named_purge_still_works(tree):
    project = str(tree["project"])
    ids = planned(tree)
    waiting = ids["profile"]                                     # waits for the market task: a task of the post that has not run
    rid, folder = ended(tree, "open", 90)
    media.bind_tasks(str(tree["data"]), rid, {"code": waiting})
    media.update(str(tree["data"]), rid, lambda r: None, now=datetime.datetime.now(UTC) - datetime.timedelta(days=90))     # binding stamped it: age it again
    held = run(tree, "media-purge")
    assert held["removed"] == [] and "still going" in held["skipped"][0] and os.path.exists(folder), "by age: the post is not abandoned"
    assert ops.dispatch(project, wait=False).get("media_purged") is None
    done = run(tree, "media-purge", "--recording", rid)          # the person names it: it goes
    assert done["removed"][0]["recording"] == rid and not os.path.exists(folder)
    # a code task whose run is going keeps even a recording that was named
    rid2, folder2 = ended(tree, "cancelled", 9)
    ran = ops.run_next(project)
    media.bind_tasks(str(tree["data"]), rid2, {"code": ran["ran"]})
    conn = ops_core.context(project)
    conn["conn"].execute("UPDATE task_runs SET status = 'running' WHERE task_id = ?", (ran["ran"],))
    conn["conn"].commit()
    assert run(tree, "media-purge", "--recording", rid2)["removed"] == [] and os.path.exists(folder2)
