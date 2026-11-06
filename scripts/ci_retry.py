#!/usr/bin/env python3
"""Run a command again, a bounded number of times with a growing wait, when it fails: for the CI steps that build a container
image from the dated Debian snapshot archive, whose server answers a build now and then with an error that a second try does not
meet (a 504, a reset connection: apt's own `Acquire::Retries` does not cover every one of them, and the build exits 100).

Usage:
  python3 scripts/ci_retry.py [--attempts N] [--delay SECONDS] [--max-delay SECONDS] [--attempt-timeout SECONDS] -- COMMAND [ARG...]

  --attempts N           the most times COMMAND runs (default 3, at least 1)
  --delay S              the wait before the second attempt, in seconds (default 60); each later wait doubles it
  --max-delay S          the longest wait between two attempts (default 300)
  --attempt-timeout S    the most seconds one attempt may take; an attempt still running then is stopped, with every process it
                         started, and counts as failed (default: no limit)

COMMAND's output is not captured: it goes to the log as it is written. Before each attempt after the first, and when the last
one failed, a line says so on stderr, as a GitHub Actions annotation (`::warning::`, `::error::`), so that a retry is seen in the
run's summary and a job that passed on its second attempt is never mistaken for one that never failed.

Any failure is tried again, not only a transient one: the error a build prints does not tell the two apart (apt exits 100 for a
missing package and for a 504 alike). A definition that is really broken fails every attempt, so a retry can never turn a red
job green; what it costs then is the time of the extra attempts, bounded by --attempts and --attempt-timeout.

Exit codes: COMMAND's own of the last attempt (124 when the last attempt timed out); 2 for a bad option; 127 when COMMAND cannot
be started (not retried: a missing program does not come back).
Standard library only; Python 3.9 compatible.
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time

EXIT_USAGE = 2
EXIT_TIMEOUT = 124  # what timeout(1) answers
EXIT_NOT_FOUND = 127


def parse(argv):
    if "--" not in argv:
        if argv in (["--help"], ["-h"]):
            print(__doc__.strip())
            sys.exit(0)
        print("ci_retry: give the command after `--` (see --help)", file=sys.stderr)
        sys.exit(EXIT_USAGE)
    cut = argv.index("--")
    own, command = argv[:cut], argv[cut + 1:]
    parser = argparse.ArgumentParser(prog="ci_retry.py", add_help=True, description="Run a command again when it fails.")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--delay", type=float, default=60.0)
    parser.add_argument("--max-delay", type=float, default=300.0)
    parser.add_argument("--attempt-timeout", type=float, default=None)
    args = parser.parse_args(own)
    if not command:
        parser.error("no command after `--`")
    if args.attempts < 1:
        parser.error("--attempts must be at least 1")
    if args.delay < 0 or args.max_delay < 0 or (args.attempt_timeout is not None and args.attempt_timeout <= 0):
        parser.error("--delay and --max-delay must be 0 or more, --attempt-timeout more than 0")
    return args, command


def waits(attempts, delay, max_delay):
    """The wait before each attempt after the first: delay, then doubled each time, never above max_delay."""
    return [min(delay * (2 ** i), max_delay) for i in range(attempts - 1)]


def run_once(command, timeout):
    """COMMAND's exit code; EXIT_TIMEOUT when it ran past the timeout, after its whole process group was stopped."""
    proc = subprocess.Popen(command, start_new_session=True)  # its own group: a timeout stops what it started too
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        for sig, grace in ((signal.SIGTERM, 10), (signal.SIGKILL, 10)):
            try:
                os.killpg(proc.pid, sig)
            except ProcessLookupError:
                break
            try:
                proc.wait(timeout=grace)
                break
            except subprocess.TimeoutExpired:
                continue
        return EXIT_TIMEOUT


def say(level, text):
    print(f"::{level}::ci_retry: {text}", file=sys.stderr, flush=True)


def main(argv=None, sleep=time.sleep):
    args, command = parse(sys.argv[1:] if argv is None else argv)
    shown = " ".join(command)
    pauses = waits(args.attempts, args.delay, args.max_delay)
    code = 0
    for attempt in range(1, args.attempts + 1):
        if attempt > 1:
            pause = pauses[attempt - 2]
            say("warning", f"attempt {attempt - 1} of {args.attempts} failed (exit {code}); attempt {attempt} in {pause:g} s: {shown}")
            sleep(pause)
        try:
            code = run_once(command, args.attempt_timeout)
        except OSError as e:
            say("error", f"cannot start the command ({type(e).__name__}: {e}): {shown}")
            return EXIT_NOT_FOUND
        if code == 0:
            if attempt > 1:
                say("warning", f"passed on attempt {attempt} of {args.attempts}: {shown}")
            return 0
        if code == EXIT_TIMEOUT and args.attempt_timeout is not None:
            print(f"ci_retry: attempt {attempt} ran past {args.attempt_timeout:g} s and was stopped", file=sys.stderr, flush=True)
    say("error", f"failed on every one of {args.attempts} attempts (last exit {code}): {shown}")
    return code


if __name__ == "__main__":
    sys.exit(main())
