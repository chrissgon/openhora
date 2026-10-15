"""Offline tests of evals/executor.py: what a container is given, and nothing more. No docker is called.

Run: uv run --with pytest pytest evals/tests/test_executor.py
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "executor.py"
spec = importlib.util.spec_from_file_location("executor", SCRIPT)
ex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ex)


def run_folder(tmp_path):
    root = tmp_path / "eval-abc"
    (root / "case").mkdir(parents=True)
    (root / "out").mkdir()
    (root / "prompt.md").write_text("hello\n")
    skill = tmp_path / "skills" / "core-demo"
    skill.mkdir(parents=True)
    return root, skill


def mounted(argv):
    return [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]


def test_the_definition_hash_follows_the_files_and_names_everything(tmp_path):
    (tmp_path / "proxy").mkdir()
    (tmp_path / "Dockerfile").write_text("FROM scratch\n")
    (tmp_path / "proxy" / "allow.txt").write_text("^model\\.example$\n")
    first = ex.definition_hash(str(tmp_path))
    assert first == ex.definition_hash(str(tmp_path)) and len(first) == 64
    (tmp_path / "proxy" / "allow.txt").write_text("^other\\.example$\n")
    second = ex.definition_hash(str(tmp_path))
    assert second != first
    n = ex.names(str(tmp_path))
    assert all(second[:12] in value for value in n.values())
    assert set(n) == {"image", "proxy_image", "network", "proxy", "keys_image", "keys", "open_network", "keys_strong",
                      "strong_network", "strong_open_network", "held_network", "strong_held_network", "keys_network"}


def test_a_command_sees_the_run_folder_and_the_one_adapter_script_and_nothing_else(tmp_path):
    root, skill = run_folder(tmp_path)
    adapter = tmp_path / "adapters" / "demo"
    adapter.mkdir(parents=True)
    runner = adapter / "run-prompt.sh"
    runner.write_text("exit 0\n")
    (adapter / "README.md").write_text("how the harness is judged\n")
    cmd = ["bash", str(runner), "--prompt-file", str(root / "prompt.md"), "--cwd", str(root / "case"), "--out", str(root / "out"),
           "--model", "m"]
    argv, name = ex.command(cmd, str(root), cwd=str(root), runner=str(runner), network="proxy")
    inside = argv[argv.index(ex.names()["image"]) + 1:]
    assert inside == ["bash", "/wb/run-prompt.sh", "--prompt-file", "/eval/prompt.md", "--cwd", "/eval/case",
                      "--out", "/eval/out", "--model", "m"]
    targets = {m.split(":")[1]: m for m in mounted(argv)}
    assert set(targets) == {"/eval", "/wb/run-prompt.sh"}  # no adapters folder, no skill folder, no shared folder
    assert targets["/wb/run-prompt.sh"].split(":")[0] == os.path.realpath(runner)  # the file, not its folder
    assert not targets["/eval"].endswith(":ro") and targets["/wb/run-prompt.sh"].endswith(":ro")
    assert str(skill) not in " ".join(argv) and "--tmpfs" not in argv
    home = os.path.realpath(os.path.expanduser("~"))
    assert all(m.split(":")[0] != home and not home.startswith(m.split(":")[0] + os.sep) for m in mounted(argv))
    assert argv[argv.index("-w") + 1] == "/eval" and name.startswith("wb-eval-run-") and name in argv
    assert "--rm" in argv and "--privileged" not in argv


def pairs(argv):
    return [argv[i:i + 2] for i in range(len(argv) - 1)]


def test_a_container_starts_with_no_capability_no_way_to_gain_one_and_a_process_limit(tmp_path):
    root, _ = run_folder(tmp_path)
    argv, _ = ex.command(["true"], str(root))
    before_image = argv[:argv.index(ex.names()["image"])]
    assert ["--cap-drop", "ALL"] in pairs(before_image) and ["--security-opt", "no-new-privileges"] in pairs(before_image)
    assert ["--pids-limit", str(ex.PIDS_LIMIT)] in pairs(before_image) and 256 <= ex.PIDS_LIMIT <= 32768
    assert "--cap-add" not in argv and not any(a.startswith("seccomp=unconfined") for a in argv)


def test_the_clock_and_the_identity_are_the_images_and_never_the_callers(tmp_path):
    root, _ = run_folder(tmp_path)
    env = {"TZ": "America/Sao_Paulo", "GIT_AUTHOR_NAME": "someone", "GIT_AUTHOR_EMAIL": "s@host.example",
           "GIT_COMMITTER_NAME": "someone", "GIT_COMMITTER_EMAIL": "s@host.example", "LANG": "pt_BR.UTF-8",
           "GIT_ALLOW_PROTOCOL": "file", "GIT_TERMINAL_PROMPT": "0"}
    argv, _ = ex.command(["true"], str(root), env=env)
    joined = " ".join(argv)
    assert "Sao_Paulo" not in joined and "someone" not in joined and "pt_BR" not in joined
    assert "GIT_ALLOW_PROTOCOL=file" in argv and "GIT_TERMINAL_PROMPT=0" in argv
    dockerfile = (Path(ex.DEFINITION) / "Dockerfile").read_text()
    for setting in ("TZ=UTC", "LANG=C.UTF-8", "USER=eval", "PYTHONDONTWRITEBYTECODE=1"):
        assert setting in dockerfile
    assert "ARG DEBIAN_FRONTEND" in dockerfile and "ENV DEBIAN_FRONTEND" not in dockerfile


def test_the_image_is_built_and_run_for_one_platform_and_another_one_gets_another_name(tmp_path, monkeypatch):
    root, _ = run_folder(tmp_path)
    monkeypatch.delenv(ex.PLATFORM_ENV, raising=False)
    assert ex.IMAGE_PLATFORM == "linux/arm64" and ex.image_platform() == "linux/arm64"
    argv, _ = ex.command(["true"], str(root))
    assert ["--platform", "linux/arm64"] in pairs(argv)
    evidence_names = ex.names()
    monkeypatch.setenv(ex.PLATFORM_ENV, "linux/amd64")
    argv, _ = ex.command(["true"], str(root))
    assert ["--platform", "linux/amd64"] in pairs(argv)
    assert all(value.endswith("-amd64") for value in ex.names().values())
    assert not set(ex.names().values()) & set(evidence_names.values())
    monkeypatch.setenv(ex.PLATFORM_ENV, "windows/amd64; rm")
    with pytest.raises(ex.ExecutorError):
        ex.image_platform()


def test_the_built_image_is_saved_as_an_archive_with_its_checksum_and_never_overwritten(tmp_path, monkeypatch):
    import hashlib
    calls = []

    def fake_docker(*args, env=None, check=True, timeout=1800):
        calls.append(args)
        if args[0] == "save":
            Path(args[2]).write_bytes(b"the image, as layers")
    environment = {"kind": "container", "image": "wb-eval:abc", "image_digest": "sha256:" + "1" * 64, "image_platform": "linux/arm64"}
    monkeypatch.setattr(ex, "ensure", lambda env=None: environment)
    monkeypatch.setattr(ex, "docker", fake_docker)
    out = tmp_path / "image.tar"
    result = ex.archive(str(out))
    assert calls == [("save", "-o", str(out), "wb-eval:abc")]
    assert result == {"archive": str(out), "archive_sha256": hashlib.sha256(b"the image, as layers").hexdigest(),
                      "image": "wb-eval:abc", "image_digest": "sha256:" + "1" * 64, "image_platform": "linux/arm64"}
    with pytest.raises(ex.ExecutorError):
        ex.archive(str(out))
    assert ex.main(["archive"]) == 2 and ex.main(["--help"]) == 0


def test_everything_the_image_installs_is_pinned():
    """Base images by digest, the package index by a dated snapshot, the runners by a lock file, gh by checksum."""
    import json
    import re
    folder = Path(ex.DEFINITION)
    for dockerfile in (folder / "Dockerfile", folder / "proxy" / "Dockerfile", folder / "keyproxy" / "Dockerfile"):
        froms = [l for l in dockerfile.read_text().splitlines() if l.startswith("FROM ")]
        assert froms and all(re.search(r"@sha256:[0-9a-f]{64}( AS \w+)?$", l) for l in froms), froms
    text = (folder / "Dockerfile").read_text()
    assert re.search(r"ARG DEBIAN_SNAPSHOT=\d{8}T\d{6}Z", text) and "snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}" in text
    assert "deb.debian.org" not in text and "npm ci" in text and "npm install" not in text
    assert re.search(r"ARG GH_VERSION=\d+\.\d+\.\d+", text) and "sha256sum -c" in text
    package = json.loads((folder / "runners" / "package.json").read_text())
    lock = json.loads((folder / "runners" / "package-lock.json").read_text())
    assert all(re.fullmatch(r"\d+\.\d+\.\d+", v) for v in package["dependencies"].values())  # exact, no range
    for name, version in package["dependencies"].items():
        entry = lock["packages"][f"node_modules/{name}"]
        assert entry["version"] == version and entry["integrity"].startswith("sha512-")
    assert all(e.get("integrity") for path, e in lock["packages"].items() if path)


def test_a_secret_travels_by_name_and_only_when_named(tmp_path):
    root, _ = run_folder(tmp_path)
    env = {"MODEL_KEY": "value-that-must-not-appear", "OTHER_KEY": "another-value", "GIT_ALLOW_PROTOCOL": "file"}
    argv, _ = ex.command(["true"], str(root), env=env, pass_names=["MODEL_KEY", "UNSET_KEY"], network="proxy")
    joined = " ".join(argv)
    assert "value-that-must-not-appear" not in joined and "another-value" not in joined
    assert ["-e", "MODEL_KEY"] in [argv[i:i + 2] for i in range(len(argv))]
    assert "OTHER_KEY" not in joined and "UNSET_KEY" not in joined
    assert "GIT_ALLOW_PROTOCOL=file" in argv


@pytest.mark.parametrize("network, expected", [("none", ["--network", "none"]), ("proxy", None), ("open", [])])
def test_network_is_none_the_proxied_internal_one_or_open(tmp_path, network, expected):
    root, _ = run_folder(tmp_path)
    argv, _ = ex.command(["true"], str(root), network=network)
    n = ex.names()
    if network == "none":
        assert argv[argv.index("--network") + 1] == "none" and not any("PROXY" in a.upper() for a in argv)
    elif network == "proxy":
        assert argv[argv.index("--network") + 1] == n["network"]
        assert f"HTTPS_PROXY=http://{n['proxy']}:{ex.PROXY_PORT}" in argv
    else:
        assert "--network" not in argv and not any("PROXY" in a.upper() for a in argv)


def test_an_unknown_network_is_refused(tmp_path):
    root, _ = run_folder(tmp_path)
    with pytest.raises(ex.ExecutorError):
        ex.command(["true"], str(root), network="host")


def test_only_the_model_providers_are_on_the_proxys_list():
    lines = [l for l in (Path(ex.DEFINITION) / "proxy" / "allow.txt").read_text().splitlines() if l.strip()]
    assert lines and all(l.startswith("^") and l.endswith("$") for l in lines)  # anchored: no partial match
    conf = (Path(ex.DEFINITION) / "proxy" / "tinyproxy.conf").read_text()
    assert "FilterDefaultDeny Yes" in conf and "ConnectPort 443" in conf


def test_a_setup_command_sees_only_the_run_folder_and_a_missing_script_is_refused(tmp_path):
    root, _ = run_folder(tmp_path)
    argv, _ = ex.command(["git", "init"], str(root))
    assert [m.split(":")[1] for m in mounted(argv)] == ["/eval"]
    with pytest.raises(ex.ExecutorError):
        ex.command(["true"], str(root), runner=str(tmp_path / "no-such" / "run-prompt.sh"))


FLOOR_KEY = "fake-floor-key-for-the-executor-tests-0003"


def env_pairs(argv):
    return [argv[i + 1] for i, a in enumerate(argv) if a == "-e"]


@pytest.mark.parametrize("network", ["proxy", "open", "none"])
def test_the_key_the_key_proxy_holds_never_enters_a_run(tmp_path, network):
    root, _ = run_folder(tmp_path)
    r, n = ex.route(), ex.names()
    env = {r["secret"]: FLOOR_KEY, "MODEL_KEY": "another-value"}
    argv, _ = ex.command(["true"], str(root), env=env, pass_names=[r["secret"], "MODEL_KEY"], network=network)
    given = env_pairs(argv)
    assert FLOOR_KEY not in " ".join(argv)
    assert f"{r['secret']}={r['placeholder']}" in given and r["secret"] not in given  # never by name, so never its value
    assert "MODEL_KEY" in given  # any other passed variable travels as before
    url = f"{r['base_url_env']}={ex.keyproxy_url()}"
    if network == "none":
        assert url not in given and argv[argv.index("--network") + 1] == "none"
        return
    assert url in given and ex.keyproxy_url() == f"http://{n['keys']}:{r['port']}/api/v1"
    if network == "proxy":
        assert argv[argv.index("--network") + 1] == n["held_network"]  # where only its key proxy is, never the egress proxy
        assert not [e for e in given if e.split("=")[0].upper() in ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY")]
    else:
        assert argv[argv.index("--network") + 1] == n["open_network"]  # the open network the key proxy also listens on


def test_a_run_without_the_held_key_is_as_it_was(tmp_path):
    root, _ = run_folder(tmp_path)
    r = ex.route()
    argv, _ = ex.command(["true"], str(root), env={"MODEL_KEY": "v"}, pass_names=["MODEL_KEY", r["secret"]], network="proxy")
    given = env_pairs(argv)
    assert not any(e.startswith(r["secret"]) or e.startswith(r["base_url_env"]) for e in given)
    assert "NO_PROXY=localhost,127.0.0.1" in given
    argv, _ = ex.command(["true"], str(root), env={"MODEL_KEY": "v"}, pass_names=["MODEL_KEY"], network="open")
    assert "--network" not in argv  # a web case of the strong tier stays on the default network
    held = {r["secret"]: FLOOR_KEY}
    assert ex.holds([r["secret"]], held, "proxy") and ex.holds([r["secret"]], held, "open")
    assert not ex.holds([r["secret"]], held, "none") and not ex.holds([r["secret"]], {}, "proxy")
    assert not ex.holds(["MODEL_KEY"], {"MODEL_KEY": "v", **held}, "proxy")


class FakeDocker:
    """docker as the key proxy's start sees it: a container that runs with a label, or none."""

    def __init__(self):
        self.calls, self.envs, self.running_label = [], [], None

    def __call__(self, *args, env=None, check=True, timeout=1800):
        import subprocess
        self.calls.append(args)
        self.envs.append(dict(env or {}))
        out, err, code = "", "", 0
        if args[0] == "inspect":
            if self.running_label is None:
                code, err = 1, "No such object"
            else:
                out = f"true {self.running_label}\n"
        elif args[0] == "run":
            self.running_label = next(a.split("=", 1)[1] for a in args if a.startswith(ex.KEYPROXY_LABEL + "="))
        elif args[0] == "logs":
            err = "keyproxy: listening on port 8890, forwarding /api/v1/ to https://openrouter.ai through the egress proxy\n"
        return subprocess.CompletedProcess(["docker", *args], code, out, err)


def test_the_key_proxy_gets_the_key_by_name_and_is_reused_until_the_key_changes(monkeypatch):
    r, n = ex.route(), ex.names()
    docker = FakeDocker()
    monkeypatch.setattr(ex, "docker", docker)
    env = {r["secret"]: FLOOR_KEY, "PATH": "/usr/bin"}
    assert ex.keyproxy(env=env) == n["keys"]
    run = next(c for c in docker.calls if c[0] == "run")
    assert all(FLOOR_KEY not in a for c in docker.calls for a in c)  # never on a command line, the label included
    assert ["-e", r["secret"]] in pairs(list(run)) and docker.envs[docker.calls.index(run)][r["secret"]] == FLOOR_KEY
    assert ["--network", n["keys_network"]] in pairs(list(run)) and f"HTTPS_PROXY=http://{n['proxy']}:{ex.PROXY_PORT}" in run
    assert ["--cap-drop", "ALL"] in pairs(list(run)) and "--rm" in run and "--restart" not in run
    assert not any(a in ("-p", "--publish", "--network=host") for a in run)  # nothing published on the host
    assert run[run.index(n["keys_image"]) + 1:] == ()  # the provider of the route: no upstream given
    assert ("network", "connect", n["open_network"], n["keys"]) in docker.calls
    assert ("network", "connect", n["held_network"], n["keys"]) in docker.calls  # the held runs reach it by name there
    started = len(docker.calls)
    assert ex.keyproxy(env=env) == n["keys"]  # running with that key: reused
    assert [c[0] for c in docker.calls[started:]] == ["inspect"]
    ex.keyproxy(env={**env, r["secret"]: FLOOR_KEY + "-stored-again"})  # a key stored again replaces it
    assert [c[:2] for c in docker.calls[started + 1:started + 4]] == [("inspect", "--format"), ("rm", "-f"), ("run", "-d")]
    with pytest.raises(ex.ExecutorError):
        ex.keyproxy(env={"PATH": "/usr/bin"})


def test_a_key_proxy_that_does_not_start_is_an_error_that_names_no_key(monkeypatch):
    docker = FakeDocker()

    def silent(*args, env=None, check=True, timeout=1800):
        r = docker(*args, env=env, check=check, timeout=timeout)
        if args[0] == "logs":
            r.stderr = "keyproxy: cannot start: OSError: address in use\n"
        return r
    monkeypatch.setattr(ex, "docker", silent)
    monkeypatch.setattr(ex, "KEYPROXY_READY_SECONDS", 0)
    with pytest.raises(ex.ExecutorError) as e:
        ex.keyproxy(env={ex.route()["secret"]: FLOOR_KEY})
    assert "did not start" in str(e.value) and FLOOR_KEY not in str(e.value)

