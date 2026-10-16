"""R18: the router's run, which happens inside the calling process, is stopped by a cancel from another thread through the watcher
(runtime/run_stop.py watch), and a request cancelled while it answers keeps nothing of its reply. Offline: the stand-in router of the chat
tree, which waits for a file before it answers (the fixtures of test_routing_read.py).

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_cancel_router.py
"""
from __future__ import annotations

import standin_tree as st
from test_chat import tree as chat_tree  # noqa: F401  (the fixture test_routing_read's tree builds on)
from test_routing_read import project, release, request_row, routed_in_thread, tree, until  # noqa: F401

ops = st.load("ops")
ops_core = st.load("ops_core")


def test_a_router_run_in_a_thread_is_stopped_by_a_cancel_from_another_thread_through_the_watcher(tree):  # noqa: F811
    path = project(tree)
    made = ops.request(path, "Which market should the invented studio go after first?", title="Market")["request"]
    thread, box = routed_in_thread(tree, made)
    try:
        until(lambda: request_row(tree, made)["routing"])
        out = ops.cancel(path, made, channel="page")        # the adapter waits for a file that is never written: only the watcher can end it
        thread.join(30)
        assert not thread.is_alive()
    finally:
        release(tree)
        thread.join(30)
    run_id = out["stopped"][0]["run"]
    assert out["stopped"] == [{"run": run_id, "state": "cancelled"}] and out["cancelled"] == [made] and out["already"] is False
    ctx = ops_core.context(path)
    row = ctx["store"].task_run_get(ctx["conn"], run_id)
    assert row["status"] == "cancelled" and row["failure"] is None and row["error"] == "cancelled by user from page"
    assert ctx["store"].task_get(ctx["conn"], made)["state"] == "cancelled" and ctx["store"].pending_list(ctx["conn"], "all") == []
    assert isinstance(box[0], dict) and box[0]["status"] == "cancelled" and box[0]["pending_id"] is None and box[0]["failure"] is None
    assert request_row(tree, made)["routing"] is None
