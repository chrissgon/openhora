"""Tests of runtime/intake.py, the generic streaming intake: the bound on the length before a byte is read, the type from the
bytes, the temporary file (exclusive, no link followed, mode 0600, removed on every failure), the hash, the deadline and the
stall limit, the lock, the extensible type table, and what the module may import. Offline; no file of a store.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_intake.py
"""
from __future__ import annotations

import ast
import errno
import hashlib
import io
import os
import stat
import time

import pytest

import standin_tree as st

intake = st.load("intake")

MOVHEAD = b"\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00qt  "
MP4HEAD = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2"
PNGHEAD = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24


class Forbidden(io.RawIOBase):
    """A body that must never be read."""

    def readable(self):
        return True

    def read(self, n=-1):
        raise AssertionError("the body was read")


class Body(io.RawIOBase):
    """A body that is generated, never held: `head`, then zeros, up to `total` bytes. `reads` counts the calls; `fail_after`
    raises OSError after that many bytes (a dropped connection); `stop_after` ends the body early."""

    def __init__(self, total, head=b"", fail_after=None, stop_after=None):
        self.total, self.head, self.given, self.reads = total, head, 0, 0
        self.fail_after, self.stop_after = fail_after, stop_after

    def readable(self):
        return True

    def read(self, n=-1):
        self.reads += 1
        if self.fail_after is not None and self.given >= self.fail_after:
            raise OSError("the connection was reset")
        if self.stop_after is not None and self.given >= self.stop_after:
            return b""
        n = min(n if n and n > 0 else 1 << 20, self.total - self.given)
        if self.stop_after is not None:
            n = min(n, self.stop_after - self.given)
        if n <= 0:
            return b""
        start = self.given
        out = bytearray(n)
        if start < len(self.head):
            piece = self.head[start:start + n]
            out[:len(piece)] = piece
        self.given += n
        return bytes(out)


class Drip:
    """A body that arrives slowly: each read1 waits `pause` seconds and gives `size` bytes. `read` is a trap (a buffered
    reader's read(n) waits for all n bytes), so a caller that uses it hangs the test. `armed` records the timeouts set."""

    def __init__(self, head, total, pause, size=1024):
        self.head, self.total, self.pause, self.size, self.given, self.armed = head, total, pause, size, 0, []

    def settimeout(self, seconds):
        self.armed.append(seconds)

    def read1(self, n):
        time.sleep(self.pause)
        piece = min(n, self.size, self.total - self.given)
        start = self.given
        self.given += piece
        out = bytearray(piece)
        chunk = self.head[start:start + piece]
        out[:len(chunk)] = chunk
        return bytes(out)

    def read(self, n):
        raise AssertionError("read(n) waits for n bytes: a slow sender would hold it past the deadline")


@pytest.fixture
def dest(tmp_path):
    folder = tmp_path / "dest"
    folder.mkdir(mode=0o700)
    return str(folder)


def take(dest, payload, **kwargs):
    kwargs.setdefault("cap", 1 << 30)
    return intake.stream_in(io.BytesIO(payload), len(payload), dest, **kwargs)


def refusal(dest, payload=None, *, stream=None, length=None, **kwargs):
    kwargs.setdefault("cap", 1 << 30)
    stream = stream if stream is not None else io.BytesIO(payload)
    with pytest.raises(intake.IntakeError) as caught:
        intake.stream_in(stream, len(payload) if length is None and payload is not None else length, dest, **kwargs)
    return caught.value


# --- the bound on the length, before a byte is read ------------------------------------------------------------------------------


def test_a_length_over_the_cap_is_refused_before_one_byte_is_read(dest):
    error = refusal(dest, stream=Forbidden(), length=101, cap=100)
    assert error.code == "too_large" and os.listdir(dest) == []


def test_a_missing_length_is_refused_before_one_byte_is_read(dest):
    assert refusal(dest, stream=Forbidden(), length=None).code == "length"


def test_a_length_that_is_not_a_number_is_refused(dest):
    for bad in ("12", 1.5, -1, True):
        assert refusal(dest, stream=Forbidden(), length=bad).code == "usage", bad


def test_a_length_under_the_minimum_is_refused_before_one_byte_is_read(dest):
    assert refusal(dest, stream=Forbidden(), length=intake.MIN_BYTES - 1).code == "too_small"
    assert refusal(dest, stream=Forbidden(), length=9, minimum=10).code == "too_small"
    assert take(dest, b"x" * 10, minimum=10).size == 10


def test_the_cap_and_the_minimum_are_inclusive(dest):
    done = take(dest, b"y" * 100, cap=100)
    assert done.size == 100


# --- the destination, and free space -----------------------------------------------------------------------------------------------


def test_free_space_below_the_need_refuses_before_the_body_is_read(dest, monkeypatch):
    monkeypatch.setattr(intake, "free_bytes", lambda path: 1000)
    error = refusal(dest, stream=Forbidden(), length=5000)
    assert error.code == "no_space" and os.listdir(dest) == []


def test_free_space_check_can_be_left_out(dest, monkeypatch):
    monkeypatch.setattr(intake, "free_bytes", lambda path: 0)
    assert take(dest, b"z" * 64, free_margin=None).size == 64


def test_the_destination_must_be_a_plain_folder_of_ours_closed_to_others(tmp_path):
    loose = tmp_path / "loose"
    loose.mkdir(mode=0o755)
    os.chmod(loose, 0o755)
    assert refusal(str(loose), b"a" * 64).code == "refused"
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    link = tmp_path / "link"
    os.symlink(private, link)
    assert refusal(str(link), b"a" * 64).code == "refused"
    assert refusal(str(tmp_path / "missing"), b"a" * 64).code == "refused"
    assert refusal(str(private / "nothing"), b"a" * 64).code == "refused"


# --- the type, from the bytes -----------------------------------------------------------------------------------------------------


def test_the_type_is_read_from_the_bytes_and_returned(dest):
    assert take(dest, MOVHEAD + b"\0" * 64).type == ("video", "mov")
    assert take(dest, MP4HEAD + b"\0" * 64).type == ("video", "mp4")
    assert take(dest, PNGHEAD + b"\0" * 64).type == ("image", "png")
    assert take(dest, b"\xff\xd8\xff\xe0" + b"\0" * 64).type == ("image", "jpeg")
    assert take(dest, b"RIFF\0\0\0\0WEBP" + b"\0" * 64).type == ("image", "webp")
    assert take(dest, b"\x00\x00\x00\x18ftypheic\0\0\0\0" + b"\0" * 64).type == ("heif", "heic")
    assert take(dest, b"plain text that is not any container at all, only words").type is None


def test_a_box_that_is_not_plausible_is_no_type():
    assert intake.sniff(b"\x00\x00\x10\x01ftypisom" + b"\0" * 8) is None      # a size past 4096
    assert intake.sniff(b"\x00\x00\x00\x04ftypisom" + b"\0" * 8) is None      # a size under 12
    assert intake.sniff(b"\x00\x00\x00\x18ftypzzzz" + b"\0" * 8) is None      # a brand nobody knows
    assert intake.sniff(b"") is None and intake.sniff(b"\x89PNG") is None


def test_accept_refuses_a_type_before_a_file_exists(dest):
    def only_png(found):
        if found != ("image", "png"):
            raise intake.IntakeError("this is not a PNG", "type")

    error = refusal(dest, MOVHEAD + b"\0" * 64, accept=only_png)
    assert error.code == "type" and os.listdir(dest) == []
    assert take(dest, PNGHEAD + b"\0" * 64, accept=only_png).type == ("image", "png")


def test_the_name_and_the_content_type_are_never_looked_at(dest):
    done = take(dest, PNGHEAD + b"\0" * 64)
    assert "png" not in os.path.basename(done.path) and done.type == ("image", "png")


def test_the_sniff_table_is_extensible_without_editing_the_function(dest, monkeypatch):
    monkeypatch.setattr(intake, "SNIFF_TABLE", list(intake.SNIFF_TABLE))
    assert intake.sniff(b"%PDF-1.7\n" + b"\0" * 40) is None
    intake.add_sniffer("document", lambda head: "pdf" if head[:5] == b"%PDF-" else None)
    assert intake.sniff(b"%PDF-1.7\n" + b"\0" * 40) == ("document", "pdf")
    assert take(dest, b"%PDF-1.7\n" + b"\0" * 40).type == ("document", "pdf")
    assert intake.sniff(PNGHEAD) == ("image", "png"), "the entries that were there still answer"


def test_a_table_can_be_passed_to_one_call(dest):
    table = [("text", lambda head: "utf8" if head.startswith(b"hello") else None)]
    assert take(dest, b"hello " + b"w" * 60, sniff_table=table).type == ("text", "utf8")
    assert take(dest, PNGHEAD + b"\0" * 64, sniff_table=table).type is None
    assert intake.sniff(b"hello", table) == ("text", "utf8") and intake.sniff(b"hello") is None


# --- the bytes on disk ----------------------------------------------------------------------------------------------------------------


def test_the_hash_size_and_bytes_are_those_of_the_body_and_the_mode_is_private(dest):
    payload = MOVHEAD + os.urandom(3 * 1024 * 1024 + 123)
    done = take(dest, payload)
    assert done.sha256 == hashlib.sha256(payload).hexdigest() and done.size == len(payload)
    assert open(done.path, "rb").read() == payload
    assert stat.S_IMODE(os.lstat(done.path).st_mode) == 0o600
    assert os.path.dirname(done.path) == dest and os.listdir(dest) == [os.path.basename(done.path)]
    assert os.path.basename(done.path).startswith(intake.PART_PREFIX) and done.path.endswith(intake.PART_SUFFIX)


def test_the_body_is_read_in_chunks_and_never_whole(dest, monkeypatch):
    monkeypatch.setattr(intake, "CHUNK_BYTES", 1000)
    seen = []
    real = intake._write
    monkeypatch.setattr(intake, "_write", lambda out, data: (seen.append(len(data)), real(out, data))[1])
    body = Body(10_000, MOVHEAD)
    done = intake.stream_in(body, 10_000, dest, cap=1 << 20)
    assert done.size == 10_000 and seen[0] == intake.SNIFF_BYTES and max(seen[1:]) <= 1000 and len(seen) >= 6 and body.reads >= 6


def test_a_sniff_is_not_the_whole_body_a_head_longer_than_the_body_is_cut_to_it(dest):
    done = take(dest, MOVHEAD + b"\0" * 20)
    assert done.size == len(MOVHEAD) + 20


def test_two_bodies_get_two_names(dest):
    a, b = take(dest, b"a" * 64), take(dest, b"a" * 64)
    assert a.path != b.path and a.sha256 == b.sha256 and len(os.listdir(dest)) == 2


def test_a_pre_placed_link_at_the_temporary_name_is_refused_and_nothing_is_written_through_it(dest, tmp_path, monkeypatch):
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    os.symlink(victim, os.path.join(dest, intake.PART_PREFIX + "ab" * 8 + intake.PART_SUFFIX))
    monkeypatch.setattr(intake.secrets, "token_hex", lambda n: "ab" * n)
    error = refusal(dest, MOVHEAD + b"\0" * 100)
    assert error.code == "refused" and victim.read_text() == "keep me"


def test_a_file_already_at_the_temporary_name_is_refused_and_left_alone(dest, monkeypatch):
    name = os.path.join(dest, intake.PART_PREFIX + "cd" * 8 + intake.PART_SUFFIX)
    with open(name, "wb") as f:
        f.write(b"someone else's")
    monkeypatch.setattr(intake.secrets, "token_hex", lambda n: "cd" * n)
    assert refusal(dest, b"a" * 64).code == "refused"
    assert open(name, "rb").read() == b"someone else's"


@pytest.mark.parametrize("how", ["short", "reset"])
def test_the_temporary_file_is_removed_when_the_body_fails(dest, how):
    body = Body(5_000_000, MOVHEAD, **({"stop_after": 4_500_000} if how == "short" else {"fail_after": 1_500_000}))
    with pytest.raises(intake.IntakeError) as caught:
        intake.stream_in(body, 5_000_000, dest, cap=1 << 30, free_margin=None)
    assert caught.value.code in ("usage", "stalled") and os.listdir(dest) == []


def test_a_body_shorter_than_its_head_is_refused(dest):
    assert refusal(dest, stream=Body(100, MOVHEAD, stop_after=20), length=100, free_margin=None).code == "usage"
    assert os.listdir(dest) == []


def test_a_full_disk_while_writing_is_no_space_and_leaves_no_file(dest, monkeypatch):
    calls = []
    real = intake._write

    def full(out, chunk):
        calls.append(1)
        if len(calls) > 1:
            raise OSError(errno.ENOSPC, "No space left on device")
        real(out, chunk)

    monkeypatch.setattr(intake, "_write", full)
    assert refusal(dest, stream=Body(5_000_000, MOVHEAD), length=5_000_000, free_margin=None).code == "no_space"
    assert os.listdir(dest) == []
    monkeypatch.setattr(intake, "_write", lambda out, chunk: (_ for _ in ()).throw(OSError(errno.EIO, "Input/output error")))
    assert refusal(dest, stream=Body(5_000_000, MOVHEAD), length=5_000_000, free_margin=None).code == "refused"
    assert os.listdir(dest) == []


def test_an_interrupt_in_the_middle_removes_the_temporary_file(dest):
    class Interrupted(Body):
        def read(self, n=-1):
            if self.given > 2000:
                raise KeyboardInterrupt()
            return super().read(min(n, 1000) if n and n > 0 else 1000)

    with pytest.raises(KeyboardInterrupt):
        intake.stream_in(Interrupted(10_000, MOVHEAD), 10_000, dest, cap=1 << 20, free_margin=None)
    assert os.listdir(dest) == []


# --- time: the deadline and the stall limit ----------------------------------------------------------------------------------------


def test_the_deadline_holds_against_a_slow_sender_and_leaves_no_file(dest):
    stream = Drip(MOVHEAD, 10_000_000, pause=0.2)
    started = time.monotonic()
    error = refusal(dest, stream=stream, length=10_000_000, max_seconds=1, free_margin=None)
    elapsed = time.monotonic() - started
    assert error.code == "timeout" and "took more than" in str(error) and elapsed < 3, elapsed
    assert stream.given < 10_000_000 and os.listdir(dest) == []
    assert stream.armed and all(0 < t <= intake.STALL_SECONDS for t in stream.armed), "every read is armed"
    assert stream.armed[-1] < stream.armed[0], "with the time that is left"


def test_a_read_that_blocks_is_cut_at_the_time_left(dest):
    class Blocking:
        armed = None

        def settimeout(self, seconds):
            self.armed = seconds

        def read1(self, n):
            time.sleep(self.armed)                         # a socket that waits for its timeout
            raise TimeoutError("timed out")

    started = time.monotonic()
    error = refusal(dest, stream=Blocking(), length=100_000, max_seconds=1, free_margin=None)
    assert error.code == "timeout" and time.monotonic() - started < 2.5 and os.listdir(dest) == []


def test_a_stall_is_refused_and_every_read_is_armed_with_the_stall_limit(dest):
    class Stalls:
        armed = []

        def settimeout(self, seconds):
            self.armed.append(seconds)

        def read1(self, n):
            raise TimeoutError("timed out")

    stream = Stalls()
    error = refusal(dest, stream=stream, length=100_000, stall_seconds=5, free_margin=None)
    assert error.code == "stalled" and os.listdir(dest) == [] and stream.armed == [5]


def test_a_stall_in_the_middle_of_the_body_removes_the_file(dest):
    class StallsLater(Drip):
        def read1(self, n):
            if self.given >= 8192:
                raise TimeoutError("timed out")
            return super().read1(n)

    class Seen(StallsLater):
        files_when_it_fired = None

        def read1(self, n):
            if self.given >= 8192:
                Seen.files_when_it_fired = len(os.listdir(dest))
            return super().read1(n)

    stream = Seen(MOVHEAD, 100_000, pause=0)
    error = refusal(dest, stream=stream, length=100_000, free_margin=None)
    assert error.code == "stalled" and stream.given == 8192 and os.listdir(dest) == []
    assert Seen.files_when_it_fired == 1, "the temporary file existed when the stall fired, and was removed after"


def test_a_stream_with_read1_is_read_with_read1_and_one_without_with_read(dest):
    assert take(dest, b"q" * 64).size == 64                              # BytesIO has read1
    plain = Body(64, MOVHEAD)
    assert not hasattr(plain, "read1") and intake.stream_in(plain, 64, dest, cap=1000, free_margin=None).size == 64


# --- the lock ------------------------------------------------------------------------------------------------------------------------


def test_one_upload_at_a_time_and_the_lock_is_released(tmp_path):
    path = str(tmp_path / ".upload.lock")
    first = intake.one_at_a_time(path)
    with pytest.raises(intake.IntakeError) as caught:
        intake.one_at_a_time(path)
    assert caught.value.code == "refused" and "another upload" in str(caught.value)
    with pytest.raises(BlockingIOError):
        with intake.Lock(path, blocking=False):
            pass
    first.release()
    first.release()                                                     # a second release does nothing
    with intake.Lock(path, blocking=False):                             # free again
        assert os.fstat(0)


def test_the_lock_file_is_private_and_a_link_at_its_name_is_not_followed(tmp_path):
    path = tmp_path / ".upload.lock"
    with intake.Lock(str(path), blocking=False):
        pass
    assert stat.S_IMODE(os.lstat(path).st_mode) == 0o600
    other = tmp_path / "other.lock"
    os.symlink(tmp_path / "target", other)
    with pytest.raises(intake.IntakeError):
        intake.one_at_a_time(str(other))
    assert not (tmp_path / "target").exists()


# --- what the module is --------------------------------------------------------------------------------------------------------------


def imports_of(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
    return names, tree


def test_the_module_imports_none_of_the_store_the_video_or_the_operations_layer():
    names, tree = imports_of(intake.__file__)
    for forbidden in ("captions", "theme", "video", "media", "ops", "recording", "sources"):
        assert forbidden not in names and not any(n.startswith("ops_") for n in names), forbidden
    local = {n for n in names if os.path.exists(os.path.join(os.path.dirname(intake.__file__), n + ".py"))}
    assert local == set(), f"the intake imports nothing of runtime/: {local}"
    assert names <= {"__future__", "errno", "fcntl", "hashlib", "os", "secrets", "stat", "time", "typing"}


def test_no_function_takes_a_recording_or_a_slot():
    _, tree = imports_of(intake.__file__)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            for arg in args.posonlyargs + args.args + args.kwonlyargs + [a for a in (args.vararg, args.kwarg) if a]:
                assert arg.arg not in ("recording", "slot", "record", "rid"), (node.name, arg.arg)


# --- the review round: a lying stream, the lock, the folder swap, a box that is no type ------------------------------------------------


def test_a_stream_that_gives_more_than_it_was_asked_for_is_refused_and_leaves_no_file(dest):
    class Liar:
        def read1(self, n):
            return b"\0" * (n + 1)

    error = refusal(dest, stream=Liar(), length=100_000, free_margin=None)
    assert error.code == "usage" and "more bytes" in str(error) and os.listdir(dest) == []

    class LiesLater(Body):
        def read(self, n=-1):
            return super().read(n) + (b"x" if self.given > 6000 else b"")

    error = refusal(dest, stream=LiesLater(100_000, MOVHEAD), length=100_000, free_margin=None)
    assert error.code == "usage" and os.listdir(dest) == []


def test_with_a_lock_path_two_intakes_do_not_overlap_and_the_lock_is_released_after_each(dest, tmp_path):
    lock_path = str(tmp_path / ".upload.lock")
    inner = {}

    class Reentrant(Body):
        def read(self, n=-1):
            if "error" not in inner:    # while the first intake holds the lock, a second one starts
                try:
                    intake.stream_in(io.BytesIO(b"b" * 64), 64, dest, cap=1000, free_margin=None, lock_path=lock_path)
                except intake.IntakeError as e:
                    inner["error"] = e
            return super().read(n)

    done = intake.stream_in(Reentrant(10_000, MOVHEAD), 10_000, dest, cap=1 << 20, free_margin=None, lock_path=lock_path)
    assert done.size == 10_000 and inner["error"].code == "refused" and "another upload" in str(inner["error"])
    assert len(os.listdir(dest)) == 1, "the second intake left nothing"
    again = intake.stream_in(io.BytesIO(b"c" * 64), 64, dest, cap=1000, free_margin=None, lock_path=lock_path)
    assert again.size == 64, "the lock was released"


def test_the_lock_is_released_when_the_intake_fails(dest, tmp_path):
    lock_path = str(tmp_path / ".upload.lock")
    assert refusal(dest, stream=Body(5000, MOVHEAD, stop_after=100), length=5000, free_margin=None, lock_path=lock_path).code == "usage"
    with intake.Lock(lock_path, blocking=False):
        pass
    held = intake.one_at_a_time(lock_path)
    try:
        assert refusal(dest, stream=Forbidden(), length=64, lock_path=lock_path).code == "refused"
    finally:
        held.release()


def test_a_folder_swapped_for_a_link_after_the_check_is_not_followed(dest, tmp_path, monkeypatch):
    evil = tmp_path / "evil"
    evil.mkdir(mode=0o700)
    moved = dest + ".moved"

    def swap(fd):
        os.rename(dest, moved)
        os.symlink(evil, dest)
        return 10 ** 12

    monkeypatch.setattr(intake, "free_bytes", swap)
    done = intake.stream_in(io.BytesIO(MOVHEAD + b"\0" * 100), len(MOVHEAD) + 100, dest, cap=1 << 20)
    assert os.listdir(evil) == [], "nothing was written through the link"
    assert len(os.listdir(moved)) == 1 and done.size == len(MOVHEAD) + 100


def test_a_folder_swapped_after_the_check_leaves_nothing_in_the_other_folder_when_the_body_fails(dest, tmp_path, monkeypatch):
    evil = tmp_path / "evil"
    evil.mkdir(mode=0o700)
    monkeypatch.setattr(intake, "free_bytes", lambda fd: (os.rename(dest, dest + ".moved"), os.symlink(evil, dest), 10 ** 12)[2])
    error = refusal(dest, stream=Body(5000, MOVHEAD, stop_after=100), length=5000)
    assert error.code == "usage" and os.listdir(evil) == [] and os.listdir(dest + ".moved") == []


def test_a_link_at_the_name_of_the_folder_is_refused_when_the_call_starts(tmp_path):
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    os.symlink(real, tmp_path / "link")
    assert refusal(str(tmp_path / "link"), b"a" * 64).code == "refused" and os.listdir(real) == []


def test_a_box_the_video_and_heif_entries_reject_is_no_type_and_not_an_image():
    assert intake.sniff(b"\xff\xd8\xff\xe0ftypzzzz" + b"\0" * 20) is None
    assert intake.sniff(b"RIFFftypWEBP" + b"\0" * 20) is None
    assert intake.sniff(b"\x89PNG\r\n\x1a\n") == ("image", "png") and intake.sniff(b"\xff\xd8\xff\xe0\0\x10JFIF") == ("image", "jpeg")
    assert intake.sniff(b"RIFF\0\0\0\0WEBPVP8 ") == ("image", "webp")
