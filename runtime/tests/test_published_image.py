"""Tests of the published eval image in runtime/lab.py: the lock file names the image for this checkout's definition,
the identity of a published image is its repo digest and never its own id, and a machine without the image is refused
with the setup command named. Offline: the executor and its docker are fakes, the lock file is written in a tmp folder;
every name and digest is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_published_image.py
"""
from __future__ import annotations

import json

import pytest

import standin_tree as st

lab = st.load("lab")
proof = st.load("proof")

DEF = "d" * 64
REPO = "ghcr.io/example-owner/openhora-eval"
INDEX = "sha256:" + "1" * 64
MANIFEST = "sha256:" + "2" * 64
CONFIG = "sha256:" + "3" * 64
LOCAL_ID = "sha256:" + "a" * 64
OTHER_ID = "sha256:" + "b" * 64


class Done:
    def __init__(self, code, out=""):
        self.returncode, self.stdout, self.stderr = code, out, ""


class Machine:
    """A fake executor over a fake docker: which images are on the machine, and what `docker image inspect` says."""

    IMAGE_PLATFORM = "linux/arm64"

    def __init__(self, *, repo_digests=None, local_id=None):
        self.repo_digests, self.local_id, self.asked, self.built = repo_digests, local_id, [], []

    def definition_hash(self):
        return DEF

    def image_platform(self):
        return "linux/arm64"

    def names(self):
        return {"image": "wb-eval:demo"}

    def docker(self, *args, check=True, **kwargs):
        self.asked.append(args)
        if args[:2] != ("image", "inspect"):
            self.built.append(args)
            return Done(1)
        if "{{json .RepoDigests}}" in args:
            ref = args[-1]
            return Done(0, json.dumps(self.repo_digests)) if self.repo_digests is not None and "@" in ref else Done(1)
        return Done(0, self.local_id + "\n") if self.local_id else Done(1)

    def ensure(self):
        self.built.append(("ensure",))
        return {"kind": "container", "image_digest": MANIFEST}


@pytest.fixture
def machine(tmp_path, monkeypatch):
    kit = lab.load()
    monkeypatch.setattr(kit, "EXECUTOR", "container")
    holder = {"machine": Machine(), "lock": None}
    monkeypatch.setattr(kit, "load_executor", lambda: holder["machine"])
    lock = tmp_path / "image-lock.json"
    monkeypatch.setattr(lab, "lock_path", lambda: str(lock))

    def set_lock(published=True):
        data = {"repository": REPO if published else None, "images": {}}
        if published:
            data["images"][DEF] = {"index_digest": INDEX, "platforms": {
                "linux/arm64": {"manifest_digest": MANIFEST, "config_digest": CONFIG}}}
        lock.write_text(json.dumps(data))

    holder["set_lock"] = set_lock
    return holder


def test_a_published_image_is_identified_by_its_repo_digest_whatever_its_own_id_is(machine):
    machine["set_lock"]()
    for image_id in (LOCAL_ID, OTHER_ID):  # the classic and the containerd image stores give different ids
        machine["machine"] = Machine(repo_digests=[f"{REPO}@{MANIFEST}"], local_id=image_id)
        seen = lab.image()
        assert seen["digest"] == MANIFEST and seen["source"] == "published" and seen["name"] == f"{REPO}@{MANIFEST}"
        assert seen["setup"] is None
        assert all("{{.Id}}" not in a for asked in machine["machine"].asked for a in asked)
    assert machine["machine"].built == []  # only inspected


def test_a_published_image_that_is_not_pulled_has_no_digest_and_names_the_pull_command(machine):
    machine["set_lock"]()
    machine["machine"] = Machine(repo_digests=None, local_id=LOCAL_ID)  # a local build of the same definition is here
    seen = lab.image()
    assert seen["digest"] is None and seen["source"] == "published" and seen["setup"] == "python3 evals/executor.py pull"
    machine["machine"] = Machine(repo_digests=[f"{REPO}@sha256:{'8' * 64}"])  # another image under the same name
    assert lab.image()["digest"] is None


def test_without_an_entry_in_the_lock_the_local_build_is_the_image(machine):
    machine["set_lock"](published=False)
    machine["machine"] = Machine(local_id=LOCAL_ID)
    seen = lab.image()
    assert (seen["digest"], seen["source"], seen["name"], seen["setup"]) == (LOCAL_ID, "local", "wb-eval:demo", None)
    machine["machine"] = Machine()
    seen = lab.image()
    assert seen["digest"] is None and seen["source"] == "local" and seen["setup"] == "python3 evals/executor.py ensure"


def test_a_lock_that_cannot_be_read_hides_the_image_and_a_missing_one_is_empty(machine, tmp_path):
    machine["machine"] = Machine(local_id=LOCAL_ID)
    assert lab.image()["source"] == "local"  # no lock file at all: nothing is published
    (tmp_path / "image-lock.json").write_text("{")
    assert lab.image()["digest"] is None and lab.published_digests() == []


def test_the_published_digests_are_the_manifests_of_the_lock(machine):
    assert lab.published_digests() == []
    machine["set_lock"]()
    assert lab.published_digests() == [MANIFEST]


def test_a_machine_without_the_published_image_is_refused_with_the_pull_command_and_nothing_is_built_or_pulled(machine):
    machine["set_lock"]()
    machine["machine"] = Machine(repo_digests=None)
    with pytest.raises(lab.LabError) as e:
        lab._container()
    assert e.value.kind == "container" and "python3 evals/executor.py pull" in e.value.reason
    assert "never builds it" in e.value.reason and f"{REPO}@{MANIFEST}" in e.value.reason
    assert machine["machine"].built == []  # neither ensure() nor a pull


def test_a_machine_without_a_local_image_for_a_definition_the_lock_does_not_name_is_told_to_run_ensure(machine):
    machine["set_lock"](published=False)
    machine["machine"] = Machine()
    with pytest.raises(lab.LabError) as e:
        lab._container()
    assert "python3 evals/executor.py ensure" in e.value.reason and "never builds it" in e.value.reason
    assert machine["machine"].built == []


def test_a_machine_with_the_image_reaches_ensure(machine):
    machine["set_lock"]()
    machine["machine"] = Machine(repo_digests=[f"{REPO}@{MANIFEST}"])
    assert lab._container()["image_digest"] == MANIFEST
    assert machine["machine"].built == [("ensure",)]


def test_the_proof_holds_when_the_repo_digest_here_is_the_published_one_in_the_evidence(machine, monkeypatch):
    """.Id differs from machine to machine; the repo digest does not: the image is accepted."""
    machine["set_lock"]()
    entry = {"evidence_images": [MANIFEST]}
    monkeypatch.setattr(lab, "measurement_problem", lambda: None)
    for image_id in (LOCAL_ID, OTHER_ID):
        machine["machine"] = Machine(repo_digests=[f"{REPO}@{MANIFEST}"], local_id=image_id)
        assert proof.checks(entry)["image"] is None
    # evidence measured in a local image (its id) is not the published image's digest: local-only, said so
    local_entry = {"evidence_images": [LOCAL_ID]}
    reason = proof.checks(local_entry)["image"]
    assert reason.startswith("the image on this machine is not the one the evidence was measured in")
    assert "locally built image holds on the machine that built it only" in reason
    # and the published image not yet pulled is asked for, by command
    machine["machine"] = Machine(repo_digests=None, local_id=LOCAL_ID)
    assert proof.checks(entry)["image"] == "the published eval image is not on this machine: run python3 evals/executor.py pull"
