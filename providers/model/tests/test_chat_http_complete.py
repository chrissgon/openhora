"""providers/model/chat-http.py, the paths that succeed: the request it sends, the reply it prints, the dry run and the checks.

Only a stand-in on loopback is reached (chat_http_stub.py); the key is the fake `sk-test-not-a-key`; every name is fictional.
"""
import json

import pytest

from chat_http_stub import FAKE_KEY, request, route, run, sha, stub  # noqa: F401  (stub is a fixture)


def sent(stub):
    assert len(stub.requests) == 1
    return stub.requests[0], json.loads(stub.requests[0]["body"])


def test_a_reply_is_printed_with_its_usage_the_cached_tokens_and_the_provider_in_lower_case(stub):
    rt = route(stub)
    done = run(["complete"], request(rt))
    assert done.returncode == 0 and done.stderr == ""
    out = json.loads(done.stdout)
    assert set(out) == {"v", "text", "finish", "usage", "latency_ms", "upstream"}
    assert out["v"] == 1 and out["text"] == "hello" and out["finish"] == "stop" and out["upstream"] == "provider-a"
    assert out["usage"] == {"input": 120, "output": 7, "cache_read": 100, "cache_write": 20}
    assert isinstance(out["latency_ms"], int) and not isinstance(out["latency_ms"], bool) and out["latency_ms"] >= 0


def test_the_request_is_a_post_with_the_key_the_pin_and_no_fallback(stub):
    rt = route(stub, zdr=True)
    run(["complete"], request(rt))
    first, body = sent(stub)
    assert first["method"] == "POST" and first["path"] == "/v1/chat/completions"
    assert first["headers"]["authorization"] == "Bearer " + FAKE_KEY
    assert body["model"] == "vendor-x/model-a" and body["stream"] is False
    assert body["temperature"] == 0 and body["max_tokens"] == 300
    assert body["provider"] == {"order": ["provider-a"], "allow_fallbacks": False, "data_collection": "deny", "zdr": True}
    assert body["usage"] == {"include": True} and body["reasoning"] == {"enabled": False}
    assert body["messages"] == [{"role": "system", "content": "You are a test system."}, {"role": "user", "content": "A test user line."}]


def test_reasoning_on_sends_no_reasoning_key(stub):
    req = request(route(stub))
    req["params"]["reasoning"] = "on"
    run(["complete"], req)
    assert "reasoning" not in sent(stub)[1]


@pytest.mark.parametrize("breakpoint_on", [False, True])
def test_cache_control_is_sent_only_with_the_cache_breakpoint(stub, breakpoint_on):
    run(["complete"], request(route(stub, cache_breakpoint=breakpoint_on)))
    first, body = sent(stub)
    raw = first["body"].decode("utf-8")
    if breakpoint_on:
        assert body["messages"][0] == {"role": "system", "content": [{"type": "text", "text": "You are a test system.",
                                                                       "cache_control": {"type": "ephemeral"}}]}
        assert raw.count("cache_control") == 1
    else:
        assert "cache_control" not in raw and isinstance(body["messages"][0]["content"], str)
    assert body["messages"][1] == {"role": "user", "content": "A test user line."}


def test_a_route_without_a_pin_still_forbids_fallbacks_and_data_collection(stub):
    run(["complete"], request(route(stub, pin=None)))
    assert sent(stub)[1]["provider"] == {"allow_fallbacks": False, "data_collection": "deny", "zdr": False}


@pytest.mark.parametrize("given,expected", [("stop", "stop"), ("length", "length"), ("content_filter", "other"), (None, "other")])
def test_the_finish_reason_is_one_of_three_words(stub, given, expected):
    doc = {"provider": "x", "choices": [{"finish_reason": given, "message": {"content": "t"}}]}
    stub.reply(200, doc)
    out = json.loads(run(["complete"], request(route(stub, pin=None))).stdout)
    assert out["finish"] == expected


def test_missing_usage_fields_are_null_and_a_missing_provider_is_null(stub):
    stub.reply(200, {"choices": [{"message": {"content": "t"}}], "usage": {"prompt_tokens": 5, "completion_tokens": "7"}})
    out = json.loads(run(["complete"], request(route(stub))).stdout)
    assert out["usage"] == {"input": 5, "output": None, "cache_read": None, "cache_write": None} and out["upstream"] is None


def test_a_dry_run_reads_no_key_and_makes_no_connection_and_prints_what_would_be_sent(stub):
    rt = route(stub, cache_breakpoint=True)
    req = request(rt)
    dry = run(["complete", "--dry-run"], req, key=None)
    assert dry.returncode == 0 and dry.stderr == ""
    out = json.loads(dry.stdout)
    assert stub.requests == []
    assert set(out) == {"would", "would_sha256"} and out["would_sha256"] == sha(out["would"])
    assert out["would"]["method"] == "POST" and out["would"]["url"] == stub.base_url + "/chat/completions"
    assert FAKE_KEY not in dry.stdout and "uthorization" not in dry.stdout
    run(["complete"], req)       # the real request carries exactly the body the dry run showed
    assert sent(stub)[1] == out["would"]["body"]


def test_check_needs_the_key_and_the_network_is_not_used(stub):
    ok = run(["--check"], key=FAKE_KEY)
    assert ok.returncode == 0 and json.loads(ok.stdout) == {"ok": True} and ok.stderr == ""
    missing = run(["--check"], key=None)
    assert missing.returncode == 3 and missing.stdout == "" and missing.stderr == "chat-http: E_KEY\n"
    assert stub.requests == []


def test_help_prints_the_usage_and_exits_zero():
    done = run(["--help"])
    assert done.returncode == 0 and "complete [--dry-run]" in done.stdout and done.stderr == ""


def test_vacuity_a_wrong_expectation_is_caught(stub):
    """The oracle compares literal values: a planted wrong expectation fails."""
    run(["complete"], request(route(stub)))
    with pytest.raises(AssertionError):
        assert sent(stub)[1]["provider"]["order"] == ["another-provider"]
    with pytest.raises(AssertionError):
        assert sent(stub)[0]["headers"]["authorization"] == "Bearer sk-wrong"
