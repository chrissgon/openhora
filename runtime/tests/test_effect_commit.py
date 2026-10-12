"""Tests of the effect kind `push` (runtime/effect_commit.py, CONS-3): the commit of files to a branch that a handler
hands to ops.execute_under_policy under a standing approval. The module answers five questions about a document and
has no gate-path function, since no skill's confirmation gate names this word. Offline; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_effect_commit.py
"""
from __future__ import annotations

import standin_tree as st

effects = st.load("effects")
effect_commit = st.load("effect_commit")

DOC = {"policy": "published-posts", "kind": "push", "target": "example-owner/example-profile@main",
       "files": ["data/posts.json", "assets/posts/one.png"], "items": 2, "idempotency_key": "published-posts-2026-W42",
       "payload_sha256": "ab" * 32,
       "args": ["--repo", "example-owner/example-profile", "--branch", "main", "--message-file", "/work/message.txt",
                "--file", "data/posts.json=/work/target.json"]}


def test_the_kind_runs_under_a_policy_with_the_code_provider_and_no_platform():
    assert effect_commit.POLICY is True
    assert effect_commit.PROVIDER_CLASS == "integration:vcs"
    assert effect_commit.policy_platform(DOC) is None


def test_the_effect_the_approval_is_checked_against_is_the_four_fields_of_the_document():
    assert effect_commit.policy_effect(DOC) == {"kind": "push", "target": "example-owner/example-profile@main",
                                                 "files": ["data/posts.json", "assets/posts/one.png"], "items": 2}


def test_the_argv_is_the_verb_and_the_documents_args_and_nothing_else():
    argv = effect_commit.policy_argv(DOC)
    assert argv == ["commit-files", *DOC["args"]]
    argv.append("--changed")
    assert DOC["args"][-1] == "data/posts.json=/work/target.json"  # a copy: the document is not changed through it


def test_the_one_line_says_how_many_files_go_to_which_target():
    assert effect_commit.describe(DOC) == "commit 2 files to example-owner/example-profile@main"


def test_the_registry_loads_the_module_for_the_word_push_and_its_describe_serves_the_state_file_row():
    kind = effects.module_for("push")
    assert kind is effect_commit
    row = effects.approval_row({"scope": "standing", "payload_sha256": "cd" * 32, "approved_at": "2026-10-09T10:00:00Z",
                                "expires_at": None, "status": "executed"}, {**DOC, "effect": "push"})
    assert row[1] == "commit 2 files to example-owner/example-profile@main" and row[2] == "sha256:" + "cd" * 32


def test_the_module_has_no_gate_path_function_since_no_skill_gate_names_this_word():
    for name in ("parse", "verify", "execute", "document", "body", "prepare", "head", "refusal", "mismatch", "title",
                 "summary", "unconfigured"):
        assert not hasattr(effect_commit, name), name
