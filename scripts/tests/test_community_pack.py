"""Offline tests of scripts/community_pack.py: the check of a community request before a model runs, and the packing of the
evidence file the lab test wrote into the two files the attestation covers. No model, no network, no docker: the evidence
file the runner would write is built here, and the packed files are then read by the same validators the pull request's check
uses.

Run: uv run --with pytest pytest scripts/tests/test_community_pack.py
"""
from __future__ import annotations

import hashlib
import importlib.util
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


cp = load("community_pack_under_test", "scripts/community_pack.py")
ce = load("community_evidence_helpers_for_pack", "evals/tests/test_community_evidence.py")
es = ce.es
FLASH = "openrouter/deepseek/deepseek-v4.1-flash"
NAMES = ("OPENROUTER_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")
KEYS = {name: f"a-value-of-{name.lower()}" for name in NAMES}  # stand-ins; none is a credential
REF = "ana/openhora/.github/workflows/lab.yml@refs/heads/main"
IDS = ["--repository", "ana/openhora", "--repository-id", "111", "--run-id", "222", "--run-attempt", "1", "--run-number", "5"]


def git(root, *args):
    env = {**{k: v for k, v in os.environ.items() if not k.startswith("GIT_")}, "GIT_AUTHOR_NAME": "Ana", "GIT_AUTHOR_EMAIL": "ana@mail.example",
           "GIT_COMMITTER_NAME": "Ana", "GIT_COMMITTER_EMAIL": "ana@mail.example"}
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    repo = ce.skill(root)
    ce.versions(repo, ("1.0.0", "new"))
    ce.gate_root(root)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "official")
    return root, repo, git(root, "rev-parse", "HEAD"), tmp_path / "local"


def lab_file(repo, local, where="local", **kw):
    """What the runner leaves: a lab evidence file (no source marker) in the local evidence folder, or in the skill's."""
    kwargs = {"model": FLASH, "adapter": "agents-dir", "mv": 9, "bundle": False, **kw}
    kwargs["extra_event"] = {"grader": "claude-sonnet-5-5", **kwargs.get("extra_event", {})}
    path = ce.community(repo, **kwargs)
    lines = [json.loads(l) for l in path.read_text().splitlines()]
    lines[0].pop("source", None)
    target_dir = (local / "core-demo") if where == "local" else (repo / "evals" / "evidence")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"lab-{lines[0]['test']}.jsonl"
    target.write_text("".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lines))
    for f in path.parent.glob(path.stem + "*"):
        f.unlink()
    return target


def pack(root, local, commit, out, model=FLASH, extra=()):
    return cp.main(["pack", "--skill", "core-demo", "--model", model, "--out", str(out), *IDS, "--workflow-ref", REF,
                    "--commit", commit, "--root", str(root), "--local-evidence", str(local), *extra])


# --- preflight ----------------------------------------------------------------------------------------------

def preflight(args, env=None, root=REPO):
    return cp.main(["preflight", "--root", str(root), *args], env=KEYS if env is None else env)


def test_a_request_for_a_listed_model_with_its_keys_set_passes(capsys):
    assert preflight(["--skill", "biz-icp-positioning", "--model", FLASH, "--cases", "1,2"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert preflight(["--skill", "biz-icp-positioning", "--model", "deepseek-v4.1-flash", "--full", "--adapter", "agents-dir"]) == 0  # an alias


@pytest.mark.parametrize("args, said", [
    (["--skill", "no-such-skill", "--model", FLASH, "--full"], "is not a skill"),
    (["--skill", "../x", "--model", FLASH, "--full"], "skill must be a skill name"),
    (["--skill", "biz-icp-positioning", "--model", "vendor/unlisted", "--full"], "is not a model of the gate file"),
    (["--skill", "biz-icp-positioning", "--model", "bad model", "--full"], "model must be a model id"),
    (["--skill", "biz-icp-positioning", "--model", FLASH, "--full", "--adapter", "claude-code"], "runs through the adapter agents-dir"),
    (["--skill", "biz-icp-positioning", "--model", FLASH], "exactly one of full"),
    (["--skill", "biz-icp-positioning", "--model", FLASH, "--full", "--cases", "1"], "exactly one of full"),
    (["--skill", "biz-icp-positioning", "--model", FLASH, "--cases", "1;rm -rf /"], "cases must be case ids"),
])
def test_a_request_the_workflow_must_not_run_is_refused(args, said, capsys):
    assert preflight(args) == 1
    assert said in capsys.readouterr().err


def test_a_missing_key_is_named_and_no_value_is_ever_printed(capsys):
    assert preflight(["--skill", "biz-icp-positioning", "--model", FLASH, "--full"], env={NAMES[1]: KEYS[NAMES[1]]}) == 1
    captured = capsys.readouterr()
    assert "OPENROUTER_API_KEY" in captured.err and "CLAUDE_CODE_OAUTH_TOKEN" not in captured.err
    assert not any(value in captured.err + captured.out for value in KEYS.values())
    # the grader's token is needed whatever the model: every grading goes through the grader's own entry of the gate file
    assert preflight(["--skill", "biz-icp-positioning", "--model", FLASH, "--full"], env={NAMES[0]: KEYS[NAMES[0]]}) == 1
    assert "CLAUDE_CODE_OAUTH_TOKEN" in capsys.readouterr().err


def test_a_model_with_no_route_is_not_tested_in_the_community(tmp_path, capsys):
    root = tmp_path / "r"
    (root / "evals").mkdir(parents=True)
    (root / "skills" / "core-demo").mkdir(parents=True)
    (root / "skills" / "core-demo" / "SKILL.md").write_text("x")
    gate = json.loads((REPO / "evals" / "eval-gate.json").read_text())
    gate["models"]["local-model"] = {"aliases": [], "adapter": "agents-dir", "pass_env": [], "route": None, "provider_pin": None,
                                     "upstream_models": ["m"], "price_source": "https://example.test/p", "run_token_budget": 1}
    (root / "evals" / "eval-gate.json").write_text(json.dumps(gate))
    assert preflight(["--skill", "core-demo", "--model", "local-model", "--full"], root=root) == 1
    assert "has no route" in capsys.readouterr().err


# --- pack ---------------------------------------------------------------------------------------------------

def test_the_packed_files_pass_the_validators_the_pull_request_check_uses(tree, tmp_path, capsys):
    root, repo, commit, local = tree
    source = lab_file(repo, local)
    out = tmp_path / "out"
    assert pack(root, local, commit, out) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["name"] == "community-111-222-1" and result["files"] == ["community-111-222-1.jsonl", "community-111-222-1.manifest.json"]
    evidence, manifest = out / result["files"][0], out / result["files"][1]
    assert hashlib.sha256(evidence.read_bytes()).hexdigest() == result["evidence_sha256"]
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == result["manifest_sha256"]
    # the event line gains the marker and nothing else; every other line is the runner's, byte for byte
    before, after = source.read_text().splitlines(), evidence.read_text().splitlines()
    assert json.loads(after[0]) == {**json.loads(before[0]), "source": "community"} and after[1:] == before[1:]
    data = json.loads(manifest.read_text())
    assert data == {"record": "community-manifest", "repository": "ana/openhora", "repository_id": 111, "run_id": 222, "run_attempt": 1,
                    "run_number": 5, "workflow": ".github/workflows/lab.yml", "commit": commit, "skill": "core-demo", "model": FLASH,
                    "evidence_sha256": result["evidence_sha256"]}
    assert es.EVIDENCE_LINES.manifest_problems(data, partial=True) == []
    assert any("run_runner_group" in p for p in es.EVIDENCE_LINES.manifest_problems(data))  # the attestation job adds it
    # Placed in the skill's folder with a bundle, the trio is a valid community file, read strictly as a new one is.
    folder = repo / "evals" / "evidence"
    for name in result["files"]:
        (folder / name).write_bytes((out / name).read_bytes())
    (folder / "community-111-222-1.sigstore.json").write_text(json.dumps(ce.BUNDLE))
    complete = folder / "community-111-222-1.manifest.json"
    complete.write_text(json.dumps({**data, "run_runner_group": es.EVIDENCE_LINES.RUNNER_GROUP}, indent=2, sort_keys=True))
    assert es.community_file_problems(str(folder / "community-111-222-1.jsonl"), str(root), "core-demo", strict=True) == []


def test_an_untracked_file_in_the_skill_s_folder_is_found_and_a_committed_one_is_not(tree, tmp_path, capsys):
    root, repo, commit, local = tree
    committed = lab_file(repo, local, where="skill", run_id=1)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "an earlier lab file")
    commit = git(root, "rev-parse", "HEAD")
    assert pack(root, local, commit, tmp_path / "out") == 1  # nothing new: the committed file is not this run's
    assert "found 0" in capsys.readouterr().err
    lab_file(repo, local, where="skill", run_id=2, date="2030-02-01")
    assert pack(root, local, commit, tmp_path / "out") == 0
    assert committed.exists()


@pytest.mark.parametrize("what, said", [
    ("none", "found 0"), ("two", "found 2"), ("head", "is not the commit of the official workflow"),
    ("models", "exactly"), ("incomplete", "not complete"), ("local image", "published eval image"),
    ("other skill", "evidence is of"), ("marker", "already carries a source"), ("bad ref", "--workflow-ref"),
    ("bad ids", "whole numbers"), ("unlisted", "is not a model of the gate file")])
def test_a_run_that_is_not_a_clean_community_test_of_the_model_packs_nothing(what, said, tree, tmp_path, capsys):
    root, repo, commit, local = tree
    out = tmp_path / "out"
    model, skill = FLASH, "core-demo"
    if what != "none":
        kw = {"models": dict(extra_event={"models": [FLASH, "claude-sonnet-5-5"], "adapters": {FLASH: "agents-dir", "claude-sonnet-5-5": "claude-code"},
                                           "adapter_sha256": {"agents-dir": "b" * 64, "claude-code": "b" * 64}}),
              "incomplete": dict(kind="partial", extra_event={"complete": False}),
              "local image": dict(extra_event={"image_source": "local"})}.get(what, {})
        source = lab_file(repo, local, **kw)
        if what == "marker":
            lines = [json.loads(l) for l in source.read_text().splitlines()]
            lines[0]["source"] = "community"
            source.write_text("".join(json.dumps(l) + "\n" for l in lines))
        if what == "other skill":  # a file of core-demo found where the request is for another skill
            skill = "core-other"
            ce.versions(ce.skill(root, name=skill), ("1.0.0", "new"))
            (local / skill).mkdir()
            source.rename(local / skill / source.name)
    if what == "two":
        lab_file(repo, local, date="2030-02-01")
    if what == "head":
        commit = "e" * 40
    if what == "unlisted":
        model = "vendor/unlisted"
    argv = ["pack", "--skill", skill, "--model", model, "--out", str(out), *IDS, "--workflow-ref", REF, "--commit", commit,
            "--root", str(root), "--local-evidence", str(local)]
    if what == "bad ref":
        argv[argv.index("--workflow-ref") + 1] = "not a ref"
    if what == "bad ids":
        argv[argv.index("--run-id") + 1] = "12x"
    assert cp.main(argv) == 1
    assert said in capsys.readouterr().err
    assert not out.exists() or not list(out.iterdir())  # nothing is left to attest


def test_the_command_line_is_documented():
    assert "preflight" in cp.__doc__ and "pack" in cp.__doc__ and "Only the NAMES" in cp.__doc__
    with pytest.raises(SystemExit) as stopped:
        cp.main(["--help"])
    assert stopped.value.code == 0
