"""Tests for the shared lock's places in evals/execution.py: a call that takes a web place, an account place and a
place of the total, in that order, never leaves two calls waiting for each other.

Run: uv run --with pytest pytest evals/tests/test_account_slots.py
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "execution.py"
spec = importlib.util.spec_from_file_location("execution_under_test", SCRIPT)
ex = importlib.util.module_from_spec(spec)
sys.modules["execution_under_test"] = ex
spec.loader.exec_module(ex)


@pytest.fixture(autouse=True)
def own_lock_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.setattr(ex, "SLOT_POLL", 0.01)


def test_many_threads_over_web_account_and_total_places_all_finish_within_every_limit():
    control = {"total_jobs": 3, "web_jobs_default": 1, "account_jobs": {"a": 2, "b": 1}}
    guard = threading.Lock()
    now = {"total": 0, "a": 0, "b": 0}
    most = {"total": 0, "a": 0, "b": 0}
    web_now, web_most = {}, {}
    errors = []

    def work(i):
        model, account, web = f"model-{i % 3}", ("a" if i % 3 else "b"), i % 2 == 0
        try:
            with ex.Slots(control, model, web=web, account=account):
                with guard:
                    for key in ("total", account):
                        now[key] += 1
                        most[key] = max(most[key], now[key])
                    if web:
                        web_now[model] = web_now.get(model, 0) + 1
                        web_most[model] = max(web_most.get(model, 0), web_now[model])
                time.sleep(0.005)
                with guard:
                    for key in ("total", account):
                        now[key] -= 1
                    if web:
                        web_now[model] -= 1
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(24)]
    for t in threads:
        t.start()
    deadline = time.time() + 20
    for t in threads:
        t.join(max(0.0, deadline - time.time()))
    assert not any(t.is_alive() for t in threads) and errors == []
    assert most["a"] <= 2 and most["b"] <= 1 and most["total"] <= 3
    assert all(n <= 1 for n in web_most.values())


def test_two_processes_on_one_lock_folder_with_mixed_accounts_both_finish(tmp_path):
    driver = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('execution_driver', {str(SCRIPT)!r})\n"
        "ex = importlib.util.module_from_spec(spec); sys.modules['execution_driver'] = ex; spec.loader.exec_module(ex)\n"
        f"ex.LOCK_DIR = {str(tmp_path / 'locks')!r}\n"
        "ex.SLOT_POLL = 0.01\n"
        "control = {'total_jobs': 2, 'web_jobs_default': 1, 'account_jobs': {'a': 1, 'b': 1}}\n"
        "for i in range(20):\n"
        "    with ex.Slots(control, 'm', web=i % 2 == 0, account='ab'[i % 2]):\n"
        "        pass\n")
    procs = [subprocess.Popen([sys.executable, "-c", driver]) for _ in range(2)]
    assert [p.wait(timeout=60) for p in procs] == [0, 0]
