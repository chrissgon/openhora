"""providers/model/chat-http.py, the paths that fail: every code with its exit, the refusals before any connection, and the secrecy of the
output. Only a stand-in on loopback is reached; the key is the fake `sk-test-not-a-key`; every name is fictional.
"""
import json
import socket
import subprocess
import sys
import textwrap
import time

import pytest

from chat_http_stub import CHAT, FAKE_KEY, Trickle, leaked, request, route, run, sha, stub  # noqa: F401  (stub is a fixture)

BODY_MARKER = "zz-planted-body-marker-91"       # planted in what a service answers
PROMPT_MARKER = "zz-planted-prompt-marker-47"    # planted in what the person's prompt says
MARKERS = [FAKE_KEY, BODY_MARKER, PROMPT_MARKER]


def fails(done, code, exit_code):
    """The whole of a failure: one line on stderr, nothing on stdout, the exit of the code."""
    assert done.stderr == f"chat-http: {code}\n" and done.stdout == "", (done.stdout, done.stderr)
    assert done.returncode == exit_code
    assert leaked(MARKERS, done.stdout, done.stderr) == []


def secret_request(rt, **over):
    return request(rt, system="system " + PROMPT_MARKER, user="user " + PROMPT_MARKER, **over)


@pytest.mark.parametrize("status,code", [(429, "E_RATE"), (500, "E_UPSTREAM"), (503, "E_UPSTREAM"), (400, "E_HTTP"), (401, "E_HTTP"),
                                         (404, "E_HTTP"), (204, "E_HTTP")])
def test_a_status_has_its_code_and_the_body_of_the_error_never_leaves(stub, status, code):
    stub.reply(status, {"error": {"message": BODY_MARKER + " " + FAKE_KEY + " " + PROMPT_MARKER}} if status != 204 else b"")
    fails(run(["complete"], secret_request(route(stub))), code, 1)


def test_a_redirect_is_not_followed(stub):
    stub.reply(302, b"", headers={"Location": stub.base_url + "/elsewhere"})
    fails(run(["complete"], secret_request(route(stub))), "E_HTTP", 1)
    assert [r["path"] for r in stub.requests] == ["/v1/chat/completions"]


@pytest.mark.parametrize("body", [BODY_MARKER, b"[]", '{"choices": []}', '{"choices": [{}]}', '{"choices": [{"message": {"content": null}}]}',
                                  '{"choices": [{"message": {"content": ["a"]}}]}', '{"choices": "x"}', b"\xff\xfe"])
def test_a_reply_that_is_not_a_text_is_an_invalid_response(stub, body):
    stub.reply(200, body)
    fails(run(["complete"], secret_request(route(stub))), "E_RESPONSE", 1)


def test_a_reply_over_the_size_limit_is_refused_and_one_at_the_limit_is_not(stub):
    pad = "x" * 70000
    stub.ok(content=pad + BODY_MARKER)
    fails(run(["complete"], secret_request(route(stub))), "E_RESPONSE", 1)
    small = json.dumps({"choices": [{"message": {"content": "ok"}}], "pad": ""})
    stub.reply(200, small.replace('"pad": ""', '"pad": "' + "y" * (65536 - len(small)) + '"'))
    assert len(stub.body) == 65536
    assert json.loads(run(["complete"], secret_request(route(stub))).stdout)["text"] == "ok"


def test_a_reply_from_another_provider_than_the_pin_is_refused_and_its_text_is_not_printed(stub):
    stub.ok(content=BODY_MARKER, provider="Another-Provider")
    fails(run(["complete"], secret_request(route(stub))), "E_PIN", 1)


def test_a_reply_that_names_the_pin_in_other_case_passes_and_a_route_without_a_pin_accepts_any(stub):
    stub.ok(provider="PROVIDER-A")
    assert run(["complete"], request(route(stub))).returncode == 0
    stub.ok(provider="Anyone")
    assert run(["complete"], request(route(stub, pin=None))).returncode == 0


def test_a_slow_service_is_a_timeout(stub):
    stub.ok()
    stub.delay = 3.0
    fails(run(["complete"], secret_request(route(stub), deadline_ms=300)), "E_TIMEOUT", 1)


def test_a_closed_port_is_a_network_error():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    rt = route(base_url=f"http://127.0.0.1:{port}/v1")
    fails(run(["complete"], secret_request(rt)), "E_NETWORK", 1)


def test_a_missing_or_malformed_key_is_refused_before_any_connection(stub):
    for key in (None, "", "two words", "line\nbreak"):
        fails(run(["complete"], secret_request(route(stub)), key=key), "E_KEY", 3)
    assert stub.requests == []


@pytest.mark.parametrize("make", [
    lambda s: (route(s), []),                                              # no route is accepted
    lambda s: (route(s), [sha(route(s, model="other/model"))]),            # another route is
    lambda s: (route(s, allow_fallbacks=True), None),                      # accepted by hash, still refused: fallbacks
    lambda s: (route(s, data_collection="allow"), None),                   # accepted by hash, still refused: data collection
    lambda s: (route(s, base_url="https://user:pw@127.0.0.1:9/v1"), None),
    lambda s: (route(s, base_url="https://127.0.0.1:9/v1?x=1"), None),
    lambda s: (route(s, base_url="ftp://127.0.0.1:9/v1"), None),
    lambda s: (route(s, base_url="http://192.0.2.1:9/v1"), None),          # http to a host that is not loopback
])
def test_a_route_that_was_not_accepted_or_that_widens_is_refused_before_any_connection(stub, make):
    rt, accepted = make(stub)
    fails(run(["complete"], secret_request(rt, accepted=accepted)), "E_ROUTE", 3)
    assert stub.requests == []


def test_http_is_refused_without_the_loopback_switch_and_the_switch_does_not_open_other_hosts(stub):
    fails(run(["complete"], secret_request(route(stub)), loopback=False), "E_ROUTE", 3)
    fails(run(["complete"], secret_request(route(base_url="http://example.invalid/v1")), loopback=True), "E_ROUTE", 3)
    fails(run(["complete"], secret_request(route(stub)), extra_env={"MODEL_TEXT_LOOPBACK_TEST": "yes"}, loopback=False), "E_ROUTE", 3)
    assert stub.requests == []


@pytest.mark.parametrize("mutate", [
    lambda r: r.pop("system"), lambda r: r.update(v=2), lambda r: r.update(extra=1), lambda r: r["route"].pop("pin"),
    lambda r: r["route"].update(zdr="yes"), lambda r: r["route"].update(extra=1), lambda r: r.update(deadline_ms=0),
    lambda r: r.update(deadline_ms=True), lambda r: r.update(deadline_ms=600001), lambda r: r["params"].update(reasoning="max"),
    lambda r: r["params"].update(max_tokens=0), lambda r: r["params"].update(temperature=3), lambda r: r["params"].update(temperature=True),
    lambda r: r.update(accepted="abc"), lambda r: r.update(user=5),
])
def test_a_malformed_request_is_a_usage_error_and_nothing_is_sent(stub, mutate):
    req = secret_request(route(stub))
    mutate(req)
    fails(run(["complete"], req), "E_USAGE", 2)
    assert stub.requests == []


@pytest.mark.parametrize("args,raw", [(["complete"], "not json " + PROMPT_MARKER), (["complete"], ""), (["complete"], "[]"), (["complete", "--bogus"], "{}"),
                                      (["nope"], ""), ([], ""), (["complete"], "x" * 1048577)])
def test_a_bad_command_or_input_is_a_usage_error(args, raw):
    fails(run(args, raw=raw), "E_USAGE", 2)


@pytest.mark.parametrize("where", ["system", "user"])
def test_a_lone_surrogate_in_the_text_is_a_usage_error_and_nothing_is_sent(stub, where):
    req = secret_request(route(stub))
    text = json.dumps(req).replace(f'"{where}": "{where} ', f'"{where}": "\\ud800 ')
    assert "\\ud800" in text
    fails(run(["complete"], raw=text), "E_USAGE", 2)
    assert stub.requests == []


def test_an_unexpected_failure_is_an_internal_error_with_no_trace(stub, tmp_path):
    """A copy of the provider with a planted fault that carries the key, a body marker and the prompt in its message: only the code leaves."""
    source = CHAT.read_text(encoding="utf-8")
    assert "def canonical(obj) -> bytes:\n" in source
    planted = source.replace("def canonical(obj) -> bytes:\n", "def canonical(obj) -> bytes:\n    raise RuntimeError(%r + __import__('os').environ['MODEL_TEXT_KEY'])\n" % (BODY_MARKER + PROMPT_MARKER))
    copy = tmp_path / "planted.py"
    copy.write_text(planted, encoding="utf-8")
    fails(run(["complete"], secret_request(route(stub)), script=copy), "E_INTERNAL", 1)
    assert stub.requests == []


def test_the_reply_is_printed_in_ascii_so_no_text_can_fail_to_encode(stub):
    stub.ok(content="caf\u00e9 \u4e2d \U0001f600 \ud800")
    done = run(["complete"], request(route(stub)))
    assert done.returncode == 0 and done.stdout.isascii()
    assert json.loads(done.stdout)["text"] == "caf\u00e9 \u4e2d \U0001f600 \ud800"


@pytest.mark.parametrize("mode", ["headers", "body"])
def test_a_service_that_trickles_a_byte_at_a_time_is_cut_at_the_deadline(mode):
    trickle = Trickle(mode)
    try:
        start = time.monotonic()
        done = run(["complete"], secret_request(route(base_url=trickle.base_url), deadline_ms=1000), timeout=15)
        took = time.monotonic() - start
    finally:
        trickle.close()
    fails(done, "E_TIMEOUT", 1)
    assert took < 4.0, took


def test_vacuity_without_the_watchdog_the_trickle_outlasts_the_deadline(tmp_path):
    """The same test on a copy of the provider whose watchdog is switched off does not end by itself within four seconds."""
    source = CHAT.read_text(encoding="utf-8")
    assert 'armed = hasattr(signal, "setitimer")' in source
    copy = tmp_path / "no_watchdog.py"
    copy.write_text(source.replace('armed = hasattr(signal, "setitimer")', "armed = False"), encoding="utf-8")
    trickle = Trickle("body")
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            run(["complete"], secret_request(route(base_url=trickle.base_url), deadline_ms=1000), script=copy, timeout=4)
    finally:
        trickle.close()


def test_a_success_never_prints_the_key_or_the_prompt_either(stub):
    done = run(["complete"], secret_request(route(stub)))
    assert done.returncode == 0 and leaked([FAKE_KEY, PROMPT_MARKER], done.stdout, done.stderr) == []


def test_vacuity_the_secrecy_oracle_catches_a_provider_that_leaks(tmp_path):
    """A copy of the provider that prints the key, a body byte and the prompt on stderr is caught by the same oracle."""
    assert leaked(MARKERS, "x " + BODY_MARKER) == [BODY_MARKER] and leaked(MARKERS, "clean") == []
    leaky = tmp_path / "leaky.py"
    leaky.write_text(textwrap.dedent("""
        import os, sys
        sys.stdin.read()
        sys.stderr.write("chat-http: E_HTTP " + os.environ["MODEL_TEXT_KEY"] + " %s %s\\n")
        sys.exit(1)
    """ % (BODY_MARKER, PROMPT_MARKER)))
    done = run(["complete"], request(route()), script=leaky)
    assert sorted(leaked(MARKERS, done.stdout, done.stderr)) == sorted(MARKERS)
    with pytest.raises(AssertionError):
        fails(done, "E_HTTP", 1)
    assert sys.version_info >= (3, 9)
