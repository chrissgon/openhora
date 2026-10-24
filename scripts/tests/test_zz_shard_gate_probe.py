import os


def test_the_gate_sees_a_failing_shard():
    assert os.environ.get("WB_FULL_FUZZ") != "1"
