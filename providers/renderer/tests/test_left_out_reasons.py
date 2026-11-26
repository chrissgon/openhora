"""Every beat the timeline leaves out has one reason (V9b-3f). `resolve_timeline` gives a beat the neighbour pass cuts to zero `overlap`. (The HyperFrames
page stage's and the `hf-page` schema's tests went with that engine, PF-b.)

Offline: the documents are the kit's fictional post. No ffmpeg, no browser, no docker."""
from __future__ import annotations

import copy

import pytest

import renderer_kit as K
import _edl
from test_dropped_beat_picture import layout, live_shape, with_slots


@pytest.fixture(scope="module")
def docs(tmp_path_factory):
    folder = tmp_path_factory.mktemp("leftout")
    data, edl, beats, vocab = K.hf_documents(folder)
    return data, edl, beats, vocab, folder


def resolve(docs, rows):
    data, edl, beats, vocab, _ = docs
    beats = with_slots(copy.deepcopy(beats), rows)
    return _edl.resolve_timeline(edl, beats, vocab, data)


def test_a_beat_cut_to_zero_by_the_neighbour_pass_is_dropped_as_overlap_and_every_dropped_id_has_one_reason(docs):
    # two pictures that start on the same word: the shorter is cut to nothing by the neighbour pass; the text beats under a picture are `under_picture`
    timeline = resolve(docs, [layout("a1", 7, "s1", 22, 24), layout("a0", 8, "s0", 22, 27)])
    reasons = {r["id"]: r["reason"] for r in timeline["dropped_reasons"]}
    assert reasons.get("a1") == "overlap"
    assert sorted(reasons) == sorted(timeline["dropped"]) and len(timeline["dropped_reasons"]) == len(timeline["dropped"])
    assert set(reasons.values()) <= {"overlap", "under_picture"}


def test_the_live_shape_has_a_reason_for_every_dropped_beat(docs):
    data, edl, beats, vocab = live_shape(docs)
    timeline = _edl.resolve_timeline(edl, with_slots(beats, beats["layouts"] + [layout("a4", 8, "s4", 22, 31)]), vocab, data)
    assert "a3" in timeline["dropped"]
    assert sorted(r["id"] for r in timeline["dropped_reasons"]) == sorted(timeline["dropped"])
    assert "overlap" in {r["reason"] for r in timeline["dropped_reasons"]} and {r["reason"] for r in timeline["dropped_reasons"]} <= {"under_picture", "overlap"}


def test_a_timeline_that_drops_nothing_has_no_reason_rows(docs):
    timeline = resolve(docs, [])
    assert timeline["dropped"] == [] and "dropped_reasons" not in timeline
