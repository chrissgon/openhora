"""The record of the accepted file in base 64 (S41-10; the rule of the S18 entry of docs/decisions.md: the package that adds the 49th group first moves the record to a denser mask).

Held here: a mask written in base 64 reads back to the same groups for every group and for random sets; the hexadecimal records of versions 2 and 3 are still read as they were written (the test writes
them with its own hexadecimal encoder, never the module's), so a project accepted before is compared with its old record and gets no widening line it did not have; the new versions are 4 (no key) and 5
(keyed); a digit outside the alphabet, an empty mask, a version outside 2 to 5 and a record read by old code (versions 2 and 3 only) fall to "no record" and so to the listing of everything, the safe side;
the worst case the tests build (100 senders, every group) is far under a cursor's 4,096 bytes and keeps room for the groups that will come. Offline.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_policy_widening_mask.py
"""
from __future__ import annotations

import json
import random

import pytest

import standin_tree as st

operations = st.load("operations")
policy_widening = st.load("policy_widening")
project_config = st.load("project_config")

NAMES = list(operations.GROUPS)
ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_"      # the test's own copy of the alphabet: 64 distinct characters that are safe in JSON


def hex_record(snap: dict, version: int) -> str:
    """A record as versions 2 and 3 wrote it, with the test's own encoder: the groups list and one hexadecimal mask for each place."""
    mask = lambda groups: None if groups is None else format(sum(1 << NAMES.index(g) for g in groups), "x")      # noqa: E731
    return json.dumps({"v": version, "groups": NAMES, "channels": {c: mask(v) for c, v in snap["channels"].items()},
                       "senders": {policy_widening.place_id(k, "k" if version == 3 else ""): mask(v) for k, v in snap["senders"].items()}}, sort_keys=True, separators=(",", ":"))


def groups_of(back: dict, channel: str) -> set:
    return set(back["channels"][channel])


def test_the_alphabet_is_sixty_four_distinct_json_safe_characters():
    assert policy_widening.DIGITS64 == ALPHABET and len(set(ALPHABET)) == 64
    assert all(c == json.loads(json.dumps(c)) and c not in '"\\' for c in ALPHABET)


@pytest.mark.parametrize("bits,text", [(0, "0"), (1, "1"), (63, "_"), (64, "10"), (4095, "__"), (4096, "100"), (1 << 48, "1" + "0" * 8)])
def test_a_number_is_written_most_significant_digit_first_at_least_one_digit(bits, text):
    assert policy_widening._digits64(bits) == text


def test_every_group_alone_and_every_group_together_read_back_as_written():
    for name in NAMES:
        snap = {"channels": {"messaging": [name], "page": []}, "senders": {}}
        back = policy_widening.parse(policy_widening.dump(snap))
        assert groups_of(back, "messaging") == {name} and groups_of(back, "page") == set(), name
    snap = {"channels": {"messaging": list(NAMES)}, "senders": {}}
    assert groups_of(policy_widening.parse(policy_widening.dump(snap)), "messaging") == set(NAMES)


def test_random_sets_of_groups_for_channels_and_senders_read_back_as_written_with_and_without_a_key():
    rng = random.Random(41100)
    for secret in ("", "the-projects-key"):
        for _ in range(60):
            snap = {"channels": {c: rng.sample(NAMES, rng.randint(0, len(NAMES))) for c in operations.POLICY_CHANNELS},
                    "senders": {f"telegram:{n}": rng.sample(NAMES, rng.randint(0, len(NAMES))) for n in range(rng.randint(0, 12))}}
            back = policy_widening.parse(policy_widening.dump(snap, secret))
            assert {c: set(v) for c, v in back["channels"].items()} == {c: set(v) for c, v in snap["channels"].items()}
            assert {k: set(v) for k, v in back["sender_ids"].items()} == {policy_widening.place_id(k, secret): set(v) for k, v in snap["senders"].items()}
            assert policy_widening.widening(back, snap, secret) == [], "a record of a file widens nothing over itself"


def test_a_place_with_no_entry_is_none_and_not_an_empty_mask():
    snap = {"channels": {"messaging": None, "page": []}, "senders": {"telegram:1": None}}
    back = policy_widening.parse(policy_widening.dump(snap))
    assert back["channels"] == {"messaging": None, "page": []} and back["sender_ids"] == {policy_widening.place_id("telegram:1"): None}


def test_the_versions_are_4_without_a_key_and_5_with_one():
    snap = {"channels": {"messaging": ["read"]}, "senders": {}}
    assert json.loads(policy_widening.dump(snap))["v"] == 4 and json.loads(policy_widening.dump(snap, "k"))["v"] == 5


@pytest.mark.parametrize("version", [2, 3])
def test_a_record_of_the_hexadecimal_versions_is_still_read_as_it_was_written_and_compares_as_before(version):
    secret = "k" if version == 3 else ""
    old = {"channels": {"messaging": list(operations.DEFAULT_POLICY["messaging"]), "page": ["read", "approve-plans"]}, "senders": {"telegram:1001": ["read", "talk", "interpret"]}}
    record = hex_record(old, version)
    back = policy_widening.parse(record)
    assert back is not None
    assert {c: set(v) for c, v in back["channels"].items()} == {c: set(v) for c, v in old["channels"].items()}
    assert {k: set(v) for k, v in back["sender_ids"].items()} == {policy_widening.place_id("telegram:1001", secret): {"read", "talk", "interpret"}}
    assert policy_widening.widening(back, old, secret) == [], "the same file widens nothing over its own old record"
    wider = {"channels": old["channels"], "senders": {"telegram:1001": ["read", "talk", "interpret", "interpret-fallback"]}}
    assert [(w["place"], w["group"]) for w in policy_widening.widening(back, wider, secret)] == [("telegram:1001", "interpret-fallback")], "and only what is added is listed"


def test_the_digits_of_the_old_and_the_new_versions_are_not_mixed_up():
    """`1f` is 31 in hexadecimal and 70 in base 64: the version decides, and a hexadecimal record never reads as base 64."""
    names = ["read", "talk", "answer", "release", "approve-plans", "approve-acceptances", "brakes"]
    base = {"v": 2, "groups": names, "channels": {"page": "1f"}, "senders": {}}
    assert set(policy_widening.parse(json.dumps(base))["channels"]["page"]) == {"read", "talk", "answer", "release", "approve-plans"}
    dense = dict(base, v=4)
    assert set(policy_widening.parse(json.dumps(dense))["channels"]["page"]) == {"read", "talk", "answer", "release", "brakes"}      # 1 * 64 + 15 = 79 = 0b1001111: bits 0 to 3 and 6


@pytest.mark.parametrize("record", [
    {"v": 4, "groups": NAMES, "channels": {"page": ""}, "senders": {}},
    {"v": 4, "groups": NAMES, "channels": {"page": "a b"}, "senders": {}},
    {"v": 4, "groups": NAMES, "channels": {"page": "!"}, "senders": {}},
    {"v": 4, "groups": NAMES, "channels": {"page": 7}, "senders": {}},
    {"v": 4, "groups": NAMES, "channels": {"page": "0"}, "senders": {"x": "é"}},
    {"v": 2, "groups": NAMES, "channels": {"page": "G"}, "senders": {}},
    {"v": 2, "groups": NAMES, "channels": {"page": "-"}, "senders": {}},
    {"v": 6, "groups": NAMES, "channels": {"page": "0"}, "senders": {}},
    {"v": 1, "groups": NAMES, "channels": {"page": "0"}, "senders": {}},
    {"v": 4, "groups": "read", "channels": {"page": "0"}, "senders": {}},
    {"v": 4, "groups": NAMES, "channels": {"nowhere": "0"}, "senders": {}},
])
def test_a_record_that_is_not_one_this_module_wrote_is_no_record(record):
    assert policy_widening.parse(json.dumps(record)) is None


def test_the_worst_case_is_far_under_the_cursor_and_keeps_room_for_the_next_groups():
    snap = {"channels": {c: list(NAMES) for c in operations.POLICY_CHANNELS}, "senders": {f"{'p' * 32}:{n:064d}": list(NAMES) for n in range(project_config.SENDERS_MAX)}}
    size = len(policy_widening.dump(snap, "the-projects-key").encode())
    assert size < 3700, size
    assert size + 9 * (len("approve-effect-publish") + 4) + 2 * 100 < 4 * 1024, "nine more groups and two more digits on every one of 100 senders still fit (the room was for twelve before CB-5 added three groups)"
    hex_size = len(hex_record(snap, 3).encode())
    assert hex_size > size + 300, "base 64 gives about a third less on the masks"


def test_the_record_is_read_back_whole_for_the_worst_case():
    snap = {"channels": {c: list(NAMES) for c in operations.POLICY_CHANNELS}, "senders": {f"telegram:{n}": list(NAMES) for n in range(project_config.SENDERS_MAX)}}
    back = policy_widening.parse(policy_widening.dump(snap, "k"))
    assert len(back["sender_ids"]) == project_config.SENDERS_MAX and all(set(v) == set(NAMES) for v in back["sender_ids"].values())
