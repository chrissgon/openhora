"""A pytest plugin that keeps one shard of the collected tests: with `--wb-shard K/N`, the items at positions i (0-based, in the
order pytest collected them and the other plugins left them) with i % N == K - 1. The others are reported as deselected.
Without the option it does nothing.

CI's whole suite runs as N jobs, one per K (.github/workflows/checks.yml, the job tests-shard). Every collected item is in exactly
one shard by construction, and a new test file is collected as before, so it is never left out. Every shard collects the same items:
the same commit, image, environment and targets, and pytest-xdist already refuses workers that collect differently.
It is loaded by scripts/shard_tests.py, never by a conftest. Python 3.9 compatible; standard library and pytest only.
"""
from __future__ import annotations

import pytest

OPTION = "--wb-shard"


def parse(text):
    """(K, N) from "K/N" with 1 <= K <= N; ValueError otherwise."""
    k, sep, n = (text or "").partition("/")
    if not (sep and k.isdigit() and n.isdigit()) or not 1 <= int(k) <= int(n):
        raise ValueError(f"{OPTION} takes K/N with 1 <= K <= N, not {text!r}")
    return int(k), int(n)


def split(items, k, n):
    """(kept, deselected): the items whose position i has i % n == k - 1, and the rest, both in their order."""
    kept = [item for i, item in enumerate(items) if i % n == k - 1]
    dropped = [item for i, item in enumerate(items) if i % n != k - 1]
    return kept, dropped


def pytest_addoption(parser):
    parser.addoption(OPTION, default=None, metavar="K/N", help="keep the K-th of N shards of the collected tests")


def pytest_configure(config):
    text = config.getoption(OPTION)
    if text is not None:
        try:
            parse(text)
        except ValueError as e:
            raise pytest.UsageError(str(e))


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(session, config, items):
    text = config.getoption(OPTION)
    if text is None:
        return
    k, n = parse(text)
    kept, dropped = split(items, k, n)
    items[:] = kept
    if dropped:
        config.hook.pytest_deselected(items=dropped)
