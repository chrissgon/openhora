"""A calendar line by name, when the project's sources folder is refused (package sources-identity, review of #673).

The lookup reads the newest snapshot through `sources.Folder`; a refused folder (code `foreign`, `folder`, `path`) used to escape as an error and lose the reply, and a first fix that counted it as
"no snapshot" made the person hear that the event does not exist, which is false. The lookup now returns the problem `folder`, and the line says the reason's sentence (a step on the computer),
reads no provider (it cannot cure a folder) and does not search again. Any other fault of the sources is raised as before. Real snapshots behind the real runtime/item_refs.py (the world of
test_event_lookup.py). Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_event_lookup_refused_folder.py
"""
from __future__ import annotations

import pytest

import phrase_kit as pk
import standin_tree as st
from closed_heads import closed_heads, tier1_forms  # noqa: F401
from test_calendar_write import world  # noqa: F401
from test_event_lookup import CANCEL, LIVE, OWNER, PT, build, calendar_reads, carry
from test_items_refused_reason import refuse_folder

ops_core = st.load("ops_core")
event_lookup = st.load("event_lookup")
item_refs = st.load("item_refs")
sources = st.load("sources")

pytestmark = pytest.mark.usefixtures("tier1_forms")


def test_a_refused_folder_is_the_reason_and_never_no_such_event(world, monkeypatch):
    build(world, monkeypatch)
    before = len(calendar_reads(world))
    refuse_folder(world)
    reply, extras = carry(world, LIVE, CANCEL)
    assert "\n" not in reply and pk.said(reply, "NW_ITEMS_REFUSED_FOLDER", PT), reply
    assert not pk.said(reply, "EV_NAME_NONE_DAY", PT) and not pk.said(reply, "EV_NAME_NONE", PT, days=30)
    assert len(calendar_reads(world)) == before, "no provider is read for a folder it cannot cure"
    assert "resend" not in extras, "and no card"


def test_the_problem_of_the_lookup_is_folder_for_a_refused_folder_and_stale_for_an_old_snapshot(world, monkeypatch):
    build(world, monkeypatch)
    ctx = ops_core.context(world["path"])
    assert event_lookup.events(ctx, OWNER)[1] is None
    world["snaps"].later(hours=30)
    assert event_lookup.events(ctx, OWNER) == ([], "stale"), "an old snapshot is still stale"
    world["snaps"].later(hours=-30)      # fresh again; the age is looked at before the folder is opened, so an old snapshot is stale whatever the folder (OPEN-3 keeps that line)
    refuse_folder(world)
    assert event_lookup.events(ctx, OWNER) == ([], "folder")


def test_any_other_fault_of_the_sources_is_raised_and_not_counted_as_a_refusal(world, monkeypatch):
    build(world, monkeypatch)
    ctx = ops_core.context(world["path"])

    def broken(*args, **kwargs):
        raise sources.SourcesError("the index does not match its record", "integrity")
    monkeypatch.setattr(item_refs, "read_index", broken)
    with pytest.raises(sources.SourcesError):
        event_lookup.events(ctx, OWNER)
