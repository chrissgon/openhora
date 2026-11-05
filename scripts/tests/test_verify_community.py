"""Offline tests of scripts/verify_community.py (decision D19, hardening S5): a community evidence file with a valid
attestation is accepted and shown in the community column; a wrong signer workflow, a signer digest that is not the
manifest's commit, a self-hosted runner, a commit that is not in main and a digest mismatch are each rejected. No network
and no model: the GitHub CLI is replaced by a fake that applies the flags it is given to a certificate the test describes,
so a test fails when the verifier does not bind the signer, the digest, the runner or the fork.

Run: uv run --with pytest pytest scripts/tests/test_verify_community.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


vc = load("verify_community_under_test", "scripts/verify_community.py")
ce = load("community_evidence_helpers_for_verify", "evals/tests/test_community_evidence.py")
es = ce.es
OFFICIAL = "acme/openhora"
FLASH = "openrouter/deepseek/deepseek-v4.1-flash"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FakeGh:
    """The GitHub CLI's `attestation verify`, reduced to what the flags promise: it succeeds only when every flag it is
    given agrees with the certificate (identity, signer digest, runner, source repository, issuer) and the file's digest is a
    subject of the bundle. A flag the verifier does not pass is not enforced, which is what the tests below rely on."""

    def __init__(self, identity, digest, runner="github-hosted", repo="ana/openhora", issuer=vc.OIDC_ISSUER):
        self.cert = {"identity": identity, "digest": digest, "runner": runner, "repo": repo, "issuer": issuer}
        self.calls = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        assert argv[:3] == ["gh", "attestation", "verify"], argv
        path = argv[3]
        flag = lambda name: argv[argv.index(name) + 1] if name in argv else None
        bundle = json.loads(Path(flag("--bundle")).read_text())
        if sha256(path) not in bundle.get("subjects", []):
            return 1, "", "no attestation with the digest of this file"
        if flag("--cert-identity") not in (None, self.cert["identity"]):
            return 1, "", "the certificate identity does not match"
        if flag("--signer-digest") not in (None, self.cert["digest"]):
            return 1, "", "the signer digest does not match"
        if flag("--repo") not in (None, self.cert["repo"]):
            return 1, "", "the source repository does not match"
        if flag("--cert-oidc-issuer") not in (None, self.cert["issuer"]):
            return 1, "", "the issuer does not match"
        if "--deny-self-hosted-runners" in argv and self.cert["runner"] != "github-hosted":
            return 1, "", "the run was on a self-hosted runner"
        return 0, "ok", ""


def git(root, *args, check=True):
    env = {**{k: v for k, v in os.environ.items() if not k.startswith("GIT_")}, "GIT_AUTHOR_NAME": "Ana", "GIT_AUTHOR_EMAIL": "ana@mail.example",
           "GIT_COMMITTER_NAME": "Ana", "GIT_COMMITTER_EMAIL": "ana@mail.example"}
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=env)
    assert r.returncode == 0 or not check, r.stderr
    return r.stdout.strip()


class World:
    """A checkout: a skill, the committed gate file, a base commit on main (the official workflow's commit) and a pull
    request's worth of changes on top of it."""

    def __init__(self, root):
        self.root = root
        git(root, "init", "-q", "-b", "main")
        self.repo = ce.skill(root)
        ce.versions(self.repo, ("1.0.0", "new"))
        ce.gate_root(root)
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "base")
        self.commit = git(root, "rev-parse", "HEAD")
        self.base = self.commit
        self.status = vc.load_status(str(REPO))

    def run_files(self, **kw):
        """One community run in the skill's folder, signed (as far as the fake goes) for this world's commit."""
        kwargs = {"model": FLASH, "adapter": "agents-dir", "mv": 9, **kw}
        kwargs["extra_event"] = {"grader": "claude-sonnet-5-5", **kwargs.get("extra_event", {})}
        kwargs["manifest_extra"] = {"commit": self.commit, "repository": "ana/openhora", **kwargs.get("manifest_extra", {})}
        path = ce.community(self.repo, **kwargs)
        self.bundle(path)
        return path

    def bundle(self, path, subjects=None):
        manifest = path.with_name(path.stem + ".manifest.json")
        body = dict(ce.BUNDLE, subjects=[sha256(path), sha256(manifest)] if subjects is None else subjects)
        path.with_name(path.stem + ".sigstore.json").write_text(json.dumps(body))

    def gh(self, **kw):
        return FakeGh(f"https://github.com/{OFFICIAL}/.github/workflows/community-eval.yml@{self.commit}", self.commit, **kw)

    def verify(self, path, gh=None, **kw):
        gh = gh or self.gh()
        err = io.StringIO()
        rel = os.path.relpath(path, self.root).replace(os.sep, "/")
        code, summary = vc.run(str(self.root), OFFICIAL, "main", [rel], self.status, gh=gh, out=io.StringIO(), err=err, **kw)
        return code, summary, err.getvalue(), gh


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


# --- accepted -----------------------------------------------------------------------------------------------

def test_a_file_with_a_valid_attestation_is_accepted_and_shown_in_the_community_column(world):
    path = world.run_files(run_number=1)
    code, summary, err, gh = world.verify(path)
    assert code == 0 and summary["refused"] == {} and len(summary["verified"]) == 1, err
    # A community full test counts only through its pool, which needs a second contributor: bo's fork submits one too.
    world.run_files(run_number=1, repo_id=222, date="2030-01-02", manifest_extra={"repository": "bo/openhora"})  # not verified here: the column is what is tested
    git(world.root, "add", "-A")
    git(world.root, "commit", "-q", "-m", "community evidence")
    figures = es.all_status(str(world.root), "core-demo")["community"]["skills"]["core-demo"][FLASH]
    assert figures["runs"] == 18 and figures["gaps"] == 0 and figures["band"] == "reliable" and figures["contributors"] == 2


def test_a_quick_test_file_is_verified_like_the_others_with_the_same_attestation_and_checks(world):
    path = world.run_files(run_number=1, kind="quick", per_case=1, extra_event={"runs": 1})
    code, summary, err, gh = world.verify(path)  # read strictly, as a new file is: one run for a quick test, the configured number otherwise
    assert code == 0 and summary["refused"] == {} and len(summary["verified"]) == 1, err
    assert len(gh.calls) == 2 and all("--deny-self-hosted-runners" in argv and "--signer-digest" in argv for argv in gh.calls)
    # A quick file that says it ran three times a case, or has a line without the skill, is refused by the same shape check.
    for number, extra in ((2, {"extra_event": {"runs": 3}}), (3, {"extra_event": {"runs": 1, "baseline": {"1": "run", "2": "none", "3": "none"}}})):
        refused = world.run_files(run_number=number, kind="quick", per_case=1, **extra)
        code, summary, _, _ = world.verify(refused)
        assert code == 1 and "quick test" in json.dumps(summary["refused"])


def test_the_flags_that_bind_the_signer_are_always_passed(world):
    path = world.run_files(run_number=1)
    _, _, _, gh = world.verify(path)
    assert len(gh.calls) == 2  # the evidence file and its manifest, against the one bundle
    for argv in gh.calls:
        assert argv[:3] == ["gh", "attestation", "verify"] and "--bundle" in argv
        assert argv[argv.index("--repo") + 1] == "ana/openhora"  # the fork the manifest names
        assert argv[argv.index("--cert-identity") + 1] == f"https://github.com/{OFFICIAL}/.github/workflows/community-eval.yml@{world.commit}"
        assert argv[argv.index("--signer-digest") + 1] == world.commit
        assert "--deny-self-hosted-runners" in argv
    assert {Path(a[3]).name.split(".", 1)[1] for a in gh.calls} == {"jsonl", "manifest.json"}


# --- each rejection -----------------------------------------------------------------------------------------

def test_a_wrong_signer_workflow_is_rejected(world):
    path = world.run_files(run_number=1)
    for identity in (f"https://github.com/{OFFICIAL}/.github/workflows/other.yml@{world.commit}",
                     f"https://github.com/ana/openhora/.github/workflows/community-eval.yml@{world.commit}",  # the fork's own copy
                     f"https://github.com/{OFFICIAL}/.github/workflows/community-eval.yml@refs/heads/main"):
        code, summary, _, _ = world.verify(path, FakeGh(identity, world.commit))
        assert code == 1 and "no valid attestation" in json.dumps(summary["refused"]), identity


def test_a_signer_digest_that_is_not_the_commit_of_the_manifest_is_rejected(world):
    path = world.run_files(run_number=1)
    gh = FakeGh(f"https://github.com/{OFFICIAL}/.github/workflows/community-eval.yml@{world.commit}", "b" * 40)
    code, summary, _, _ = world.verify(path, gh)
    assert code == 1 and "signer digest" in json.dumps(summary["refused"])
    # And a manifest that names a commit other than the one that signed is refused the same way.
    other = world.run_files(run_number=2, manifest_extra={"commit": "c" * 40})
    code, summary, _, _ = world.verify(other)
    assert code == 1


def test_a_self_hosted_runner_is_rejected(world):
    path = world.run_files(run_number=1)
    code, summary, _, gh = world.verify(path, world.gh(runner="self-hosted"))
    assert code == 1 and "self-hosted" in json.dumps(summary["refused"])
    assert all("--deny-self-hosted-runners" in argv for argv in gh.calls)


def test_a_commit_that_is_not_in_the_history_of_main_is_rejected(world):
    git(world.root, "checkout", "-q", "-b", "side")
    (world.root / "side.txt").write_text("x")
    git(world.root, "add", "-A")
    git(world.root, "commit", "-q", "-m", "side")
    side = git(world.root, "rev-parse", "HEAD")
    git(world.root, "checkout", "-q", "main")
    world.commit = side
    path = world.run_files(run_number=1)
    code, summary, _, gh = world.verify(path)
    assert code == 1 and "not in the history of main" in json.dumps(summary["refused"])
    assert gh.calls == []  # refused before any attestation is asked for
    world.commit = "d" * 40  # a commit the checkout has never seen
    code, summary, _, _ = world.verify(world.run_files(run_number=2))
    assert code == 1 and "cannot be checked" in json.dumps(summary["refused"])


def test_a_digest_mismatch_is_rejected(world):
    path = world.run_files(run_number=1)
    # The manifest's digest is not the file's: refused by the shape, before the attestation.
    manifest = path.with_name(path.stem + ".manifest.json")
    data = json.loads(manifest.read_text())
    data["evidence_sha256"] = "0" * 64
    manifest.write_text(json.dumps(data))
    code, summary, _, gh = world.verify(path)
    assert code == 1 and "evidence_sha256 is not the sha256" in json.dumps(summary["refused"]) and gh.calls == []
    # The file is the manifest's but is not a subject of the bundle (it was changed after it was attested).
    other = world.run_files(run_number=2)
    world.bundle(other, subjects=["1" * 64, sha256(other.with_name(other.stem + ".manifest.json"))])
    code, summary, _, _ = world.verify(other)
    assert code == 1 and "no valid attestation" in json.dumps(summary["refused"])
    # The manifest is not a subject either.
    third = world.run_files(run_number=3)
    world.bundle(third, subjects=[sha256(third)])
    code, summary, _, _ = world.verify(third)
    assert code == 1


def test_a_file_that_fails_the_evidence_validators_is_rejected_before_any_attestation(world):
    path = world.run_files(run_number=1, extra_event={"image_source": "local"})
    code, summary, _, gh = world.verify(path)
    assert code == 1 and "image_source must be" in json.dumps(summary["refused"]) and gh.calls == []
    unlisted = world.run_files(run_number=2, model="vendor/not-listed", adapter="oh")
    assert world.verify(unlisted)[0] == 1


# --- the change against its base ----------------------------------------------------------------------------

def test_a_pull_request_adds_files_and_never_edits_or_deletes_committed_ones(world):
    first = world.run_files(run_number=1)
    git(world.root, "add", "-A")
    git(world.root, "commit", "-q", "-m", "first")
    base = git(world.root, "rev-parse", "HEAD")
    second = world.run_files(run_number=2)
    git(world.root, "add", "-A")
    git(world.root, "commit", "-q", "-m", "second")
    err = io.StringIO()
    code, summary = vc.run(str(world.root), OFFICIAL, "main", None, world.status, base=base, gh=world.gh(), out=io.StringIO(), err=err)
    assert code == 0 and [Path(p).name for p in summary["verified"]] == [second.name], err.getvalue()
    # An edit of a committed file is refused whatever its attestation says.
    first.write_text(first.read_text() + "\n")
    git(world.root, "add", "-A")
    git(world.root, "commit", "-q", "-m", "edit")
    code, summary = vc.run(str(world.root), OFFICIAL, "main", None, world.status, base=base, gh=world.gh(), out=io.StringIO(), err=io.StringIO())
    assert code == 1 and any("never edited" in p for ps in summary["refused"].values() for p in ps)
    git(world.root, "rm", "-q", str(first))
    git(world.root, "commit", "-q", "-m", "delete")
    code, summary = vc.run(str(world.root), OFFICIAL, "main", None, world.status, base=base, gh=world.gh(), out=io.StringIO(), err=io.StringIO())
    assert code == 1 and summary["refused"]
    # A change with no community file passes.
    clean = git(world.root, "rev-parse", "HEAD")
    code, summary = vc.run(str(world.root), OFFICIAL, "main", None, world.status, base=clean, gh=world.gh(), out=io.StringIO(), err=io.StringIO())
    assert code == 0 and summary == {"verified": [], "refused": {}, "gaps": [], "attempt_gaps": [], "other_callers": []}


# --- gaps ---------------------------------------------------------------------------------------------------

def test_a_gap_in_the_run_numbers_is_a_warning_never_a_refusal(world):
    world.run_files(run_number=1, date="2030-01-01")
    git(world.root, "add", "-A")
    git(world.root, "commit", "-q", "-m", "first")
    base = git(world.root, "rev-parse", "HEAD")
    world.run_files(run_number=4, date="2030-01-04")  # runs 2 and 3 were not submitted
    git(world.root, "add", "-A")
    git(world.root, "commit", "-q", "-m", "fourth")
    err = io.StringIO()
    code, summary = vc.run(str(world.root), OFFICIAL, "main", None, world.status, base=base, gh=world.gh(), out=io.StringIO(), err=err)
    assert code == 0
    assert summary["gaps"] == [{"repository": "ana/openhora", "workflow": ce.el.CALLER_WORKFLOW, "missing": [2, 3]}]
    assert "::warning::ana/openhora" in err.getvalue() and "#2, #3" in err.getvalue()
    assert es.all_status(str(world.root), "core-demo")["community"]["gaps"] == 2


def test_a_missing_attempt_and_another_caller_workflow_are_warnings_too(world):
    world.run_files(run_number=1, run_id=5001, attempt=1)
    git(world.root, "add", "-A")
    git(world.root, "commit", "-q", "-m", "first")
    base = git(world.root, "rev-parse", "HEAD")
    world.run_files(run_number=2, run_id=5002, attempt=2, date="2030-01-02")  # attempt 1 of run 2 is not submitted
    world.run_files(run_number=1, repo_id=777, workflow=".github/workflows/other.yml", date="2030-01-03")
    git(world.root, "add", "-A")
    git(world.root, "commit", "-q", "-m", "more")
    err = io.StringIO()
    code, summary = vc.run(str(world.root), OFFICIAL, "main", None, world.status, base=base, gh=world.gh(), out=io.StringIO(), err=err)
    assert code == 0
    assert summary["attempt_gaps"] == [{"repository": "ana/openhora", "workflow": ce.el.CALLER_WORKFLOW, "run_id": 5002, "missing": [1]}]
    assert summary["other_callers"] == [{"repository": "ana/openhora", "workflow": ".github/workflows/other.yml"}]
    assert "without its attempt(s) 1" in err.getvalue() and "not the one file the guide names" in err.getvalue()


# --- the attested runner group ------------------------------------------------------------------------------

def test_a_manifest_without_the_runner_group_or_with_another_is_refused_before_any_attestation(world):
    for extra in ({"run_runner_group": "Default"}, {"run_runner_group": ""}):
        path = world.run_files(manifest_extra=extra)
        code, summary, _, gh = world.verify(path)
        assert code == 1 and "run_runner_group must be" in json.dumps(summary["refused"]) and gh.calls == []
    path = world.run_files()
    manifest = path.with_name(path.stem + ".manifest.json")
    data = json.loads(manifest.read_text())
    del data["run_runner_group"]
    manifest.write_text(json.dumps(data))
    world.bundle(path)
    code, summary, _, gh = world.verify(path)
    assert code == 1 and "missing key 'run_runner_group'" in json.dumps(summary["refused"]) and gh.calls == []


# --- the minimum signing commit -----------------------------------------------------------------------------

def test_a_signing_commit_older_than_the_minimum_or_off_the_first_parent_line_is_refused(world):
    old = world.commit
    (world.root / "later.txt").write_text("x")
    git(world.root, "add", "-A")
    git(world.root, "commit", "-q", "-m", "later")
    newer = git(world.root, "rev-parse", "HEAD")
    git(world.root, "checkout", "-q", "-b", "side")
    (world.root / "side.txt").write_text("x")
    git(world.root, "add", "-A")
    git(world.root, "commit", "-q", "-m", "side")
    side = git(world.root, "rev-parse", "HEAD")
    git(world.root, "checkout", "-q", "main")
    git(world.root, "merge", "-q", "--no-ff", "-m", "merge", "side")
    # No minimum: any commit in the history of main signs, as before.
    world.commit = old
    assert world.verify(world.run_files(run_number=1))[0] == 0
    # With a minimum, the older commit is refused, the minimum itself and a later one are accepted.
    code, summary, _, gh = world.verify(world.run_files(run_number=2), minimum=newer)
    assert code == 1 and "older than the minimum signing commit" in json.dumps(summary["refused"]) and gh.calls == []
    world.commit = newer
    assert world.verify(world.run_files(run_number=3), minimum=newer)[0] == 0
    # A commit that reached main through a merge is in its history but not on its first-parent line.
    world.commit = side
    assert world.verify(world.run_files(run_number=4))[0] == 0
    code, summary, _, _ = world.verify(world.run_files(run_number=5), minimum=newer)
    assert code == 1 and "not on the first-parent line" in json.dumps(summary["refused"])


def test_the_minimum_is_read_from_the_code_root_and_must_be_a_commit_or_null(tmp_path):
    (tmp_path / "evals").mkdir()
    assert vc.read_minimum(str(tmp_path)) == (None, None)
    for body, ok in (('{"min_signing_commit": null}', True), ('{"min_signing_commit": "' + "a" * 40 + '"}', True),
                     ('{"min_signing_commit": "main"}', False), ('{"min_signing_commit": null, "note": "x"}', False), ("[]", False), ("{", False)):
        (tmp_path / "evals" / "community.json").write_text(body)
        minimum, problem = vc.read_minimum(str(tmp_path))
        assert (problem is None) is ok, body
    assert json.loads((REPO / "evals" / "community.json").read_text()) == {"min_signing_commit": None}


def test_the_strict_reading_uses_the_base_trees_gate_file_not_the_pull_requests(world, tmp_path):
    path = world.run_files(run_number=1)
    assert world.verify(path)[0] == 0
    base_tree = tmp_path / "base-tree"
    (base_tree / "evals").mkdir(parents=True)
    gate = json.loads((world.root / "evals" / "eval-gate.json").read_text())
    gate["runs"] = 5  # the base wants 5 runs; the pull request's own gate file says 3
    gate["baseline_runs"] = 1
    (base_tree / "evals" / "eval-gate.json").write_text(json.dumps(gate))
    (base_tree / "skills").mkdir()
    code, summary, _, gh = world.verify(path, ref_root=str(base_tree))
    assert code == 1 and "configured number is 5" in json.dumps(summary["refused"]) and gh.calls == []


# --- the command line ---------------------------------------------------------------------------------------

def test_the_command_line_needs_the_official_repository_and_a_checkout_of_the_workbench_for_its_code(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert vc.main(["--root", str(tmp_path), "--all"]) == 2
    with pytest.raises(SystemExit) as stopped:
        vc.main(["--root", str(tmp_path), "--official-repo", OFFICIAL, "--code-root", str(tmp_path), "--all"])
    assert "--code-root must be a checkout" in str(stopped.value)
    with pytest.raises(SystemExit) as stopped:
        vc.main(["--help"])
    assert stopped.value.code == 0
    assert "never edited" in capsys.readouterr().out
