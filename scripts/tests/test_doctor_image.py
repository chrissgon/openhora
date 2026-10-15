"""Tests for the eval image in scripts/doctor.py: four states, and the doctor never pulls or builds. Offline: docker is a
fake, the checkout is a stand-in with an invented definition; every name and digest is invented.

Run: uv run --with pytest==9.1.1 pytest scripts/tests/test_doctor_image.py
"""
from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("doctor_image_under_test", SCRIPTS / "doctor.py")
doctor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(doctor)

DEF = "d" * 64
REPO = "ghcr.io/example-owner/openhora-eval"
MANIFEST = "sha256:" + "2" * 64
STUB_EXECUTOR = f'''
def definition_hash():
    return "{DEF}"


def image_platform():
    return "linux/arm64"


def names():
    return {{"image": "wb-eval:stub"}}
'''


def image_root(tmp_path, published=False):
    """A stand-in checkout: an executor with an invented definition, the real lock script and a lock file."""
    (tmp_path / "evals").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "evals" / "executor.py").write_text(STUB_EXECUTOR)
    shutil.copy(SCRIPTS / "image_lock.py", tmp_path / "scripts" / "image_lock.py")
    lock = {"repository": REPO if published else None, "images": {}}
    if published:
        lock["images"][DEF] = {"index_digest": "sha256:" + "1" * 64, "platforms": {
            "linux/arm64": {"manifest_digest": MANIFEST, "config_digest": "sha256:" + "3" * 64}}}
    (tmp_path / "evals" / "image-lock.json").write_text(json.dumps(lock))
    return tmp_path


class FakeDocker:
    """`docker image inspect`: knows which references are on the machine and whether a local build is, and logs what it
    was asked."""

    def __init__(self, *, repo_digests=None, local=False, down=False):
        self.repo_digests, self.local, self.down, self.asked = repo_digests, local, down, []

    def __call__(self, args):
        self.asked.append(list(args))
        if self.down:
            raise doctor.DockerUnavailable("the docker daemon cannot be reached")
        if "{{json .RepoDigests}}" in args:
            return (0, json.dumps(self.repo_digests)) if self.repo_digests is not None else (1, "")
        return (0, "sha256:" + "a" * 64) if self.local else (1, "")


def test_a_published_image_that_is_present(tmp_path):
    root = image_root(tmp_path, published=True)
    docker = FakeDocker(repo_digests=[f"{REPO}@{MANIFEST}"])
    found = doctor.image_state(docker, root=str(root))
    assert found["state"] == "published-present" and found["detail"] == f"{REPO}@{MANIFEST}"
    assert doctor.IMAGE_STATES[found["state"]] == "published and present"
    assert all("{{.Id}}" not in a for asked in docker.asked for a in asked)  # the image's own id is never read


def test_a_published_image_that_is_not_pulled_names_the_command(tmp_path):
    root = image_root(tmp_path, published=True)
    found = doctor.image_state(FakeDocker(repo_digests=None, local=True), root=str(root))
    assert found["state"] == "published-not-pulled"
    assert "python3 evals/executor.py pull" in doctor.IMAGE_STATES[found["state"]]


def test_a_local_build_does_not_pass_for_the_published_image(tmp_path):
    """The lock names a published image; a local build with another id is here; the published one is still not pulled."""
    root = image_root(tmp_path, published=True)
    found = doctor.image_state(FakeDocker(repo_digests=[f"{REPO}@sha256:{'8' * 64}"], local=True), root=str(root))
    assert found["state"] == "published-not-pulled"


def test_an_image_built_locally_when_the_lock_names_none(tmp_path):
    root = image_root(tmp_path, published=False)
    found = doctor.image_state(FakeDocker(local=True), root=str(root))
    assert found["state"] == "local-only"
    assert doctor.IMAGE_STATES["local-only"] == "no published image for this definition: built locally, evidence is local-only"


def test_a_missing_image_an_unreachable_docker_and_an_unreadable_lock(tmp_path):
    root = image_root(tmp_path, published=False)
    found = doctor.image_state(FakeDocker(local=False), root=str(root))
    assert found["state"] == "missing" and "python3 evals/executor.py ensure" in found["detail"]
    down = doctor.image_state(FakeDocker(down=True), root=str(root))
    assert down["state"] == "missing" and "daemon" in down["detail"]
    (root / "evals" / "image-lock.json").write_text("{")
    bad = doctor.image_state(FakeDocker(local=True), root=str(root))
    assert bad["state"] == "missing" and "cannot be looked up" in bad["detail"]


def test_the_doctor_only_inspects_it_never_pulls_or_builds(tmp_path, monkeypatch):
    ran = []

    def refuse(argv, **kwargs):
        ran.append(argv)
        raise OSError("no docker")

    monkeypatch.setattr(doctor.subprocess, "run", refuse)
    root = image_root(tmp_path, published=True)
    assert doctor.image_state(root=str(root))["state"] == "missing"
    assert ran and all(a[:3] == ["docker", "image", "inspect"] for a in ran)


def test_the_help_and_the_report_carry_the_image(monkeypatch, capsys):
    assert doctor.main(["--help"]) == 0
    helped = capsys.readouterr().out
    assert "published and present" in helped and "python3 evals/executor.py pull" in helped
    monkeypatch.setattr(doctor, "image_state", lambda: {"state": "published-not-pulled", "detail": "x"})
    monkeypatch.setattr(doctor, "secrets_report", lambda classes: [])
    monkeypatch.setattr(doctor, "collect_requires", lambda: {})
    assert doctor.main(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["image"] == {"state": "published-not-pulled", "detail": "x"}
