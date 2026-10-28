"""A probe, never merged: it fails only on CI (GITHUB_ACTIONS is set there), to show that the failure re-run of the shards cannot turn a red job green."""
import os


def test_planted_failure_on_ci_only():
    if os.environ.get("GITHUB_ACTIONS") == "true":
        left = [1, 2, 3]
        assert left == [1, 2, 4]
