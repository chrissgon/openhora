"""Tests of the flow `new-video` (flows/new-video.json, package V1b1-4): the file is read and checked by the flow code, its one task is the step `media`
with both parameters bound, and the plan builder takes it with an id and a post. Offline; names invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_flow_new_video.py
"""
from __future__ import annotations

import datetime

import pytest

import standin_tree as st

flow_files = st.load("flow_files")
steps = st.load("steps")
step_media = st.load("step_media")

RID = "0123456789abcdef"
POST = "docs/marketing/content/2027-11-02-aster-lane.md"
CLOCK = datetime.datetime(2027, 11, 2, tzinfo=datetime.timezone.utc)


def test_flow_files_reads_new_video_and_its_check_finds_no_problem():
    flow = flow_files.load("new-video")
    assert flow["flow"] == "new-video" and "new-video" in flow_files.names() and set(flow["params"]) == {"media", "post"}
    assert flow_files.problems(flow_files.to_file(flow), "new-video") == []
    assert flow_files.main(["--check", "new-video"]) == 0


def test_its_one_task_is_the_step_media_with_both_parameters_bound():
    flow = flow_files.load("new-video")
    [task] = flow["tasks"]
    assert task["step"] == "media" and task["key"] == "video" and task["milestone"] is True and task["depends_on"] == []
    assert task["args"] == {"media": "{media}", "post": "{post}"}
    bound = flow_files.bind(flow, {"media": RID, "post": POST}, CLOCK)
    assert bound["flow"]["tasks"][0]["args"] == {"media": RID, "post": POST} and bound["bound"]["params"] == {"media": RID, "post": POST}


def test_the_plan_builder_accepts_it_with_an_id_and_a_post_and_refuses_a_bad_one():
    flow = flow_files.load("new-video")
    bound = flow_files.bind(flow, {"media": RID, "post": POST}, CLOCK)["flow"]["tasks"][0]
    planned = steps.plan_task(bound["step"], bound["args"], key=bound["key"], title=bound["title"], text=bound["text"], milestone=True)
    assert planned["step"] == "media" and planned["args"] == {"media": RID, "post": POST} and planned["footprint"] == []
    with pytest.raises(steps.StepFailure) as refused:
        steps.plan_task("media", {"media": "nope", "post": POST}, key="video", title="t", text="x")
    assert refused.value.code == "bad_args" and refused.value.field == "media"


def test_the_step_kind_it_names_is_registered_and_the_default_flow_text_says_nothing_is_published():
    assert steps.kind_of("media") is step_media.KIND
    [task] = flow_files.load("new-video")["tasks"]
    assert "nothing is published" in task["text"]
