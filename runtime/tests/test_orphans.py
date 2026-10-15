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
upkeep = st.load("upkeep")

NOW = 1_800_000_000.0                     # 2027-01-15 08:00:00 UTC
OLD = "2027-01-15 07:00:00 +0000 UTC"     # an hour old
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
        if args[0] == "rm" or args[:2] == ("network", "rm"):
            return (1, "") if args[-1] in self.fail_removal else (0, "")
        raise AssertionError(f"the sweep ran a command it should not: {args}")

    @property
    def removals(self):
        return [c for c in self.calls if c[0] == "rm" or c[:2] == ("network", "rm")]

    @property
    def mutations(self):
        return [c for c in self.calls if c[0] not in ("ps",) and c[:2] != ("network", "ls")]


def container(name, run=None, created=OLD, state="running"):
    labels = "wb.eval=1" + (f",wb.eval.run={run}" if run else "")
    return {"ID": "x" * 12, "Names": name, "Labels": labels, "CreatedAt": created, "State": state}


def network(name, run=None, created=OLD):
    labels = "wb.eval=1" + (f",wb.eval.run={run}" if run else "")
    return {"ID": "y" * 12, "Name": name, "Labels": labels, "CreatedAt": created}


def shared():
    """What a harness keeps for good: its egress proxy, its networks, and key holders named after the definition's tag."""
    return ([container(f"wb-eval-proxy-{TAG}", created=VERY_OLD), container(f"wb-eval-keys-{TAG}", created=VERY_OLD),
             container(f"wb-eval-keys-strong-{TAG}", created=VERY_OLD), container(f"wb-eval-route-openrouter-{TAG}", created=VERY_OLD)],
            [network(f"wb-eval-net-{TAG}", created=VERY_OLD), network(f"wb-eval-route-openrouter-{TAG}", created=VERY_OLD),
             network(f"wb-eval-open-{TAG}", created=VERY_OLD), network(f"wb-eval-strong-held-{TAG}", created=VERY_OLD)])


def removed_names(result):
    return sorted(r["name"] for r in result["removed"])


def test_a_key_proxy_and_network_whose_run_container_is_gone_are_removed_by_label_and_the_container_goes_before_the_network():
    docker = FakeDocker([container(f"wb-eval-keys-{RUN_A}", RUN_A)], [network(f"wb-eval-held-{RUN_A}", RUN_A)])
    result = orphans.sweep(docker, now=NOW)
    assert removed_names(result) == sorted([f"wb-eval-keys-{RUN_A}", f"wb-eval-held-{RUN_A}"])
    assert all(r["via"] == "label" and r["run"] == RUN_A for r in result["removed"])
    assert docker.removals == [("rm", "-f", f"wb-eval-keys-{RUN_A}"), ("network", "rm", f"wb-eval-held-{RUN_A}")]


def test_an_orphan_that_predates_the_label_is_found_by_the_name_prefix_alone():
    docker = FakeDocker([container(f"wb-eval-run-{RUN_B}", state="exited"), container(f"wb-eval-keys-{RUN_B}")], [network(f"wb-eval-held-{RUN_B}")])
    result = orphans.sweep(docker, now=NOW)
    assert removed_names(result) == sorted([f"wb-eval-run-{RUN_B}", f"wb-eval-keys-{RUN_B}", f"wb-eval-held-{RUN_B}"])
    assert {r["via"] for r in result["removed"]} == {"name"}


def test_a_running_run_container_is_never_removed_by_a_pass_whatever_its_age_and_what_belongs_to_it_stays_with_it():
    docker = FakeDocker([container(f"wb-eval-run-{RUN_A}", RUN_A, created=VERY_OLD, state="running"),
                         container(f"wb-eval-keys-{RUN_A}", RUN_A, created=VERY_OLD)],
                        [network(f"wb-eval-held-{RUN_A}", RUN_A, created=VERY_OLD)])
    result = orphans.sweep(docker, now=NOW)
    assert result["removed"] == [] and docker.mutations == []
    assert any("it is running" in k["why"] for k in result["kept"])
    assert {k["why"] for k in result["kept"] if k["name"] != f"wb-eval-run-{RUN_A}"} == {"its run's container still exists",
                                                                                          "a container of its run still exists"}


def test_a_run_container_in_a_state_that_is_not_known_to_have_ended_is_kept():
    for state in ("created", "restarting", "paused", None):
        docker = FakeDocker([{**container(f"wb-eval-run-{RUN_A}", RUN_A, created=VERY_OLD), **({"State": state} if state else {})}])
        if state is None:
            del docker.containers[0]["State"]
        assert orphans.sweep(docker, now=NOW)["removed"] == [], state


def test_only_the_explicit_mode_removes_a_running_container_and_only_a_stuck_one():
    docker = FakeDocker([container(f"wb-eval-run-{RUN_A}", RUN_A, created=VERY_OLD, state="running"),      # a day: stuck
                         container(f"wb-eval-run-{RUN_B}", RUN_B, created=OLD, state="running"),          # an hour: may be a long run
                         container(f"wb-eval-keys-{RUN_A}", RUN_A, created=VERY_OLD)],
                        [network(f"wb-eval-held-{RUN_A}", RUN_A, created=VERY_OLD)])
    assert orphans.sweep(docker, now=NOW)["removed"] == []
    result = orphans.sweep(docker, now=NOW, include_running=True)
    assert removed_names(result) == sorted([f"wb-eval-run-{RUN_A}", f"wb-eval-keys-{RUN_A}", f"wb-eval-held-{RUN_A}"])
    assert f"wb-eval-run-{RUN_B}" in [k["name"] for k in result["kept"]]
    assert docker.removals[0] == ("rm", "-f", f"wb-eval-run-{RUN_A}")


def test_the_shared_proxies_and_key_holders_are_never_removed_whatever_their_labels_and_age():
    containers, networks = shared()
    # even one that carries a run label (a mistake, a later harness) is not a run's when its name is not
    containers += [container(f"wb-eval-proxy-{TAG}-copy", RUN_A, created=VERY_OLD), container(f"wb-eval-keys-{TAG}", RUN_A, created=VERY_OLD),
                   container(f"wb-eval-keys-strong-{TAG}", RUN_A, created=VERY_OLD, state="exited"),
                   container(f"wb-eval-keys-net-{TAG}", RUN_A, created=VERY_OLD), container("wb-eval-strong-held-x", RUN_A, created=VERY_OLD)]
    networks += [network(f"wb-eval-net-{TAG}", RUN_A, created=VERY_OLD), network(f"wb-eval-open-{TAG}", RUN_A, created=VERY_OLD)]
    for include_running in (False, True):
        docker = FakeDocker(containers, networks)
        result = orphans.sweep(docker, now=NOW, include_running=include_running)
        assert result["removed"] == [] and docker.mutations == []


def test_a_label_alone_selects_nothing_a_run_name_is_needed_too():
    odd = [container("my-app", RUN_A, created=VERY_OLD, state="exited"), container(f"other-wb-eval-run-{RUN_A}", RUN_A, created=VERY_OLD, state="exited"),
           container(f"wb-eval-keys-strong-{TAG}", RUN_A, created=VERY_OLD, state="exited")]
    docker = FakeDocker(odd, [network("my-net", RUN_A, created=VERY_OLD)])
    assert orphans.sweep(docker, now=NOW)["removed"] == [] and docker.mutations == []


def test_the_selection_by_name_needs_exactly_sixteen_hexadecimal_characters():
    for name in (f"wb-eval-keys-{TAG}", "wb-eval-run-", "wb-eval-run-XYZ", f"wb-eval-run-{RUN_A}0", f"wb-eval-run-{RUN_A[:-1]}", "wb-eval-run-0123456789ABCDEF"):
        assert orphans.run_of_name("container", name) is None, name
    assert orphans.run_of_name("container", f"wb-eval-run-{RUN_A}") == RUN_A
    assert orphans.run_of_name("container", f"wb-eval-keys-{RUN_A}") == RUN_A
    assert orphans.run_of_name("network", f"wb-eval-held-{RUN_A}") == RUN_A
    assert orphans.run_of_name("network", f"wb-eval-net-{TAG}") is None
    for name in (f"wb-eval-proxy-{TAG}", f"wb-eval-net-{TAG}", f"wb-eval-route-openrouter-{TAG}", f"wb-eval-keys-{TAG}", f"wb-eval-keys-strong-{TAG}",
                 f"wb-eval-keys-net-{TAG}", f"wb-eval-open-{TAG}", f"wb-eval-strong-held-{TAG}"):
        assert orphans.is_shared(name), name
    assert not orphans.is_shared(f"wb-eval-keys-{RUN_A}") and not orphans.is_shared(f"wb-eval-run-{RUN_A}")


def test_a_key_proxy_or_network_being_started_is_kept_until_the_grace_has_passed():
    docker = FakeDocker([container(f"wb-eval-keys-{RUN_C}", RUN_C, created=YOUNG)], [network(f"wb-eval-held-{RUN_C}", RUN_C, created=YOUNG)])
    result = orphans.sweep(docker, now=NOW)
    assert result["removed"] == [] and len(result["kept"]) == 2 and docker.mutations == []
    assert orphans.GRACE_SECONDS == 1800 and orphans.RUNNING_GRACE_SECONDS == 6 * 3600


def test_an_object_whose_age_cannot_be_read_is_kept():
    docker = FakeDocker([container(f"wb-eval-keys-{RUN_A}", RUN_A, created="yesterday-ish")])
    result = orphans.sweep(docker, now=NOW)
    assert result["removed"] == [] and result["kept"][0]["why"] == "its age cannot be read"


def test_a_tool_that_cannot_list_does_nothing_and_says_so_and_a_failed_removal_is_kept_not_raised():
    docker = FakeDocker([container(f"wb-eval-keys-{RUN_A}", RUN_A)], fail_listing=True)
    result = orphans.sweep(docker, now=NOW)
    assert result["removed"] == [] and "could not list the containers" in result["problem"] and docker.removals == []
    docker = FakeDocker([container(f"wb-eval-keys-{RUN_A}", RUN_A), container(f"wb-eval-keys-{RUN_B}", RUN_B)], fail_removal={f"wb-eval-keys-{RUN_A}"})
    result = orphans.sweep(docker, now=NOW)
    assert removed_names(result) == [f"wb-eval-keys-{RUN_B}"] and result["kept"][0]["why"] == "the tool could not remove it"


def test_a_dry_run_lists_and_removes_nothing():
    docker = FakeDocker([container(f"wb-eval-keys-{RUN_A}", RUN_A)])
    result = orphans.sweep(docker, now=NOW, dry_run=True)
    assert result["removed"][0]["dry_run"] is True and docker.mutations == []


def test_the_creation_time_is_read_from_docker_s_two_forms():
    assert orphans.parse_created("2027-01-15 08:00:00 +0000 UTC") == NOW
    assert orphans.parse_created("2027-01-15T08:00:00.123456789Z") == NOW
    assert orphans.parse_created("2027-01-15 10:00:00 +0200 CEST") == NOW
    assert orphans.parse_created("") is None and orphans.parse_created(None) is None and orphans.parse_created("soon") is None


def test_the_sweep_never_runs_a_command_other_than_listing_and_removing():
    docker = FakeDocker([container(f"wb-eval-keys-{RUN_A}", RUN_A)], [network(f"wb-eval-held-{RUN_A}", RUN_A)])
    orphans.sweep(docker, now=NOW, include_running=True)
    assert {c[0] for c in docker.calls} <= {"ps", "network", "rm"}
    assert not any(c[0] in ("stop", "kill", "exec", "run", "inspect", "system", "prune") for c in docker.calls)


# --- the switches: the project's key, the environment, and the explicit command -------------------------------------------------


def test_the_automatic_pass_is_off_when_the_project_says_so_and_the_explicit_command_is_not(monkeypatch):
    monkeypatch.delenv(upkeep.CONTAINERS_ENV, raising=False)
    docker = FakeDocker([container(f"wb-eval-keys-{RUN_A}", RUN_A, created=VERY_OLD)])
    on = upkeep._containers({"sweep_orphan_containers": True}, NOW, docker)
    assert removed_names(on) == [f"wb-eval-keys-{RUN_A}"]
    # with a tool given the switches are not asked (a test's own tool); with none they are, and docker is never reached here
    reached = []
    monkeypatch.setattr("shutil.which", lambda name: reached.append(name) or None)
    assert upkeep._containers({"sweep_orphan_containers": False}, NOW, None)["disabled"] is True and reached == []
    monkeypatch.setenv(upkeep.CONTAINERS_ENV, "off")
    assert upkeep._containers({}, NOW, None)["disabled"] is True and reached == []
    monkeypatch.delenv(upkeep.CONTAINERS_ENV)
    assert upkeep._containers({}, NOW, None)["disabled"] is True and reached == ["docker"], "no docker client: nothing is swept"


def test_the_explicit_command_dry_run_and_its_arguments(monkeypatch, capsys):
    import lab
    docker = FakeDocker([container(f"wb-eval-run-{RUN_A}", RUN_A, created=VERY_OLD)])
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(lab, "container_tool", docker)
    monkeypatch.setattr(upkeep.time, "time", lambda: NOW)
    assert upkeep.main(["containers", "--dry-run", "--include-running"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["removed"] == [{"kind": "container", "name": f"wb-eval-run-{RUN_A}", "run": RUN_A, "via": "label", "dry_run": True}]
    assert docker.mutations == []
    assert upkeep.main(["containers", "--include-running"]) == 0 and docker.removals == [("rm", "-f", f"wb-eval-run-{RUN_A}")]
    assert upkeep.main(["containers"]) == 0
    assert upkeep.main(["containers", "--everything"]) == 2 and upkeep.main(["nothing"]) == 2


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
