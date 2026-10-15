"""What the docker tests of the key proxy share: a stand-in provider that answers like the two providers do, a way to
start it on the networks a key proxy reaches its provider on, and the helpers that run a script in a held run's
container. Not a test file. No model and no real provider is called, and every key is a fake one.

The stand-in speaks HTTPS on 8443 with a certificate made for its own name. It writes one line per request to its
log (the method, the path with its query, every header name with its value unless the header can carry a
credential, the top-level keys of the body, the body's model, and whether the one Authorization it received is the
key the test gave the key proxy), and answers a chat completion and a Messages call, streamed or not, with the
fixtures of evals/tests/fixtures/usage/. It never answers with the Authorization it received.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "usage"
CREDENTIAL = re.compile(r"auth|api[-_]?key|token|secret|cookie|credential|password", re.I)

STANDIN_SERVER = r'''
import http.server, json, os, ssl
EXPECTED = "Bearer " + os.environ["STANDIN_EXPECTED_KEY"]
FIXTURES = "/standin/fixtures/"
CREDENTIAL = __import__("re").compile(r"auth|api[-_]?key|token|secret|cookie|credential|password", __import__("re").I)

def fixture(name):
    with open(FIXTURES + name, "rb") as f:
        return f.read()

class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a):
        pass
    def answer(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        try:
            doc = json.loads(body or b"{}")
        except ValueError:
            doc = {}
        doc = doc if isinstance(doc, dict) else {}
        auth = self.headers.get_all("Authorization") or []
        headers = [[k, "<credential>" if CREDENTIAL.search(k) else v] for k, v in self.headers.items()]
        path = self.path.split("?", 1)[0]
        print("seen " + json.dumps({"method": self.command, "path": self.path, "headers": headers, "body_keys": sorted(doc),
                                    "model": doc.get("model"), "stream": doc.get("stream") is True,
                                    "authorized": auth == [EXPECTED], "authorizations": len(auth)}), flush=True)
        stream = doc.get("stream") is True
        if path == "/v1/messages":
            self.reply(200, fixture("anthropic_stream.sse") if stream else fixture("anthropic_message.json"), stream)
        elif path == "/v1/messages/count_tokens":
            self.reply(200, b'{"input_tokens": 10}', False)
        elif path == "/api/v1/chat/completions":
            self.reply(200, fixture("openrouter_stream.sse") if stream else fixture("openrouter_completion.json"), stream)
        else:
            self.reply(404, json.dumps({"path": self.path, "authorized": auth == [EXPECTED]}).encode(), False)
    def reply(self, status, data, stream):
        self.send_response(status)
        self.send_header("Content-Type", "text/event-stream" if stream else "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    do_GET = do_POST = answer

server = http.server.ThreadingHTTPServer(("0.0.0.0", 8443), H)
server.request_queue_size = 128
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain("/standin/cert.pem", "/standin/key.pem")
server.socket = context.wrap_socket(server.socket, server_side=True)
print("standin listening", flush=True)
server.serve_forever()
'''


def load_executor(name="executor_docker_support"):
    spec = importlib.util.spec_from_file_location(name, REPO / "evals" / "executor.py")
    ex = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ex)
    if os.environ.get("WB_EVAL_DOCKER_TESTS") == "1" and not os.environ.get(ex.PLATFORM_ENV):
        try:
            native = subprocess.run(["docker", "version", "--format", "{{.Server.Os}}/{{.Server.Arch}}"],
                                    capture_output=True, text=True, timeout=60).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            native = ""
        if native and native != ex.IMAGE_PLATFORM:
            os.environ[ex.PLATFORM_ENV] = native  # no emulation: the definition is what is under test here
    return ex


def docker(*args, env=None, check=True, timeout=600):
    r = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, env={**os.environ, **(env or {})})
    assert not check or r.returncode == 0, r.stderr
    return r


class Standin:
    """The stand-in provider, a container of the eval image on the networks given (a key proxy reaches its provider on its
    route's network)."""

    def __init__(self, ex, folder, networks):
        if not shutil.which("openssl"):
            pytest.skip("openssl is needed to make the stand-in provider's certificate")
        self.ex, self.networks = ex, list(networks)
        self.name = f"wb-eval-standin-{uuid.uuid4().hex[:8]}"
        self.key = f"fake-provider-key-{uuid.uuid4().hex}"  # the key the key proxy under test holds
        self.folder = Path(folder)
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", f"/CN={self.name}",
                        "-addext", f"subjectAltName=DNS:{self.name}", "-keyout", str(self.folder / "key.pem"),
                        "-out", str(self.folder / "cert.pem")], check=True, capture_output=True)
        (self.folder / "server.py").write_text(STANDIN_SERVER)
        os.chmod(self.folder / "key.pem", 0o644)  # read by the image's user, inside the container only
        shutil.copytree(FIXTURES, self.folder / "fixtures")
        self.cafile = str(self.folder / "cert.pem")
        self.upstream = f"https://{self.name}:8443"

    def start(self):
        n = self.ex.names()
        docker("run", "-d", "--rm", "--platform", self.ex.image_platform(), *self.ex.labels(), "--name", self.name,
               "--network", self.networks[0], "-e", "STANDIN_EXPECTED_KEY", "-v", f"{os.path.realpath(self.folder)}:/standin:ro",
               n["image"], "python3", "/standin/server.py", env={"STANDIN_EXPECTED_KEY": self.key})
        for network in self.networks[1:]:
            docker("network", "connect", network, self.name)
        for _ in range(150):
            if "standin listening" in docker("logs", self.name, check=False).stdout:
                return self
            time.sleep(0.1)
        raise AssertionError(docker("logs", self.name, check=False).stderr)

    def stop(self):
        docker("rm", "-f", self.name, check=False)

    def seen(self):
        """What the stand-in received: one dict per request, oldest first."""
        lines = docker("logs", self.name, check=False).stdout.splitlines()
        return [json.loads(line[5:]) for line in lines if line.startswith("seen ")]


def held_run(ex, standin, model, key_name, key_value, folder, network="proxy", budget=None):
    """hold() for model, with the stand-in in the provider's place and the key proxy reaching it directly: (run id, held)."""
    run_id = ex.new_run_id()
    held = ex.hold(run_id, model, {key_name: key_value, "PATH": os.environ.get("PATH", "")}, network, meter_dir=str(folder),
                   upstream=standin.upstream, cafile=standin.cafile, egress=False, budget=budget)
    return run_id, held


def inside(ex, root, script, run_id, model, key_name, key_value, network="proxy", runner=None, timeout=180):
    """script in the container of the run run_id, started as a held model run is: its key proxy is held_run()'s."""
    # security-scan: allow shell-string -- every script is a literal of the test files, run inside the container
    argv, name = ex.command(["bash", "-c", script], str(root), cwd=str(Path(root) / "case"), env={key_name: key_value},
                            pass_names=[key_name], network=network, runner=runner, model=model, run_id=run_id)
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env={**os.environ, key_name: key_value})
    finally:
        ex.remove(name)


def run_folder(tmp_path, name="eval-run"):
    folder = Path(tmp_path) / name
    (folder / "case").mkdir(parents=True)
    (folder / "out").mkdir()
    (folder / "prompt.md").write_text("Answer with one word.\n")
    return folder


def leftovers(ex, run_ids=None):
    """The containers and networks the harness labelled that are still there: (names of containers, names of networks).
    With run_ids, only those of the runs given."""
    flt = ["--filter", "label=wb.eval=1"]
    containers = docker("ps", "-a", "--format", "{{.Names}}", *flt).stdout.split()
    networks = docker("network", "ls", "--format", "{{.Name}}", *flt).stdout.split()
    if run_ids is not None:
        mine = tuple(run_ids)
        containers = [c for c in containers if c.endswith(mine)]
        networks = [n for n in networks if n.endswith(mine)]
    return containers, networks
