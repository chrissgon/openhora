"""Fixtures every test of evals/ shares."""
import os

import pytest


@pytest.fixture(autouse=True)
def isolated_local_evidence(tmp_path_factory, monkeypatch):
    """A person's own evidence lives outside the checkout (eval_status.local_evidence_base). No test reads or writes the
    real folder of whoever runs the suite: the folder is each test's own, empty unless the test fills it."""
    monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(tmp_path_factory.mktemp("local-evidence-default")))
    # The base of the pull request (WB_BASE_REF) is the caller's, for the validator of the checkout it runs in. A test builds its own
    # checkouts, where that ref names no commit: each test sets it itself when it needs it.
    monkeypatch.delenv("WB_BASE_REF", raising=False)
    # Nor is the base chosen by whoever runs the suite: a workbench.baseRef in their global or system git config is not read.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
