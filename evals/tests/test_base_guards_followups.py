"""Offline tests of two corners of the own-copy rule of the base resolver (follow-ups of package BUMP-GUARD): a rebase
onto the moved integration branch before the branch has a commit of its own leaves the upstream's tip as the branch's
tip, which is not the branch's own work; and a branch that pushed to another name, merged the integration branch
forward and pushed again keeps its pushed copy as its own, because that copy's tip is one the branch pushed itself. The
repository and its helpers are those of test_versions.py.

Run: uv run --with pytest pytest evals/tests/test_base_guards_followups.py
"""
from __future__ import annotations

from test_base_guards import integration_line  # noqa: F401
from test_base_guards_named import add_remote
from test_base_resolver import sha  # noqa: F401
from test_versions import edit, es, git, repo, versions  # noqa: F401  (repo is a fixture)


def move_integration(root, monkeypatch):
    """integration gets a second bump, pushed; origin/integration is fetched."""
    git(root, "checkout", "-q", "integration")
    edit(root, "and A.", "and A and B.")
    monkeypatch.setenv("WB_BASE_REF", "HEAD")
    es.bump(str(root), "eng-demo", "y", date="2030-02-05")
    monkeypatch.delenv("WB_BASE_REF")
    git(root, "commit", "-q", "-am", "second integration change")
    git(root, "push", "-q", "origin", "integration")
    git(root, "fetch", "-q", "origin")


def test_a_rebase_onto_the_moved_integration_branch_before_an_own_commit_leaves_it_the_base(repo, tmp_path_factory, monkeypatch):
    add_remote(repo, tmp_path_factory)
    integration_line(repo, monkeypatch, "y")
    git(repo, "push", "-q", "origin", "integration")
    git(repo, "fetch", "-q", "origin")
    git(repo, "checkout", "-q", "-b", "work", "origin/integration")
    move_integration(repo, monkeypatch)
    git(repo, "checkout", "-q", "work")
    git(repo, "rebase", "-q", "origin/integration")
    assert sha(repo, "work") == sha(repo, "origin/integration")
    reflog = git(repo, "reflog", "show", "--format=%H %gs", "refs/heads/work")
    assert "rebase" in reflog.splitlines()[0]  # the entry that used to pass for the branch's own work
    commit, source, _ = es.resolve_base(str(repo))
    assert commit == sha(repo, "origin/integration") and source == "the upstream of work, origin/integration"
    edit(repo, "and A and B.", "and A, B and C.")
    assert es.bump(str(repo), "eng-demo", "y", date="2030-03-01")["version"] == "1.5.0"
    assert [l["version"] for l in versions(repo)][-3:] == ["1.3.0", "1.4.0", "1.5.0"]


def test_a_rebase_with_an_own_commit_still_makes_the_pushed_copy_its_own(repo, tmp_path_factory, monkeypatch):
    add_remote(repo, tmp_path_factory)
    integration_line(repo, monkeypatch, "y")
    git(repo, "push", "-q", "origin", "integration")
    git(repo, "fetch", "-q", "origin")
    git(repo, "checkout", "-q", "-b", "work", "origin/integration")
    (repo / "notes.txt").write_text("own work\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "own work")
    move_integration(repo, monkeypatch)
    git(repo, "checkout", "-q", "work")
    git(repo, "rebase", "-q", "origin/integration")
    git(repo, "push", "-q", "-u", "origin", "work:pkg/x")
    assert es._is_own_copy(str(repo), "work", "origin/pkg/x")
    assert not es._is_own_copy(str(repo), "work", "origin/integration")


def test_a_pushed_copy_stays_the_branchs_own_after_the_integration_branch_is_merged_forward_and_pushed(repo, tmp_path_factory, monkeypatch):
    add_remote(repo, tmp_path_factory)
    git(repo, "fetch", "-q", "origin")
    edit(repo, "1. Read the change.", "1. Read A.")
    es.bump(str(repo), "eng-demo", "y", date="2030-02-01")
    git(repo, "commit", "-q", "-am", "the change")
    git(repo, "push", "-q", "-u", "origin", "change:pkg/x")
    # main moves on with a file the change does not touch; the branch merges it forward and pushes again
    git(repo, "checkout", "-q", "main")
    (repo / "other.txt").write_text("main moves\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "main moves")
    git(repo, "push", "-q", "origin", "main")
    git(repo, "checkout", "-q", "change")
    git(repo, "merge", "-q", "-m", "merge main", "main")
    git(repo, "push", "-q", "origin", "change:pkg/x")
    assert git(repo, "reflog", "show", "--format=%gs", "refs/heads/change").splitlines()[0].startswith("merge")
    assert sha(repo, "change") == sha(repo, "origin/pkg/x")
    assert es._is_own_copy(str(repo), "change", "origin/pkg/x")
    commit, source, _ = es.resolve_base(str(repo))
    assert commit == sha(repo, "main") and "default branch" in source
    edit(repo, "1. Read A.", "1. Read AA.")
    assert es.bump(str(repo), "eng-demo", "y", date="2030-02-02")["version"] == "1.3.0"
    assert len(versions(repo)) == 2
