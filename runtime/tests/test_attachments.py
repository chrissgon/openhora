"""The files a listed sender sends through a messaging app (package ATT-1, runtime part): the limits and sentences of runtime/attachments.py, the folders
where a file waits, and the operations of runtime/ops_attachments.py against the real operations layer and a real store: hold, add, discard, the limits of
the day and of the hold, the grant that adds without a card, the provenance a version keeps and the sender's id that no file of the project ever holds.
The converter is a stand-in that reads the files the builders of sources_fixture.py make; no network, no model, no messenger. Every name and id is invented.
The bridge's side (the update, the fetch, the card) is in test_messaging_attach.py.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_attachments.py
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

import standin_tree as st
from sources_fixture import make_docx, make_pdf, make_xlsx, standin_convert, with_sources

ops = st.load("ops")
ops_core = st.load("ops_core")
operations = st.load("operations")
sources = st.load("sources")
attachments = st.load("attachments")
project_config = st.load("project_config")

REPO = st.REPO
IDENT = "4242424242"
SENDER = f"telegram:{IDENT}"
OTHER = "5151515151"
POLICIES = {"staff": ["read", "add-sources"], "desk": ["read", "add-sources-direct"], "reader": ["read"]}


def fake_key() -> str:
    """A string the credential scan reads as a key, made here so that no such string sits in the repository."""
    return "sk-" + "ant-" + "api03-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"


def accept(path, **keys):
    """Write the keys into the project's runtime.json and accept the file as the person does: read `config`, type the hash of its widening list."""
    file = Path(path) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(file.read_text())
    raw.update(keys)
    file.write_text(json.dumps(raw))
    shown = ops.config(path)
    return ops.accept_config(path, shown["sha256"], widen=shown["widening_sha256"])


@pytest.fixture
def case(tmp_path, monkeypatch):
    """A project with its configuration accepted: the sender IDENT is listed on telegram with the profile `staff` (read and add-sources), the converter is
    the stand-in. Returns a namespace with the project's path, its context, and helpers: `fetch(data)` makes an incoming folder holding the file as a
    provider leaves it, `hold(data, ...)` calls attachment-hold as the bridge does, `rows()` the store's attachments."""
    monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(tmp_path / "evidence"))
    project = tmp_path / "project"
    (project / "docs" / "workbench").mkdir(parents=True)
    config = with_sources({"workbench": str(REPO), "data_dir": str(tmp_path / "data"), "store_db": str(tmp_path / "store" / "tasks.sqlite")}, tmp_path)
    (project / "docs" / "workbench" / "runtime.json").write_text(json.dumps(config), encoding="utf-8")
    path = str(project)
    ops.accept_config(path, project_config.load(path)["sha256"])
    accept(path, policies=POLICIES, channels={"messaging": "staff"}, messaging={"senders": {"telegram": [IDENT]}})
    monkeypatch.setattr(sources, "provider_convert", lambda cfg, call=None: standin_convert)
    ctx = ops_core.context(path)
    counter = iter(range(1, 10000))
    c = SimpleNamespace(path=path, ctx=ctx, cfg=ctx["cfg"], data=Path(ctx["cfg"]["data_dir"]), folder=Path(ctx["cfg"]["sources_dir"]), tmp=tmp_path)

    def fetch(data):
        token, folder = attachments.make_incoming(c.cfg["data_dir"])
        Path(folder, "content").write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return token

    def hold(data, name="Q3 plan.pdf", declared="application/pdf", ref=None, target=None, direct=False, sender=SENDER, declared_bytes=None):
        return ops.attachment_hold(path, fetch(data), "telegram", ref or f"ref-{next(counter)}", name, declared, declared_bytes, target, direct,
                                   channel="messaging", sender=sender)
    c.fetch, c.hold = fetch, hold
    c.rows = lambda *statuses: ctx["store"].attachments_list(ctx["conn"], list(statuses) or None)
    c.tree = lambda base: sorted(str(p.relative_to(base)) for p in Path(base).rglob("*"))
    return c


PDF = make_pdf("The Q3 plan: grow the newsletter by a third.")


# --- the limits and the sentences are constants ------------------------------------------------------------------------------------


def test_the_numbers_are_fixed_in_code():
    assert attachments.FILE_CAP == sources.ORIGINAL_CAP == 25 * 1024 * 1024
    assert (attachments.DAY_FILES, attachments.DAY_BYTES) == (20, 100 * 1024 * 1024)
    assert (attachments.HELD_MAX, attachments.PER_MESSAGE, attachments.HELD_DAYS) == (10, 5, 7)
    assert attachments.NAME_MAX == 100 and attachments.INCOMING_KEPT_SECONDS == 24 * 3600


def test_the_sentences_are_the_ones_the_spec_names():
    a = attachments
    assert a.OFF == "Files are not taken from this app for this project. Add it on the page or in the terminal (source-import)."
    assert a.MEDIA == ("Voice notes, videos, audio and stickers are not taken yet, and neither are images other than PNG, JPEG, WebP, GIF or HEIC. Send a photo or an image of "
                       "those types to save it to Drive or OneDrive, or a PDF, a Word document, a spreadsheet, a presentation, an HTML page or a text file to add it to the project.")
    assert a.IMAGE_NOT_SOURCE == "Images are not added to the project; I can save them to Drive or OneDrive."
    assert a.TOO_LARGE.format(name="a.pdf", size="30.0 MiB", cap="25.0 MiB") == "a.pdf is 30.0 MiB; a file from this app is at most 25.0 MiB."
    assert a.DAY.format(n=20, size="80.0 MiB") == ("This project took 20 files (80.0 MiB) from messaging apps today, its limit. "
                                                    "Send it again tomorrow, or add it on the page.")
    assert a.HELD_FULL.format(n=10) == "10 files wait for your answer already. Answer them first (/pending)."
    assert a.GONE.format(platform="telegram") == "That file can no longer be fetched from telegram. Send it again."
    assert a.MISMATCH.format(name="a.pdf", declared="application/pdf", sniffed="Word document") == (
        "a.pdf says it is a application/pdf and its bytes are a Word document, so it was not taken.")
    assert a.REFUSED.format(name="a.docx", reason="it holds what looks like a credential") == (
        "a.docx was not added and was deleted: it holds what looks like a credential.")
    assert a.CAPTION_IGNORED == "The text sent with a file is read only as a request to save it; use the buttons on its card for anything else."


def test_a_size_is_said_in_binary_units_and_a_name_is_cleaned_and_cut():
    assert [attachments.size_text(n) for n in (0, 812, 1024, 3584, 12 * 1024 * 1024)] == ["0 bytes", "812 bytes", "1.0 KiB", "3.5 KiB", "12.0 MiB"]
    clean = attachments.clean_name
    assert clean("Q3 plan.pdf") == "Q3 plan.pdf" and clean("../../etc/passwd") == "passwd" and clean("C:\\Users\\x\\plan.pdf") == "plan.pdf"
    assert clean("a\x00b\x1b[31m\nc.pdf") == "a b [31m c.pdf" and clean("") == "file" and clean(None) == "file" and clean(" \x00 ") == "file"
    assert clean("plan\u202egpj.exe") == "plan gpj.exe", "a bidirectional override does not disguise an extension"
    long = clean("x" * 300 + ".pdf")
    assert len(long) == attachments.NAME_MAX and long.endswith(".pdf") and "…" not in long, "cut cleanly, the extension kept, nothing a file name refuses"
    assert clean("drive:abc.pdf") == "file-drive:abc.pdf", "a file source's origin never starts with the Drive prefix"
    assert attachments.stem("Q3 plan.pdf") == "Q3 plan" and attachments.stem("README") == "README" and attachments.stem(".env") == ".env"


def test_only_an_exact_at_id_on_one_file_is_read_from_the_caption():
    read = attachments.caption_target
    assert read("@survey-results", 1) == ("survey-results", False)
    assert read("  @survey-results \n", 1) == ("survey-results", False)
    assert read(None, 1) == (None, False) and read("", 1) == (None, False) and read("   ", 2) == (None, False)
    assert read("@survey-results", 2) == (None, True), "a message of several files names no source"
    for text in ("@Survey", "@survey results", "please add this to @survey", "@survey please", "@", "@-x", "add it", "/pending", "@" + "a" * 41):
        assert read(text, 1) == (None, True), text


def test_what_the_platform_declared_is_checked_before_a_byte_is_fetched():
    check = attachments.declared_problem
    cap = 20 * 1024 * 1024
    for kind in ("voice", "video", "audio", "sticker", "audio/ogg", "video/mp4", "image/svg+xml", "image/tiff", "IMAGE/BMP"):
        assert check({"type": kind, "size": 10}, cap) == {"code": "media"}, kind
    for kind in ("photo", "image/jpeg", "IMAGE/PNG", "image/webp", "image/gif", "image/heic", "image/heif"):
        assert check({"type": kind, "size": 10}, cap) is None, kind          # a save-only image (ATT-3): taken
    assert check({"type": "application/pdf", "size": cap + 1}, cap) == {"code": "too_large", "size": cap + 1}
    assert check({"type": "application/pdf", "size": cap}, cap) is None and check({"type": None, "size": None}, cap) is None
    assert check({"type": "application/pdf", "size": True}, cap) is None, "a boolean is not a size"
    assert attachments.fetch_budget(cap, {"files": 1, "bytes": 0}) == cap
    assert attachments.fetch_budget(cap, {"files": 5, "bytes": attachments.DAY_BYTES - 7}) == 7


def test_a_declared_type_that_names_a_kind_must_be_what_the_bytes_are_and_a_generic_one_goes_by_the_bytes():
    wrong = attachments.mismatch
    assert wrong("application/pdf", "docx") is True and wrong("application/pdf; charset=binary", "pdf") is False
    word = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert wrong(word, "docx") is False and wrong(word, "ooxml") is False and wrong(word, "xlsx") is True and wrong(word, "pdf") is True
    assert wrong("text/plain", "text") is False and wrong("text/plain", "csv") is False and wrong("text/csv", "text") is False
    assert wrong("text/plain", "pdf") is True and wrong("text/html", "docx") is True
    for generic in (None, "", "application/octet-stream", "binary/octet-stream", "application/zip"):
        assert wrong(generic, "pdf") is False, generic
    assert wrong("application/x-unknown-kind", "pdf") is False, "a type the converter does not list is not a contradiction"


def test_the_checks_before_a_fetch_count_the_files_of_the_message_against_the_day_and_the_hold():
    one = lambda n, **k: {"ref": f"r{n}", "name": f"f{n}.pdf", "size": 1000, "type": "application/pdf", **k}   # noqa: E731
    made = attachments.precheck([one(n) for n in range(7)], cap=10 ** 7, today={"files": 0, "bytes": 0}, held=[], platform="telegram")
    assert [bool(d["over"]) for d in made] == [False] * 5 + [True] * 2 and all(d["refuse"] is None for d in made[:5])
    made = attachments.precheck([one(n) for n in range(4)], cap=10 ** 7, today={"files": 18, "bytes": 0}, held=[], platform="telegram")
    assert [d["refuse"] and d["refuse"]["code"] for d in made] == [None, None, "day", "day"], "20 a day, the files of this message counted as they pass"
    made = attachments.precheck([one(0)], cap=10 ** 7, today={"files": 0, "bytes": attachments.DAY_BYTES}, held=[], platform="telegram")
    assert made[0]["refuse"]["code"] == "day"
    held = [{"ref_sha256": "x" * 64, "id": n} for n in range(9)]
    made = attachments.precheck([one(0), one(1)], cap=10 ** 7, today={"files": 0, "bytes": 0}, held=held, platform="telegram")
    assert [d["refuse"] and d["refuse"]["code"] for d in made] == [None, "held_max"], "10 held at most"
    again = [{"ref_sha256": attachments.ref_digest("telegram", "r0"), "id": 77}]
    made = attachments.precheck([one(0), one(0)], cap=10 ** 7, today={"files": 0, "bytes": 0}, held=again, platform="telegram")
    assert made[0]["duplicate"]["id"] == 77 and made[0]["refuse"] is None
    made = attachments.precheck([one(0, type="voice"), one(1, size=10 ** 9)], cap=10 ** 7, today={"files": 0, "bytes": 0}, held=[], platform="telegram")
    assert [d["refuse"]["code"] for d in made] == ["media", "too_large"]


def test_a_card_is_bound_to_the_file_the_source_and_whether_it_is_a_new_source_or_a_refresh():
    sha = "ab" * 32
    one = attachments.card_sha256(sha, "q3-plan", "import")
    assert one == hashlib.sha256(f"attachment\n{sha}\nq3-plan\nimport".encode()).hexdigest()
    assert len({one, attachments.card_sha256(sha, "q3-plan", "refresh"), attachments.card_sha256(sha, "other", "import"),
                attachments.card_sha256("cd" * 32, "q3-plan", "import")}) == 4
    assert attachments.ref_digest("telegram", "abc") != attachments.ref_digest("discord", "abc")


# --- the folders ------------------------------------------------------------------------------------------------------------------


def test_limit_48_a_file_waits_in_private_folders_made_without_following_a_link(tmp_path):
    data = tmp_path / "data"
    token, folder = attachments.make_incoming(str(data))
    assert attachments.TOKEN.fullmatch(token) and folder == str(data / "attachments" / "incoming" / token)
    for part in (data / "attachments", data / "attachments" / "incoming", Path(folder)):
        assert stat.S_IMODE(part.stat().st_mode) == 0o700, part
    assert attachments.incoming_path(str(data), token) == folder
    (Path(folder) / "content").write_bytes(b"x" * 40)
    stream, size = attachments.open_content(folder)
    with stream:
        assert size == 40 and stream.read() == b"x" * 40
    attachments.remove_incoming(str(data), token)
    assert not Path(folder).exists()
    attachments.remove_incoming(str(data), token)       # quiet when it is gone
    for bad in (None, "", "../x", "ABCDEF0123456789", "zz" * 8, token + "0"):
        with pytest.raises(attachments.FolderError):
            attachments.incoming_path(str(data), bad)
    # a link where a folder belongs is refused, and so is a link for the file
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link_data = tmp_path / "linked"
    link_data.mkdir()
    (link_data / "attachments").symlink_to(elsewhere)
    with pytest.raises(attachments.FolderError):
        attachments.make_incoming(str(link_data))
    assert list(elsewhere.iterdir()) == []
    token, folder = attachments.make_incoming(str(data))
    (Path(folder) / "content").symlink_to(tmp_path / "secret.txt")
    (tmp_path / "secret.txt").write_text("not for the hold")
    with pytest.raises(attachments.FolderError):
        attachments.open_content(folder)
    swapped = data / "attachments" / "incoming" / ("0" * 16)
    swapped.symlink_to(elsewhere)
    with pytest.raises(attachments.FolderError):
        attachments.incoming_path(str(data), "0" * 16)


def test_a_held_file_is_moved_into_its_folder_read_back_and_deleted_through_descriptors(tmp_path):
    data = tmp_path / "data"
    _, folder = attachments.make_incoming(str(data))
    (Path(folder) / ".incoming-abc.part").write_bytes(b"held bytes")
    kept = attachments.keep_held(str(data), 7, folder, ".incoming-abc.part")
    assert kept == str(data / "attachments" / "held" / "7" / "original") and Path(kept).read_bytes() == b"held bytes"
    assert stat.S_IMODE(Path(kept).stat().st_mode) == 0o400 and stat.S_IMODE(Path(kept).parent.stat().st_mode) == 0o700
    assert not (Path(folder) / ".incoming-abc.part").exists()
    assert attachments.read_held(str(data), 7) == b"held bytes" and attachments.read_held(str(data), 8) is None
    attachments.delete_held(str(data), 7)
    assert not (data / "attachments" / "held" / "7").exists() and attachments.read_held(str(data), 7) is None
    attachments.delete_held(str(data), 7)               # quiet
    with pytest.raises(attachments.FolderError):
        attachments.keep_held(str(data), 9, folder, "no-such-part")
    assert not (data / "attachments" / "held" / "9").exists(), "nothing is left behind by a failed move"


# --- hold -------------------------------------------------------------------------------------------------------------------------


def test_a_fetched_file_is_held_with_its_type_read_from_its_bytes_and_a_name_that_is_only_a_label(case):
    done = case.hold(PDF, name="../Q3 plan.pdf")
    row = done["attachment"]
    assert done["held"] is True and (row["id"], row["status"], row["kind"], row["name"]) == (1, "held", "pdf", "Q3 plan.pdf")
    assert row["sha256"] == hashlib.sha256(PDF).hexdigest() and row["bytes"] == len(PDF) and row["profile"] == "staff"
    assert (done["target"], done["label"], done["next_version"]) == ("q3-plan", "import", 1)
    assert done["card_sha256"] == attachments.card_sha256(row["sha256"], "q3-plan", "import")
    assert "sender" not in row and IDENT not in json.dumps(done), "a shell never reads the sender's id"
    held = case.data / "attachments" / "held" / "1" / "original"
    assert held.read_bytes() == PDF and stat.S_IMODE(held.stat().st_mode) == 0o400, "the extension comes from the sniffed kind, never the name"
    assert case.tree(case.data / "attachments" / "incoming") == [], "the incoming folder is removed"
    assert case.tree(case.folder) == [".openhora-sources"], "nothing reaches the sources folder before an add"
    stored = case.rows()[0]
    assert stored["sender"] == IDENT and stored["platform"] == "telegram" and stored["ref_sha256"] == attachments.ref_digest("telegram", "ref-1", IDENT)
    assert "ref-1" not in json.dumps(stored), "the platform's reference is never stored"
    listed = ops.attachments(case.path)
    assert [h["id"] for h in listed["held"]] == [1] and listed["today"] == {"files": 1, "bytes": len(PDF)} and IDENT not in json.dumps(listed)
    assert listed["limits"]["held_max"] == 10 and listed["held"][0]["expires_at"].startswith(("20", "21"))


def test_the_same_reference_twice_is_one_file_and_the_second_answers_with_its_id(case):
    case.hold(PDF, ref="same")
    with pytest.raises(ops.OpsError, match="Q3 plan.pdf already waits for your answer \\(file 1\\)"):
        case.hold(PDF, ref="same")
    assert [(r["status"], r["code"]) for r in case.rows()] == [("held", None), ("refused", "duplicate")], "the second fetch happened, so it counts"
    assert case.tree(case.data / "attachments" / "incoming") == []
    assert case.hold(PDF, ref="another")["attachment"]["id"] == 3


def test_a_declared_type_that_the_bytes_contradict_is_refused_and_still_counts_for_the_day(case):
    with pytest.raises(ops.OpsError, match="says it is a application/pdf and its bytes are a Word document, so it was not taken"):
        case.hold(make_docx(["a paragraph"]))
    rows = case.rows()
    assert [(r["status"], r["code"], r["kind"]) for r in rows] == [("refused", "mismatch", "docx")]
    assert ops.attachments(case.path)["today"]["files"] == 1 and not (case.data / "attachments" / "held").exists()
    assert case.hold(make_docx(["a paragraph"]), name="a.docx", declared="application/octet-stream")["attachment"]["kind"] == "docx"


def test_a_type_that_is_not_read_is_refused_with_the_intakes_sentence_and_nothing_is_kept(case):
    with pytest.raises(ops.OpsError, match="was not added and was deleted: .*not read"):
        case.hold(b"\x00\x00\x00\x18ftypavif\x00\x00\x00\x00avifmif1miaf" + b"\x00" * 32, name="photo.avif", declared=None)
    assert [(r["status"], r["code"]) for r in case.rows()] == [("refused", "type")]
    assert not (case.data / "attachments" / "held").exists()


def test_the_day_and_the_hold_are_limits_the_operation_keeps_even_when_the_bridge_did_not_check(case, monkeypatch):
    monkeypatch.setattr(attachments, "HELD_MAX", 2)
    case.hold(PDF)
    case.hold(PDF)
    with pytest.raises(ops.OpsError, match="2 files wait for your answer already. Answer them first \\(/pending\\)."):
        case.hold(PDF)
    assert [r["status"] for r in case.rows()] == ["held", "held", "refused"]
    monkeypatch.setattr(attachments, "HELD_MAX", 10)
    monkeypatch.setattr(attachments, "DAY_FILES", 3)
    with pytest.raises(ops.OpsError, match="took 3 files .* from messaging apps today, its limit. Send it again tomorrow, or add it on the page"):
        case.hold(PDF)


def test_the_day_is_the_utc_day_so_yesterday_s_files_do_not_count(case, monkeypatch):
    import datetime
    case.hold(PDF)
    monkeypatch.setattr(attachments, "DAY_FILES", 1)
    with pytest.raises(ops.OpsError, match="its limit"):
        case.hold(PDF)
    tomorrow = attachments.utcnow() + datetime.timedelta(days=1)
    monkeypatch.setattr(attachments, "utcnow", lambda: tomorrow)
    assert case.hold(PDF)["attachment"]["id"] == 3


def test_the_id_of_a_source_comes_from_the_name_unless_the_caption_named_one_and_never_reuses_a_held_name(case):
    assert case.hold(PDF, name="Survey results.pdf")["target"] == "survey-results"
    assert case.hold(PDF, name="Survey results.pdf")["target"] == "survey-results-2", "a second held file of the same name is another source"
    assert case.hold(PDF, name="x.pdf", target="board-notes")["target"] == "board-notes"
    assert case.hold(PDF, name="!!!.pdf")["target"] == "file"
    ops.source_add(case.path, "survey-results-2", "file", "survey.csv")
    assert case.hold(PDF, name="Survey results.pdf")["target"] == "survey-results-3"


def test_a_caption_that_names_a_source_of_another_type_is_refused_and_a_registered_file_source_is_refreshed(case):
    ops.source_add(case.path, "board-notes", "notion", "0123456789abcdef0123456789abcdef")
    with pytest.raises(ops.OpsError, match="`board-notes` is a notion source: a file cannot be added to it"):
        case.hold(PDF, target="board-notes")
    assert [(r["status"], r["code"]) for r in case.rows()] == [("refused", "target")]
    ops.source_add(case.path, "q3-plan", "file", "q3.pdf")
    first = case.hold(PDF, target="q3-plan")
    assert (first["target"], first["label"], first["next_version"]) == ("q3-plan", "import", 1), "a registered source with no version is imported"
    ops.attachment_add(case.path, first["attachment"]["id"], channel="messaging", sender=SENDER)
    second = case.hold(make_pdf("The Q3 plan, second draft."), target="q3-plan")
    assert (second["label"], second["next_version"]) == ("refresh", 2)


def test_a_file_the_operation_was_not_given_is_gone_and_a_channel_other_than_messaging_cannot_hold(case):
    with pytest.raises(ops.OpsError, match="That file can no longer be fetched from telegram. Send it again."):
        ops.attachment_hold(case.path, "0123456789abcdef", "telegram", "r", "a.pdf", None, None, None, False, channel="messaging", sender=SENDER)
    token = case.fetch(PDF)
    for channel in (None, "page", "terminal", "chat", "mcp"):
        with pytest.raises(ops.OpsError, match="the messaging bridge's call"):
            ops.attachment_hold(case.path, token, "telegram", "r", "a.pdf", None, None, None, False, channel=channel, sender=SENDER)
    with pytest.raises(ops.OpsError, match="the sender's own"):
        ops.attachment_hold(case.path, token, "discord", "r", "a.pdf", None, None, None, False, channel="messaging", sender=SENDER)
    with pytest.raises(ops.OpsError):
        ops.attachment_hold(case.path, token, "telegram", "r", "a.pdf", None, None, None, False, channel="messaging", sender=None)
    assert case.rows() == []


def test_a_provider_that_left_no_file_or_a_link_holds_nothing(case):
    token, folder = attachments.make_incoming(case.cfg["data_dir"])
    with pytest.raises(ops.OpsError, match="can no longer be fetched"):
        ops.attachment_hold(case.path, token, "telegram", "r", "a.pdf", None, None, None, False, channel="messaging", sender=SENDER)
    assert not Path(folder).exists(), "the incoming folder is removed whatever happens"
    token, folder = attachments.make_incoming(case.cfg["data_dir"])
    Path(case.tmp, "outside.pdf").write_bytes(PDF)
    os.symlink(Path(case.tmp, "outside.pdf"), Path(folder, "content"))
    with pytest.raises(ops.OpsError, match="can no longer be fetched"):
        ops.attachment_hold(case.path, token, "telegram", "r", "a.pdf", None, None, None, False, channel="messaging", sender=SENDER)
    assert case.rows() == []


# --- add and discard --------------------------------------------------------------------------------------------------------------


def test_adding_a_held_file_makes_version_1_with_a_provenance_and_no_sender_anywhere_and_the_held_file_is_gone(case):
    done = case.hold(PDF)
    added = ops.attachment_add(case.path, done["attachment"]["id"], channel="messaging", sender=SENDER)
    assert (added["added"], added["imported"], added["source"], added["version"], added["label"]) == (True, True, "q3-plan", 1, "import")
    assert added["reply"].splitlines()[0] == "Added Q3 plan.pdf as `q3-plan`, version 1."
    assert added["reply"].splitlines()[1:] == [f"Note: {w}" for w in added["warnings"]], "a warning the import made is told, in its own words"
    store, conn = case.ctx["store"], case.ctx["conn"]
    version = store.source_latest(conn, "q3-plan")
    came = {"channel": "messaging", "platform": "telegram", "profile": "staff", "attachment": 1}
    assert version["provenance"] == came and version["by"] == "runtime" and version["label"] == "import"
    assert store.source_get(conn, "q3-plan")["origin"] == "Q3 plan.pdf"
    manifest = json.loads((case.folder / "q3-plan" / "1" / "manifest.json").read_text())
    assert manifest["provenance"] == came
    assert version["catalog"]["provenance"] == "sent on telegram, profile staff"
    catalog = ops.sources_catalog(case.path)["sources"][0]
    assert catalog["catalog"]["provenance"] == "sent on telegram, profile staff"
    assert "provenance: sent on telegram, profile staff" in sources.catalog_text(sources.list_catalog(case.ctx, hashes=False))
    row = case.rows()[0]
    assert (row["status"], row["source_id"], row["version"], row["sender"]) == ("added", "q3-plan", 1, IDENT)
    assert not (case.data / "attachments" / "held" / "1").exists(), "the held file is deleted"
    for base in (case.folder, Path(case.path)):
        for file in (p for p in base.rglob("*") if p.is_file() and p.name != "runtime.json"):    # the person's own configuration lists the sender, by design
            assert IDENT.encode() not in file.read_bytes(), f"{file}: the sender's id is in the store only"
    assert IDENT not in json.dumps(catalog) and IDENT not in json.dumps(ops.attachments(case.path))
    assert ops.attachments(case.path)["held"] == [] and [r["status"] for r in ops.attachments(case.path)["recent"]] == ["added"]


def test_a_caption_that_names_a_source_makes_the_next_version_labelled_refresh(case):
    ops.attachment_add(case.path, case.hold(PDF, name="Plan v1.pdf")["attachment"]["id"], channel="messaging", sender=SENDER)
    done = case.hold(make_pdf("The plan, revised."), name="Plan v2.pdf", target="plan-v1")
    assert done["label"] == "refresh" and done["next_version"] == 2
    added = ops.attachment_add(case.path, done["attachment"]["id"], channel="messaging", sender=SENDER)
    assert (added["version"], added["label"]) == (2, "refresh")
    assert case.ctx["store"].source_latest(case.ctx["conn"], "plan-v1")["label"] == "refresh"
    assert [v["provenance"]["attachment"] for v in case.ctx["store"].source_versions(case.ctx["conn"], "plan-v1")] == [1, 2]


def test_the_same_bytes_again_change_nothing_and_say_so(case):
    ops.attachment_add(case.path, case.hold(PDF)["attachment"]["id"], channel="messaging", sender=SENDER)
    done = case.hold(PDF, target="q3-plan")
    added = ops.attachment_add(case.path, done["attachment"]["id"], channel="messaging", sender=SENDER)
    assert added["imported"] is False and added["version"] == 1
    assert added["reply"] == "Q3 plan.pdf is already the newest version of `q3-plan` (version 1): nothing changed."
    assert case.ctx["store"].source_version_count(case.ctx["conn"], "q3-plan") == 1


def test_a_spreadsheet_a_document_and_text_become_sources_like_a_file_of_the_person(case):
    sheet = make_xlsx([("Q3", [["region", "sales"], ["north", "12"]])])
    for data, name in ((sheet, "Sales.xlsx"), (make_docx(["Notes of the call"]), "Call notes.docx"), (b"name,price\napple,1\npear,3\nplum,5\n", "prices.csv")):
        added = ops.attachment_add(case.path, case.hold(data, name=name, declared=None)["attachment"]["id"], channel="messaging", sender=SENDER)
        assert added["version"] == 1, name
    assert [s["id"] for s in ops.sources_catalog(case.path)["sources"]] == ["call-notes", "prices", "sales"]


def test_a_credential_in_the_converted_text_refuses_the_file_deletes_it_and_ends_the_row_refused(case):
    done = case.hold(make_pdf(f"The key is {fake_key()} and must not travel."), name="keys.pdf")
    with pytest.raises(ops.OpsError) as caught:
        ops.attachment_add(case.path, done["attachment"]["id"], channel="messaging", sender=SENDER)
    assert str(caught.value) == "keys.pdf was not added and was deleted: it holds what looks like a credential."
    assert fake_key() not in str(caught.value)
    row = case.rows()[0]
    assert (row["status"], row["code"], row["source_id"]) == ("refused", "credential", None)
    assert not (case.data / "attachments" / "held" / "1").exists()
    assert [s for s in sources.list_catalog(case.ctx, hashes=False) if s["version"]] == [], "no version was made"
    assert not (case.folder / "keys").exists() and not (case.folder / "keys-pdf").exists()


def test_a_file_the_converter_cannot_read_is_refused_and_deleted_but_a_machine_that_is_not_set_up_leaves_it_held(case, monkeypatch):
    done = case.hold(PDF)

    def broken(cfg, call=None):
        def convert(*args):
            raise sources.SourcesError("the converter failed (failed): the document is broken", "convert")      # the provider's exit 4: the content is refused
        return convert
    monkeypatch.setattr(sources, "provider_convert", broken)
    with pytest.raises(ops.OpsError, match="was not added and was deleted: it could not be read as a document"):
        ops.attachment_add(case.path, done["attachment"]["id"], channel="messaging", sender=SENDER)
    assert case.rows()[0]["code"] == "convert" and not (case.data / "attachments" / "held" / "1").exists()
    second = case.hold(PDF)

    for kind in ("not-configured", "failed", "timeout"):          # whatever the machine did: docker down, a hiccup, a timeout; none is the file's doing
        def not_set_up(cfg, call=None, kind=kind):
            def convert(*args):
                raise sources.SourcesError(f"the converter failed ({kind}): docker is not running", "converter")
            return convert
        monkeypatch.setattr(sources, "provider_convert", not_set_up)
        with pytest.raises(ops.OpsError, match="docker is not running") as caught:
            ops.attachment_add(case.path, second["attachment"]["id"], channel="messaging", sender=SENDER)
        assert caught.value.phone == attachments.MACHINE and "docker" not in caught.value.phone
        assert case.rows()[1]["status"] == "held" and (case.data / "attachments" / "held" / "2" / "original").is_file()


def test_a_held_file_that_changed_or_vanished_on_this_machine_is_refused(case):
    first, second = case.hold(PDF), case.hold(make_pdf("Another file"), name="b.pdf")
    path = case.data / "attachments" / "held" / "1"
    os.chmod(path / "original", 0o600)
    (path / "original").write_bytes(PDF + b"tampered")
    with pytest.raises(ops.OpsError, match="it changed on this machine while it waited"):
        ops.attachment_add(case.path, first["attachment"]["id"], channel="messaging", sender=SENDER)
    assert case.rows()[0]["code"] == "changed" and not path.exists()
    attachments.delete_held(case.cfg["data_dir"], 2)
    with pytest.raises(ops.OpsError, match="The held file is gone from this machine. Send it again."):
        ops.attachment_add(case.path, second["attachment"]["id"], channel="messaging", sender=SENDER)
    assert case.rows()[1]["code"] == "lost"


def test_the_source_a_file_would_be_added_to_is_looked_at_again_when_it_is_added(case):
    done = case.hold(PDF, name="Report.pdf")
    ops.source_add(case.path, "report", "file", "report.csv")
    store, conn = case.ctx["store"], case.ctx["conn"]
    sources.import_version(case.ctx, store.source_get(conn, "report"), b"a,b\n1,2\n3,4\n5,6\n", convert=standin_convert)
    with pytest.raises(ops.OpsError, match="The source `report` changed since this file arrived. Discard it \\(/discard 1\\) and send it again."):
        ops.attachment_add(case.path, done["attachment"]["id"], channel="messaging", sender=SENDER)
    assert case.rows()[0]["status"] == "held", "nothing was decided, the person can discard it"


def test_a_held_file_expires_after_seven_days_when_someone_tries_to_add_it_and_the_upkeep_is_not_needed(case, monkeypatch):
    import datetime
    done = case.hold(PDF)
    later = attachments.utcnow() + datetime.timedelta(days=attachments.HELD_DAYS, minutes=1)
    monkeypatch.setattr(attachments, "utcnow", lambda: later)
    with pytest.raises(ops.OpsError, match="Q3 plan.pdf waited more than 7 days and was deleted. Send it again."):
        ops.attachment_add(case.path, done["attachment"]["id"], channel="messaging", sender=SENDER)
    assert case.rows()[0]["status"] == "expired" and not (case.data / "attachments" / "held" / "1").exists()


def test_a_discard_deletes_the_file_and_ends_the_hold_and_a_decided_file_cannot_be_decided_again(case):
    done = case.hold(PDF)
    out = ops.attachment_discard(case.path, done["attachment"]["id"], channel="messaging", sender=SENDER)
    assert out["discarded"] is True and out["reply"] == "Discarded Q3 plan.pdf."
    assert case.rows()[0]["status"] == "discarded" and not (case.data / "attachments" / "held" / "1").exists()
    for call in (ops.attachment_discard, ops.attachment_add):
        with pytest.raises(ops.OpsError, match="That file is discarded, not waiting for your answer."):
            call(case.path, 1, channel="messaging", sender=SENDER)
    with pytest.raises(ops.OpsError, match="No file 9 waits for you."):
        ops.attachment_discard(case.path, 9, channel="messaging", sender=SENDER)
    with pytest.raises(ops.OpsError):
        ops.attachment_add(case.path, "1", channel="messaging", sender=SENDER)


def test_the_terminal_and_the_page_decide_a_held_file_with_no_sender(case):
    first, second = case.hold(PDF), case.hold(make_pdf("Another"), name="b.pdf")
    assert ops.attachment_add(case.path, first["attachment"]["id"])["version"] == 1
    assert ops.attachment_discard(case.path, second["attachment"]["id"], channel="page")["discarded"] is True
    assert [r["status"] for r in case.rows()] == ["added", "discarded"]


# --- who may -----------------------------------------------------------------------------------------------------------------------


def test_a_sender_whose_profile_lacks_add_sources_cannot_hold_add_or_discard(case):
    accept(case.path, messaging={"senders": {"telegram": [IDENT, {"id": OTHER, "policy": "reader"}]}})
    other = f"telegram:{OTHER}"
    token = case.fetch(PDF)
    with pytest.raises(ops.OpsError, match="/attachment-hold is not enabled for this channel"):
        ops.attachment_hold(case.path, token, "telegram", "r", "a.pdf", None, None, None, False, channel="messaging", sender=other)
    held = case.hold(PDF)
    for call in (ops.attachment_add, ops.attachment_discard):
        with pytest.raises(ops.OpsError, match="is not enabled for this channel"):
            call(case.path, held["attachment"]["id"], channel="messaging", sender=other)
    assert case.rows()[0]["status"] == "held" and not Path(case.cfg["data_dir"], "attachments", "incoming", token).exists()


def test_a_messaging_call_names_its_sender_and_the_default_policy_of_messaging_takes_no_file(case):
    with pytest.raises(ops.OpsError, match="names the sender"):
        ops.attachment_add(case.path, 1, channel="messaging")
    accept(case.path, channels={"messaging": ["read"]}, policies=None)
    token = case.fetch(PDF)
    with pytest.raises(ops.OpsError, match="/attachment-hold is not enabled"):
        ops.attachment_hold(case.path, token, "telegram", "r", "a.pdf", None, None, None, False, channel="messaging", sender=SENDER)
    accept(case.path, channels=None)
    token = case.fetch(PDF)
    with pytest.raises(ops.OpsError, match="/attachment-hold is not enabled"):
        ops.attachment_hold(case.path, token, "telegram", "r", "a.pdf", None, None, None, False, channel="messaging", sender=SENDER)


def test_the_grant_that_adds_without_a_card_is_checked_in_the_operation_against_the_senders_profile(case):
    with pytest.raises(ops.OpsError, match="/add-sources-direct is not enabled"):
        case.hold(PDF, direct=True)                      # `staff` has add-sources and not the grant
    assert case.rows() == []
    accept(case.path, messaging={"senders": {"telegram": [{"id": IDENT, "policy": "desk"}]}})
    done = case.hold(PDF, direct=True)
    assert done["added"]["version"] == 1 and done["added"]["reply"].startswith("Added Q3 plan.pdf as `q3-plan`, version 1.")
    row = case.rows()[0]
    assert (row["status"], row["direct"], row["profile"]) == ("added", True, "desk")
    assert case.ctx["store"].source_latest(case.ctx["conn"], "q3-plan")["provenance"]["profile"] == "desk"
    assert not (case.data / "attachments" / "held" / "1").exists()
    with pytest.raises(ops.OpsError, match="is not enabled"):
        ops.attachment_discard(case.path, 1, channel="messaging", sender=SENDER)


def test_a_held_file_never_enters_a_run_a_prompt_or_the_catalog_until_it_is_added(case):
    case.hold(PDF)
    assert ops.sources_catalog(case.path)["sources"] == [] and ops_core.context(case.path)["cfg"]["sources_dir"] == str(case.folder)
    ops_sources = st.load("ops_sources")
    assert ops_sources.catalog_block(case.ctx) == "" and ops_sources.known_ids(case.ctx) == []
    assert not sources.related(str(case.data / "attachments"), str(case.folder)), "the hold and the sources folder are disjoint (limit L22)"


def test_provenance_is_words_and_never_an_account():
    clean = sources.clean_provenance
    assert clean(None) is None
    assert clean({"channel": "messaging", "platform": "whatsapp-cloud", "profile": None, "attachment": 3}) == {
        "channel": "messaging", "platform": "whatsapp-cloud", "profile": None, "attachment": 3}
    for bad in ({}, [], "x", {"sender": "4242"}, {"platform": "Telegram"}, {"platform": "tele gram"}, {"platform": "x" * 70}, {"attachment": 0},
                {"attachment": True}, {"attachment": "3"}, {"platform": None}, {"platform": "+5511912345678"}):
        with pytest.raises(sources.SourcesError):
            clean(bad)
    assert sources.provenance_text({"channel": "messaging", "platform": "telegram", "profile": "staff"}) == "sent on telegram, profile staff"
    assert sources.provenance_text({"platform": "discord", "profile": None}) == "sent on discord" and sources.provenance_text(None) is None


def test_a_source_id_is_made_from_a_name_and_a_drive_file_keeps_its_own_fallback():
    make = sources.source_id_from_name
    assert make("Q3 plan", []) == "q3-plan" and make("Q3 plan", ["q3-plan"]) == "q3-plan-2" and make("!!!", []) == "file" and make("", ["file"]) == "file-2"
    assert make("é", [], "memo") == "memo" and len(make("x" * 80, [])) <= 36
    assert sources.drive_source_id("!!!", []) == "drive-file"


def test_no_operation_about_attachments_is_a_row_of_the_mcp_mode_and_the_grant_is_the_messaging_channels_alone():
    names = ("attachments", "attachment-hold", "attachment-add", "attachment-discard")
    for name in names:
        assert "mcp" not in operations.by_name(name)["channels"], name
    assert operations.by_name("attachment-hold")["channels"] == ("messaging",)
    assert "add-sources-direct" in operations.GRANTS["messaging"] and not {"add-sources", "add-sources-direct"} & set(operations.GRANTS["mcp"])
    for group in ("add-sources", "add-sources-direct"):
        assert operations.group_refusal("mcp", group), group
    assert operations.group_refusal("page", "add-sources-direct") and operations.group_refusal("page", "add-sources") is None
    assert operations.group_refusal("messaging", "add-sources") is None and operations.group_refusal("messaging", "add-sources-direct") is None
    assert "add-sources" not in operations.default_groups("messaging") and "add-sources-direct" not in operations.default_groups("messaging")
    assert operations.GRANT_TEXT["messaging:add-sources-direct"] == ("a file a listed sender sends becomes a new source of the project without a confirmation "
                                                                    "(a file for a source that already exists still waits for a card)")
    assert operations.permitted("attachment-hold", "messaging", {"messaging": ["add-sources"]}, None) is True
    assert operations.granted("attachment-hold", "messaging", {"messaging": ["add-sources"]}, "direct") is False
    assert operations.granted("attachment-hold", "messaging", {"messaging": ["add-sources-direct"]}, "direct") is True


# --- the review of ATT-1a --------------------------------------------------------------------------------------------------------------------------


OTHER = "5151515151"
OTHER_KEY = f"telegram:{OTHER}"


def desk(case):
    """IDENT with the profile that holds the grant, and a second listed sender with `staff`."""
    accept(case.path, policies=dict(POLICIES, desk=["read", "add-sources", "add-sources-direct"]),
           messaging={"senders": {"telegram": [{"id": IDENT, "policy": "desk"}, OTHER]}})


def test_a_sender_lists_adds_and_discards_only_the_files_they_sent_and_the_person_s_own_shells_see_them_all(case):
    accept(case.path, messaging={"senders": {"telegram": [IDENT, OTHER]}})
    first = case.hold(PDF)["attachment"]["id"]
    second = ops.attachment_hold(case.path, case.fetch(make_pdf("The other sender's file")), "telegram", "ref-other", "Other.pdf", None, None, None, False,
                                 channel="messaging", sender=OTHER_KEY)["attachment"]["id"]
    assert [r["id"] for r in ops.attachments(case.path, channel="messaging", sender=SENDER)["held"]] == [first]
    assert [r["id"] for r in ops.attachments(case.path, channel="messaging", sender=OTHER_KEY)["held"]] == [second]
    assert [r["id"] for r in ops.attachments(case.path)["held"]] == [first, second], "the terminal and the page see every file"
    assert [r["id"] for r in ops.attachments(case.path, channel="page")["held"]] == [first, second]
    for call in (ops.attachment_add, ops.attachment_discard):
        with pytest.raises(ops.OpsError) as caught:
            call(case.path, first, channel="messaging", sender=OTHER_KEY)
        assert str(caught.value) == f"No file {first} waits for you.", "the answer tells nothing of a file that is someone else's"
    assert [r["status"] for r in case.rows()] == ["held", "held"]
    ops.attachment_discard(case.path, first, channel="messaging", sender=SENDER)
    with pytest.raises(ops.OpsError) as caught:
        ops.attachment_add(case.path, first, channel="messaging", sender=OTHER_KEY)
    assert str(caught.value) == f"No file {first} waits for you.", "not even that it was discarded"
    assert [r["id"] for r in ops.attachments(case.path, channel="messaging", sender=OTHER_KEY)["recent"]] == []
    assert [r["id"] for r in ops.attachments(case.path, channel="messaging", sender=SENDER)["recent"]] == [first]
    assert ops.attachment_add(case.path, second, channel="messaging", sender=OTHER_KEY)["version"] == 1
    with pytest.raises(ops.OpsError, match="names the sender"):
        ops.attachments(case.path, channel="messaging")


def test_a_direct_add_never_makes_a_new_version_of_a_source_that_exists_and_holds_the_file_for_a_card(case):
    desk(case)
    registered = sources.register(case.ctx, "q3-plan", "file", "q3.pdf")             # a source with no version yet is a source that exists
    declined = case.hold(PDF, target="q3-plan", direct=True)
    assert declined["direct_declined"] is True and "added" not in declined and declined["attachment"]["status"] == "held"
    assert case.rows()[0]["direct"] is False and case.ctx["store"].source_latest(case.ctx["conn"], registered["id"]) is None
    assert (case.data / "attachments" / "held" / "1" / "original").is_file()
    ops.attachment_add(case.path, 1, channel="messaging", sender=SENDER)
    again = case.hold(make_pdf("A second draft"), target="q3-plan", direct=True, ref=None)
    assert again["direct_declined"] is True and again["label"] == "refresh" and case.rows()[1]["status"] == "held"
    fresh = case.hold(make_pdf("A different file"), name="Brand new.pdf", direct=True)
    assert fresh["added"]["version"] == 1 and "direct_declined" not in fresh
    named = case.hold(make_pdf("A file for a source nobody has"), target="free-id", direct=True)
    assert named["added"]["source"] == "free-id", "a free id the caption named is a new source: the grant covers it"


def test_a_fetch_that_ended_with_no_file_is_recorded_and_counts_against_the_day(case, monkeypatch):
    monkeypatch.setattr(attachments, "DAY_FILES", 3)
    for n, code in enumerate(("gone", "fetch", "size")):
        out = ops.attachment_hold(case.path, None, "telegram", f"never-{n}", "Big one.pdf", "application/pdf", 999, None, False, None, code, 4096,
                                  channel="messaging", sender=SENDER)
        assert out == {"recorded": True, "code": code}
    rows = case.rows()
    assert [(r["status"], r["code"], r["bytes"], r["sha256"], r["kind"]) for r in rows] == [("refused", c, 4096, None, None) for c in ("gone", "fetch", "size")]
    assert ops.attachments(case.path)["today"] == {"files": 3, "bytes": 3 * 4096} and not (case.data / "attachments" / "held").exists()
    assert "never-0" not in json.dumps(rows), "the reference is a hash, here too"
    with pytest.raises(ops.OpsError, match="took 3 files"):
        case.hold(PDF)
    with pytest.raises(ops.OpsError, match="one of gone, fetch, size"):
        ops.attachment_hold(case.path, None, "telegram", "r", "x.pdf", failed="melted", channel="messaging", sender=SENDER)
    with pytest.raises(ops.OpsError, match="/attachment-hold is not enabled"):
        accept(case.path, channels={"messaging": ["read"]}, policies=None)
        ops.attachment_hold(case.path, None, "telegram", "r", "x.pdf", failed="gone", channel="messaging", sender=SENDER)


def test_a_fetch_that_reached_the_hold_and_was_refused_still_counts_a_duplicate_a_page_upload_and_a_declared_medium_included(case):
    case.hold(PDF, ref="same")
    with pytest.raises(ops.OpsError, match="already waits"):
        case.hold(PDF, ref="same")
    assert [(r["status"], r["code"]) for r in case.rows()] == [("held", None), ("refused", "duplicate")]
    lock = sources.intake.one_at_a_time(sources.upload_lock_path(case.cfg))            # the page is uploading
    try:
        with pytest.raises(ops.OpsError, match="Another file is being fetched"):
            case.hold(PDF)
    finally:
        lock.release()
    assert case.rows()[-1]["code"] == "busy"
    with pytest.raises(ops.OpsError, match="Voice notes, videos"):
        case.hold(PDF, declared="voice")                 # the authority checks what the bridge checked before the fetch
    with pytest.raises(ops.OpsError, match="is 30.0 MiB; a file from this app is at most 25.0 MiB"):
        case.hold(PDF, declared_bytes=30 * 1024 * 1024)
    assert [r["code"] for r in case.rows()][-2:] == ["media", "too_large"]
    assert ops.attachments(case.path)["today"]["files"] == 5


def test_the_intake_is_bound_by_the_least_of_the_provider_s_cap_and_the_day_s_bytes_left(case, monkeypatch):
    big = "Words of a long text file for a cap to cut. " * 40
    monkeypatch.setattr(attachments, "DAY_BYTES", 3000)
    with pytest.raises(ops.OpsError, match="was not added and was deleted: the body is 1760 bytes, more than the 500 this route takes"):
        ops.attachment_hold(case.path, case.fetch(big), "telegram", "r1", "Big.txt", "text/plain", None, None, False, 500,
                            channel="messaging", sender=SENDER)
    assert case.rows()[0]["code"] == "size" and case.rows()[0]["bytes"] == len(big)
    with pytest.raises(ops.OpsError, match="more than the 1240 this route takes"):      # no provider cap: what is left of the day, 3000 less the 1760 fetched
        case.hold(big, name="Again.txt", declared="text/plain")
    assert case.rows()[1]["code"] == "size"


def test_a_file_with_another_name_is_not_taken_from_the_provider_s_folder(case, tmp_path):
    token, folder = attachments.make_incoming(case.cfg["data_dir"])
    elsewhere = tmp_path / "elsewhere.pdf"
    elsewhere.write_bytes(PDF)
    os.link(elsewhere, Path(folder, "content"))                # a hard link: the bytes are also a file of someone else's
    with pytest.raises(attachments.FolderError, match="another name"):
        attachments.open_content(folder)
    with pytest.raises(ops.OpsError, match="can no longer be fetched"):
        ops.attachment_hold(case.path, token, "telegram", "r", "a.pdf", None, None, None, False, channel="messaging", sender=SENDER)
    assert elsewhere.read_bytes() == PDF and case.rows() == []


def test_a_problem_of_this_machine_reaches_a_phone_as_a_fixed_sentence_and_the_terminal_keeps_the_detail(case, monkeypatch):
    held = case.hold(PDF)["attachment"]["id"]

    def broken(cfg, call=None):
        def convert(*args):
            raise sources.SourcesError(f"the converter failed (failed): docker said no at {case.cfg['data_dir']}", "converter")
        return convert
    monkeypatch.setattr(sources, "provider_convert", broken)
    with pytest.raises(ops.OpsError) as caught:
        ops.attachment_add(case.path, held, channel="messaging", sender=SENDER)
    assert isinstance(caught.value, st.load("ops_attachments").MachineProblem) and str(case.cfg["data_dir"]) in str(caught.value)
    assert caught.value.phone == attachments.MACHINE and "/" not in caught.value.phone
    monkeypatch.setattr(attachments, "keep_held", lambda *a, **k: (_ for _ in ()).throw(attachments.FolderError(f"no room in {case.cfg['data_dir']}")))
    with pytest.raises(ops.OpsError) as caught:
        case.hold(make_pdf("Another file"), name="Next.pdf")
    assert caught.value.phone == "Next.pdf could not be kept on this machine. Send it again in a while." and "/" not in caught.value.phone
