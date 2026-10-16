"""Offline tests of the one base resolver (evals/eval_status.py, resolve_base) and of the bump that refuses a base that is
not the change's base, each in a small git repository: the order of the steps (WB_BASE_REF, the config key workbench.baseRef,
the branch's upstream, the merge base with the default branch), the refusal of a bump whose version file is not the base's
lines plus at most one, and the validator's class checks reading the same base. The repository and its helpers are those of
test_versions.py.

Run: uv run --with pytest pytest evals/tests/test_base_resolver.py
"""
from __future__ import annotations

import pytest

from test_versions import edit, es, findings, git, repo, validate, versions  # noqa: F401  (repo is a fixture)


@pytest.fixture
def stacked(repo, monkeypatch):  # noqa: F811
    """main holds eng-demo at 1.2.0 (one version line); `integration` is cut from it and holds two more lines (1.3.0, 1.4.0),
    each raised against the line before it; `work` is cut from `integration`, as a package branch is, with an edit not
    yet bumped. No upstream, no WB_BASE_REF and no workbench.baseRef."""
    git(repo, "checkout", "-q", "-b", "integration", "main")
    edit(repo, "1. Read the change.", "1. Read the change and its tests.")
    monkeypatch.setenv("WB_BASE_REF", "main")
    es.bump(str(repo), "eng-demo", "y", date="2030-02-01")
    git(repo, "commit", "-q", "-am", "first integration change")
    edit(repo, "1. Read the change and its tests.", "1. Read the change, its tests and its docs.")
    monkeypatch.setenv("WB_BASE_REF", "HEAD")
    es.bump(str(repo), "eng-demo", "y", date="2030-03-01")
    git(repo, "commit", "-q", "-am", "second integration change")
    monkeypatch.delenv("WB_BASE_REF")
    assert [l["version"] for l in versions(repo)] == ["1.2.0", "1.3.0", "1.4.0"]
    git(repo, "checkout", "-q", "-b", "work")
    edit(repo, "its docs.", "its docs and the callers.")
    return repo


def snapshot(root):
    skill = root / "skills" / "eng-demo"
    return (skill / "SKILL.md").read_text(), (skill / "evals" / "versions.jsonl").read_text()


def sha(root, ref):
    return git(root, "rev-parse", ref).strip()


def test_a_bump_against_the_wrong_base_is_refused_and_writes_nothing(stacked, capsys):
    before = snapshot(stacked)
    assert es.comparison_base(str(stacked)) == sha(stacked, "main")  # the base of the bug report: main
    with pytest.raises(es.BaseMismatch) as e:
        es.bump(str(stacked), "eng-demo", "y", date="2030-04-01")
    message = str(e.value)
    assert "nothing written" in message and "WB_BASE_REF" in message and "workbench.baseRef" in message
    assert "the merge base with the default branch (main)" in message
    assert snapshot(stacked) == before and '  version: "1.4.0"' in before[0]
    with pytest.raises(SystemExit) as exit_:
        es.main(["bump", "--skill", "eng-demo", "--class", "y"], root=str(stacked))
    assert exit_.value.code == 2 and snapshot(stacked) == before
    assert "workbench.baseRef" in capsys.readouterr().err
    with pytest.raises(es.BaseMismatch):  # a first-line bump (no class) is refused as well: three lines against one
        es.bump(str(stacked), "eng-demo")
    assert snapshot(stacked) == before


def test_a_bump_against_the_right_base_still_works_and_prints_the_base(stacked, capsys):
    git(stacked, "config", "workbench.baseRef", "integration")
    line = es.bump(str(stacked), "eng-demo", "y", date="2030-04-01")
    err = capsys.readouterr().err
    assert line["version"] == "1.5.0" and [l["version"] for l in versions(stacked)] == ["1.2.0", "1.3.0", "1.4.0", "1.5.0"]
    assert "git config workbench.baseRef integration" in err and sha(stacked, "integration")[:12] in err
    assert findings(stacked) == {"file": [], "class": [], "bump": []}
    es.bump(str(stacked), "eng-demo", "y", date="2030-04-02")  # idempotent: the one added line is rewritten
    assert len(versions(stacked)) == 4


def test_a_correct_one_line_bump_on_a_branch_cut_from_main_is_untouched(repo, capsys):  # noqa: F811
    edit(repo, "1. Read the change.", "1. Read the change twice.")
    assert es.bump(str(repo), "eng-demo", "y", date="2030-02-01")["version"] == "1.3.0"
    assert "the merge base with the default branch (main)" in capsys.readouterr().err
    assert len(versions(repo)) == 2


def test_the_resolver_order_is_the_variable_then_the_config_key_then_the_upstream_then_the_default_branch(stacked, monkeypatch):
    root = str(stacked)
    git(stacked, "branch", "side", "integration~1")
    commit, source, error = es.resolve_base(root)  # no variable, no key, no upstream
    assert (commit, error) == (sha(stacked, "main"), None) and source == "the merge base with the default branch (main)"
    git(stacked, "branch", "--set-upstream-to=side", "work")  # the upstream of the branch
    commit, source, _ = es.resolve_base(root)
    assert commit == sha(stacked, "side") and source == "the upstream of work, side"
    git(stacked, "config", "workbench.baseRef", "integration")  # the config key wins over the upstream
    commit, source, _ = es.resolve_base(root)
    assert commit == sha(stacked, "integration") and source == "git config workbench.baseRef integration"
    monkeypatch.setenv("WB_BASE_REF", "main")  # the variable wins over the key
    commit, source, _ = es.resolve_base(root)
    assert commit == sha(stacked, "main") and source == "WB_BASE_REF main"
    assert es.comparison_base(root) == sha(stacked, "main")


def test_an_upstream_that_is_the_branch_itself_is_not_a_base(stacked):
    git(stacked, "config", "branch.work.remote", ".")
    git(stacked, "config", "branch.work.merge", "refs/heads/work")  # what push -u leaves: the branch tracks its own copy
    commit, source, _ = es.resolve_base(str(stacked))
    assert commit == sha(stacked, "main") and "default branch" in source


def test_a_name_that_resolves_to_nothing_is_an_error_never_another_base(stacked, monkeypatch):
    root = str(stacked)
    git(stacked, "config", "workbench.baseRef", "no-such-ref")
    commit, source, error = es.resolve_base(root)
    assert commit is None and source is None and "workbench.baseRef is 'no-such-ref'" in error
    assert es.base_resolution(root)[0] == "error" and es.comparison_base(root) is None
    found, _ = es.evidence_problems(root)
    assert "workbench.baseRef" in found
    monkeypatch.setenv("WB_BASE_REF", "integration")  # the variable is read first and is valid
    assert es.resolve_base(root)[2] is None
    monkeypatch.setenv("WB_BASE_REF", "also-missing")
    assert "WB_BASE_REF is 'also-missing'" in es.resolve_base(root)[2]
    before = snapshot(stacked)
    with pytest.raises(es.BaseMismatch, match="also-missing"):
        es.bump(root, "eng-demo", "y")
    assert snapshot(stacked) == before


def test_the_validator_reads_its_class_checks_against_the_resolver_and_says_which_base(stacked):
    def check():
        report = validate.Report()
        validate.check_versions(report, root=str(stacked))
        return report

    git(stacked, "config", "workbench.baseRef", "integration")
    es.bump(str(stacked), "eng-demo", "y", date="2030-04-01")
    report = check()
    assert not report.errors
    assert any("compared with" in n and "git config workbench.baseRef integration" in n for n in report.notes)
    git(stacked, "config", "--unset", "workbench.baseRef")  # the old fallback: main, so the package branch adds 3 lines
    report = check()
    assert any("lines were added" in e["message"] for e in report.errors)
    assert any("the merge base with the default branch (main)" in n for n in report.notes)
    git(stacked, "config", "workbench.baseRef", "no-such-ref")
    report = check()
    assert not report.errors and any("skipped" in n and "no-such-ref" in n for n in report.notes)
