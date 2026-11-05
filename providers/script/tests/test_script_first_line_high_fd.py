"""The first line of the egress proxy is read from a pipe whose descriptor can be numbered 1,024 or more (a long-lived process holds that
many open). select.select refuses such a descriptor (FD_SETSIZE); the reader must not."""
from __future__ import annotations

import importlib.util
import os
import resource
import select
import sys
import types
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("script_container_high_fd", HERE.parent / "container.py")
host = importlib.util.module_from_spec(spec)
sys.modules["script_container_high_fd"] = host
spec.loader.exec_module(host)

HIGH = 1100          # above FD_SETSIZE (1,024), below any usual hard limit


@pytest.fixture
def high_pipe():
    """A pipe whose read end is descriptor HIGH. The soft limit is raised for the test and restored after; skipped if it cannot be."""
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    want = HIGH + 64
    if soft != resource.RLIM_INFINITY and soft < want:
        if hard != resource.RLIM_INFINITY and hard < want:
            pytest.skip("the descriptor limit cannot be raised above 1,024")
        resource.setrlimit(resource.RLIMIT_NOFILE, (want, hard))
    read, write = os.pipe()
    try:
        os.dup2(read, HIGH)
    except OSError:
        os.close(read)
        os.close(write)
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))
        pytest.skip("a descriptor above 1,024 cannot be made here")
    os.close(read)
    try:
        yield HIGH, write
    finally:
        for fd in (HIGH, write):
            try:
                os.close(fd)
            except OSError:
                pass
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))


def egress_with(fd):
    egress = host.Egress.__new__(host.Egress)
    egress.proc = types.SimpleNamespace(stdout=types.SimpleNamespace(fileno=lambda: fd), poll=lambda: None)
    return egress


def test_the_first_line_is_read_from_a_pipe_numbered_above_1023(high_pipe):
    fd, write = high_pipe
    assert fd > 1023
    os.write(write, b"ready api.example:443=8.8.8.8\nmore later\n")
    assert egress_with(fd)._first_line() == "ready api.example:443=8.8.8.8"


def test_a_line_that_arrives_in_two_parts_on_that_pipe_is_joined(high_pipe):
    fd, write = high_pipe
    os.write(write, b"refused not_pu")
    os.write(write, b"blic api.example\n")
    assert egress_with(fd)._first_line() == "refused not_public api.example"


def test_a_pipe_closed_with_no_line_gives_an_empty_first_line(high_pipe):
    fd, write = high_pipe
    os.close(write)
    assert egress_with(fd)._first_line() == ""


def test_vacuity_select_select_raises_on_that_same_descriptor(high_pipe):
    fd, write = high_pipe
    os.write(write, b"ready\n")
    with pytest.raises(ValueError, match="out of range"):
        select.select([fd], [], [], 1)
