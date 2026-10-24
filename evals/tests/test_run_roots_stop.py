"""The stop path of the execution kit (evals/execution.py): return_all_runs, which both stop handlers call right before
os._exit (evals/eval_run.py main.on_signal, runtime/lab.py session.on_signal), never returns while a run folder is still
being moved, and never hangs when the handler runs on top of its own thread's move. Offline, no adapter, no model:
shutil.move is replaced by one that pauses at a chosen point, so each interleaving is forced, not hoped for."""
from __future__ import annotations

import importlib.util
import os
import shutil
import threading
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "execution.py"
WAIT = 10  # every wait of this file has this deadline; a pass takes well under a second


@pytest.fixture
def kit():
    """A fresh copy of the kit for each test: its own RUN_ROOTS and its own lock, so a test that leaves the lock held
    (the unfixed code hangs a thread on it) cannot hang the next test."""
    spec = importlib.util.spec_from_file_location("workbench_eval_execution_stop_probe", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def planted_root(kit, tmp_path, monkeypatch, name):
    """A registered run root with case/, out/ and prompt.md, made as new_run_root makes it, under tmp_path."""
    monkeypatch.setattr(kit, "temp_base", lambda names=(): str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir(exist_ok=True)
    dest = tmp_path / "workspace" / name
    root = kit.new_run_root(str(dest))
    Path(root, "case", "made-by-the-run.md").write_text("x\n")
    Path(root, "out", "response.md").write_text("r\n")
    Path(root, "prompt.md").write_text("p")
    return root, dest


def returned(root, dest):
    return ((dest / "cwd" / "made-by-the-run.md").is_file() and (dest / "outputs" / "response.md").is_file()
            and (dest / "prompt.md").is_file() and not os.path.exists(root))


def test_a_stop_waits_for_a_move_another_thread_has_begun(kit, tmp_path, monkeypatch):
    """The CI failures of 2026-10-15 (the case file missing) and 2026-10-18 (the temporary folder left): a worker whose
    run was just stopped is inside return_run, has popped its root and is moving it; the handler's return_all_runs
    must not return (and so must not let os._exit cut the move) until that move has ended."""
    root, dest = planted_root(kit, tmp_path, monkeypatch, "worker")
    inside, go = threading.Event(), threading.Event()
    real_move = shutil.move

    def paused_move(src, target, *a, **k):
        if os.path.basename(src) == "out":  # case/ is already moved, out/ and prompt.md are not
            inside.set()
            assert go.wait(WAIT)
        return real_move(src, target, *a, **k)
    monkeypatch.setattr(kit.shutil, "move", paused_move)

    worker = threading.Thread(target=kit.return_run, args=(root,), daemon=True)
    worker.start()
    assert inside.wait(WAIT)
    assert root not in kit.RUN_ROOTS  # popped: the snapshot of the unfixed return_all_runs does not see it
    handler = threading.Thread(target=kit.return_all_runs, daemon=True)
    handler.start()
    handler.join(0.5)
    still_waiting = handler.is_alive()
    go.set()
    worker.join(WAIT)
    handler.join(WAIT)
    assert still_waiting, "return_all_runs returned while another thread was still moving a run folder"
    assert not worker.is_alive() and not handler.is_alive() and returned(root, dest)


def test_a_stop_on_top_of_its_own_threads_move_does_not_hang_and_returns_the_other_runs(kit, tmp_path, monkeypatch):
    """A signal handler runs in the main thread, between two bytecodes of whatever that thread was doing: here, the
    move of its own run folder (main()'s final cleanup, or a single-threaded runtime run). The handler then calls
    return_all_runs in the same thread that holds the folders' lock. It must neither wait for itself (a deadlock: the
    process would hang until it is killed) nor skip the other folders."""
    mine, mine_dest = planted_root(kit, tmp_path, monkeypatch, "mine")
    other, other_dest = planted_root(kit, tmp_path, monkeypatch, "other")
    calls = []
    real_move = shutil.move

    def move_with_a_signal(src, target, *a, **k):
        if os.path.basename(src) == "out" and not calls:  # the "signal" lands during the move of mine's out/
            calls.append("handler")
            kit.return_all_runs()
        return real_move(src, target, *a, **k)
    monkeypatch.setattr(kit.shutil, "move", move_with_a_signal)

    t = threading.Thread(target=kit.return_run, args=(mine,), daemon=True)
    t.start()
    t.join(WAIT)
    assert not t.is_alive(), "return_all_runs hung on top of its own thread's move"
    assert calls == ["handler"] and returned(other, other_dest) and returned(mine, mine_dest)
    assert kit.RUN_ROOTS == {}


def test_a_stop_with_no_move_in_progress_returns_every_registered_run(kit, tmp_path, monkeypatch):
    """The vacuity check of the two above: with nothing in progress, every registered folder goes back and is removed."""
    pairs = [planted_root(kit, tmp_path, monkeypatch, f"r{i}") for i in range(3)]
    kit.return_all_runs()
    assert all(returned(root, dest) for root, dest in pairs) and kit.RUN_ROOTS == {}
