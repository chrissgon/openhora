"""Offline tests of community evidence (the plan's decisions D19 and D36; package P10): the closed marker of an event line,
the shape of the three files of a community run, the strict reading of a new file, the column of its own in the status, the
cap per contributor, the flagged gaps in run numbers, the flag `community_only` that keeps a pair reliable only through
community evidence from releasing unattended work, and the demotion by three failed verdicts. No model and no network:
the attestation itself is verified by scripts/verify_community.py (tested beside it); here the files are read as they stand.

Run: uv run --with pytest pytest evals/tests/test_community_evidence.py
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("bands_helpers_for_community", Path(__file__).with_name("test_bands.py"))
tb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tb)
es, CFG, H, skill, versions, git, field, use = tb.es, tb.CFG, tb.H, tb.skill, tb.versions, tb.git, tb.field, tb.use
el = es.EVIDENCE_LINES

BUNDLE = {"mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json", "verificationMaterial": {}, "dsseEnvelope": {}}
COMMIT = "a" * 40
SEQ = iter(range(1, 10 ** 6))


def community(folder, model="old-model", adapter="oh", repo_id=111, run_id=None, attempt=1, run_number=1, kind="full",
              date="2030-01-01", version="1.0.0", with_score=0.9, base_score=0.5, cases=(1, 2, 3), per_case=3, extra_event=None,
              workflow=".github/workflows/lab.yml", repository="ana/openhora", manifest_extra=None, bundle=True, mv=5):
    """Write the three files of one community run in the skill's evidence folder. A full test has per_case lines with the
    skill and per_case without it, for every case; a partial one has the lines with the skill alone."""
    run_id = run_id or next(SEQ) + 1000
    name = f"community-{repo_id}-{run_id}-{attempt}"
    test = f"{date.replace('-', '')}T000000Z-{next(SEQ):08x}"
    hashes = es.case_hashes(str(folder))
    event = {"record": "test", "skill": folder.name, "test": test, "kind": kind, "version": version, "content_sha256": H["a"],
             "date": date, "models": [model], "adapters": {model: adapter}, "adapter_sha256": {adapter: H["b"]},
             "grader": "s-model", "runs": max(3, per_case), "timeout_seconds": 900, "retries": 2, "measurement_version": mv,
             "measurement_sha256": H["d"], "image_digest": "sha256:" + H["e"], "image_platform": "linux/amd64",
             "grading_template_sha256": H["f"], "tools": {}, "cases": {str(c): hashes[str(c)] for c in cases},
             "baseline": {str(c): "run" if kind == "full" else "none" for c in cases}, "web_cases": [], "counts": {},
             "extra_pass_env": [], "complete": True, "complete_models": [model], "image_source": "published", "source": "community"}
    if kind == "full":
        event["gate"] = {model: {"passed": True, "with": with_score, "baseline": base_score, "threshold": 0.8, "tolerance": 0.05}}
    event.update(extra_event or {})
    runs = []
    for case in cases:
        for variant, score in (("with", with_score), ("without", base_score)):
            if variant == "without" and kind != "full":
                continue
            for _ in range(per_case):
                res = tb.results(score)
                runs.append({"record": "run", "skill": folder.name, "version": version, "content_sha256": H["a"], "model": model,
                             "adapter": adapter, "kind": kind, "test": test, "date": date, "measurement_version": mv,
                             "measurement_sha256": H["d"], "case": case, "case_sha256": hashes[str(case)], "variant": variant,
                             "outcome": "graded", "score": sum(res) / len(res), "results": res})
    data = "".join(json.dumps(l) + "\n" for l in [event] + runs).encode()
    folder_ev = folder / "evals" / "evidence"
    folder_ev.mkdir(parents=True, exist_ok=True)
    (folder_ev / f"{name}.jsonl").write_bytes(data)
    manifest = {"record": "community-manifest", "repository": repository, "repository_id": repo_id, "run_id": run_id,
                "run_attempt": attempt, "run_number": run_number, "workflow": workflow, "commit": COMMIT, "skill": folder.name,
                "model": model, "evidence_sha256": hashlib.sha256(data).hexdigest(), **(manifest_extra or {})}
    (folder_ev / f"{name}.manifest.json").write_text(json.dumps(manifest, indent=2))
    if bundle:
        (folder_ev / f"{name}.sigstore.json").write_text(json.dumps(BUNDLE))
    return folder_ev / f"{name}.jsonl"


@pytest.fixture
def root(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    return tmp_path


@pytest.fixture
def repo(root):
    folder = skill(root)
    versions(folder, ("1.0.0", "new"))
    return folder


def commit(root, who="Ana <ana@mail.example>", message="community evidence"):
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message, author=who)


def section(root):
    return es.community_section(str(root), ["core-demo"], CFG, es.evidence_authors(str(root)), es.all_status(str(root), "core-demo")["skills"])


# --- the closed marker --------------------------------------------------------------------------------------

def test_a_valid_community_run_is_accepted_by_its_shape(root, repo):
    path = community(repo)
    assert es.community_file_problems(str(path), str(root), "core-demo") == []


def test_source_is_a_closed_marker_that_a_lab_or_a_local_file_never_carries(root, repo):
    event = tb.event(repo, "full", "1.0.0", "2030-01-01", [(1, "with", 0.9, None)])
    lines = [json.loads(l) for l in event.read_text().splitlines()]
    lines[0]["source"] = "community"
    event.write_text("".join(json.dumps(l) + "\n" for l in lines))
    problems = es.evidence_file_problems(str(event), str(root), "core-demo")
    assert any("never carries it" in p for p in problems)
    assert es.skill_evidence(str(repo)) == []  # and it is not read as lab evidence
    lines[0]["source"] = "someone"
    assert any("source must be" in p for p in el.event_line_problems(lines[0]))
    lines[0].pop("source")
    assert el.event_line_problems(lines[0]) == []


def test_a_community_file_without_the_marker_or_with_a_local_image_or_two_models_is_refused(root, repo):
    path = community(repo, run_id=1)
    lines = [json.loads(l) for l in path.read_text().splitlines()]
    for change, expect in (
            (lambda e: e.pop("source"), "source must be"),
            (lambda e: e.update(image_source="local"), "image_source must be"),
            (lambda e: e.update(models=["old-model", "s-model"], adapters={"old-model": "oh", "s-model": "h"},
                                adapter_sha256={"oh": H["b"], "h": H["b"]}), "exactly one")):
        broken = copy.deepcopy(lines)
        change(broken[0])
        target = repo / "evals" / "evidence" / "community-111-2-1.jsonl"
        data = "".join(json.dumps(l) + "\n" for l in broken).encode()
        target.write_bytes(data)
        manifest = json.loads((repo / "evals" / "evidence" / "community-111-1-1.manifest.json").read_text())
        manifest.update(run_id=2, evidence_sha256=hashlib.sha256(data).hexdigest())
        (repo / "evals" / "evidence" / "community-111-2-1.manifest.json").write_text(json.dumps(manifest))
        (repo / "evals" / "evidence" / "community-111-2-1.sigstore.json").write_text(json.dumps(BUNDLE))
        assert any(expect in p for p in es.community_file_problems(str(target), str(root), "core-demo")), expect


def test_the_three_files_must_agree_with_one_another(root, repo):
    expectations = {
        "bundle": ("sigstore.json is missing", dict(bundle=False)),
        "sha": ("evidence_sha256 is not the sha256", dict(manifest_extra={"evidence_sha256": "0" * 64})),
        "ids": ("not the ones the file's name carries", dict(manifest_extra={"repository_id": 7})),
        "model": ("not the one the manifest names", dict(manifest_extra={"model": "s-model"})),
        "skill": ("skill must be the folder's name", dict(manifest_extra={"skill": "other-skill"})),
        "free text": ("unknown key", dict(manifest_extra={"note": "trust me"})),
        "commit": ("commit must be", dict(manifest_extra={"commit": "main"})),
        "repository": ("repository must be", dict(manifest_extra={"repository": "not a repository"})),
    }
    for what, (expect, kwargs) in expectations.items():
        path = community(repo, **kwargs)
        problems = es.community_file_problems(str(path), str(root), "core-demo")
        assert any(expect in p for p in problems), (what, problems)
        for f in path.parent.glob(path.stem + "*"):
            f.unlink()
    path = community(repo)
    (path.parent / (path.stem + ".manifest.json")).unlink()
    assert any("manifest.json is missing" in p for p in es.community_file_problems(str(path), str(root), "core-demo"))


def test_a_link_is_never_a_community_file(root, repo, tmp_path):
    path = community(repo)
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text(json.dumps(BUNDLE))
    bundle = path.with_name(path.stem + ".sigstore.json")
    bundle.unlink()
    bundle.symlink_to(elsewhere)
    assert any("is a link" in p for p in es.community_file_problems(str(path), str(root), "core-demo"))
    bundle.unlink()
    bundle.write_text(json.dumps(BUNDLE))
    data = path.read_bytes()
    path.unlink()
    target = tmp_path / "target.jsonl"
    target.write_bytes(data)
    path.symlink_to(target)
    assert any("is a link" in p for p in es.community_file_problems(str(path), str(root), "core-demo"))


def test_a_locally_edited_skill_is_not_evidence(root, repo):
    path = community(repo)
    versions(repo, ("1.0.0", "new"))
    (repo / "evals" / "versions.jsonl").write_text(json.dumps({"version": "1.0.0", "content_sha256": H["c"], "class": "new",
                                                                "date": "2030-01-01"}) + "\n")
    assert any("content_sha256 is not the hash the version file gives" in p
               for p in es.community_file_problems(str(path), str(root), "core-demo"))


# --- the strict reading of a new file -----------------------------------------------------------------------

def gate_root(root):
    """A tree with the committed gate file: its models, routes and adapters are the strict reading's source."""
    (root / "evals").mkdir(exist_ok=True)
    (root / "evals" / "eval-gate.json").write_text((REPO / "evals" / "eval-gate.json").read_text())
    return root


def test_a_new_file_must_be_a_listed_model_with_a_route_through_its_adapter_and_the_configured_runs(root, repo):
    gate_root(root)
    flash = "openrouter/deepseek/deepseek-v4.1-flash"
    ok = community(repo, model=flash, adapter="agents-dir", extra_event={"grader": "claude-sonnet-5-5"})
    assert es.community_file_problems(str(ok), str(root), "core-demo", strict=True) == []
    wrong_adapter = community(repo, model=flash, adapter="claude-code", extra_event={"grader": "claude-sonnet-5-5"})
    assert any("ran through the adapter claude-code" in p for p in es.community_file_problems(str(wrong_adapter), str(root), "core-demo", strict=True))
    unlisted = community(repo, model="vendor/not-listed", adapter="oh", extra_event={"grader": "claude-sonnet-5-5"})
    assert any("models must be" in p for p in es.community_file_problems(str(unlisted), str(root), "core-demo", strict=True))
    trial = community(repo, model=flash, adapter="agents-dir", extra_event={"grader": "claude-sonnet-5-5", "runs": 2})
    assert any("configured number is 3" in p for p in es.community_file_problems(str(trial), str(root), "core-demo", strict=True))
    # A file already merged is read by its own event line: a later change of the gate file does not invalidate it.
    assert es.community_file_problems(str(wrong_adapter), str(root), "core-demo", strict=None) == []


def test_a_model_with_no_route_is_not_tested_in_the_community(root, repo):
    gate_root(root)
    gate = json.loads((root / "evals" / "eval-gate.json").read_text())
    gate["models"]["claude-sonnet-5-5"]["route"] = None
    gate["models"]["claude-sonnet-5-5"]["provider_pin"] = None
    gate["models"]["claude-sonnet-5-5"]["pass_env"] = []
    gate["strong_pass_env"] = []
    (root / "evals" / "eval-gate.json").write_text(json.dumps(gate))
    reading = es.community_strict_reading(str(root))
    assert "claude-sonnet-5-5" not in reading["entries"] and "openrouter/deepseek/deepseek-v4.1-flash" in reading["entries"]


def test_the_walk_over_the_evidence_folder_reads_community_files_and_refuses_what_belongs_to_none(root, repo):
    path = community(repo)
    found, checked = es.evidence_problems(str(root))
    assert found == {} and checked == 3
    (path.parent / (path.stem + ".sigstore.json")).unlink()
    found, _ = es.evidence_problems(str(root))
    assert any("sigstore.json is missing" in p for p in found[os.path.relpath(path, root)])
    orphan = path.parent / "community-999-5-1.manifest.json"
    orphan.write_text("{}")
    (path.parent / "community-notes.txt").write_text("x")
    found, _ = es.evidence_problems(str(root))
    assert any("not in the folder" in p for p in found[os.path.relpath(orphan, root)])
    assert any("the name must be community-" in p for p in found[os.path.relpath(path.parent / "community-notes.txt", root)])


# --- the column of its own ----------------------------------------------------------------------------------

def test_community_evidence_has_a_column_of_its_own_and_never_changes_a_lab_figure(root, repo):
    tb.full(repo)
    commit(root, "Owner <owner@mail.example>", "lab evidence")
    before = es.all_status(str(root), "core-demo")
    assert "community" not in before
    community(repo, model="f-model", adapter="fh")
    commit(root)
    after = es.all_status(str(root), "core-demo")
    assert {k: v for k, v in after.items() if k != "community"} == before  # the rows, the counts and the bands are the lab's
    figures = after["community"]["skills"]["core-demo"]["f-model"]
    assert (figures["runs"], figures["current_runs"], figures["files"], figures["contributors"]) == (9, 9, 1, 1)
    assert figures["mean"] == pytest.approx(0.9) and figures["score"] == pytest.approx(0.705, abs=0.001)
    assert figures["band"] == "reliable" and figures["capped"] == 0 and figures["gaps"] == 0
    assert after["community"]["cap"] == es.COMMUNITY_CAP and after["community"]["gaps"] == 0
    assert "mail.example" not in json.dumps(after)  # who contributed is never printed


def test_the_committed_evidence_has_no_community_section(root):
    status = es.all_status(str(REPO), "biz-icp-positioning")
    assert "community" not in status


def test_the_inventory_gains_the_column_only_once_community_evidence_exists(root, repo):
    tb.full(repo)
    commit(root, "Owner <owner@mail.example>", "lab evidence")
    (root / "docs").mkdir()
    assert "Community verified" not in es.inventory_block(str(root))
    community(repo, model="f-model", adapter="fh")
    commit(root)
    block = es.inventory_block(str(root))
    assert "Community verified: runs, mean, score" in block and "(community only)" in block


# --- the cap per contributor --------------------------------------------------------------------------------

def test_a_contributor_adds_at_most_cap_lines_with_the_skill_per_model_and_the_newest_are_kept(root, repo):
    old = community(repo, model="f-model", adapter="fh", date="2030-01-01", run_number=1, with_score=0.0, base_score=0.0, per_case=5)
    new = community(repo, model="f-model", adapter="fh", date="2030-02-01", run_number=2, with_score=1.0, base_score=0.0, per_case=5)
    commit(root, "Ana <ana@mail.example>")  # 15 + 15 lines with the skill: the cap is 30
    figures = section(root)["skills"]["core-demo"]["f-model"]
    assert figures["runs"] == 30 and figures["capped"] == 0
    third = community(repo, model="f-model", adapter="fh", date="2030-03-01", run_number=3, with_score=1.0, base_score=0.0, per_case=5)
    commit(root, "Ana <ana@mail.example>")
    figures = section(root)["skills"]["core-demo"]["f-model"]
    assert figures["runs"] == 30 and figures["capped"] == 15 and figures["mean"] == 1.0  # the oldest 15, all failures, are gone
    assert figures["contributors"] == 1 and figures["files"] == 3
    # A second contributor has a cap of their own, and a second model too.
    community(repo, model="f-model", adapter="fh", date="2030-04-01", repo_id=222, run_number=1, with_score=0.0, base_score=0.0, per_case=5)
    commit(root, "Bo <bo@mail.example>")
    figures = section(root)["skills"]["core-demo"]["f-model"]
    assert figures["runs"] == 45 and figures["contributors"] == 2 and figures["mean"] == pytest.approx(30 / 45, abs=1e-3)
    community(repo, model="old-model", adapter="oh", date="2030-05-01", run_number=4, per_case=5)
    commit(root, "Ana <ana@mail.example>")
    other = section(root)["skills"]["core-demo"]["old-model"]
    assert other["runs"] == 15 and other["capped"] == 0
    assert old.exists() and new.exists() and third.exists()  # a capped file stays in the repository; only the figures leave it


def test_a_file_not_yet_committed_is_one_contributor_and_without_history_nothing_is_computed(root, repo):
    tb.full(repo)
    commit(root, "Owner <owner@mail.example>", "lab evidence")
    community(repo, model="f-model", adapter="fh")  # in the working tree, not committed
    figures = section(root)["skills"]["core-demo"]["f-model"]
    assert figures["contributors"] == 1 and figures["runs"] == 9
    assert es.community_section(str(root), ["core-demo"], CFG, None, [])["computed"] is False


# --- gaps in run numbers ------------------------------------------------------------------------------------

def test_a_gap_in_the_run_numbers_of_a_fork_s_workflow_is_flagged_never_refused(root, repo):
    for number in (1, 2, 4):
        community(repo, model="f-model", adapter="fh", run_number=number, date=f"2030-01-0{number}")
    commit(root)
    data = section(root)
    assert data["gaps"] == 1 and data["skills"]["core-demo"]["f-model"]["gaps"] == 1  # run 3 was not submitted
    assert es.evidence_problems(str(root))[0] == {}  # flagged, not refused
    manifests = [m for _, m in es.community_manifests(str(root))]
    assert es.community_gaps(manifests) == {(111, ".github/workflows/lab.yml"): [3]}
    # Run numbers count per workflow and per fork: another workflow or another fork has its own count.
    community(repo, model="f-model", adapter="fh", run_number=1, workflow=".github/workflows/other.yml", repo_id=333)
    community(repo, model="f-model", adapter="fh", run_number=1, repo_id=444)
    assert section(root)["gaps"] == 1
    # The first runs count too: submitting run 3 alone leaves 1 and 2 missing.
    community(repo, model="f-model", adapter="fh", run_number=3, repo_id=555)
    assert section(root)["gaps"] == 3
    # An attempt of a run shares its number.
    community(repo, model="f-model", adapter="fh", run_number=1, attempt=2, repo_id=444)
    assert section(root)["gaps"] == 3


# --- community only: never releasing unattended work (D36) -------------------------------------------------

def only(root, model):
    return section(root)["skills"]["core-demo"][model]["community_only"]


def test_community_only_is_set_exactly_when_the_pair_is_reliable_only_through_community_evidence(root, repo):
    # A pair with no lab evidence at all, reliable in the community column: only through community evidence.
    community(repo, model="old-model", adapter="oh")
    commit(root)
    assert only(root, "old-model") is True
    # A pair whose lab band is reliable too is not "only": the lab proves it.
    tb.event(repo, "full", "1.0.0", "2030-01-01", [(c, v, 0.9 if v == "with" else 0.5, None) for c in (1, 2, 3)
                                                     for v in ("with", "without") for _ in range(3)])
    commit(root, "Owner <owner@mail.example>", "lab evidence")
    community(repo, model="s-model", adapter="h", repo_id=222)
    commit(root)
    assert section(root)["skills"]["core-demo"]["s-model"]["band"] == "reliable"
    assert only(root, "s-model") is False
    assert only(root, "old-model") is True  # nothing changed for the other pair


def test_a_pair_that_is_not_reliable_in_the_community_column_is_not_community_only(root, repo):
    community(repo, model="old-model", adapter="oh", with_score=0.6, base_score=0.5)  # the gate fails: needs a test
    community(repo, model="f-model", adapter="fh", kind="partial")  # no full test: needs a test
    community(repo, model="s-model", adapter="h", with_score=0.5, base_score=0.0, repo_id=222)  # a score under 0.70 would be watch
    commit(root)
    data = section(root)["skills"]["core-demo"]
    assert data["old-model"]["band"] == "needs a test" and data["old-model"]["community_only"] is False
    assert data["f-model"]["band"] == "needs a test" and data["f-model"]["community_only"] is False
    assert data["s-model"]["community_only"] is False


def test_a_pair_with_a_lab_row_that_is_not_reliable_is_community_only_when_the_community_makes_it_reliable(root, repo):
    tb.event(repo, "partial", "1.0.0", "2030-01-01", [(1, "with", 0.9, {"model": "f-model", "adapter": "fh"})])  # f-model: a partial test only
    commit(root, "Owner <owner@mail.example>", "lab evidence")
    community(repo, model="f-model", adapter="fh")
    commit(root)
    lab = es.all_status(str(root), "core-demo")["skills"][0]["models"]["f-model"]
    assert lab["band"] == "needs a test"
    assert only(root, "f-model") is True


@pytest.mark.parametrize("failed, band, held", [(2, "reliable", True), (3, "watch", False)])
def test_three_failed_verdicts_demote_a_community_ranked_pair_as_they_do_a_lab_pair(root, repo, failed, band, held):
    tb.full(repo)
    commit(root, "Owner <owner@mail.example>", "lab evidence")  # the repository's owner added lab evidence: all of their failures count
    community(repo, model="old-model", adapter="oh", date="2030-01-01")
    commit(root)
    assert only(root, "old-model") is True
    field(repo, [l for n in range(1, failed + 1) for l in use(n, "failed", model="old-model", week="2030-W20")])
    commit(root, "Owner <owner@mail.example>", "field verdicts")
    figures = section(root)["skills"]["core-demo"]["old-model"]
    assert figures["band"] == band and figures["community_only"] is held
    if failed == 3:
        assert figures["kind"] == "field signal" and "`failed` verdicts" in figures["cause"]
