"""Fixtures every test of evals/ shares."""
import pytest


@pytest.fixture(autouse=True)
def isolated_local_evidence(tmp_path_factory, monkeypatch):
    """A person's own evidence lives outside the checkout (eval_status.local_evidence_base). No test reads or writes the
    real folder of whoever runs the suite: the folder is each test's own, empty unless the test fills it."""
    monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(tmp_path_factory.mktemp("local-evidence-default")))
