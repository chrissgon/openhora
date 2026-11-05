#!/usr/bin/env python3
"""Hold one of a few machine-wide test slots while a command runs, so that at most N heavy test runs share one machine.

Usage:
  python3 scripts/test_slots.py [--slots N] [--wait SECONDS] [--dir DIR] -- COMMAND [ARG...]
  python3 scripts/test_slots.py [--slots N] --workers

The pre-commit hook starts pytest through this script (docs/decisions.md, 2026-10-20: at most 3 heavy test runs at once). It
takes the lock of a free slot, waits for one when all are held, and then replaces itself with COMMAND (exec), which inherits the
open lock: the slot is held for exactly as long as COMMAND lives, and a killed COMMAND (or a killed hook, when it was the
command) frees it, because a lock on an open file is released by the system when the process that holds it ends. There is no
lock file to clean up and no stale slot.

  --slots N     the number of slots (default: the variable WB_TEST_SLOTS, else 3)
  --wait S      the most seconds to wait for a slot (default: WB_TEST_SLOT_WAIT, else 3600); 0 tries once
  --dir DIR     the folder of the lock files (default: WB_TEST_SLOT_DIR, else ${TMPDIR:-/tmp}/openhora-test-slots). The limit is
                machine-wide only for processes that share this folder: set WB_TEST_SLOT_DIR to one path when the agents of a
                machine run with different TMPDIR values.

  --workers     print how many pytest-xdist workers ONE run should use, and exit 0 (it needs no command): the machine's cores divided by the
                slots, at least 2, so that N runs that each take a slot together use about as many workers as the machine has cores (3 slots on
                14 cores: 4 workers each, 12 in all; on 4 cores: 2 each). WB_TEST_WORKERS (a whole number of at least 1) sets it by hand; a bad
                value exits 2. The hook and the by-hand command of AGENTS.md ("Which tests run, and when") pass it as `-n "$(... --workers)"`;
                CI keeps `-n auto`, because a CI job is the only run on its runner.

Exit codes: COMMAND's own; 2 for a bad option; 75 when no slot became free within the wait (nothing was run, and the message says
so: the tests are not skipped, they have not run); 127 when COMMAND cannot be started.
Standard library only; Python 3.9 compatible.
"""
from __future__ import annotations

import argparse
import fcntl
import os
import sys
import time

DEFAULT_SLOTS = 3
DEFAULT_WAIT = 3600
EXIT_NO_SLOT = 75  # EX_TEMPFAIL; never 1-5, which are pytest's own (3 is its internal error)


def default_dir():
    return os.environ.get("WB_TEST_SLOT_DIR") or os.path.join(os.environ.get("TMPDIR") or "/tmp", "openhora-test-slots")


def slot_path(directory, index):
    return os.path.join(directory, "slot-%d.lock" % index)


def try_acquire(directory, slots):
    """The open file descriptor and the index of the first free slot, or None when every slot is held."""
    os.makedirs(directory, exist_ok=True)
    for index in range(slots):
        fd = os.open(slot_path(directory, index), os.O_RDWR | os.O_CREAT, 0o666)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            continue
        return fd, index
    return None


def acquire(directory, slots, wait, poll=0.25, clock=time.monotonic, sleep=time.sleep, say=None):
    """Wait at most `wait` seconds for a free slot; the descriptor and index, or None at the deadline."""
    deadline = clock() + wait
    told = False
    while True:
        got = try_acquire(directory, slots)
        if got is not None:
            return got
        if clock() >= deadline:
            return None
        if not told and say is not None:
            say("test_slots: all %d test slots are held by other runs on this machine; waiting for one (at most %d s)" % (slots, wait))
            told = True
        sleep(poll)


def positive_int(text, name):
    try:
        value = int(text)
    except (TypeError, ValueError):
        value = -1
    if value < 0 or (name == "slots" and value < 1):
        raise argparse.ArgumentTypeError("%s must be a whole number%s, got %r" % (name, " of at least 1" if name == "slots" else "", text))
    return value


def workers(slots, cpu=None, env=os.environ):
    """The xdist workers of one run: WB_TEST_WORKERS when it is set (a whole number of at least 1, else ArgumentTypeError), else the cores
    divided by the slots, at least 2."""
    raw = env.get("WB_TEST_WORKERS")
    if raw is not None:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = 0
        if value < 1:
            raise argparse.ArgumentTypeError("WB_TEST_WORKERS must be a whole number of at least 1, got %r" % raw)
        return value
    return max(2, (cpu or os.cpu_count() or 2) // slots)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog="Run `python3 scripts/test_slots.py -h` for the whole text.", usage="%(prog)s [options] -- COMMAND [ARG...]  |  %(prog)s [--slots N] --workers")
    parser.add_argument("--slots", type=lambda t: positive_int(t, "slots"), help="number of slots (default WB_TEST_SLOTS, else 3)")
    parser.add_argument("--wait", type=lambda t: positive_int(t, "wait"), help="seconds to wait (default WB_TEST_SLOT_WAIT, else 3600)")
    parser.add_argument("--dir", help="folder of the lock files")
    parser.add_argument("--workers", action="store_true", help="print the pytest-xdist workers of one run (WB_TEST_WORKERS, else the cores divided by the slots, at least 2) and exit")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="after --: the command to run while the slot is held")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command and not args.workers:
        parser.error("no command: put it after --")
    try:
        slots = args.slots if args.slots is not None else positive_int(os.environ.get("WB_TEST_SLOTS", DEFAULT_SLOTS), "slots")
        if args.workers:
            sys.stdout.write("%d\n" % workers(slots))
            return 0
        wait = args.wait if args.wait is not None else positive_int(os.environ.get("WB_TEST_SLOT_WAIT", DEFAULT_WAIT), "wait")
    except argparse.ArgumentTypeError as error:
        parser.error(str(error))
    directory = args.dir or default_dir()
    got = acquire(directory, slots, wait, say=lambda m: sys.stderr.write(m + "\n"))
    if got is None:
        sys.stderr.write("test_slots: no test slot became free in %d s (%d slots in %s). Nothing was run and the tests have NOT passed: "
                         "wait for the other runs to finish, or raise WB_TEST_SLOT_WAIT (seconds) or WB_TEST_SLOTS.\n" % (wait, slots, directory))
        return EXIT_NO_SLOT
    fd, index = got
    try:
        os.ftruncate(fd, 0)
        os.write(fd, ("%d %s\n" % (os.getpid(), " ".join(command)[:200])).encode("utf-8", "replace"))  # who holds it, for a person who looks
    except OSError:
        pass
    os.set_inheritable(fd, True)
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        os.execvp(command[0], command)
    except OSError as error:
        sys.stderr.write("test_slots: cannot start %s: %s\n" % (command[0], error))
        return 127


if __name__ == "__main__":
    sys.exit(main())
