"""The sweep of orphan containers and the model server of a local model (backlog N14): `wb-eval-model-<run id>` is removed like a
key proxy (when its run container is gone, past the grace, before its network) and nothing that only looks like it is selected.
A FAKE container tool: no docker is run.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_orphans_model_server.py
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import standin_tree as st

orphans = st.load("orphans")
_spec = importlib.util.spec_from_file_location("orphans_tests_for_model_server", Path(__file__).with_name("test_orphans.py"))
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

FakeDocker, container, network, shared, removed_names = base.FakeDocker, base.container, base.network, base.shared, base.removed_names
NOW, VERY_OLD, YOUNG, TAG = base.NOW, base.VERY_OLD, base.YOUNG, base.TAG
RUN_A, RUN_B, RUN_C = base.RUN_A, base.RUN_B, base.RUN_C


def test_a_model_server_whose_run_container_is_gone_is_removed_past_the_grace_like_a_key_proxy_and_before_its_network():
    docker = FakeDocker([container(f"wb-eval-model-{RUN_A}", RUN_A)], [network(f"wb-eval-held-{RUN_A}", RUN_A)])
    result = orphans.sweep(docker, now=NOW)
    assert removed_names(result) == sorted([f"wb-eval-model-{RUN_A}", f"wb-eval-held-{RUN_A}"])
    assert docker.removals == [("rm", "-f", f"wb-eval-model-{RUN_A}"), ("network", "rm", f"wb-eval-held-{RUN_A}")]
    assert orphans.run_of_name("container", f"wb-eval-model-{RUN_A}") == RUN_A and orphans.run_of_name("container", "wb-eval-model-short") is None


def test_a_model_server_of_a_live_run_or_a_young_one_stays_and_so_does_its_network():
    docker = FakeDocker([container(f"wb-eval-run-{RUN_B}", RUN_B), container(f"wb-eval-model-{RUN_B}", RUN_B),
                         container(f"wb-eval-model-{RUN_C}", RUN_C, created=YOUNG)],
                        [network(f"wb-eval-held-{RUN_B}", RUN_B), network(f"wb-eval-held-{RUN_C}", RUN_C, created=YOUNG)])
    result = orphans.sweep(docker, now=NOW)
    assert result["removed"] == [] and docker.mutations == []
    why = {k["name"]: k["why"] for k in result["kept"]}
    assert why[f"wb-eval-model-{RUN_B}"] == "its run's container still exists" and why[f"wb-eval-model-{RUN_C}"].startswith("younger than")


def test_a_name_that_only_looks_like_a_model_server_and_the_shared_names_are_never_selected():
    containers, networks = shared()
    extra = [container(f"wb-eval-model-{TAG}", created=VERY_OLD), container("wb-eval-model-", created=VERY_OLD),
             container(f"wb-eval-model-{RUN_A}x", created=VERY_OLD), container(f"wb-eval-proxy-{RUN_A}", RUN_A, created=VERY_OLD)]
    docker = FakeDocker(containers + extra, networks)
    result = orphans.sweep(docker, now=NOW)
    assert result["removed"] == [] and docker.mutations == []
    assert orphans.is_shared(f"wb-eval-proxy-{RUN_A}") and not orphans.is_shared(f"wb-eval-model-{RUN_A}")
