"""The CDP driver's second contract, with a fake browser pipe: the policy is chosen by the path, the first contract's freeze is byte-identical to what it
always was and an admitted page gets none of it, an uncaught exception and a policy violation are recorded and refused, the page is opened and sought in
the order the contract says. No browser, no network."""
from __future__ import annotations

import base64
import hashlib
import json

import pytest

import renderer_kit  # noqa: F401  (puts the renderer's modules on the path)
import _cdp


class FakeChrome(_cdp.Chrome):
    """A Chrome that was never started: `send` records every command and answers the few the pages need."""

    def __init__(self, tmp_path, serve=None):
        super().__init__("/nonexistent", serve or {}, str(tmp_path))
        self.sent = []
        self.answers = {"Target.createTarget": {"targetId": "T"}, "Target.attachToTarget": {"sessionId": "S"}}

    def send(self, method, params=None, session=None, timeout=60):
        self.sent.append((method, params or {}, session))
        return self.answers.get(method, {})


def headers_of(chrome, url):
    chrome.sent.clear()
    chrome._on_request({"request": {"url": url}, "requestId": "R"}, "S")
    method, params, _ = chrome.sent[-1]
    return method, params


def test_the_first_contracts_freeze_is_byte_identical_to_what_it_always_was():
    assert hashlib.sha256(_cdp.FREEZE_JS.encode()).hexdigest() == "4e02508acfee0afc500a18712d180433da641128b60e0af79a580a0ae521120f"
    assert _cdp.CSP == ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self'; font-src 'self'; connect-src 'none'; "
                        "base-uri 'none'; form-action 'none'")
    assert "window.__csp = [];" in _cdp.CSP_WATCH_JS and "securitypolicyviolation" in _cdp.CSP_WATCH_JS
    assert "Math.random" not in _cdp.CSP_WATCH_JS and "boom" not in _cdp.CSP_WATCH_JS


def test_the_policy_of_an_admitted_page_is_the_one_in_the_decision_and_still_allows_no_connection():
    assert _cdp.CSP_ADMITTED == ("default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; font-src 'self'; "
                                 "connect-src 'none'; base-uri 'none'; form-action 'none'")


def test_the_policy_is_chosen_by_the_path_and_only_html_gets_one(tmp_path):
    serve = {"/t/oh/keyword/renderat.html": (b"<p>a</p>", "text/html; charset=utf-8"), "/h/b0/index.html": (b"<p>b</p>", "text/html; charset=utf-8"),
             "/h/vendor/gsap.min.js": (b"1", "text/javascript"), "/fonts/text.ttf": (b"f", "font/ttf")}
    chrome = FakeChrome(tmp_path, serve)
    csp = lambda p: [h["value"] for h in p["responseHeaders"] if h["name"] == "Content-Security-Policy"]
    method, params = headers_of(chrome, _cdp.ORIGIN + "/t/oh/keyword/renderat.html")
    assert method == "Fetch.fulfillRequest" and csp(params) == [_cdp.CSP]
    assert csp(headers_of(chrome, _cdp.ORIGIN + "/h/b0/index.html?x=1")[1]) == [_cdp.CSP_ADMITTED]
    assert csp(headers_of(chrome, _cdp.ORIGIN + "/h/vendor/gsap.min.js")[1]) == [] and csp(headers_of(chrome, _cdp.ORIGIN + "/fonts/text.ttf")[1]) == []
    assert base64.b64decode(headers_of(chrome, _cdp.ORIGIN + "/h/vendor/gsap.min.js")[1]["body"]) == b"1"
    method, params = headers_of(chrome, _cdp.ORIGIN + "/h/b9/other.html")                  # not served: failed and recorded, whatever the path
    assert method == "Fetch.failRequest" and chrome.blocked == [_cdp.ORIGIN + "/h/b9/other.html"]
    assert headers_of(chrome, "https://example.test/x")[0] == "Fetch.failRequest"


def test_a_page_of_the_first_contract_gets_the_freeze_and_an_admitted_page_only_the_policy_watch(tmp_path):
    chrome = FakeChrome(tmp_path)
    chrome.new_page(1080, 1920)
    chrome.new_page(1080, 1920, contract="admitted")
    sources = [p["source"] for m, p, _ in chrome.sent if m == "Page.addScriptToEvaluateOnNewDocument"]
    assert sources == [_cdp.FREEZE_JS, _cdp.CSP_WATCH_JS]
    with pytest.raises(ValueError):
        chrome.new_page(1080, 1920, contract="other")


def test_an_uncaught_exception_is_recorded_for_its_own_session(tmp_path):
    chrome = FakeChrome(tmp_path)
    chrome._events.put({"method": "Runtime.exceptionThrown", "sessionId": "S1", "params": {"exceptionDetails": {"exception": {"description": "TypeError: x is not a function\n    at a"}}}})
    chrome._events.put({"method": "Runtime.exceptionThrown", "sessionId": "S2", "params": {"exceptionDetails": {"text": "Uncaught"}}})
    chrome._events.put(None)
    chrome._event_loop()
    assert chrome.exceptions == {"S1": ["TypeError: x is not a function"], "S2": ["Uncaught"]}


class FakePage(_cdp.Page):
    def __init__(self, chrome, answers):
        self.c, self.sid, self.contract, self.before = chrome, "S", "admitted", 0
        self.answers, self.expressions = answers, []

    def evaluate(self, expression, await_promise=False, timeout=60):
        self.expressions.append(expression)
        for key, value in self.answers:
            if key in expression:
                return value(len(self.expressions)) if callable(value) else value
        return None

    def screenshot(self, optimize_for_speed=False):
        self.expressions.append("<screenshot>")
        return b"png"


def test_the_state_of_an_admitted_page_refuses_a_violation_a_blocked_request_a_browser_refusal_and_an_exception(tmp_path):
    chrome = FakeChrome(tmp_path)
    page = FakePage(chrome, [("window.__csp", ["http://x connect-src"])])
    with pytest.raises(_cdp.RenderBlocked):
        page._admitted_state(0)
    page = FakePage(chrome, [("window.__csp", [])])
    page._admitted_state(0)
    chrome.blocked.append("https://x/y")
    with pytest.raises(_cdp.RenderBlocked):
        page._admitted_state(0)
    page._admitted_state(1)
    chrome.page_errors.append("network: refused")
    with pytest.raises(_cdp.RenderBlocked):
        page._admitted_state(1)
    chrome.page_errors.clear()
    chrome.exceptions["S"] = ["Error: boom"]
    with pytest.raises(_cdp.BlockFailed):
        page._admitted_state(1)


def test_an_exception_that_follows_a_policy_violation_is_the_violation(tmp_path):
    chrome = FakeChrome(tmp_path)
    chrome.exceptions["S"] = ["TypeError: Failed to fetch"]
    seen = {"n": 0}

    def csp(_n):
        seen["n"] += 1
        return [] if seen["n"] == 1 else ["x connect-src"]
    page = FakePage(chrome, [("window.__csp", csp)])
    with pytest.raises(_cdp.RenderBlocked):
        page._admitted_state(0)


def test_opening_waits_for_the_runtime_checks_the_fonts_then_cuts_the_corner_and_a_runtime_that_never_is_ready_is_block_failed(tmp_path):
    chrome = FakeChrome(tmp_path)
    spec = {"faces": [["oh-text", "500", "normal"]], "system": []}
    page = FakePage(chrome, [("document.readyState", "complete"), ("READY", True), ("window.__csp", [])])
    page.open_admitted("/h/b0/index.html", "READY", spec)
    nav = [p["url"] for m, p, _ in chrome.sent if m == "Page.navigate"]
    assert nav == [_cdp.ORIGIN + "/h/b0/index.html"]
    ex = page.expressions
    order = [next(i for i, e in enumerate(ex) if key in e) for key in ("document.readyState", "READY", "window.__ohFonts = async", "__ohFonts(", "clipPath")]
    assert order == sorted(order) and json.dumps(spec) in ex[order[3]] and ", true)" in ex[order[3]] and _cdp.CLIP_PATH in ex[order[4]]
    page = FakePage(FakeChrome(tmp_path), [("document.readyState", "complete"), ("READY", False), ("window.__csp", [])])
    with pytest.raises(_cdp.BlockFailed):
        page.open_admitted("/h/b0/index.html", "READY", spec, timeout_s=0.3)


def test_a_seek_waits_for_two_frames_checks_the_state_and_the_faces_again_and_returns_the_png(tmp_path):
    chrome = FakeChrome(tmp_path)
    page = FakePage(chrome, [("window.__csp", [])])
    page.fonts = {"faces": [["oh-text", "500", "normal"]], "system": []}
    assert page.seek_admitted(0.5) == b"png"
    ex = page.expressions
    assert "window.__hf.seek(0.5)" in ex[0] and "originalRequestAnimationFrame" in ex[0] and "window.__csp" in ex[1] and ", false)" in ex[2] and ex[3] == "<screenshot>"
