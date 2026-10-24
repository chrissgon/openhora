import os
_seen = []


def test_the_nightly_reruns_a_test_that_fails_once():
    if os.environ.get("WB_FULL_FUZZ") == "1":     # only where the full fuzz is on (the nightly, a whole-suite shard): elsewhere it passes
        _seen.append(1)
        assert len(_seen) > 1


def test_the_nightly_fails_on_a_test_that_always_fails():
    assert os.environ.get("WB_FULL_FUZZ") != "1"
