"""The sweep of orphan containers (package P-OPS, finding I6), against a FAKE container tool: no docker is run, and no real container is
named or touched. The objects are those the harness makes (names and labels as evals/executor.py gives them): the labels `wb.eval` and
`wb.eval.run=<run id>`, the run container, its key proxy and its network, and the shared proxy, networks and key holders that are
never a run's.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_orphans.py
"""
from __future__ import annotations

import json
import sys

import pytest

import standin_tree as st

orphans = st.load("orphans")

NOW = 1_800_000_000.0
OLD = "2027-01-15 07:00:00 +0000 UTC"     # NOW is 2027-01-15 08:00:00 UTC; an hour old
VERY_OLD = "2027-01-14 00:00:00 +0000 UTC"
YOUNG = "2027-01-15 07:59:30 +0000 UTC"   # 30 seconds
RUN_A, RUN_B, RUN_C = "0123456789abcdef", "fedcba9876543210", "00112233aabbccdd"
TAG = "a1b2c3d4e5f6"                      # the 12 hexadecimal characters a harness's shared objects are named after


class FakeDocker:
    """A container client that knows a list of containers and networks, answers `ps -a` and `network ls`, and records every removal."""

    def __init__(self, containers=(), networks=(), fail_listing=False, fail_removal=()):
        self.containers, self.networks = list(containers), list(networks)
        self.calls, self.fail_listing, self.fail_removal = [], fail_listing, set(fail_removal)

    def __call__(self, *args):
        self.calls.append(args)
        if args[0] == "ps":
            return (1, "") if self.fail_listing else (0, "\n".join(json.dumps(c) for c in self.containers))
        if args[:2] == ("network", "ls"):
            return (0, "\n".join(json.dumps(n) for n in self.networks))
        if args[0] == "rm":
            return (1, "") if args[2] in self.fail_removal else (0, "")
        if args[:2] == ("network", "rm"):
            return (1, "") if args[2] in self.fail_removal else (0, "")
        raise AssertionError(f"the sweep ran a command it should not: {args}")

    @property
    def removals(self):
        return [c for c in self.calls if c[0] == "rm" or c[:2] == ("network", "rm")]

    @property
    def mutations(self):
        return [c for c in self.calls if c[0] not in ("ps",) and c[:2] != ("network", "ls")]


def container(name, run=None, created=OLD):
    labels = "wb.eval=1" + (f",wb.eval.run={run}" if run else "")
    return {"ID": "x" * 12, "Names": name, "Labels": labels, "CreatedAt": created}


def network(name, run=None, created=OLD):
    labels = "wb.eval=1" + (f",wb.eval.run={run}" if run else "")
    return {"ID": "y" * 12, "Name": name, "Labels": labels, "CreatedAt": created}


def shared():
    """What a harness keeps for good: its egress proxy, its networks, and key holders named after the definition's tag."""
    return ([container(f"wb-eval-proxy-{TAG}", created=VERY_OLD), container(f"wb-eval-keys-{TAG}", created=VERY_OLD),
             container(f"wb-eval-keys-strong-{TAG}", created=VERY_OLD), container(f"wb-eval-route-openrouter-{TAG}", created=VERY_OLD)],
            [network(f"wb-eval-net-{TAG}", created=VERY_OLD), network(f"wb-eval-route-openrouter-{TAG}", created=VERY_OLD)])


def removed_names(result):
    return sorted(r["name"] for r in result["removed"])


def test_an_orphan_found_by_its_label_is_removed_with_its_network_and_the_container_goes_before_the_network():
    docker = FakeDocker([container(f"wb-eval-run-{RUN_A}", RUN_A), container(f"wb-eval-keys-{RUN_A}", RUN_A)],
                        [network(f"wb-eval-held-{RUN_A}", RUN_A)])
    result = orphans.sweep(docker, now=NOW, busy=False)
    assert removed_names(result) == sorted([f"wb-eval-run-{RUN_A}", f"wb-eval-keys-{RUN_A}", f"wb-eval-held-{RUN_A}"])
    assert all(r["via"] == "label" and r["run"] == RUN_A for r in result["removed"])
    assert docker.removals == [("rm", "-f", f"wb-eval-run-{RUN_A}"), ("rm", "-f", f"wb-eval-keys-{RUN_A}"),
                               ("network", "rm", f"wb-eval-held-{RUN_A}")]


def test_an_orphan_that_predates_the_label_is_found_by_the_name_prefix_alone():
    docker = FakeDocker([container(f"wb-eval-run-{RUN_B}"), container(f"wb-eval-keys-{RUN_B}")], [network(f"wb-eval-held-{RUN_B}")])
    result = orphans.sweep(docker, now=NOW, busy=False)
    assert removed_names(result) == sorted([f"wb-eval-run-{RUN_B}", f"wb-eval-keys-{RUN_B}", f"wb-eval-held-{RUN_B}"])
    assert {r["via"] for r in result["removed"]} == {"name"}


def test_the_shared_proxies_and_key_holders_are_never_removed_whatever_their_labels_and_age():
    containers, networks = shared()
    # even one that carries a run label (a mistake, a later harness) is not a run's when its name is not
    containers.append(container(f"wb-eval-proxy-{TAG}-copy", RUN_A, created=VERY_OLD))
    containers.append(container(f"wb-eval-keys-{TAG}", RUN_A, created=VERY_OLD))
    networks.append(network(f"wb-eval-net-{TAG}", RUN_A, created=VERY_OLD))
    docker = FakeDocker(containers, networks)
    result = orphans.sweep(docker, now=NOW, busy=False)
    assert result["removed"] == [] and docker.mutations == []


def test_the_selection_by_name_needs_exactly_sixteen_hexadecimal_characters():
    for name in (f"wb-eval-keys-{TAG}", "wb-eval-run-", "wb-eval-run-XYZ", f"wb-eval-run-{RUN_A}0", f"wb-eval-run-{RUN_A[:-1]}", "wb-eval-run-0123456789ABCDEF"):
        assert orphans.run_of_name("container", name) is None, name
    assert orphans.run_of_name("container", f"wb-eval-run-{RUN_A}") == RUN_A
    assert orphans.run_of_name("container", f"wb-eval-keys-{RUN_A}") == RUN_A
    assert orphans.run_of_name("network", f"wb-eval-held-{RUN_A}") == RUN_A
    assert orphans.run_of_name("network", f"wb-eval-net-{TAG}") is None
    for name in (f"wb-eval-proxy-{TAG}", f"wb-eval-net-{TAG}", f"wb-eval-route-openrouter-{TAG}", f"wb-eval-keys-{TAG}"):
        assert orphans.is_shared(name)
    assert not orphans.is_shared(f"wb-eval-keys-{RUN_A}") and not orphans.is_shared(f"wb-eval-run-{RUN_A}")


def test_a_container_that_is_not_the_harnesss_is_never_selected():
    other = [container("web-server-1"), container("postgres", created=VERY_OLD),
             {"ID": "z" * 12, "Names": "my-app", "Labels": "wb.eval.run=not-a-run-id", "CreatedAt": VERY_OLD}]
    docker = FakeDocker(other, [network("bridge"), network("my-app_default", created=VERY_OLD)])
    assert orphans.sweep(docker, now=NOW, busy=False)["removed"] == [] and docker.mutations == []


def test_a_live_run_is_kept_while_the_machine_is_busy_and_only_what_is_older_than_the_long_grace_goes():
    docker = FakeDocker([container(f"wb-eval-run-{RUN_A}", RUN_A, created=OLD),            # an hour: a run in progress may be this old
                         container(f"wb-eval-keys-{RUN_A}", RUN_A, created=OLD),
                         container(f"wb-eval-keys-{RUN_B}", RUN_B, created=VERY_OLD)],       # a day: no run lasts so long
                        [network(f"wb-eval-held-{RUN_A}", RUN_A, created=OLD), network(f"wb-eval-held-{RUN_B}", RUN_B, created=VERY_OLD)])
    result = orphans.sweep(docker, now=NOW, busy=True)
    assert removed_names(result) == sorted([f"wb-eval-keys-{RUN_B}", f"wb-eval-held-{RUN_B}"])
    assert sorted(k["name"] for k in result["kept"]) == sorted([f"wb-eval-run-{RUN_A}", f"wb-eval-keys-{RUN_A}", f"wb-eval-held-{RUN_A}"])
    assert result["busy"] is True and result["grace_seconds"] == orphans.BUSY_GRACE_SECONDS


def test_a_run_being_started_is_kept_even_when_nothing_else_runs():
    docker = FakeDocker([container(f"wb-eval-run-{RUN_C}", RUN_C, created=YOUNG)], [network(f"wb-eval-held-{RUN_C}", RUN_C, created=YOUNG)])
    result = orphans.sweep(docker, now=NOW, busy=False)
    assert result["removed"] == [] and len(result["kept"]) == 2 and docker.mutations == []


def test_an_object_whose_age_cannot_be_read_is_kept():
    bad = container(f"wb-eval-run-{RUN_A}", RUN_A, created="yesterday-ish")
    docker = FakeDocker([bad])
    result = orphans.sweep(docker, now=NOW, busy=False)
    assert result["removed"] == [] and result["kept"][0]["why"] == "its age cannot be read"


def test_a_tool_that_cannot_list_does_nothing_and_says_so_and_a_failed_removal_is_kept_not_raised():
    docker = FakeDocker([container(f"wb-eval-run-{RUN_A}", RUN_A)], fail_listing=True)
    result = orphans.sweep(docker, now=NOW, busy=False)
    assert result["removed"] == [] and "could not list the containers" in result["problem"] and docker.removals == []
    docker = FakeDocker([container(f"wb-eval-run-{RUN_A}", RUN_A), container(f"wb-eval-keys-{RUN_A}", RUN_A)],
                        fail_removal={f"wb-eval-run-{RUN_A}"})
    result = orphans.sweep(docker, now=NOW, busy=False)
    assert removed_names(result) == [f"wb-eval-keys-{RUN_A}"] and result["kept"][0]["why"] == "the tool could not remove it"


def test_a_dry_run_lists_and_removes_nothing():
    docker = FakeDocker([container(f"wb-eval-run-{RUN_A}", RUN_A)])
    result = orphans.sweep(docker, now=NOW, busy=False, dry_run=True)
    assert result["removed"][0]["dry_run"] is True and docker.mutations == []


def test_the_creation_time_is_read_from_docker_s_two_forms():
    assert orphans.parse_created("2027-01-15 08:00:00 +0000 UTC") == NOW
    assert orphans.parse_created("2027-01-15T08:00:00.123456789Z") == NOW
    assert orphans.parse_created("2027-01-15 10:00:00 +0200 CEST") == NOW
    assert orphans.parse_created("") is None and orphans.parse_created(None) is None and orphans.parse_created("soon") is None


def test_the_sweep_never_runs_a_command_other_than_listing_and_removing():
    docker = FakeDocker([container(f"wb-eval-run-{RUN_A}", RUN_A)], [network(f"wb-eval-held-{RUN_A}", RUN_A)])
    orphans.sweep(docker, now=NOW, busy=False)
    assert {c[0] for c in docker.calls} <= {"ps", "network", "rm"}
    assert not any(c[0] in ("stop", "kill", "exec", "run", "inspect", "system", "prune") for c in docker.calls)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
