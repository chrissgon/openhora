"""providers/model/chat-http.py (package ROUTE-REASONING): how `params.reasoning` "off" is sent, by the route's optional `reasoning_off`.

`disable` or no key sends {"enabled": false} (today's body); `minimal` sends {"effort": "minimal"} (an endpoint that answers 400 to a disabled
reasoning); `reasoning` "on" sends no field for either; any other value of the key is a usage error before a connection. The body is read from what the
loopback stand-in was sent and from --dry-run; the oracle's literals are written here. Every name is fictional.
"""
import json

import pytest

from chat_http_stub import request, route, run, stub  # noqa: F401  (stub is a fixture)

DISABLED = {"enabled": False}
MINIMAL = {"effort": "minimal"}


def body_sent(stub):
    assert len(stub.requests) == 1
    return json.loads(stub.requests[0]["body"])


def reasoning_matches(body, expected):
    """The oracle: `expected` None means no reasoning field at all. Raises AssertionError on a mismatch."""
    if expected is None:
        assert "reasoning" not in body, body
    else:
        assert body.get("reasoning") == expected, body


def with_reasoning(rt, value):
    req = request(rt)
    req["params"]["reasoning"] = value
    return req


@pytest.mark.parametrize("over,expected", [({}, DISABLED), ({"reasoning_off": "disable"}, DISABLED), ({"reasoning_off": "minimal"}, MINIMAL)])
def test_off_sends_the_form_the_route_names_and_an_absent_key_is_todays_body(stub, over, expected):
    done = run(["complete"], request(route(stub, **over)))
    assert done.returncode == 0 and done.stderr == ""
    body = body_sent(stub)
    reasoning_matches(body, expected)
    assert set(body) == {"model", "messages", "temperature", "max_tokens", "stream", "provider", "usage", "reasoning"}, "nothing else changes"
    assert body["provider"] == {"order": ["provider-a"], "allow_fallbacks": False, "data_collection": "deny", "zdr": False}


@pytest.mark.parametrize("over", [{}, {"reasoning_off": "disable"}, {"reasoning_off": "minimal"}])
def test_on_sends_no_reasoning_field_whatever_the_key_says(stub, over):
    assert run(["complete"], with_reasoning(route(stub, **over), "on")).returncode == 0
    reasoning_matches(body_sent(stub), None)


@pytest.mark.parametrize("over,expected", [({}, DISABLED), ({"reasoning_off": "minimal"}, MINIMAL)])
def test_the_dry_run_shows_the_same_body(over, expected):
    done = run(["complete", "--dry-run"], request(route(None, **over)), key=None)
    assert done.returncode == 0
    reasoning_matches(json.loads(done.stdout)["would"]["body"], expected)


@pytest.mark.parametrize("bad", ["none", "Minimal", "low", "", None, True, 1, ["minimal"], {"effort": "minimal"}])
def test_an_unknown_value_of_the_key_is_a_usage_error_before_any_connection(stub, bad):
    done = run(["complete"], request(route(stub, reasoning_off=bad)))
    assert done.returncode == 2 and done.stderr == "chat-http: E_USAGE\n" and done.stdout == ""
    assert stub.requests == []


def test_the_key_is_part_of_the_hash_a_route_is_accepted_by(stub):
    """A route accepted without the key is another route when the key is added (the provider hashes what it is given)."""
    accepted = request(route(stub))["accepted"]
    done = run(["complete"], request(route(stub, reasoning_off="minimal"), accepted=accepted))
    assert done.returncode == 3 and done.stderr == "chat-http: E_ROUTE\n"
    assert stub.requests == []


def test_vacuity_the_oracle_fails_on_a_planted_wrong_body():
    """Each wrong body is refused by the oracle, so the tests above can fail: the wrong form, an extra field, a missing field, a field where none is wanted."""
    for body, expected in [({"reasoning": DISABLED}, MINIMAL), ({"reasoning": MINIMAL}, DISABLED), ({"reasoning": {"enabled": False, "effort": "minimal"}}, MINIMAL),
                           ({}, DISABLED), ({"reasoning": DISABLED}, None), ({"reasoning": MINIMAL}, None)]:
        with pytest.raises(AssertionError):
            reasoning_matches(body, expected)
    reasoning_matches({"reasoning": MINIMAL}, MINIMAL)
    reasoning_matches({}, None)


def test_vacuity_a_stand_in_that_ignored_the_key_would_be_caught(stub):
    """With `minimal` the body is not the disabled one: an implementation that sent {"enabled": false} for every row fails this assertion."""
    run(["complete"], request(route(stub, reasoning_off="minimal")))
    with pytest.raises(AssertionError):
        reasoning_matches(body_sent(stub), DISABLED)
