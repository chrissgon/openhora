"""Tests for scripts/image_lock.py: the lock file of the published eval image is written only from an artifact whose
definition hash matches this checkout, whose provenance verifies and which the registry agrees with. Offline: the
verifier (gh) and the manifest reader (docker) are replaced; every digest and name is invented.

Run: uv run --with pytest==9.1.1 pytest scripts/tests/test_image_lock.py
"""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "image_lock.py"
spec = importlib.util.spec_from_file_location("image_lock_under_test", SCRIPT)
image_lock = importlib.util.module_from_spec(spec)
spec.loader.exec_module(image_lock)

DEF = "d" * 64
OTHER_DEF = "e" * 64
REPO = "ghcr.io/example-owner/openhora-eval"
SOURCE = "example-owner/example-repo"
INDEX = "sha256:" + "1" * 64
AMD = "sha256:" + "2" * 64
ARM = "sha256:" + "3" * 64
CFG_AMD = "sha256:" + "4" * 64
CFG_ARM = "sha256:" + "5" * 64


def artifact(**changes):
    art = {"repository": REPO, "definition_sha256": DEF, "index_digest": INDEX,
           "platforms": {"linux/amd64": {"manifest_digest": AMD, "config_digest": CFG_AMD},
                         "linux/arm64": {"manifest_digest": ARM, "config_digest": CFG_ARM}}}
    art.update(changes)
    return art


def registry(art=None, **tweaks):
    """A fake fetch_manifest over the registry the artifact describes."""
    art = art or artifact()
    index = {"manifests": [{"digest": art["platforms"][p]["manifest_digest"],
                            "platform": {"os": p.split("/")[0], "architecture": p.split("/")[1]}} for p in art["platforms"]]}
    manifests = {art["platforms"][p]["manifest_digest"]: {"config": {"digest": art["platforms"][p]["config_digest"]}}
                 for p in art["platforms"]}
    table = {art["index_digest"]: index, **manifests}
    table.update(tweaks)

    def fetch(repository, digest):
        if digest not in table:
            raise image_lock.Refused(f"{digest} cannot be read")
        return table[digest]
    return fetch


class Verifier:
    def __init__(self, missing=()):
        self.missing, self.calls = set(missing), []

    def __call__(self, repository, digest, source_repo):
        self.calls.append((repository, digest, source_repo))
        return "no valid provenance" if digest in self.missing else None


def go(tmp_path, argv, art=None, *, verify=None, fetch=None, definition=DEF, text=None):
    src = tmp_path / "artifact.json"
    src.write_text(text if text is not None else json.dumps(art if art is not None else artifact()))
    out, err = io.StringIO(), io.StringIO()
    code = image_lock.run(["--from-json", str(src), "--source-repo", SOURCE, "--lock", str(tmp_path / "lock.json"), *argv],
                          verify=verify or Verifier(), fetch=fetch or registry(art), expected_definition=definition,
                          out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def lock_of(tmp_path):
    return json.loads((tmp_path / "lock.json").read_text())


def test_a_good_artifact_writes_the_expected_lock_sorted_and_stable(tmp_path):
    verify = Verifier()
    code, out, err = go(tmp_path, [], verify=verify)
    assert code == 0 and "verified" in out and err == ""
    expected = {"repository": REPO, "images": {DEF: {"index_digest": INDEX, "platforms": {
        "linux/amd64": {"config_digest": CFG_AMD, "manifest_digest": AMD},
        "linux/arm64": {"config_digest": CFG_ARM, "manifest_digest": ARM}}}}}
    assert lock_of(tmp_path) == expected
    text = (tmp_path / "lock.json").read_text()
    assert text == json.dumps(expected, indent=2, sort_keys=True) + "\n"
    # the provenance of the index and of both manifests was asked for, against the source repository
    assert [c[1] for c in verify.calls] == [INDEX, AMD, ARM] and {c[2] for c in verify.calls} == {SOURCE}
    # and writing the same artifact again changes nothing
    code, _, _ = go(tmp_path, [], verify=verify)
    assert code == 0 and (tmp_path / "lock.json").read_text() == text


def test_a_digest_built_from_another_definition_is_rejected_and_nothing_is_written(tmp_path):
    code, _, err = go(tmp_path, [], definition=OTHER_DEF)
    assert code == 1 and "definition" in err and DEF[:12] in err and OTHER_DEF[:12] in err
    assert not (tmp_path / "lock.json").exists()


@pytest.mark.parametrize("missing", [INDEX, AMD, ARM])
def test_a_digest_without_valid_provenance_is_rejected_and_nothing_is_written(tmp_path, missing):
    code, _, err = go(tmp_path, [], verify=Verifier(missing=[missing]))
    assert code == 1 and missing in err and "provenance" in err
    assert not (tmp_path / "lock.json").exists()


def test_the_provenance_command_is_the_one_the_plan_names(monkeypatch):
    seen = []

    class Result:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(image_lock.subprocess, "run", lambda argv, **kw: seen.append((argv, kw)) or Result())
    assert image_lock.verify_attestation(REPO, AMD, SOURCE) is None
    argv, kw = seen[0]
    assert argv == ["gh", "attestation", "verify", f"oci://{REPO}@{AMD}", "--repo", SOURCE,
                    "--signer-workflow", f"{SOURCE}/.github/workflows/eval-image.yml", "--source-ref", "refs/heads/main",
                    "--deny-self-hosted-runners"]
    assert kw["timeout"] > 0


def test_a_failing_gh_is_a_missing_provenance(monkeypatch):
    class Result:
        returncode, stdout, stderr = 1, "", "no attestations found"

    monkeypatch.setattr(image_lock.subprocess, "run", lambda *a, **k: Result())
    assert "no attestations found" in image_lock.verify_attestation(REPO, AMD, SOURCE)

    def boom(*a, **k):
        raise FileNotFoundError("gh")
    monkeypatch.setattr(image_lock.subprocess, "run", boom)
    assert "did not run" in image_lock.verify_attestation(REPO, AMD, SOURCE)


def test_a_registry_that_disagrees_with_the_artifact_is_rejected(tmp_path):
    wrong_config = registry(**{AMD: {"config": {"digest": "sha256:" + "9" * 64}}})
    code, _, err = go(tmp_path, [], fetch=wrong_config)
    assert code == 1 and "config" in err
    not_listed = registry(**{INDEX: {"manifests": []}})
    code, _, err = go(tmp_path, [], fetch=not_listed)
    assert code == 1 and "does not list" in err
    assert not (tmp_path / "lock.json").exists()


@pytest.mark.parametrize("art,why", [
    (artifact(index_digest="sha256:short"), "index_digest"),
    (artifact(definition_sha256="xyz"), "definition_sha256"),
    (artifact(repository="ghcr.io/Example-Owner/openhora-eval"), "lower case"),
    (artifact(repository="ghcr.io/someone-else/openhora-eval"), "owner"),
    (artifact(platforms={"linux/amd64": {"manifest_digest": AMD, "config_digest": CFG_AMD}}), "platforms"),
    ({"repository": REPO}, "exactly"),
])
def test_a_malformed_artifact_is_rejected(tmp_path, art, why):
    code, _, err = go(tmp_path, [], art=art, fetch=lambda *a: {})
    assert code == 1 and why in err
    assert not (tmp_path / "lock.json").exists()


def test_an_artifact_that_is_not_json_is_rejected(tmp_path):
    code, _, err = go(tmp_path, [], text="not json")
    assert code == 1 and "cannot be read" in err


def test_a_second_definition_is_added_and_a_changed_image_needs_replace(tmp_path):
    go(tmp_path, [])
    other = artifact(definition_sha256=OTHER_DEF, index_digest="sha256:" + "6" * 64)
    code, _, _ = go(tmp_path, [], art=other, definition=OTHER_DEF)
    assert code == 0 and sorted(lock_of(tmp_path)["images"]) == sorted([DEF, OTHER_DEF])
    rebuilt = artifact(index_digest="sha256:" + "7" * 64)
    code, _, err = go(tmp_path, [], art=rebuilt)
    assert code == 1 and "--replace" in err and lock_of(tmp_path)["images"][DEF]["index_digest"] == INDEX
    code, _, _ = go(tmp_path, ["--replace"], art=rebuilt)
    assert code == 0 and lock_of(tmp_path)["images"][DEF]["index_digest"] == "sha256:" + "7" * 64


def test_another_repository_than_the_lock_names_is_rejected(tmp_path):
    go(tmp_path, [])
    code, _, err = go(tmp_path, [], art=artifact(repository="ghcr.io/example-owner/other-name"))
    assert code == 1 and "names the repository" in err


def test_check_reads_the_lock_without_writing_and_without_the_network(tmp_path, capsys):
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({"repository": None, "images": {}}))
    out, err = io.StringIO(), io.StringIO()
    never = Verifier()
    code = image_lock.run(["--check", "--lock", str(lock)], verify=never, expected_definition=DEF, out=out, err=err)
    assert code == 0 and "no published image for this definition" in out.getvalue() and never.calls == []
    go(tmp_path, [])
    before = lock.read_bytes()
    out = io.StringIO()
    code = image_lock.run(["--check", "--lock", str(lock)], verify=never, expected_definition=DEF, out=out, err=err)
    assert code == 0 and "published: linux/amd64, linux/arm64" in out.getvalue() and never.calls == []
    assert lock.read_bytes() == before


def test_check_with_verify_provenance_asks_for_every_digest_and_refuses_a_missing_one(tmp_path):
    go(tmp_path, [])
    lock = str(tmp_path / "lock.json")
    good, out, err = Verifier(), io.StringIO(), io.StringIO()
    assert image_lock.run(["--check", "--verify-provenance", "--source-repo", SOURCE, "--lock", lock], verify=good,
                          expected_definition=DEF, out=out, err=err) == 0
    assert sorted(c[1] for c in good.calls) == sorted([INDEX, AMD, ARM])
    bad = Verifier(missing=[ARM])
    assert image_lock.run(["--check", "--verify-provenance", "--source-repo", SOURCE, "--lock", lock], verify=bad,
                          expected_definition=DEF, out=out, err=err) == 1
    assert ARM in err.getvalue()


@pytest.mark.parametrize("lock,why", [
    ({"repository": None, "images": {DEF: {"index_digest": INDEX, "platforms": {}}}}, "repository is null"),
    ({"repository": REPO}, "exactly the keys"),
    ({"repository": "docker.io/x/y", "images": {}}, "repository must be"),
    ({"repository": REPO, "images": {"short": {}}}, "definition hash"),
    ({"repository": REPO, "images": {DEF: {"index_digest": "nope", "platforms": {"linux/arm64": {
        "manifest_digest": AMD, "config_digest": CFG_AMD}}}}}, "index_digest"),
])
def test_check_refuses_a_lock_that_is_not_well_formed(tmp_path, lock, why):
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(lock))
    out, err = io.StringIO(), io.StringIO()
    assert image_lock.run(["--check", "--lock", str(path)], expected_definition=DEF, out=out, err=err) == 1
    assert why in err.getvalue()


def test_a_lock_file_that_cannot_be_read_is_an_error_and_a_missing_one_is_empty(tmp_path):
    assert image_lock.read_lock(str(tmp_path / "none.json")) == {"repository": None, "images": {}}
    (tmp_path / "bad.json").write_text("{")
    with pytest.raises(image_lock.Refused):
        image_lock.read_lock(str(tmp_path / "bad.json"))


def test_published_names_the_manifest_of_the_platform_and_a_bad_lock_names_nothing():
    lock = {"repository": REPO, "images": {DEF: {"index_digest": INDEX, "platforms": {
        "linux/arm64": {"manifest_digest": ARM, "config_digest": CFG_ARM}}}}}
    found = image_lock.published(lock, DEF, "linux/arm64")
    assert found["ref"] == f"{REPO}@{ARM}" and found["manifest_digest"] == ARM and found["index_digest"] == INDEX
    assert image_lock.published(lock, DEF, "linux/amd64") is None
    assert image_lock.published(lock, OTHER_DEF, "linux/arm64") is None
    assert image_lock.published({"repository": None, "images": {}}, DEF, "linux/arm64") is None
    assert image_lock.published({"junk": 1}, DEF, "linux/arm64") is None
    assert image_lock.published_digests(lock) == [ARM] and image_lock.published_digests({"junk": 1}) == []


def test_the_image_is_accepted_by_its_repo_digest_whatever_its_own_id_is():
    """The two image stores of Docker give an image different ids; the repo digest is the same."""
    wanted = image_lock.published({"repository": REPO, "images": {DEF: {"index_digest": INDEX, "platforms": {
        "linux/arm64": {"manifest_digest": ARM, "config_digest": CFG_ARM}}}}}, DEF, "linux/arm64")
    for image_id in ("sha256:" + "a" * 64, "sha256:" + "b" * 64):  # classic store, containerd store
        def inspect(args, image_id=image_id):
            assert "{{.Id}}" not in " ".join(args)  # the id is never asked for
            return 0, json.dumps([f"{REPO}@{ARM}"]) + "\n"
        assert image_lock.present(wanted, inspect)
    assert image_lock.present(wanted, lambda a: (0, json.dumps([f"{REPO}@{INDEX}"])))  # the index digest, too
    assert not image_lock.present(wanted, lambda a: (0, json.dumps([f"{REPO}@sha256:{'8' * 64}"])))
    assert not image_lock.present(wanted, lambda a: (0, json.dumps([f"other/name@{ARM}"])))
    assert not image_lock.present(wanted, lambda a: (1, ""))
    assert not image_lock.present(wanted, lambda a: (0, "garbage"))
    assert not image_lock.present(wanted, lambda a: (0, "null"))


def test_usage_errors_exit_2(tmp_path):
    for argv in ([], ["--check", "--print-definition-hash"], ["--bogus"]):
        assert image_lock.run(argv, err=io.StringIO(), out=io.StringIO()) == 2
    out = io.StringIO()
    assert image_lock.run(["--help"], out=out) == 0 and "--from-json" in out.getvalue()
    # without a source repository to name, provenance cannot be asked
    err = io.StringIO()
    (tmp_path / "a.json").write_text("{}")
    assert image_lock.run(["--from-json", str(tmp_path / "a.json"), "--source-repo", "not a repo"], err=err,
                          expected_definition=DEF, out=io.StringIO()) == 2


def test_print_definition_hash_is_the_executors(capsys):
    out = io.StringIO()
    assert image_lock.run(["--print-definition-hash"], out=out) == 0
    assert out.getvalue().strip() == image_lock.definition_hash() and len(image_lock.definition_hash()) == 64
