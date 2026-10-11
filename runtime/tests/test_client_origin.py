"""R4-C5: the page's writes carry its real Origin. By the Fetch spec a POST under the referrer policy `no-referrer`
serialises its Origin as `null` (Safari, so a phone, follows it); the service refuses `null`, so the client names
`same-origin`. The service's rule is not widened. Offline.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_client_origin.py
"""
from __future__ import annotations

import os
import re

import pytest

from test_service import PORT, api, call, world  # noqa: F401  (the service fixture)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
JS = os.path.join(ROOT, "interface", "js")


def sources():
    for folder, _, names in os.walk(JS):
        for name in names:
            if name.endswith((".js", ".mjs")):
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as f:
                    yield os.path.relpath(path, ROOT), f.read()


def test_no_request_of_the_page_uses_the_no_referrer_policy():
    seen = list(sources())
    assert seen, "the page's scripts were found"
    for path, text in seen:
        assert not re.search(r"referrerPolicy\s*:\s*[\"']no-referrer", text), path
        assert "referrerPolicy" not in text or path.endswith("api.js"), f"{path}: a request names its policy in the one client only"
    api_js = dict(seen)[os.path.join("interface", "js", "api.js")]
    assert re.findall(r"referrerPolicy\s*:\s*\"([a-z-]+)\"", api_js) == ["same-origin"], "the one fetch path names same-origin"
    assert len(re.findall(r"\bfetch\(", "".join(text for _, text in seen))) == 1, "one fetch path"


@pytest.mark.parametrize("origin", ["null", "NULL", " null"])
def test_the_service_still_refuses_origin_null_on_a_post_and_a_get(world, origin):
    for method, path, body in (("POST", api(world, "/requests"), {"text": "x"}), ("GET", "/api/v1/projects", None)):
        status, _, answer = call(world, method, path, body, extra={"Origin": origin})
        assert (status, answer["error"]) == (403, "origin"), (method, origin)
    assert world.fake.named("request") == []


def test_the_real_origin_of_the_page_reaches_the_operation(world):
    status, _, _ = call(world, "POST", api(world, "/requests"), {"text": "x"}, extra={"Origin": f"http://127.0.0.1:{PORT}"})
    assert status == 200 and world.fake.named("request")
