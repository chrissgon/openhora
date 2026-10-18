"""The rotation race of the one Microsoft account record (package ACCT-M). Several provider processes now share the record, and Microsoft replaces
the refresh token on every use, so two refreshes can overlap: both start from the token the record held, each is answered with a new one, and
only one of the two can be written back. The rule (providers/_msgraph.py `store_rotation`): the new token is written only if the record still
holds the token this process used; the loser keeps working with the token it has, which the service leaves valid. These tests run two (and
more) refreshes interleaved against the stand-in token endpoint and assert one write-back and every call succeeding, and the pieces the
rule rests on: the compare-and-write is one step per process, the loser's token still refreshes, and a rotation is written into the record it
came from and no other. No network but loopback, no real account, no real credential.

Run: uv run --with pytest==9.1.1 pytest providers/accounts/tests/test_account_microsoft_rotation.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PROVIDERS = HERE.parents[1]
sys.path.insert(0, str(HERE))
import fake_ms_account  # noqa: E402

_spec = importlib.util.spec_from_file_location("msgraph_for_the_rotation_tests", PROVIDERS / "_msgraph.py")
msgraph = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = msgraph
_spec.loader.exec_module(msgraph)

KEY = ("openhora", "microsoft-account")
PROFILE = msgraph.account_profile(run_hint="uv run x", env_prefix="ACCOUNT_MICROSOFT", user_agent="openhora-test", not_found="not found",
                                  forbidden_hint="forbidden")


class Store:
    """A stand-in secret store: the record, and every write made to it. `delay` widens the window between the comparison and the write."""

    def __init__(self, delay=0.0):
        self.values, self.writes, self.delay = {}, [], delay

    def set_password(self, service, username, value):
        if self.delay:
            time.sleep(self.delay)
        self.writes.append(json.loads(value)["refresh_token"])
        self.values[(service, username)] = value


class Resolver:
    def __init__(self, store):
        self.store = store

    def resolve(self, name, allow_store=True):
        assert name == "MICROSOFT_ACCOUNT_TOKEN"
        found = self.store.values.get(KEY)
        return None if found is None else (found, "secret store")


@pytest.fixture
def fake():
    f = fake_ms_account.FakeMsAccount()
    yield f
    f.close()


@pytest.fixture
def store(fake):
    s = Store()
    s.values[KEY] = fake.account_record_json()
    return s


def graph_get(fake, access):
    graph = msgraph.GraphClient(PROFILE, fake.base, access, True)
    return graph.json("/me", {"$select": "mail"}, "profile get")["mail"]


def refresh(fake, record):
    return msgraph.refresh_access_token(PROFILE, fake.token_url, record)


def write_back(store, record, rotated):
    return msgraph.store_rotation(PROFILE, record, rotated, "secret store", False, lambda: Resolver(store), lambda mode: store)


def test_two_refreshes_interleaved_write_back_once_and_both_calls_succeed(fake, store):
    record_a = msgraph.parse_account_record(PROFILE, store.values[KEY])   # two processes load the same record
    record_b = msgraph.parse_account_record(PROFILE, store.values[KEY])
    access_a, rotated_a = refresh(fake, record_a)                          # A is answered with a new refresh token
    access_b, rotated_b = refresh(fake, record_b)                          # B, before A has written, is answered with another
    assert rotated_a != rotated_b and fake_ms_account.REFRESH_TOKEN not in (rotated_a, rotated_b)
    assert write_back(store, record_a, rotated_a) == "stored"
    assert write_back(store, record_b, rotated_b) == "not stored: the record changed meanwhile"
    assert store.writes == [rotated_a], "one write-back"
    assert json.loads(store.values[KEY])["refresh_token"] == rotated_a
    assert graph_get(fake, access_a) == graph_get(fake, access_b) == fake_ms_account.ADDRESS, "both calls succeed"
    assert [f["refresh_token"] for f in fake.token_forms] == [fake_ms_account.REFRESH_TOKEN] * 2


def test_the_loser_keeps_a_token_that_still_refreshes_and_so_does_the_one_in_the_record(fake, store):
    record_a = msgraph.parse_account_record(PROFILE, store.values[KEY])
    record_b = msgraph.parse_account_record(PROFILE, store.values[KEY])
    _, rotated_a = refresh(fake, record_a)
    _, rotated_b = refresh(fake, record_b)
    write_back(store, record_a, rotated_a)
    assert write_back(store, record_b, rotated_b).startswith("not stored")
    # the loser carried on with the token it had; Microsoft leaves the old one valid, so its next refresh works too
    again = refresh(fake, {**record_b, "refresh_token": rotated_b})
    assert graph_get(fake, again[0]) == fake_ms_account.ADDRESS
    # a process that starts now reads the record and refreshes with the winner's token
    fresh = msgraph.parse_account_record(PROFILE, store.values[KEY])
    assert fresh["refresh_token"] == rotated_a and refresh(fake, fresh)[0]
    # and the original token (the one both started from) is still accepted by the service in this model
    assert refresh(fake, record_a)[0]


@pytest.mark.parametrize("workers", [2, 4])
def test_threads_that_refresh_together_write_back_once_even_when_the_write_is_slow(fake, store, workers):
    """The comparison and the write are one step per process: with a slow write and every thread past its refresh before any writes, a
    lock-free read-compare-write would let all of them write."""
    store.delay = 0.05
    start = threading.Barrier(workers)
    refreshed = threading.Barrier(workers)
    results, failures = [None] * workers, []

    def work(index):
        try:
            record = msgraph.parse_account_record(PROFILE, store.values[KEY])
            start.wait(10)
            access, rotated = refresh(fake, record)
            refreshed.wait(10)                                             # every refresh is answered before any write-back
            outcome = write_back(store, record, rotated)
            results[index] = (outcome, graph_get(fake, access))
        except BaseException as exc:   # a failure in a thread must fail the test, not vanish
            failures.append(repr(exc))

    threads = [threading.Thread(target=work, args=(i,)) for i in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert not failures and None not in results, failures
    outcomes = sorted(outcome for outcome, _ in results)
    assert outcomes == ["not stored: the record changed meanwhile"] * (workers - 1) + ["stored"]
    assert len(store.writes) == 1, "one write-back"
    assert json.loads(store.values[KEY])["refresh_token"] == store.writes[0]
    assert {address for _, address in results} == {fake_ms_account.ADDRESS}, "every call succeeded"
    assert len(fake.token_forms) == workers and {f["refresh_token"] for f in fake.token_forms} == {fake_ms_account.REFRESH_TOKEN}


def test_a_process_that_refreshes_after_the_write_back_carries_the_new_token_forward(fake, store):
    first = msgraph.parse_account_record(PROFILE, store.values[KEY])
    _, rotated_1 = refresh(fake, first)
    assert write_back(store, first, rotated_1) == "stored"
    second = msgraph.parse_account_record(PROFILE, store.values[KEY])
    _, rotated_2 = refresh(fake, second)
    assert write_back(store, second, rotated_2) == "stored"
    assert store.writes == [rotated_1, rotated_2] and fake.token_forms[1]["refresh_token"] == rotated_1


def test_the_write_back_keeps_every_other_field_of_the_record_and_writes_into_the_account_entry_only(fake, store):
    store.values[("openhora", "outlook-mail")] = "legacy-record"
    record = msgraph.parse_account_record(PROFILE, store.values[KEY])
    _, rotated = refresh(fake, record)
    assert write_back(store, record, rotated) == "stored"
    stored = json.loads(store.values[KEY])
    assert {k: v for k, v in stored.items() if k != "refresh_token"} == {k: v for k, v in fake.account_record().items() if k != "refresh_token"}
    assert stored["slot"] == "main" and stored["scope"] == " ".join(fake_ms_account.PLATFORM) and stored["account"] == fake_ms_account.ADDRESS
    assert store.values[("openhora", "outlook-mail")] == "legacy-record"
    assert set(store.values) == {KEY, ("openhora", "outlook-mail")}


def test_a_rotation_is_not_stored_for_a_record_that_did_not_come_from_the_store_or_did_not_change(fake, store):
    record = msgraph.parse_account_record(PROFILE, store.values[KEY])
    _, rotated = refresh(fake, record)
    for where in ("environment", "credentials directory"):
        assert msgraph.store_rotation(PROFILE, record, rotated, where, False, lambda: Resolver(store), lambda mode: store).startswith("not stored")
    assert msgraph.store_rotation(PROFILE, record, rotated, "secret store", True, lambda: Resolver(store), lambda mode: store).startswith("not stored")
    assert msgraph.store_rotation(PROFILE, record, None, "secret store", False, lambda: Resolver(store), lambda mode: store) == "not rotated"
    assert msgraph.store_rotation(PROFILE, record, record["refresh_token"], "secret store", False, lambda: Resolver(store), lambda mode: store) == "not rotated"
    assert store.writes == []


def test_the_lock_is_one_lock_for_the_module_and_does_not_hold_a_failed_write(fake, store):
    record = msgraph.parse_account_record(PROFILE, store.values[KEY])
    _, rotated = refresh(fake, record)

    class Broken(Store):
        def set_password(self, service, username, value):
            raise RuntimeError("locked")

    broken = Broken()
    broken.values[KEY] = store.values[KEY]
    assert write_back(broken, record, rotated).startswith("not stored (RuntimeError)")
    assert msgraph.ROTATION_LOCK.acquire(blocking=False), "a failed write releases the lock"
    msgraph.ROTATION_LOCK.release()
    assert write_back(store, record, rotated) == "stored"
