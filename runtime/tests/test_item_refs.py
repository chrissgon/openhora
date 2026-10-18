"""Tests of the references to an item of a snapshot (package SNAP-IDX, runtime/item_refs.py): `<source id>#<n>` names the n-th message or event
of the newest version of a registered mail or calendar source through the index kept in that version's manifest, never through the text;
`created:<number>` names an event the runtime created and is resolved by the function the calendar write path gives. The grammar is closed; `#0`,
a number past the end, a source that is not a mail or calendar source, a snapshot older than 26 hours and a version made before the index existed
are refused with their sentences and a stable code; an index edited outside the runtime is read back through the closed shapes. Offline: the
stand-in providers of test_sources_mail.py behind the one caller; every name and address is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_item_refs.py
"""
from __future__ import annotations

import datetime
import json
import os
import stat

import pytest

import standin_tree as st
import test_sources_mail as tsm
from sources_fixture import standin_convert

item_refs = st.load("item_refs")
sources = st.load("sources")

NOW = tsm.NOW


@pytest.fixture
def desk(tmp_path, monkeypatch):
    d = tsm.Desk(tmp_path, monkeypatch)
    d.providers.mail["gmail"] = [
        tsm.message(1, "2026-10-17T09:00:00Z", sender="Ana Lima <ana@clinic.example>", subject="Appointment confirmed", thread_id="t1", reply_to="desk@clinic.example",
                    headers={"Message-ID": "<a1@clinic.example>"}),
        tsm.message(2, "2026-10-16T14:30:00Z", sender="Bob <bob@shop.example>", subject="Your order", thread_id="t2", headers={"Message-ID": "<b2@shop.example>"}),
        tsm.message(3, "2026-10-15T08:00:00Z", sender="Cleo <cleo@club.example>", subject="Hello", thread_id="t3")]
    d.providers.events[("google", "primary")] = [tsm.event(1), tsm.event(2, "2026-10-18", "2026-10-19", "Holiday", all_day=True, recurring=True)]
    d.mail("inbox")
    d.calendar("agenda", tsm.GOOGLE_CAL)
    return d


def rewrite_manifest(desk, source_id, change, version=None):
    """Change a version's manifest the way someone with access to the folder could: the file and its folder are made writable first."""
    version = version or desk.latest(source_id)["version"]
    folder = desk.folder / source_id / str(version)
    path = folder / "manifest.json"
    folder.chmod(0o700)
    path.chmod(0o600)
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    path.chmod(stat.S_IRUSR)


def resolve(desk, ref, **more):
    return item_refs.resolve(desk.ctx, ref, clock=lambda: desk.now, **more)


def refused(desk, ref, **more):
    with pytest.raises(item_refs.ItemRefError) as why:
        resolve(desk, ref, **more)
    return why.value


# --- the grammar ------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value, parts", [("inbox#1", {"kind": "item", "source": "inbox", "n": 1}), ("  inbox#12 ", {"kind": "item", "source": "inbox", "n": 12}),
                                          ("my-agenda-2#9999", {"kind": "item", "source": "my-agenda-2", "n": 9999}),
                                          ("created:7", {"kind": "created", "pending": 7}), ("created:123456789", {"kind": "created", "pending": 123456789})])
def test_a_reference_is_a_source_id_and_a_number_or_the_number_of_a_card(value, parts):
    assert item_refs.parse(value) == parts


@pytest.mark.parametrize("value", [None, 5, "", "inbox", "#3", "inbox#", "inbox#x", "inbox# 3", "inbox #3", "Inbox#3", "inbox#-1", "inbox#+1", "inbox#1.5",
                                   "inbox#12345", "inbox#3#4", "inbox/3", "in box#3", "-inbox#3", "inbox#٣", "created:", "created:0", "created:-1",
                                   "created: 3", "created:3a", "created:1234567890", "Created:3", "x" * 41 + "#1", "inbox#3;rm", "../inbox#3"])
def test_a_text_that_is_not_in_the_grammar_is_malformed_and_its_sentence_shows_it_on_one_short_line(value):
    with pytest.raises(item_refs.ItemRefError) as why:
        item_refs.parse(value)
    assert why.value.code in ("malformed",), value
    assert "\n" not in str(why.value) and "inbox#3" in str(why.value) and len(str(why.value)) < 300


def test_number_zero_has_its_own_sentence_and_a_leading_zero_is_not_a_number():
    with pytest.raises(item_refs.ItemRefError) as zero:
        item_refs.parse("inbox#0")
    assert zero.value.code == "zero" and "start at 1" in str(zero.value) and "inbox#1" in str(zero.value)
    with pytest.raises(item_refs.ItemRefError) as zeros:
        item_refs.parse("inbox#000")
    assert zeros.value.code == "zero"
    with pytest.raises(item_refs.ItemRefError) as padded:
        item_refs.parse("inbox#03")
    assert padded.value.code == "malformed" and "inbox#3" in str(padded.value)


# --- a message ----------------------------------------------------------------------------------------------------------------------------


def test_a_reference_to_a_message_gives_its_entry_from_the_index_of_the_newest_version(desk):
    got = resolve(desk, "inbox#1")
    assert (got["kind"], got["source"], got["type"], got["version"], got["n"], got["count"]) == ("item", "inbox", "mail", 1, 1, 3)
    assert got["read_at"] == "2026-10-17T10:12:00Z" and got["age"] == 0
    assert got["entry"] == {"n": 1, "id": "m1", "thread_id": "t1", "message_id": "<a1@clinic.example>", "from_address": "ana@clinic.example",
                            "reply_to_address": "desk@clinic.example", "subject": "Appointment confirmed", "change_key": None}
    second = resolve(desk, "inbox#2")["entry"]
    assert (second["id"], second["from_address"], second["subject"], second["reply_to_address"]) == ("m2", "bob@shop.example", "Your order", None)
    assert resolve(desk, "inbox#3")["entry"]["id"] == "m3"


def test_the_number_is_the_number_the_text_prints_not_a_place_in_the_providers_list(desk):
    desk.providers.mail["gmail"] = [tsm.message(1, "2026-10-15T08:00:00Z", subject="Oldest"), tsm.message(2, "2026-10-17T09:00:00Z", subject="Newest")]
    desk.later(hours=1)
    desk.refresh("inbox")
    text_ = desk.text("inbox")
    assert text_.index("Subject: Newest") < text_.index("Subject: Oldest")
    assert resolve(desk, "inbox#1")["entry"]["id"] == "m2" and resolve(desk, "inbox#2")["entry"]["id"] == "m1"


def test_a_message_left_out_for_a_credential_shifts_nothing_wrongly(desk):
    desk.providers.mail["gmail"] = [tsm.message(4, "2026-10-17T09:00:00Z", subject="One"),
                                    tsm.message(5, "2026-10-16T09:00:00Z", subject="Key", text=f"my key {tsm.KEY}"), tsm.message(6, "2026-10-15T09:00:00Z", subject="Three")]
    desk.later(hours=1)
    desk.refresh("inbox")
    assert [resolve(desk, f"inbox#{n}")["entry"]["id"] for n in (1, 2)] == ["m4", "m6"]
    assert refused(desk, "inbox#3").code == "past_end"


def test_only_the_newest_version_is_read(desk):
    assert resolve(desk, "inbox#1")["version"] == 1
    desk.providers.mail["gmail"] = [tsm.message(9, "2026-10-17T11:00:00Z", subject="Brand new")]
    desk.later(hours=2)
    desk.refresh("inbox")
    got = resolve(desk, "inbox#1")
    assert got["version"] == 2 and got["entry"]["id"] == "m9" and got["count"] == 1
    assert refused(desk, "inbox#2").code == "past_end", "the first version's second message is gone"


def test_no_provider_is_called_to_resolve_a_reference(desk):
    calls = len(desk.providers.calls)
    resolve(desk, "inbox#1")
    resolve(desk, "agenda#1")
    refused(desk, "inbox#9")
    assert len(desk.providers.calls) == calls


# --- an event -----------------------------------------------------------------------------------------------------------------------------


def test_a_reference_to_an_event_gives_its_entry_in_the_order_the_text_lists_them(desk):
    first, second = resolve(desk, "agenda#1"), resolve(desk, "agenda#2")
    assert (first["type"], first["count"], first["entry"]["id"], first["entry"]["recurring"], first["entry"]["calendar"]) == ("calendar", 2, "e1", False, "primary")
    assert (second["entry"]["id"], second["entry"]["etag"], second["entry"]["organizer_self"], second["entry"]["recurring"], second["entry"]["attendees_other"]) == (
        "e2", '"etag2"', True, True, None)
    assert sorted(first["entry"]) == sorted(item_refs.INDEX_KEYS["calendar"])


# --- refusals ---------------------------------------------------------------------------------------------------------------------------


def test_a_number_past_the_end_names_the_count_and_the_reading_time(desk):
    why = refused(desk, "inbox#4")
    assert why.code == "past_end" and "inbox has 3 items" in str(why) and "2026-10-17T10:12:00Z" in str(why) and "inbox#4 does not exist" in str(why)
    assert "has 2 items" in str(refused(desk, "agenda#3"))
    desk.providers.mail["gmail"] = [tsm.message(1)]
    desk.later(hours=1)
    desk.refresh("inbox")
    assert "has 1 item in" in str(refused(desk, "inbox#2"))


def test_a_source_that_is_not_a_mail_or_calendar_source_is_refused(desk, tmp_path):
    (tmp_path / "notes.txt").write_text("a\n", encoding="utf-8")
    sources.import_version(desk.ctx, sources.register(desk.ctx, "notes", "file", "notes.txt"), str(tmp_path / "notes.txt"), convert=standin_convert)
    why = refused(desk, "notes#1")
    assert why.code == "not_snapshot" and "notes is not a mail or calendar source" in str(why)


def test_an_unknown_source_is_refused_and_a_source_with_no_snapshot_says_to_refresh_it(desk):
    why = refused(desk, "nothing#1")
    assert why.code == "no_source" and "no source nothing" in str(why)
    sources.register(desk.ctx, "later", "mail", "gmail:box=starred;days=3;max=10")
    why = refused(desk, "later#1")
    assert why.code == "no_version" and "refresh later first" in str(why)


def test_the_kinds_a_caller_accepts_are_checked_before_anything_is_read(desk):
    why = refused(desk, "agenda#1", kinds=("mail",))
    assert why.code == "wrong_kind" and "agenda is a calendar source" in str(why) and "needs mail" in str(why)
    assert refused(desk, "inbox#1", kinds=("calendar",)).code == "wrong_kind"
    assert resolve(desk, "inbox#1", kinds=("mail",))["entry"]["id"] == "m1" and resolve(desk, "agenda#1", kinds=("mail", "calendar"))["type"] == "calendar"


def test_a_snapshot_older_than_26_hours_is_refused_with_refresh_first_and_a_refresh_makes_it_good_again(desk):
    assert item_refs.REF_MAX_AGE == sources.SNAPSHOT_MAX_AGE == 26 * 3600
    desk.now = NOW + datetime.timedelta(hours=26)
    assert resolve(desk, "inbox#1")["age"] == 26 * 3600, "exactly 26 hours is still good, as for a task (limit L53)"
    desk.now = NOW + datetime.timedelta(hours=26, seconds=1)
    why = refused(desk, "inbox#1")
    assert why.code == "stale" and "refresh inbox first" in str(why) and "2026-10-17T10:12:00Z" in str(why) and "26 hours" in str(why)
    assert refused(desk, "agenda#1").code == "stale"
    assert refused(desk, "inbox#0").code == "zero", "a malformed reference is refused first, whatever the age"
    assert refused(desk, "inbox#99").code == "stale", "an old snapshot is refused before its count is told"
    desk.refresh("inbox")
    assert resolve(desk, "inbox#1")["version"] == 2


def test_a_reading_time_in_the_future_cannot_be_trusted(desk):
    desk.now = NOW - datetime.timedelta(hours=2)
    assert refused(desk, "inbox#1").code == "stale"


def test_a_version_made_before_the_index_existed_is_refused_with_refresh_first(desk):
    rewrite_manifest(desk, "inbox", lambda m: m.pop("index"))
    why = refused(desk, "inbox#1")
    assert why.code == "no_index" and "refresh inbox first" in str(why)
    rewrite_manifest(desk, "agenda", lambda m: m.update(index="not a list"))
    assert refused(desk, "agenda#1").code == "no_index"


def test_an_index_that_does_not_match_the_version_is_refused(desk):
    rewrite_manifest(desk, "inbox", lambda m: m["index"].pop())
    assert refused(desk, "inbox#1").code == "integrity", "the index must count the items the manifest says the text lists"
    rewrite_manifest(desk, "agenda", lambda m: m["index"].reverse())
    assert refused(desk, "agenda#1").code == "integrity", "an entry must carry its own place"
    desk.later(hours=1)
    desk.refresh("inbox")
    rewrite_manifest(desk, "inbox", lambda m: m.update(version=1))
    assert refused(desk, "inbox#1").code == "integrity", "the manifest of another version"
    desk.later(hours=1)
    desk.refresh("inbox")
    rewrite_manifest(desk, "inbox", lambda m: m["converted"].update(sha256="0" * 64))
    assert refused(desk, "inbox#1").code == "integrity"


def test_a_text_changed_outside_the_runtime_is_refused(desk):
    version = desk.folder / "inbox" / "1"
    version.chmod(0o700)
    (version / "converted.md").chmod(0o600)
    (version / "converted.md").write_text("## 1. tampered\n", encoding="utf-8")
    why = refused(desk, "inbox#1")
    assert why.code == "integrity" and "refresh inbox first" in str(why)


def test_a_manifest_that_is_not_json_or_not_an_object_is_refused(desk):
    folder = desk.folder / "inbox" / "1"
    folder.chmod(0o700)
    (folder / "manifest.json").chmod(0o600)
    (folder / "manifest.json").write_text("{not json", encoding="utf-8")
    assert refused(desk, "inbox#1").code == "integrity"
    (folder / "manifest.json").write_text("[1, 2]", encoding="utf-8")
    assert refused(desk, "inbox#1").code == "integrity"
    (folder / "manifest.json").unlink()
    assert refused(desk, "inbox#1").code == "integrity"


def test_an_index_edited_outside_the_runtime_is_read_back_through_the_closed_shapes(desk):
    def hostile(manifest):
        first = manifest["index"][0]
        first.update(id="../../etc/passwd", thread_id="a b", message_id="<a b>", from_address="x y@z", reply_to_address="evil@evil.example\nBcc: boss@x.example",
                     subject="line one\nline two", change_key="with space", extra="not a key")
        manifest["index"][1].update(subject="x" * 500, id="m2")
    rewrite_manifest(desk, "inbox", hostile)
    first = resolve(desk, "inbox#1")["entry"]
    assert first == {"n": 1, "id": None, "thread_id": None, "message_id": None, "from_address": None, "reply_to_address": None, "subject": "", "change_key": None}
    assert len(resolve(desk, "inbox#2")["entry"]["subject"]) == 120
    assert resolve(desk, "inbox#3")["entry"]["id"] == "m3"


def test_the_folder_must_still_be_the_projects_sources_folder(desk):
    desk.folder.chmod(0o755)
    with pytest.raises(sources.SourcesError):
        resolve(desk, "inbox#1")
    desk.folder.chmod(0o700)
    assert resolve(desk, "inbox#1")["entry"]["id"] == "m1"


# --- an event the runtime created ----------------------------------------------------------------------------------------------------------


def test_a_reference_to_a_created_event_is_resolved_by_the_function_the_calendar_path_gives(desk):
    seen = []

    def created(ctx, pending):
        seen.append((ctx is desk.ctx, pending))
        return {"id": "evt1", "etag": '"abc"', "calendar": "primary"} if pending == 7 else None
    got = resolve(desk, "created:7", created=created)
    assert got == {"kind": "created", "pending": 7, "type": "calendar", "entry": {"id": "evt1", "etag": '"abc"', "calendar": "primary"}} and seen == [(True, 7)]
    why = refused(desk, "created:8", created=created)
    assert why.code == "created_unknown" and "card 8 did not create an event" in str(why)


def test_a_reference_to_a_created_event_needs_the_function_and_a_caller_that_takes_calendar_items(desk):
    why = refused(desk, "created:7")
    assert why.code == "created_unavailable" and "calendar operations" in str(why)
    assert refused(desk, "created:7", kinds=("mail",), created=lambda ctx, pending: {"id": "x"}).code == "wrong_kind"
    assert len(desk.providers.calls) == 2, "only the two snapshots of the fixture read a provider"


# --- where the module may reach ---------------------------------------------------------------------------------------------------------------


def test_the_module_names_no_provider_class_and_no_provider_path_and_calls_no_provider():
    source = (st.RUNTIME / "item_refs.py").read_text(encoding="utf-8")
    for forbidden in ("reader:email", "integration:calendar", "sender:email", "writer:", "providers/", "resolve.py", "workbench_sources_resolve", "subprocess", "urllib", "socket"):
        assert forbidden not in source, forbidden
    assert "import sources" in source and os.path.basename(item_refs.__file__) == "item_refs.py"
