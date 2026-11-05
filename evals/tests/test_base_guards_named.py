"""Offline tests of the second round of guards: the other-ref guard of the bump command runs only for a base the resolver
chose itself (a base named with WB_BASE_REF or a key is not second-guessed), an upstream is the branch's own pushed copy
only when its tip is an entry of the branch's own work in its reflog, the worktree key is read on a detached HEAD, and
lowering the class this change already wrote is refused with its own message. The repository and its helpers are those
of test_versions.py.

Run: uv run --with pytest pytest evals/tests/test_base_guards_named.py
"""
from __future__ import annotations

import pytest

from test_base_guards import integration_line, skill_version  # noqa: F401
from test_base_resolver import sha, snapshot  # noqa: F401
from test_versions import edit, es, git, repo, versions  # noqa: F401  (repo is a fixture)


def add_remote(root, tmp_path_factory):
    remote = tmp_path_factory.mktemp("remote")
    git(remote, "init", "-q", "--bare")
    git(root, "remote", "add", "origin", str(remote))
    git(root, "push", "-q", "origin", "main")
    return remote


def test_a_named_base_lets_a_branch_re_bump_its_own_line_that_another_ref_holds(repo, tmp_path_factory, monkeypatch):
    add_remote(repo, tmp_path_factory)
    edit(repo, "1. Read the change.", "1. Read A.")
    es.bump(str(repo), "eng-demo", "y", date="2030-02-01")
    git(repo, "commit", "-q", "-am", "the change")
    git(repo, "push", "-q", "origin", "change:pkg/x")  # the executor pattern: another name, no -u
    git(repo, "checkout", "-q", "--detach", "change")  # a detached checkout of the change's own head
    edit(repo, "1. Read A.", "1. Read AA.")
    before = snapshot(repo)
    with pytest.raises(es.BaseMismatch) as e:  # the implicit base cannot tell the change's own line from a foreign one
        es.bump(str(repo), "eng-demo", "y", date="2030-02-02")
    assert "if this line is this change's own (pushed or copied elsewhere), name the base with WB_BASE_REF" in str(e.value)
    assert snapshot(repo) == before
    monkeypatch.setenv("WB_BASE_REF", "main")  # named: not second-guessed
    assert es.bump(str(repo), "eng-demo", "y", date="2030-02-02")["version"] == "1.3.0"
    assert [l["version"] for l in versions(repo)] == ["1.2.0", "1.3.0"]
    monkeypatch.delenv("WB_BASE_REF")
    git(repo, "config", "--worktree", "workbench.baseRef", "main")  # a key names it as well, on a detached HEAD
    assert es.resolve_base(str(repo))[1] == "git config --worktree workbench.baseRef main"
    assert es.bump(str(repo), "eng-demo", "y", date="2030-02-03")["version"] == "1.3.0"


def test_the_worktree_key_is_read_on_a_detached_head_but_not_on_the_default_branch(repo, monkeypatch):
    integration_line(repo, monkeypatch, "y")
    git(repo, "checkout", "-q", "--detach", "integration")
    git(repo, "config", "--worktree", "workbench.baseRef", "main")
    commit, source, _ = es.resolve_base(str(repo))
    assert commit == sha(repo, "main") and source == "git config --worktree workbench.baseRef main"
    git(repo, "checkout", "-q", "main")
    assert "default branch" in es.resolve_base(str(repo))[1]


def test_an_integration_branch_merged_or_fast_forwarded_into_the_branch_stays_its_base(repo, tmp_path_factory, monkeypatch):
    add_remote(repo, tmp_path_factory)
    integration_line(repo, monkeypatch, "y")
    git(repo, "push", "-q", "origin", "integration")
    git(repo, "fetch", "-q", "origin")
    git(repo, "checkout", "-q", "-b", "work", "origin/integration")
    # integration moves on: a second line, pushed
    git(repo, "checkout", "-q", "integration")
    edit(repo, "and A.", "and A and B.")
    monkeypatch.setenv("WB_BASE_REF", "HEAD")
    es.bump(str(repo), "eng-demo", "y", date="2030-02-05")
    monkeypatch.delenv("WB_BASE_REF")
    git(repo, "commit", "-q", "-am", "second integration change")
    git(repo, "push", "-q", "origin", "integration")
    git(repo, "checkout", "-q", "work")
    git(repo, "fetch", "-q", "origin")
    git(repo, "merge", "-q", "--ff-only", "origin/integration")  # a pull that fast-forwards: the tip is the upstream's
    commit, source, _ = es.resolve_base(str(repo))
    assert commit == sha(repo, "origin/integration") and source == "the upstream of work, origin/integration"
    # an own commit, then a third upstream line merged in: the merge commit is the branch's, the upstream's tip is not
    (repo / "notes.txt").write_text("own work\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "own work")
    git(repo, "checkout", "-q", "integration")
    edit(repo, "and A and B.", "and A, B and C.")
    monkeypatch.setenv("WB_BASE_REF", "HEAD")
    es.bump(str(repo), "eng-demo", "y", date="2030-02-06")
    monkeypatch.delenv("WB_BASE_REF")
    git(repo, "commit", "-q", "-am", "third integration change")
    git(repo, "push", "-q", "origin", "integration")
    git(repo, "checkout", "-q", "work")
    git(repo, "fetch", "-q", "origin")
    git(repo, "merge", "-q", "-m", "merge integration", "origin/integration")
    commit, source, _ = es.resolve_base(str(repo))
    assert commit == sha(repo, "origin/integration") and source == "the upstream of work, origin/integration"


def test_push_default_upstream_does_not_turn_the_integration_branch_into_the_branchs_own_copy(repo, tmp_path_factory, monkeypatch):
    add_remote(repo, tmp_path_factory)
    integration_line(repo, monkeypatch, "y")
    git(repo, "push", "-q", "origin", "integration")
    git(repo, "fetch", "-q", "origin")
    git(repo, "config", "push.default", "upstream")  # @{push} is then @{upstream} for every branch
    git(repo, "checkout", "-q", "-b", "work", "origin/integration")
    assert git(repo, "rev-parse", "--abbrev-ref", "work@{push}").strip() == "origin/integration"
    commit, source, _ = es.resolve_base(str(repo))
    assert commit == sha(repo, "origin/integration") and source == "the upstream of work, origin/integration"


def test_lowering_the_class_this_change_already_wrote_is_refused_with_the_way_out(repo):
    edit(repo, "1. Read the change.", "1. Read A.")
    assert es.bump(str(repo), "eng-demo", "x", date="2030-02-01")["version"] == "2.0.0"
    before = snapshot(repo)
    with pytest.raises(es.BaseMismatch) as e:
        es.bump(str(repo), "eng-demo", "y", date="2030-02-02")
    assert "the version would fall below the one this change already wrote: restore" in str(e.value)
    assert "from the base to re-classify" in str(e.value)
    assert snapshot(repo) == before and skill_version(repo) == "2.0.0"
    assert es.bump(str(repo), "eng-demo", "x", date="2030-02-03")["version"] == "2.0.0"  # the same class is a rerun
