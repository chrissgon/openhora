"""The golden recording of package P2b: what the upstream receives from each pinned runner of the eval image, through
its key proxy, before package SEC and after package P2b.

Each pinned runner of the image (claude 2.1.283 through the claude-code adapter, opencode 1.18.32 through the agents-dir
adapter) runs in a container, as a held run does, against a stand-in provider that answers with a canned valid
response. The stand-in records every request it receives: the method, the path with its query, the header NAMES and
the values of the headers that are not volatile or credentials, the top-level keys of the body and its "model". The
recording is made once through the key proxy of commit cd161411 (the last before package SEC; its keyproxy.py and its
route files are read from git) and once through the final key proxy, and both are committed in evals/tests/goldens/.

The review's check is the last test: the two recordings are identical except the credential headers package SEC
removes. They are listed in CREDENTIAL_DIFFERENCES below; anything else that differs fails the test.

Tests that record are skipped unless WB_EVAL_DOCKER_TESTS=1 (they need docker and the built image):
  WB_EVAL_DOCKER_TESTS=1 uv run --with pytest pytest evals/tests/test_golden_recording_docker.py
To record the goldens again (a change of a pinned runner, or of the model list, asks for it):
  WB_GOLDEN_WRITE=1 WB_EVAL_DOCKER_TESTS=1 uv run --with pytest pytest evals/tests/test_golden_recording_docker.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("docker_support", Path(__file__).resolve().parent / "docker_support.py")
ds = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ds)
REPO = ds.REPO
GOLDENS = Path(__file__).resolve().parent / "goldens"
BEFORE, AFTER = GOLDENS / "upstream_request_before_sec.json", GOLDENS / "upstream_request_after_p2b.json"
LAST_BEFORE_SEC = "cd161411"
WRITE = os.environ.get("WB_GOLDEN_WRITE") == "1"
DOCKER = pytest.mark.skipif(os.environ.get("WB_EVAL_DOCKER_TESTS") != "1", reason="set WB_EVAL_DOCKER_TESTS=1 (needs docker)")

RUNNERS = {
    "claude": {"model": "claude-sonnet-5-5", "key": "CLAUDE_CODE_OAUTH_TOKEN", "adapter": "claude-code", "route": "anthropic",
               "old_route_file": "keyproxy-strong.json"},
    "opencode": {"model": "openrouter/deepseek/deepseek-v4.1-flash", "key": "OPENROUTER_API_KEY", "adapter": "agents-dir",
                 "route": "openrouter", "old_route_file": "keyproxy.json"},
}
# Values that are different on every run (a session, a request, a clock, a length that follows them) or that name the
# stand-in: recorded as names only. The Authorization the key proxy adds is compared as "the one key it holds".
VOLATILE = {"host", "content-length", "x-claude-code-session-id", "x-session-id", "x-session-affinity", "x-parent-session-id",
            "idempotency-key", "x-request-id", "x-client-request-id", "traceparent", "x-stainless-timeout"}

# The headers package SEC removes from what a runner sends, by their names (the key proxy drops every header whose name
# can carry a credential). A recording through the key proxy before SEC may hold these; the one after never does.
# The runners pinned today send none of them: the placeholder travels in the Authorization header, which both proxies
# replace. The list stays so that a runner that starts sending one is a stated difference and not a failure.
CREDENTIAL_DIFFERENCES = ("x-api-key", "api-key", "x-goog-api-key", "anthropic-auth-token", "cookie", "proxy-authorization")


def shape(item):
    """One request as a recording keeps it."""
    headers = [(k, v) for k, v in item["headers"]]
    return {
        "method": item["method"], "path": item["path"],
        "header_names": sorted({k.lower() for k, _ in headers}),
        "header_values": {k.lower(): v for k, v in sorted(headers) if k.lower() not in VOLATILE and v != "<credential>"},
        "authorization": "the one key the key proxy holds" if item["authorized"] and item["authorizations"] == 1 else f"WRONG: {item['authorizations']}",
        "body_keys": item["body_keys"], "model": item["model"], "stream": item["stream"],
    }


def unique(shapes):
    return sorted({json.dumps(s, sort_keys=True): s for s in shapes}.values(), key=lambda s: json.dumps(s, sort_keys=True))


def old_proxy_files(folder, route_file):
    """The key proxy of the last commit before package SEC, and its route, from git: written into folder."""
    folder.mkdir()
    for name, rel in (("keyproxy.py", "keyproxy.py"), ("route.json", route_file)):
        shown = subprocess.run(["git", "show", f"{LAST_BEFORE_SEC}:evals/container/keyproxy/{rel}"], capture_output=True, text=True,
                               cwd=REPO, timeout=60)
        if shown.returncode != 0:
            pytest.skip(f"commit {LAST_BEFORE_SEC} is not in this checkout (a shallow clone): the before-SEC recording is read from the golden")
        (folder / name).write_text(shown.stdout)
    os.chmod(folder, 0o755)


def record(ex, standin, tmp_path, which, proxy):
    """Run the pinned runner `which` through the key proxy `proxy` ("old" or "final") and return the stand-in's recording of
    what it received: ([shapes], the model names, the runner's exit text)."""
    runner = RUNNERS[which]
    n = ex.names()
    route = ex.route(name=runner["route"])
    run_id = ex.new_run_id()
    names = ex.run_names(run_id)
    root = ds.run_folder(tmp_path, f"run-{which}-{proxy}")
    meter = tmp_path / f"meter-{which}-{proxy}"
    meter.mkdir()
    before = len(standin.seen())
    try:
        if proxy == "final":
            ex.hold(run_id, runner["model"], {runner["key"]: standin.key, "PATH": os.environ["PATH"]}, "proxy", meter_dir=str(meter), upstream=standin.upstream,
                    cafile=standin.cafile, egress=False)
        else:
            old = tmp_path / f"old-{which}"
            old_proxy_files(old, runner["old_route_file"])
            ds.docker("network", "create", "--internal", *ex.labels(run_id), names["network"])
            ds.docker("run", "-d", "--rm", "--init", "--platform", ex.image_platform(), *ex.CONFINED, "--name", names["keys"], *ex.labels(run_id),
                      "--network", ex.route_network(runner["route"], n), "-e", route["secret"], "-v", f"{old}:/old:ro",
                      "-v", f"{standin.cafile}:/etc/keyproxy/upstream-ca.pem:ro", "--entrypoint", "python3", n["keys_image"],
                      "/old/keyproxy.py", "--route", "/old/route.json", "--upstream", standin.upstream, "--cafile", "/etc/keyproxy/upstream-ca.pem",
                      env={route["secret"]: standin.key})
            ds.docker("network", "connect", names["network"], names["keys"])
            for _ in range(100):
                if "keyproxy: listening" in ds.docker("logs", names["keys"], check=False).stderr:
                    break
                time.sleep(0.2)
        adapter = REPO / "adapters" / runner["adapter"] / "run-prompt.sh"
        script = f"bash /wb/run-prompt.sh --prompt-file /eval/prompt.md --cwd /eval/case --model {runner['model']} --out /eval/out; echo rc=$?"
        out = ds.inside(ex, root, script, run_id, runner["model"], runner["key"], standin.key, runner=str(adapter), timeout=600)
        assert "rc=0" in out.stdout, out.stdout + out.stderr + (root / "out" / "stderr.log").read_text(errors="ignore")[-1500:]
        assert "pong from" in (root / "out" / "response.md").read_text()
        proxy_log = ds.docker("logs", names["keys"], check=False).stderr
    finally:
        ex.release(run_id)
    shapes = unique(shape(item) for item in standin.seen()[before:])
    return shapes, sorted({s["model"] for s in shapes if s["model"]}), proxy_log


@pytest.fixture(scope="module")
def ex():
    return ds.load_executor("executor_golden")


@pytest.fixture(scope="module")
def standin(ex, tmp_path_factory):
    ex.ensure()
    n = ex.names()
    provider = ds.Standin(ex, tmp_path_factory.mktemp("standin"), [ex.route_network("anthropic", n), ex.route_network("openrouter", n)]).start()
    try:
        yield provider
    finally:
        provider.stop()


def golden(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_or_compare(path, recorded):
    """The recording on disk is the golden; WB_GOLDEN_WRITE=1 writes it instead of comparing."""
    if WRITE:
        path.write_text(json.dumps(recorded, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return
    assert recorded == golden(path), f"{path.name} differs from what the runner sends now: record it again (see the module's docstring)"


def about(which, proxy):
    runner = RUNNERS[which]
    return {"runner": which, "adapter": runner["adapter"], "model": runner["model"], "proxy": proxy}


@DOCKER
@pytest.mark.parametrize("which", sorted(RUNNERS))
def test_the_request_the_final_key_proxy_forwards_is_the_recorded_one(ex, standin, tmp_path, which):
    shapes, models, log = record(ex, standin, tmp_path, which, "final")
    assert shapes and all(s["authorization"] == "the one key the key proxy holds" for s in shapes), shapes
    # every model name the runner sends is listed: no call to a model endpoint was refused (claude's HEAD /api/hello probe
    # is refused by the path list, before and after SEC alike, and is not a model call)
    assert not [l for l in log.splitlines() if " POST " in l and " 403 " in l], f"the final key proxy refused a model call:\n{log}"
    recorded = golden(AFTER) if AFTER.exists() and not WRITE else {}
    if WRITE:
        recorded = golden(AFTER) if AFTER.exists() else {}
        recorded[which] = {**about(which, "final"), "models": models, "requests": shapes}
        AFTER.write_text(json.dumps(recorded, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return
    assert recorded[which] == {**about(which, "final"), "models": models, "requests": shapes}, \
        f"upstream_request_after_p2b.json differs from what the runner sends now: record it again (see the module's docstring)"


@DOCKER
@pytest.mark.parametrize("which", sorted(RUNNERS))
def test_the_request_the_key_proxy_of_the_last_commit_before_sec_forwarded_is_the_recorded_one(ex, standin, tmp_path, which):
    shapes, models, _ = record(ex, standin, tmp_path, which, "old")
    if WRITE:
        recorded = golden(BEFORE) if BEFORE.exists() else {}
        recorded[which] = {**about(which, f"keyproxy.py of commit {LAST_BEFORE_SEC}"), "models": models, "requests": shapes}
        BEFORE.write_text(json.dumps(recorded, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return
    assert golden(BEFORE)[which] == {**about(which, f"keyproxy.py of commit {LAST_BEFORE_SEC}"), "models": models, "requests": shapes}


# The one header that is not a credential and that the key proxy changes (package P2b, decision of 2026-10-15): the
# upstream is asked only for the encodings the proxy decodes, so that the usage of every response can be read and a run's
# tokens are never taken from what the run reports instead. The value the runners send, and the one the proxy sends.
ENCODING = {"accept-encoding": ("gzip, deflate, br, zstd", "gzip, deflate, identity")}


def without_credentials(requests, before=None):
    """The requests with the headers SEC removes taken out and the Accept-Encoding the key proxy sets left out of the
    values, so that the two recordings can be compared."""
    out = []
    for request in requests:
        dropped = set(CREDENTIAL_DIFFERENCES) | set(ENCODING)
        out.append({**request, "header_names": [h for h in request["header_names"] if h not in dropped],
                    "header_values": {k: v for k, v in request["header_values"].items() if k not in dropped}})
    return out


@pytest.mark.parametrize("which", sorted(RUNNERS))
def test_the_two_recordings_differ_in_the_credential_headers_package_sec_removes_and_in_nothing_else(which):
    before, after = golden(BEFORE)[which], golden(AFTER)[which]
    assert before["model"] == after["model"] and before["adapter"] == after["adapter"]
    assert before["models"] == after["models"], "the model names the runner sends differ"
    assert without_credentials(before["requests"]) == without_credentials(after["requests"])
    for old, new in zip(before["requests"], after["requests"]):  # the allowed difference, with its two values
        for name, (sent, rewritten) in ENCODING.items():
            assert old["header_values"].get(name) == sent and new["header_values"].get(name) == rewritten
            assert name in old["header_names"] and name in new["header_names"]
    # and what differs is what the list names: nothing else was in the before recording that the after one lacks
    names_before = {h for r in before["requests"] for h in r["header_names"]}
    names_after = {h for r in after["requests"] for h in r["header_names"]}
    assert names_before - names_after <= set(CREDENTIAL_DIFFERENCES) and not names_after - names_before
    for request in after["requests"]:
        assert request["authorization"] == "the one key the key proxy holds"  # exactly one Authorization, the key proxy's own
        assert not set(request["header_names"]) & set(CREDENTIAL_DIFFERENCES)


@pytest.mark.parametrize("which", sorted(RUNNERS))
def test_every_model_name_a_runner_sends_is_listed_in_the_gate_file(which):
    """The key proxy refuses a request that names a model its entry does not list: the golden holds every name the pinned
    runner sends, so the committed gate file must list each of them."""
    spec = importlib.util.spec_from_file_location("executor_golden_gate", REPO / "evals" / "executor.py")
    executor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(executor)
    entry = executor.model_entry(RUNNERS[which]["model"])
    sent = set(golden(BEFORE)[which]["models"])
    assert sent <= set(entry["upstream_models"]), f"{which} sends {sorted(sent - set(entry['upstream_models']))}, which the gate file does not list"
