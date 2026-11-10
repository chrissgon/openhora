"""What the transcriber tests share: a fake `docker` on PATH, builders of whisper.cpp's -ojf document (fictional speech),
the provider module and the fixtures built on them (kept here because every provider suite's conftest.py is the same shared
loopback guard). Nothing here starts a real container or reaches a network."""
import hashlib
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PROVIDER_DIR = HERE.parent
REPO = PROVIDER_DIR.parent.parent


def load_provider():
    spec = importlib.util.spec_from_file_location("transcriber_whispercpp", PROVIDER_DIR / "whispercpp.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- whisper.cpp's -ojf document, as examples/cli/cli.cpp (v1.9.5, output_json) writes it ---------------------------------


def stamp(ms):
    return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def token(text, start=None, end=None, p=0.9, dtw=-1.0, token_id=1000):
    """One entry of a segment's "tokens". start and end are milliseconds; None leaves the offsets out, as whisper does for a
    token it could not time."""
    out = {"text": text}
    if start is not None and end is not None:
        out["timestamps"] = {"from": stamp(start), "to": stamp(end)}
        out["offsets"] = {"from": start, "to": end}
    out.update({"id": token_id, "p": p, "t_dtw": dtw})
    return out


def segment(text, start, end, tokens):
    return {"timestamps": {"from": stamp(start), "to": stamp(end)}, "offsets": {"from": start, "to": end}, "text": text,
            "tokens": tokens}


def document(segments, language="en"):
    return {"systeminfo": "fictional", "model": {"type": "small", "multilingual": True},
            "params": {"model": "/models/model.bin", "language": language, "translate": False},
            "result": {"language": language}, "transcription": segments}


def speech(dtw=False):
    """Three segments of fictional speech: a sentence with punctuation, a silence note, a sentence with a contraction."""
    d = (lambda v: float(v)) if dtw else (lambda v: -1.0)
    first = segment(" Hello there, Ana.", 0, 2400, [
        token("[_BEG_]", 0, 0, 1.0, -1.0, 50364),
        token(" Hello", 320, 720, 0.98, d(33)),
        token(" there", 720, 1040, 0.90, d(75)),
        token(",", 1040, 1100, 0.60, d(104)),
        token(" Ana", 1200, 1700, 0.50, d(120)),
        token(".", 1700, 1760, 0.80, d(172)),
        token("[_TT_120]", 2400, 2400, 1.0, -1.0, 50484)])
    silence = segment(" [BLANK_AUDIO]", 2400, 4000, [
        token(" [", 2400, 2500, 0.7), token("BL", 2500, 2600, 0.7), token("ANK", 2600, 2800, 0.7), token("_", 2800, 2900, 0.7),
        token("AUD", 2900, 3300, 0.7), token("IO", 3300, 3900, 0.7), token("]", 3900, 4000, 0.7)])
    last = segment(" We'll meet at six.", 4000, 6200, [
        token(" We", 4100, 4400, 0.95, d(412)),
        token("'ll", 4400, 4700, 0.85, d(441)),
        token(" meet", 4800, 5200, 0.99, d(478)),
        token(" at", 5200, 5400, 0.99, d(522)),
        token(" six", 5500, 6100, 0.97, d(551)),
        token(".", 6100, 6200, 0.90, d(612))])
    return document([first, silence, last])


# --- the fake docker ----------------------------------------------------------------------------------------------------

FAKE_DOCKER = '''#!{python}
"""A stand-in for the docker client: it logs every call (argv and the names of its environment) and answers from
scenario.json next to it. It starts nothing."""
import json, os, sys, time

here = os.path.dirname(os.path.abspath(__file__))
argv = sys.argv[1:]
with open(os.path.join(here, "calls.jsonl"), "a") as log:
    log.write(json.dumps({{"argv": argv, "env": sorted(os.environ)}}) + "\\n")
scenario = json.load(open(os.path.join(here, "scenario.json")))
verb = argv[0] if argv else ""
if verb == "version":
    if scenario.get("daemon_down"):
        sys.stderr.write("Cannot connect to the Docker daemon\\n"); sys.exit(1)
    print("27.0.0"); sys.exit(0)
if verb == "info":
    print(scenario.get("ncpu", 8)); sys.exit(0)
if verb == "context":
    print(scenario.get("host", "unix:///var/run/docker.sock")); sys.exit(0)
if verb == "ps":
    for line in scenario.get("ps", []):
        print(line)
    sys.exit(0)
if verb == "image" and argv[1] == "inspect":
    image = scenario.get("images", {{}}).get(argv[2])
    if image is None:
        sys.stderr.write("Error: No such image\\n"); sys.exit(1)
    print(json.dumps([{{"Id": image["id"], "Architecture": image.get("arch", "arm64"), "Config": {{"Labels": image["labels"]}}}}])); sys.exit(0)
if verb == "rm":
    sys.exit(0)
if verb == "build":
    build = scenario.get("build", {{}})
    if build.get("exit", 0) != 0:
        sys.stderr.write("build failed\\n"); sys.exit(build["exit"])
    tag = argv[argv.index("--tag") + 1]
    definition = [a.split("=", 1)[1] for a in argv if a.startswith("DEFINITION_HASH=")][0]
    scenario.setdefault("images", {{}})[tag] = {{"id": build["id"], "labels": {{"org.openhora.definition": definition,
        "org.openhora.whisper-cpp.tag": build["tag"], "org.openhora.whisper-cpp.commit": build["commit"],
        "org.openhora.whisper-cpp.cpu-flags.arm64": "-DGGML_CPU_ARM_ARCH=armv8.2-a+dotprod+fp16"}}}}
    json.dump(scenario, open(os.path.join(here, "scenario.json"), "w"))
    sys.stderr.write("fake build output\\n"); sys.exit(0)
if verb == "run":
    run = scenario.get("run", {{}})
    out = [a.split(":")[0] for a in argv if a.endswith(":/out:rw")][0]
    if run.get("pid_file"):
        open(run["pid_file"], "w").write(str(os.getpid()))
    if run.get("sleep"):
        time.sleep(run["sleep"])
    for name, content in run.get("write", {{}}).items():
        path = os.path.join(out, name)
        if content == "@symlink":
            os.symlink("/etc/hostname", path)
        elif content == "@fifo":
            os.mkfifo(path)
        else:
            with open(path, "w") as f:
                f.write(content)
    if run.get("big"):
        with open(os.path.join(out, "big.bin"), "wb") as f:
            f.truncate(run["big"])
    if run.get("stderr"):
        sys.stderr.write(run["stderr"])
    if run.get("spam_kb"):
        line = ("x" * 1023 + "\\n").encode()
        for _ in range(run["spam_kb"]):
            sys.stderr.flush(); sys.stderr.buffer.write(line)
        sys.stderr.buffer.flush()
    if run.get("stderr_hex"):
        sys.stderr.flush(); sys.stderr.buffer.write(bytes.fromhex(run["stderr_hex"])); sys.stderr.buffer.flush()
    sys.exit(run.get("exit", 0))
sys.stderr.write("fake docker: unexpected " + repr(argv) + "\\n"); sys.exit(125)
'''


class Fake:
    """A fake docker binary in a folder of its own, with its scenario and its call log."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        binary = self.folder / "docker"
        binary.write_text(FAKE_DOCKER.format(python=sys.executable))
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
        self.scenario({})

    def scenario(self, value):
        (self.folder / "scenario.json").write_text(json.dumps(value))

    def update(self, **value):
        current = json.loads((self.folder / "scenario.json").read_text())
        current.update(value)
        self.scenario(current)

    def calls(self):
        path = self.folder / "calls.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]

    def verbs(self):
        return [c["argv"][0] for c in self.calls() if c["argv"]]

    def runs(self):
        return [c["argv"] for c in self.calls() if c["argv"][:1] == ["run"]]


def sha256_text(data):
    return hashlib.sha256(data).hexdigest()


# --- fixtures (here and not in conftest.py: every provider suite's conftest.py is the same shared guard) ---------


@pytest.fixture
def provider():
    return load_provider()


@pytest.fixture
def world(tmp_path, monkeypatch, provider):
    """A fake docker first on PATH, a private state folder, a models folder with one fictional model, a models.json that
    pins it, and an input file. Nothing outside tmp_path is read or written."""
    fake = Fake(tmp_path / "bin")
    monkeypatch.setenv("PATH", f"{fake.folder}{os.pathsep}{os.environ['PATH']}")
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(state))
    models = tmp_path / "models"
    models.mkdir(mode=0o700)
    weights = b"fictional model weights"
    (models / "ggml-demo.bin").write_bytes(weights)
    pins = tmp_path / "models.json"
    pins.write_text(json.dumps({"schema_version": 1, "models": [
        {"name": "demo", "file": "ggml-demo.bin", "sha256": hashlib.sha256(weights).hexdigest(), "size": len(weights),
         "dtw_preset": "small", "memory_mb": 1536, "url": "https://example.invalid/ggml-demo.bin"},
        {"name": "later", "file": "ggml-later.bin", "sha256": None, "size": 1, "dtw_preset": "medium", "memory_mb": 2048,
         "url": "https://example.invalid/ggml-later.bin"}]}))
    monkeypatch.setattr(provider, "MODELS_FILE", str(pins))
    audio = tmp_path / "talk.mp4"
    audio.write_bytes(b"\x00\x00\x00\x18ftypmp42 fictional recording")
    ns = type("World", (), {})()
    ns.fake, ns.state, ns.models, ns.pins, ns.input, ns.tmp, ns.provider = fake, state, models, pins, audio, tmp_path, provider
    ns.out = tmp_path / "out" / "transcript.json"
    ns.out.parent.mkdir()
    return ns
