"""providers/model/chat-http.py, KEY-SHAPE (package ACCT-B): the request carries a required `key_prefix` and a key that does not start with it is
refused before any connection, so a credential of another service never reaches this one. The provider names no vendor: the prefix arrives in the
request. Only a stand-in on loopback is reached; every key is fictional and none matches a real credential format.

The oracle counts the connections the stand-in received and reads the child's whole output; the literals below are the test's own.
"""
import json

import pytest

from chat_http_stub import FAKE_KEY, request, route, run, sha, stub  # noqa: F401  (stub is a fixture)

PREFIX = "sk-or-v1-"                  # the shape the runtime sends for the service it routes to; a literal of this test
WRONG = "sk-ant-oat01-AAAA"           # a credential of another service (fictional)
RIGHT = "sk-or-v1-test"
MARKER = "zz-planted-prompt-marker-52"


def req(stub, prefix=PREFIX, **over):
    body = request(route(stub), **over)
    body["key_prefix"] = prefix
    return body


def refused_before_connection(done, stub):
    """The whole of the refusal: exit 3, stderr exactly the code, nothing on stdout, no connection made."""
    return done.returncode == 3 and done.stderr == "chat-http: E_KEY\n" and done.stdout == "" and stub.requests == []


def test_a_key_of_another_service_is_refused_before_any_connection(stub):
    done = run(["complete"], req(stub), key=WRONG)
    assert refused_before_connection(done, stub), (done.returncode, done.stderr, len(stub.requests))
    assert WRONG not in done.stdout + done.stderr


def test_vacuity_a_key_of_the_shape_reaches_the_stand_in_and_the_oracle_sees_the_difference(stub):
    done = run(["complete"], req(stub), key=RIGHT)
    assert done.returncode == 0 and done.stderr == "" and json.loads(done.stdout)["text"] == "hello"
    assert len(stub.requests) == 1 and stub.requests[0]["headers"]["authorization"] == "Bearer " + RIGHT
    assert not refused_before_connection(done, stub), "the oracle must not call a call that connected a refusal"


@pytest.mark.parametrize("key", ["sk-or-v1", "sk-or-v2-test", "SK-OR-V1-test", " sk-or-v1-test", "xsk-or-v1-test", "or-v1-sk-test", "sk-or-v1_test"])
def test_a_key_that_nearly_has_the_prefix_is_refused(stub, key):
    done = run(["complete"], req(stub), key=key)
    assert done.returncode == 3 and done.stderr == "chat-http: E_KEY\n" and done.stdout == "" and stub.requests == []


def test_a_key_that_is_exactly_the_prefix_passes_the_shape_check(stub):
    done = run(["complete"], req(stub), key=PREFIX)
    assert done.returncode == 0 and len(stub.requests) == 1


def test_a_missing_key_is_still_a_key_error_and_connects_to_nothing(stub):
    done = run(["complete"], req(stub), key=None)
    assert refused_before_connection(done, stub)


def test_the_prefix_the_request_carries_decides_and_the_provider_holds_none_of_its_own(stub):
    """The same key is refused under one prefix and accepted under another: the provider has no prefix of its own."""
    assert refused_before_connection(run(["complete"], req(stub, prefix="vk-test-"), key=RIGHT), stub)
    done = run(["complete"], req(stub, prefix="vk-test-"), key="vk-test-12345")
    assert done.returncode == 0 and len(stub.requests) == 1


@pytest.mark.parametrize("prefix", ["abc", "", "x" * 33, 7, None, ["sk-or-v1-"], "sk-\nor-", "sk-\u0000or-"])
def test_a_missing_short_long_or_unprintable_prefix_is_a_usage_error(stub, prefix):
    body = req(stub)
    body["key_prefix"] = prefix
    done = run(["complete"], body, key=RIGHT)
    assert done.returncode == 2 and done.stderr == "chat-http: E_USAGE\n" and done.stdout == "" and stub.requests == []


def test_a_request_without_the_key_prefix_key_is_a_usage_error(stub):
    body = req(stub)
    del body["key_prefix"]
    done = run(["complete"], body, key=RIGHT)
    assert done.returncode == 2 and done.stderr == "chat-http: E_USAGE\n" and stub.requests == []
    body = req(stub)
    body["extra"] = 1
    done = run(["complete"], body, key=RIGHT)
    assert done.returncode == 2 and stub.requests == [], "the request is closed: an extra top-level key is refused too"


@pytest.mark.parametrize("prefix", ["abcd", "x" * 32])
def test_a_prefix_of_four_and_of_thirty_two_characters_is_accepted(stub, prefix):
    done = run(["complete"], req(stub, prefix=prefix), key=prefix + "tail")
    assert done.returncode == 0 and len(stub.requests) == 1


def test_the_prefix_is_not_part_of_the_route_its_hash_or_the_body_sent_upstream(stub):
    rt = route(stub)
    assert "key_prefix" not in rt
    body = req(stub)
    assert body["accepted"] == [sha(rt)], "the hash is over the route alone"
    done = run(["complete"], body, key=RIGHT, extra_env=None)
    assert done.returncode == 0
    sent = json.loads(stub.requests[0]["body"])
    assert PREFIX not in stub.requests[0]["body"].decode("utf-8") and "key_prefix" not in sent
    assert set(sent) == {"model", "messages", "temperature", "max_tokens", "stream", "provider", "usage", "reasoning"}


def test_the_dry_run_reads_no_key_and_still_checks_the_prefix(stub):
    done = run(["complete", "--dry-run"], req(stub), key=WRONG)
    assert done.returncode == 0 and "would" in json.loads(done.stdout) and stub.requests == []
    body = req(stub)
    del body["key_prefix"]
    done = run(["complete", "--dry-run"], body, key=None)
    assert done.returncode == 2 and done.stderr == "chat-http: E_USAGE\n"


def test_the_refusal_prints_neither_the_key_nor_the_prompt(stub):
    done = run(["complete"], req(stub, system="system " + MARKER, user="user " + MARKER), key=WRONG)
    assert refused_before_connection(done, stub)
    assert [m for m in (WRONG, FAKE_KEY, MARKER) if m in done.stdout + done.stderr] == []


def test_the_check_flag_is_unchanged_by_the_prefix():
    assert run(["--check"], key=RIGHT).returncode == 0
    done = run(["--check"], key=None)
    assert done.returncode == 3 and done.stderr == "chat-http: E_KEY\n"
