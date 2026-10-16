"""Offline tests of the guards of the bump command and of the resolver's per-worktree key, each in a small git repository:
a wrong base exactly one line behind (a lower version, or a line another branch already has), a detached HEAD, a stale
upstream, an upstream that is the branch's own pushed copy under another name, and a key that is set for one worktree
and must not be seen from another. The repository and its helpers are those of test_versions.py.

Run: uv run --with pytest pytest evals/tests/test_base_guards.py
"""
from __future__ import annotations

import re

import pytest

from test_base_resolver import sha, snapshot  # noqa: F401
from test_versions import edit, es, git, repo, versions  # noqa: F401  (repo is a fixture)


def skill_version(root):
    text = (root / "skills" / "eng-demo" / "SKILL.md").read_text()
    return re.search(r'version: "([^"]+)"', text).group(1)


def integration_line(root, monkeypatch, cls):
    """`integration` is cut from main and holds one bump of class cls; returns the text its edit wrote."""
    git(root, "checkout", "-q", "-b", "integration", "main")
    edit(root, "1. Read the change.", "1. Read the change and A.")
    monkeypatch.setenv("WB_BASE_REF", "main")
    es.bump(str(root), "eng-demo", cls, date="2030-02-01")
    monkeypatch.delenv("WB_BASE_REF")
    git(root, "commit", "-q", "-am", "integration change")
    return "1. Read the change and A."


def test_a_wrong_base_one_line_behind_is_refused_when_another_branch_has_the_line(repo, monkeypatch):
    last = integration_line(repo, monkeypatch, "x")
    assert [l["version"] for l in versions(repo)] == ["1.2.0", "2.0.0"]
    git(repo, "checkout", "-q", "-b", "work")
    edit(repo, last, last + " Twice.")
    before = snapshot(repo)
    with pytest.raises(es.BaseMismatch) as e:
        es.bump(str(repo), "eng-demo", "z", date="2030-03-01")
    assert "already on refs/heads/integration" in str(e.value) and "probably wrong" in str(e.value)
    assert "WB_BASE_REF" in str(e.value) and "git config --worktree workbench.baseRef" in str(e.value)
    assert snapshot(repo) == before and skill_version(repo) == "2.0.0"


def test_a_wrong_base_one_line_behind_is_refused_by_the_lower_version_when_no_other_branch_has_the_line(repo, monkeypatch):
    last = integration_line(repo, monkeypatch, "x")
    git(repo, "checkout", "-q", "-b", "work")
    git(repo, "branch", "-q", "-D", "integration")  # the line is now only on work: only the version can tell
    edit(repo, last, last + " Twice.")
    before = snapshot(repo)
    with pytest.raises(es.BaseMismatch) as e:
        es.bump(str(repo), "eng-demo", "z", date="2030-03-01")
    assert "gives 1.2.1, lower than the 2.0.0 the skill already has" in str(e.value) and "probably wrong" in str(e.value)
    assert snapshot(repo) == before


def test_a_detached_head_on_the_integration_branch_is_refused(repo, monkeypatch):
    last = integration_line(repo, monkeypatch, "y")
    git(repo, "checkout", "-q", "--detach", "integration")
    edit(repo, last, last + " Twice.")
    before = snapshot(repo)
    with pytest.raises(es.BaseMismatch):
        es.bump(str(repo), "eng-demo", "y", date="2030-03-01")
    assert snapshot(repo) == before


def test_a_stale_upstream_one_line_behind_is_refused(repo, monkeypatch, tmp_path_factory):
    remote = tmp_path_factory.mktemp("remote")
    git(remote, "init", "-q", "--bare")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "origin", "main")
    integration_line(repo, monkeypatch, "y")
    git(repo, "push", "-q", "origin", "integration")
    git(repo, "fetch", "-q", "origin")
    edit(repo, "1. Read the change and A.", "1. Read the change, A and B.")  # a second integration line, not pushed
    monkeypatch.setenv("WB_BASE_REF", "HEAD")
    es.bump(str(repo), "eng-demo", "y", date="2030-02-05")
    monkeypatch.delenv("WB_BASE_REF")
    git(repo, "commit", "-q", "-am", "second integration change")
    git(repo, "checkout", "-q", "-b", "work", "--track", "origin/integration")
    git(repo, "reset", "-q", "--hard", "integration")
    edit(repo, "A and B.", "A, B and C.")
    assert "the upstream of work, origin/integration" == es.resolve_base(str(repo))[1]
    before = snapshot(repo)
    with pytest.raises(es.BaseMismatch):
        es.bump(str(repo), "eng-demo", "y", date="2030-03-01")
    assert snapshot(repo) == before


def test_an_upstream_that_is_the_branchs_own_pushed_copy_under_another_name_is_not_a_base(repo, tmp_path_factory):
    remote = tmp_path_factory.mktemp("remote")
    git(remote, "init", "-q", "--bare")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "origin", "main")
    git(repo, "fetch", "-q", "origin")
    edit(repo, "1. Read the change.", "1. Read A.")
    es.bump(str(repo), "eng-demo", "y", date="2030-02-01")
    git(repo, "commit", "-q", "-am", "the change")
    git(repo, "push", "-q", "-u", "origin", "change:pkg/x")
    commit, source, _ = es.resolve_base(str(repo))
    assert commit == sha(repo, "main") and "default branch" in source
    edit(repo, "1. Read A.", "1. Read AA.")  # a second edit: the bump rewrites the one line, whose copy is on origin/pkg/x
    assert es.bump(str(repo), "eng-demo", "y", date="2030-02-02")["version"] == "1.3.0"
    assert len(versions(repo)) == 2


def test_a_branch_cut_from_the_integration_branch_with_an_upstream_is_read_against_it(repo, monkeypatch, tmp_path_factory):
    remote = tmp_path_factory.mktemp("remote")
    git(remote, "init", "-q", "--bare")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "origin", "main")
    integration_line(repo, monkeypatch, "y")
    git(repo, "push", "-q", "origin", "integration")
    git(repo, "fetch", "-q", "origin")
    git(repo, "checkout", "-q", "-b", "work", "origin/integration")
    edit(repo, "1. Read the change and A.", "1. Read the change, A and B.")
    commit, source, _ = es.resolve_base(str(repo))
    assert commit == sha(repo, "integration") and source == "the upstream of work, origin/integration"
    assert es.bump(str(repo), "eng-demo", "y", date="2030-03-01")["version"] == "1.4.0"


def test_a_key_set_in_one_worktree_is_not_seen_from_another(repo, monkeypatch, tmp_path_factory):
    integration_line(repo, monkeypatch, "y")
    git(repo, "checkout", "-q", "-b", "work")
    git(repo, "config", "extensions.worktreeConfig", "true")
    other = tmp_path_factory.mktemp("worktrees") / "other"
    git(repo, "worktree", "add", "-q", "-b", "other", str(other), "integration")
    git(other, "config", "--worktree", "workbench.baseRef", "integration")
    commit, source, _ = es.resolve_base(str(other))
    assert commit == sha(repo, "integration") and source == "git config --worktree workbench.baseRef integration"
    commit, source, _ = es.resolve_base(str(repo))  # the first worktree has no such key: the clone-wide config is untouched
    assert commit == sha(repo, "main") and "default branch" in source
    # A key written without --worktree lands in the clone-wide config, which every worktree shares: it is not read
    # while the clone has more than one worktree and extensions.worktreeConfig is off.
    git(repo, "config", "extensions.worktreeConfig", "false")
    git(repo, "config", "--local", "workbench.baseRef", "integration")
    assert "default branch" in es.resolve_base(str(repo))[1] and "default branch" in es.resolve_base(str(other))[1]


def test_a_key_is_ignored_on_the_default_branch_and_a_branch_key_is_honoured(repo, monkeypatch):
    integration_line(repo, monkeypatch, "y")
    git(repo, "checkout", "-q", "main")
    git(repo, "config", "--worktree", "workbench.baseRef", "integration")
    commit, source, _ = es.resolve_base(str(repo))
    assert commit == sha(repo, "main") and "default branch" in source
    git(repo, "config", "branch.main.workbenchBaseRef", "integration")
    assert "default branch" in es.resolve_base(str(repo))[1]
    git(repo, "checkout", "-q", "-b", "work", "integration")
    git(repo, "config", "--worktree", "--unset", "workbench.baseRef")
    git(repo, "config", "branch.work.workbenchBaseRef", "main")
    commit, source, _ = es.resolve_base(str(repo))
    assert commit == sha(repo, "main") and source == "git config branch.work.workbenchBaseRef main"


def test_a_class_bump_of_a_skill_with_no_line_in_the_base_says_the_base_may_be_wrong_first(repo):
    other = repo / "skills" / "eng-new"
    (other / "evals").mkdir(parents=True)
    (other / "SKILL.md").write_text((repo / "skills/eng-demo/SKILL.md").read_text().replace("eng-demo", "eng-new"))
    with pytest.raises(ValueError) as e:
        es.bump(str(repo), "eng-new", "y")
    text = str(e.value)
    assert "no version line in the base" in text and text.index("may be wrong") < text.index("is new, write its first line")
    assert "WB_BASE_REF" in text and "--worktree workbench.baseRef" in text
