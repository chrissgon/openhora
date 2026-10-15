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


@pytest.fixture(autouse=True)
def arm64_host():
    """The tests below are about the executor, not about the machine they run on: docker host is taken for arm64."""
    ex._NATIVE["platform"] = "linux/arm64"
    yield
    ex._NATIVE.clear()


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
    assert set(n) == {"image", "proxy_image", "network", "proxy", "keys_image", "tag"}


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
SECRET = "OPENROUTER_API_KEY"


def held_gate(tmp_path, monkeypatch, models=None):
    """A gate file whose model "m" is served by the OpenRouter route and "s" by the Anthropic one; the executor reads it."""
    import json
    entry = {"aliases": [], "adapter": "h", "price_source": "https://example.test/price", "run_token_budget": 1000}
    models = models or {
        "m": {**entry, "pass_env": [SECRET], "route": "openrouter", "provider_pin": "deepinfra", "upstream_models": ["vendor/m"]},
        "s": {**entry, "pass_env": ["CLAUDE_CODE_OAUTH_TOKEN"], "route": "anthropic", "provider_pin": None, "upstream_models": ["s-1"]}}
    path = tmp_path / "gate.json"
    path.write_text(json.dumps({"models": models}))
    monkeypatch.setattr(ex, "GATE_FILE", str(path))
    return models


def env_pairs(argv):
    return [argv[i + 1] for i, a in enumerate(argv) if a == "-e"]


@pytest.mark.parametrize("network", ["proxy", "open", "none"])
def test_the_key_the_key_proxy_holds_never_enters_a_run(tmp_path, monkeypatch, network):
    held_gate(tmp_path, monkeypatch)
    root, _ = run_folder(tmp_path)
    r = ex.route(name="openrouter")
    run_id = ex.new_run_id()
    env = {r["secret"]: FLOOR_KEY, "MODEL_KEY": "another-value"}
    argv, name = ex.command(["true"], str(root), env=env, pass_names=[r["secret"], "MODEL_KEY"], network=network, model="m", run_id=run_id)
    given = env_pairs(argv)
    assert FLOOR_KEY not in " ".join(argv) and name == f"wb-eval-run-{run_id}"
    assert f"{r['secret']}={r['placeholder']}" in given and r["secret"] not in given  # never by name, so never its value
    assert "MODEL_KEY" in given  # any other passed variable travels as before
    url = f"{r['base_url_env']}={ex.keyproxy_url(run_id, 'openrouter')}"
    if network == "none":
        assert url not in given and argv[argv.index("--network") + 1] == "none"
        return
    assert url in given and ex.keyproxy_url(run_id, "openrouter") == f"http://wb-eval-keys-{run_id}:{r['port']}/api/v1"
    # on its own network, where only its own key proxy is, never the egress proxy: the same name for a web run
    assert argv[argv.index("--network") + 1] == f"wb-eval-held-{run_id}" and argv.count("--network") == 1
    assert not [e for e in given if e.split("=")[0].upper() in ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY")]


def test_a_run_without_the_held_key_is_as_it_was(tmp_path, monkeypatch):
    held_gate(tmp_path, monkeypatch)
    root, _ = run_folder(tmp_path)
    r = ex.route(name="openrouter")
    argv, _ = ex.command(["true"], str(root), env={"MODEL_KEY": "v"}, pass_names=["MODEL_KEY", r["secret"]], network="proxy", model="m")
    given = env_pairs(argv)
    assert not any(e.startswith(r["secret"]) or e.startswith(r["base_url_env"]) for e in given)
    assert "NO_PROXY=localhost,127.0.0.1" in given and argv[argv.index("--network") + 1] == ex.names()["network"]
    argv, _ = ex.command(["true"], str(root), env={"MODEL_KEY": "v"}, pass_names=["MODEL_KEY"], network="open")
    assert "--network" not in argv  # a web case with no held key stays on the default network
    held = {r["secret"]: FLOOR_KEY}
    assert ex.holds([r["secret"]], held, "proxy", "m") and ex.holds([r["secret"]], held, "open", "m")
    assert not ex.holds([r["secret"]], held, "none", "m") and not ex.holds([r["secret"]], {}, "proxy", "m")
    assert not ex.holds(["MODEL_KEY"], {"MODEL_KEY": "v", **held}, "proxy", "m")


def test_a_held_key_is_never_given_to_a_command_whose_model_the_gate_file_does_not_serve_by_that_route(tmp_path, monkeypatch):
    held_gate(tmp_path, monkeypatch)
    root, _ = run_folder(tmp_path)
    env = {SECRET: FLOOR_KEY}
    for model in (None, "not-listed", "vendor/m"):  # the upstream name is not the model's id
        with pytest.raises(ex.ExecutorError) as e:
            ex.command(["true"], str(root), env=env, pass_names=[SECRET], network="proxy", model=model)
        assert FLOOR_KEY not in str(e.value)
    with pytest.raises(ex.ExecutorError):  # the model "s" is served by the other provider's route
        ex.command(["true"], str(root), env=env, pass_names=[SECRET], network="proxy", model="s")
    with pytest.raises(ex.ExecutorError):  # both providers' keys in one command: one command, one key proxy
        ex.command(["true"], str(root), env={SECRET: FLOOR_KEY, "CLAUDE_CODE_OAUTH_TOKEN": "fake-token-0004"},
                   pass_names=[SECRET, "CLAUDE_CODE_OAUTH_TOKEN"], network="proxy", model="m")
    held_gate(tmp_path, monkeypatch, models={"m": ["m-alias"]})  # a model listed in the old form has no route
    with pytest.raises(ex.ExecutorError):
        ex.command(["true"], str(root), env=env, pass_names=[SECRET], network="proxy", model="m")
    argv, _ = ex.command(["true"], str(root), env=env, pass_names=[SECRET], network="none", model=None)  # no network: no proxy needed
    assert f"{SECRET}=held-by-the-eval-key-proxy" in env_pairs(argv)


def test_an_alias_of_a_model_is_served_like_its_id(tmp_path, monkeypatch):
    models = held_gate(tmp_path, monkeypatch)
    models["m"]["aliases"] = ["m-short"]
    held_gate(tmp_path, monkeypatch, models=models)
    assert ex.model_entry("m-short")["id"] == "m" and ex.model_entry("m")["route"] == "openrouter"
    assert ex.model_entry("nobody") is None and ex.model_entry(None) is None
    assert ex.held_route([SECRET], {SECRET: FLOOR_KEY}, "proxy", "m-short") == "openrouter"


# --- the CPU platforms evidence is made on -------------------------------------------------------------------


def test_evidence_is_made_on_either_listed_platform_and_the_other_gets_its_own_names(monkeypatch):
    assert ex.IMAGE_PLATFORMS == ("linux/arm64", "linux/amd64") and ex.IMAGE_PLATFORM in ex.IMAGE_PLATFORMS
    monkeypatch.delenv(ex.PLATFORM_ENV, raising=False)
    default = ex.names()
    monkeypatch.setenv(ex.PLATFORM_ENV, "linux/amd64")
    other = ex.names()
    assert ex.image_platform() in ex.IMAGE_PLATFORMS and not set(default.values()) & set(other.values())


# --- the published image: evals/image-lock.json --------------------------------------------------------------

MANIFEST = {"linux/arm64": "sha256:" + "a" * 64, "linux/amd64": "sha256:" + "b" * 64}


def write_lock(tmp_path, monkeypatch, definition=None, repository="ghcr.io/example/wb-eval"):
    import json
    images = {}
    if definition:
        images[definition] = {"index_digest": "sha256:" + "c" * 64, "platforms": {
            platform: {"manifest_digest": digest, "config_digest": "sha256:" + "d" * 64} for platform, digest in MANIFEST.items()}}
    path = tmp_path / "image-lock.json"
    path.write_text(json.dumps({"repository": repository, "images": images}))
    monkeypatch.setattr(ex, "LOCK_FILE", str(path))
    return path


class Daemon:
    """docker as ensure() and pull() see it: images that exist, and the repo digests they list."""

    def __init__(self, present=(), digests=None):
        self.present, self.digests, self.calls = set(present), digests or {}, []

    def __call__(self, *args, env=None, check=True, timeout=1800):
        import json
        import subprocess
        self.calls.append(args)
        out, err, code = "", "", 0
        if args[0] == "info":
            out = "29.0\n"
        elif args[:2] == ("image", "inspect"):
            image = args[-1]
            if image not in self.present:
                code, err = 1, "No such image"
            elif "{{json .RepoDigests}}" in args:
                out = json.dumps(self.digests.get(image, [])) + "\n"
            else:
                out = "sha256:" + "f" * 64 + "\n"
        elif args[0] == "pull":
            self.present.add(args[-1])
        elif args[0] == "build":
            self.present.add(args[args.index("-t") + 1])
        elif args[0] == "inspect" or args[:2] == ("network", "inspect"):
            code, err = 1, "No such object"
        return subprocess.CompletedProcess(["docker", *args], code, out, err)


def test_without_a_lock_entry_the_image_is_built_here_and_its_identity_is_the_local_id(tmp_path, monkeypatch):
    write_lock(tmp_path, monkeypatch)
    daemon = Daemon()
    monkeypatch.setattr(ex, "docker", daemon)
    environment = ex.ensure()
    n = ex.names()
    assert n["image"] == f"wb-eval:{n['tag']}" and environment["image_source"] == "local"
    assert environment["image_digest"] == environment["image_id"] == "sha256:" + "f" * 64
    assert ("build", "-q", "--platform", ex.image_platform(), "-t", n["image"], ex.DEFINITION) in daemon.calls
    assert not any(c[0] == "pull" for c in daemon.calls)


@pytest.mark.parametrize("how", ["timeout", "failure"])
def test_ensure_refuses_when_docker_does_not_say_its_platform_so_no_run_starts_with_an_unknown_host(tmp_path, monkeypatch, how):
    """A slow docker must not let the image default to arm64 (emulated on an amd64 host) with host_platform recorded as
    None, which the evidence check would let pass."""
    import subprocess
    write_lock(tmp_path, monkeypatch)
    monkeypatch.delenv(ex.PLATFORM_ENV, raising=False)
    ex._NATIVE.clear()
    daemon = Daemon()

    def docker(*args, env=None, check=True, timeout=1800):
        if args == ("info", "--format", "{{.Architecture}}"):
            daemon.calls.append(args)
            if how == "timeout":
                raise subprocess.TimeoutExpired(["docker", *args], timeout)
            return subprocess.CompletedProcess(["docker", *args], 1, "", "error")
        return daemon(*args, env=env, check=check, timeout=timeout)
    monkeypatch.setattr(ex, "docker", docker)
    with pytest.raises(ex.ExecutorError) as e:
        ex.ensure()
    assert "did not say its platform" in str(e.value)
    assert not any(c[0] in ("build", "network", "run") for c in daemon.calls)  # nothing was built or started
    assert ex._NATIVE == {}


def test_image_platform_asks_docker_once_per_call(monkeypatch):
    monkeypatch.delenv(ex.PLATFORM_ENV, raising=False)
    ex._NATIVE.clear()
    asked = []

    def docker(*args, env=None, check=True, timeout=1800):
        import subprocess
        asked.append(args)
        return subprocess.CompletedProcess(["docker", *args], 1, "", "no daemon")
    monkeypatch.setattr(ex, "docker", docker)
    assert ex.image_platform() == "linux/arm64" and len(asked) == 1  # a hung daemon costs one timeout, not two


@pytest.mark.parametrize("platform", ["linux/arm64", "linux/amd64"])
def test_with_a_lock_entry_the_image_is_the_published_one_by_digest_and_ensure_never_pulls_or_builds_it(tmp_path, monkeypatch, platform):
    write_lock(tmp_path, monkeypatch, ex.definition_hash())
    monkeypatch.setenv(ex.PLATFORM_ENV, platform)
    ref = f"ghcr.io/example/wb-eval@{MANIFEST[platform]}"
    assert ex.names()["image"] == ref
    daemon = Daemon(present={ref}, digests={ref: [ref]})
    monkeypatch.setattr(ex, "docker", daemon)
    environment = ex.ensure()
    assert environment["image_source"] == "published" and environment["image"] == ref and environment["image_platform"] == platform
    assert environment["image_digest"] == MANIFEST[platform]  # the platform manifest's digest: the repo digest, not the local id
    assert environment["image_id"] is None
    assert not any(c[0] == "pull" for c in daemon.calls) and not any(c[0] == "build" and ex.DEFINITION in c for c in daemon.calls)
    assert not any("{{.Id}}" in c for c in daemon.calls)  # the local id is never read for a published image
    # the proxies are small and built here whatever the run image is
    assert any(c[0] == "build" and c[-1].endswith("keyproxy") for c in daemon.calls)


def test_a_published_image_that_is_not_present_is_an_error_that_names_the_command_and_nothing_is_pulled(tmp_path, monkeypatch):
    write_lock(tmp_path, monkeypatch, ex.definition_hash())
    daemon = Daemon()
    monkeypatch.setattr(ex, "docker", daemon)
    with pytest.raises(ex.ExecutorError) as e:
        ex.ensure()
    assert "python3 scripts/image_lock.py pull" in str(e.value) and ex.names()["image"] in str(e.value)
    assert not any(c[0] == "pull" for c in daemon.calls)


def test_a_published_image_that_lists_another_repo_digest_is_refused(tmp_path, monkeypatch):
    write_lock(tmp_path, monkeypatch, ex.definition_hash())
    ref = ex.names()["image"]
    monkeypatch.setattr(ex, "docker", Daemon(present={ref}, digests={ref: ["ghcr.io/example/wb-eval@sha256:" + "9" * 64]}))
    with pytest.raises(ex.ExecutorError) as e:
        ex.ensure()
    assert "does not list that repo digest" in str(e.value)


def test_pull_fetches_the_image_the_lock_names_and_checks_its_repo_digest(tmp_path, monkeypatch, capsys):
    write_lock(tmp_path, monkeypatch, ex.definition_hash())
    ref = ex.names()["image"]
    daemon = Daemon(digests={ref: [ref]})
    monkeypatch.setattr(ex, "docker", daemon)
    result = ex.pull()
    assert result == {"image": ref, "image_digest": MANIFEST[ex.image_platform()], "image_platform": ex.image_platform()}
    assert ("pull", "--platform", ex.image_platform(), ref) in daemon.calls
    assert ex.main(["pull"]) == 0 and ref in capsys.readouterr().out
    wrong = Daemon(digests={ref: ["ghcr.io/example/wb-eval@sha256:" + "9" * 64]})
    monkeypatch.setattr(ex, "docker", wrong)
    with pytest.raises(ex.ExecutorError):
        ex.pull()


def test_pull_without_a_lock_entry_for_this_definition_says_so(tmp_path, monkeypatch):
    write_lock(tmp_path, monkeypatch)
    monkeypatch.setattr(ex, "docker", Daemon())
    with pytest.raises(ex.ExecutorError) as e:
        ex.pull()
    assert "names no published image" in str(e.value)


def test_a_lock_file_that_is_not_in_its_form_is_an_error_and_the_committed_one_is_empty_until_a_script_fills_it(tmp_path):
    import json
    committed = ex.image_lock(str(Path(ex.LOCK_FILE)))
    assert committed == {"repository": None, "images": {}}  # P2d fills it, through a script that verifies the image first
    for bad in ({}, {"repository": "Not A Repo", "images": {}}, {"repository": None, "images": {"abc": {}}},
                {"repository": None, "images": {"a" * 64: {"index_digest": "sha256:" + "c" * 64, "platforms": {"linux/arm64": {}}}}},
                {"repository": "ghcr.io/x/y", "images": []}, {"repository": None, "images": {"a" * 64: {}}}, [],
                {"repository": "ghcr.io/Owner/name", "images": {}}, {"repository": "docker.io/owner/name", "images": {}},
                {"repository": "ghcr.io/owner", "images": {}}, {"repository": "ghcr.io/owner/name", "images": {}, "extra": 1},
                {"repository": "ghcr.io/o/n", "images": {"a" * 64: {"index_digest": "sha256:" + "c" * 64, "extra": 1, "platforms": {
                    "linux/arm64": {"manifest_digest": "sha256:" + "a" * 64, "config_digest": "sha256:" + "d" * 64}}}}},
                {"repository": "ghcr.io/o/n", "images": {"a" * 64: {"index_digest": "sha256:" + "c" * 64, "platforms": {
                    "linux/arm64": {"manifest_digest": "sha256:" + "a" * 64, "config_digest": "sha256:" + "d" * 64, "x": 1}}}}},
                {"repository": "ghcr.io/o/n", "images": {"a" * 64: {"index_digest": "sha256:" + "C" * 64, "platforms": {
                    "linux/arm64": {"manifest_digest": "sha256:" + "a" * 64, "config_digest": "sha256:" + "d" * 64}}}}}):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(bad))
        with pytest.raises(ex.ExecutorError):
            ex.image_lock(str(path))
    (tmp_path / "bad.json").write_text("{")
    with pytest.raises(ex.ExecutorError):
        ex.image_lock(str(tmp_path / "bad.json"))
    assert ex.image_lock(str(tmp_path / "missing.json")) == {"repository": None, "images": {}}


def test_a_published_image_is_never_identified_by_the_local_image_id_anywhere_in_evals():
    """Item 12 of the amendment: `.Id` is the identity of a local build only; a published image is its repo digest."""
    root = Path(ex.HERE)
    for path in list(root.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), 1):
            if "{{.Id}}" in line:
                assert path.name == "executor.py", f"{path.name}:{number} reads the image id"
    source = (root / "executor.py").read_text(encoding="utf-8")
    assert source.count("{{.Id}}") == 1  # the local build's identity, after the branch that returns a published image's digest
    assert source.index('"image_source": "published"') < source.index("{{.Id}}")


# --- the platform defaults to the docker host's (D20) ---------------------------------------------------------------


def fake_info(monkeypatch, answer, calls=None, fail=False):
    def docker(*args, env=None, check=True, timeout=1800):
        import subprocess
        (calls if calls is not None else []).append(args)
        if fail:
            raise ex.ExecutorError("docker is not installed")
        assert args == ("info", "--format", "{{.Architecture}}")
        return subprocess.CompletedProcess(["docker", *args], 0, answer + "\n", "")
    monkeypatch.setattr(ex, "docker", docker)
    ex._NATIVE.clear()


@pytest.mark.parametrize("answer, expected", [("aarch64", "linux/arm64"), ("x86_64", "linux/amd64"), ("amd64", "linux/amd64"),
                                              ("riscv64", "linux/arm64"), ("", "linux/arm64")])
def test_the_image_platform_defaults_to_the_docker_hosts_when_it_is_listed_else_to_arm64(monkeypatch, answer, expected):
    monkeypatch.delenv(ex.PLATFORM_ENV, raising=False)
    calls = []
    fake_info(monkeypatch, answer, calls)
    assert ex.image_platform() == expected and ex.image_platform() == expected
    assert len(calls) == 1  # docker is asked once per process
    if expected == "linux/amd64":  # an amd64 host builds and runs amd64: its own names, and no emulation
        assert ex.names()["image"].endswith("-amd64") and ex.names()["tag"].endswith("-amd64")


def test_an_amd64_host_runs_its_containers_as_amd64_and_not_as_an_emulated_arm64(tmp_path, monkeypatch):
    monkeypatch.delenv(ex.PLATFORM_ENV, raising=False)
    fake_info(monkeypatch, "x86_64")
    root, _ = run_folder(tmp_path)
    argv, _ = ex.command(["true"], str(root))
    assert ["--platform", "linux/amd64"] in pairs(argv)


def test_the_environment_variable_still_wins_and_a_docker_that_says_nothing_leaves_arm64(monkeypatch):
    fake_info(monkeypatch, "x86_64")
    monkeypatch.setenv(ex.PLATFORM_ENV, "linux/arm64")
    assert ex.image_platform() == "linux/arm64"
    monkeypatch.delenv(ex.PLATFORM_ENV)
    fake_info(monkeypatch, "", fail=True)  # docker is not installed: the default stays as it was
    assert ex.image_platform() == "linux/arm64" and ex.native_platform() is None


def test_a_docker_that_does_not_answer_yet_is_not_remembered_as_an_answer(monkeypatch):
    """A runtime started before the docker daemon must not default to arm64 for its life on an amd64 host."""
    import subprocess
    monkeypatch.delenv(ex.PLATFORM_ENV, raising=False)
    state, calls = {"now": None}, []

    def docker(*args, env=None, check=True, timeout=1800):
        calls.append(timeout)
        if isinstance(state["now"], BaseException):
            raise state["now"]
        return state["now"]
    monkeypatch.setattr(ex, "docker", docker)
    ex._NATIVE.clear()
    for state["now"] in (subprocess.CompletedProcess(["docker"], 1, "", "Cannot connect to the Docker daemon"),
                         ex.ExecutorError("docker is not installed or not on PATH"),
                         subprocess.TimeoutExpired(["docker", "info"], 15)):  # the daemon is not up
        assert ex.native_platform() is None and ex.image_platform() == "linux/arm64"
        assert ex._NATIVE == {}  # and nothing is kept
    state["now"] = subprocess.CompletedProcess(["docker"], 0, "x86_64\n", "")  # the daemon is up: a real answer
    assert ex.native_platform() == "linux/amd64" and ex.image_platform() == "linux/amd64"
    asked = len(calls)
    assert ex.native_platform() == "linux/amd64" and len(calls) == asked  # and kept
    assert set(calls) == {ex.HOST_INFO_TIMEOUT}


def test_docker_info_has_a_short_timeout_and_a_timeout_reads_as_unknown(monkeypatch):
    import subprocess
    seen = {}

    def run(argv, **kw):
        seen.update(kw, argv=argv)
        raise subprocess.TimeoutExpired(argv, kw["timeout"])
    monkeypatch.setattr(ex.subprocess, "run", run)
    assert ex.host_platform() is None
    assert seen["argv"][:2] == ["docker", "info"] and 0 < seen["timeout"] <= 30
