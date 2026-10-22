"""The refusal of a configuration that is not accepted and its line in the service log (slice S12, runtime/ops_core.py `_accepted`, runtime/service.py `fault_text`).

Held here: the refusal names the exact command to run, with `--widen <hash>` when the file widens what a channel or a sender may do (the hash `config` shows) and without it
when it widens nothing; and the service's log keeps that refusal whole, to the end of the command (it was cut at 300 characters: "... Read the file; when it is what you want, ru"),
while any other long error is still cut and nothing of a line or a secret is logged. Offline: the stand-in tree and the stand-in operations object. Every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_pending_config_command.py
"""
from __future__ import annotations

import json
import re
import threading

import pytest

import standin_tree as st
from test_config_hash import tree  # noqa: F401  (the stand-in tree with a configuration nobody accepted yet)
from test_service import WAIT, world  # noqa: F401  (the stand-in service)

ops = st.load("ops")
ops_core = st.load("ops_core")
service = st.load("service")
project_config = st.load("project_config")


def edit(tree, change):
    path = tree["project"] / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    change(raw)
    path.write_text(json.dumps(raw), encoding="utf-8")


def refusal(call):
    with pytest.raises(ops.OpsError) as raised:
        call()
    assert raised.value.code == 3
    return raised.value


def test_a_file_that_widens_a_channel_is_refused_with_the_command_that_carries_the_widening_hash(tree):
    path = str(tree["project"])
    ops.accept_config(path, project_config.load(path)["sha256"])
    edit(tree, lambda raw: raw.__setitem__("channels", {"messaging": ["read", "calendar-write", "approve-effect-calendar"]}))
    shown = ops.config(path)
    assert shown["accepted"] is False and re.fullmatch(r"[0-9a-f]{64}", shown["widening_sha256"] or "")
    error = refusal(lambda: ops.status(path))
    assert error.next.endswith(f"--sha256 {shown['sha256']} --widen {shown['widening_sha256']}") and "accept-config" in error.next and f"--project {path}" in error.next
    assert error.next in str(error) and str(error).endswith(error.next), "the sentence ends with the whole command"
    out = ops.accept_config(path, shown["sha256"], widen=shown["widening_sha256"])      # the command as it stands is accepted
    assert out["accepted"] == shown["sha256"]


def test_a_file_that_widens_nothing_is_refused_with_the_plain_command(tree):
    path = str(tree["project"])
    ops.accept_config(path, project_config.load(path)["sha256"])
    edit(tree, lambda raw: raw.__setitem__("language", "pt-BR"))
    shown = ops.config(path)
    assert shown["accepted"] is False and not shown["widening"]
    error = refusal(lambda: ops.status(path))
    assert "--widen" not in str(error) and f"--sha256 {shown['sha256']}" in error.next and str(error).endswith(error.next)


def test_vacuity_the_command_of_a_widening_file_without_the_hash_would_not_be_accepted(tree):
    path = str(tree["project"])
    ops.accept_config(path, project_config.load(path)["sha256"])
    edit(tree, lambda raw: raw.__setitem__("channels", {"messaging": ["read", "calendar-write"]}))
    shown = ops.config(path)
    with pytest.raises(ops.OpsError):
        ops.accept_config(path, shown["sha256"])      # the plain command: refused, which is why the refusal must carry --widen
    assert "--widen" in refusal(lambda: ops.status(path)).next


# --- the log -------------------------------------------------------------------------------------------------------------


COMMAND = "python3 /work/openhora/runtime/cli.py accept-config --project /work/northwind-shop --sha256 " + "a" * 64 + " --widen " + "c" * 64
WHOLE = ("the configuration /work/northwind-shop/docs/workbench/runtime.json has the hash " + "a" * 64 + " and the accepted one is " + "b" * 64
         + ". Read the file; when it is what you want, run: " + COMMAND)


def run_loop(world, answer, op="route_queued", rounds=2):
    seen = {"n": 0}
    done = threading.Event()

    def call(project, *args, **kwargs):
        seen["n"] += 1
        if seen["n"] >= rounds:
            done.set()
        raise answer

    world.fake.answers[op] = call
    stop = threading.Event()
    runner = threading.Thread(target=service.dispatch_loop, args=(world.svc, 0.01, stop, op))
    runner.start()
    assert done.wait(WAIT)
    stop.set()
    runner.join(WAIT)
    assert not runner.is_alive()


def test_the_log_keeps_the_not_accepted_refusal_whole_up_to_the_end_of_the_command_and_logs_it_once(world):
    assert len(WHOLE) > 300, "the live message was longer than the cut"
    run_loop(world, ops.OpsError(WHOLE, 3, next=COMMAND))
    mine = [line for line in world.lines if line.startswith(f"route_queued of {world.projects[0]['id']}:")]
    assert mine == [f"route_queued of {world.projects[0]['id']}: OpsError: {WHOLE}"]      # once while it repeats, whole
    assert mine[0].endswith("--widen " + "c" * 64) and "ru" + "n:" in mine[0]


def test_any_other_long_error_is_still_cut_so_that_nothing_of_a_line_or_a_secret_is_logged(world):
    secret = "the line the person typed " + "z" * 600 + "END-OF-TEXT"
    run_loop(world, ops.OpsError(secret, 1))
    run_loop(world, RuntimeError(secret))
    run_loop(world, ops.OpsError(secret + " run: " + COMMAND, 3, next="a different command"))      # the command is not in the message: cut
    texts = [line for line in world.lines if line.startswith(f"route_queued of {world.projects[0]['id']}:")]
    assert len(texts) == 3 and all("END-OF-TEXT" not in line and len(line) < 400 for line in texts), texts


def test_vacuity_a_log_cut_at_300_characters_loses_the_end_of_the_command():
    cut = ("OpsError: " + WHOLE)[:300]
    assert "--widen" not in cut and not cut.endswith(COMMAND), "the oracle sees the plant: a cut line cannot be run"
    assert service.fault_text(ops.OpsError(WHOLE, 3, next=COMMAND)) == WHOLE
