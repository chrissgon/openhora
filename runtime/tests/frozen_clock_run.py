"""Starts a provider script with the clock of the test world, for the tests of runtime/ that carry a card out through a real writer. Not a test file.

A writer decides that an occurrence "has already started" with the machine clock. A test world whose clock is a fixed day would then fail the day the real date passes the
instance it cancels. The world starts the writer as `python frozen_clock_run.py <script> <verb> <args>...` with WB_FROZEN_NOW set to the moment (ISO 8601 with an offset); this
file replaces `datetime.datetime.now` and runs the script unchanged. The writers are not touched: nothing here exists outside a test.
"""
import datetime
import os
import runpy
import sys

_REAL = datetime.datetime
_FROZEN = _REAL.fromisoformat(os.environ["WB_FROZEN_NOW"])


class _Frozen(_REAL):
    @classmethod
    def now(cls, tz=None):
        return _FROZEN.astimezone(tz) if tz is not None else _FROZEN.astimezone().replace(tzinfo=None)


datetime.datetime = _Frozen
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
