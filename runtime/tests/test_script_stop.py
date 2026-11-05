"""A stop reaches a project script's containers and networks (package P9 with R18): the stop's snapshot names the token of a script step from the
`docker run` line below the holder, and the removal asks the container tool for those exact names and no others. Offline; a fake container tool
and a fake process listing; invented tokens.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_script_stop.py
"""
from __future__ import annotations

import standin_tree as st

run_stop = st.load("run_stop")
orphans = st.load("orphans")

TOKEN, OTHER, RUN = "0123456789abcdef", "fedcba9876543210", "aaaaaaaaaaaaaaaa"


class Tool:
    """A container client that records every command; `rm` and `network rm` of a name it knows succeed."""

    def __init__(self, known=()):
        self.known, self.calls = set(known), []

    def __call__(self, *args):
        self.calls.append(args)
        name = args[-1]
        if args[0] == "rm" or args[:2] == ("network", "rm"):
            if name in self.known:
                self.known.discard(name)
                return 0, ""
            return 1, "no such object"
        raise AssertionError(f"the stop ran a command it should not: {args}")


def rows(*commands):
    """A holder (pid 10) and a child per command line, as processes() gives them."""
    return [(10, 1, 10, "python3 runtime/cli.py run-step --project /p --task 4", "t")] + [
        (11 + i, 10, 10, command, "t") for i, command in enumerate(commands)]


def test_the_snapshot_names_the_token_of_a_script_step_from_the_docker_run_line_below_the_holder():
    shot = run_stop.snapshot(10, rows(
        f"docker run --rm --init --name openhora-script-run-{TOKEN} --label org.openhora.script=1 sha256:abc python3 -I /opt/script/_inner.py run --kind py",
        f"docker run --rm --name openhora-script-proxy-{TOKEN} --network openhora-script-out-{TOKEN} sha256:abc",
        f"docker run --rm --name wb-eval-run-{RUN} img", "docker run --name openhora-script-run-short img", "sleep 5"))
    assert shot["runs"] == sorted([RUN, "script:" + TOKEN]) and len(shot["pids"]) == 5
    assert run_stop.snapshot(10, rows("docker run --name openhora-script-build-" + OTHER + " img"))["runs"] == ["script:" + OTHER]


def test_the_removal_asks_for_the_exact_names_of_a_script_step_containers_first_and_never_another_step():
    tool = Tool(known=[f"openhora-script-run-{TOKEN}", f"openhora-script-proxy-{TOKEN}", f"openhora-script-in-{TOKEN}", f"openhora-script-out-{TOKEN}",
                       f"openhora-script-run-{OTHER}", f"openhora-script-in-{OTHER}"])
    done = orphans.remove_runs(tool, ["script:" + TOKEN])
    assert tool.calls == [("rm", "-f", f"openhora-script-run-{TOKEN}"), ("rm", "-f", f"openhora-script-proxy-{TOKEN}"),
                          ("rm", "-f", f"openhora-script-build-{TOKEN}"), ("network", "rm", f"openhora-script-in-{TOKEN}"),
                          ("network", "rm", f"openhora-script-out-{TOKEN}")]
    assert [(r["kind"], r["name"]) for r in done["removed"]] == [
        ("container", f"openhora-script-run-{TOKEN}"), ("container", f"openhora-script-proxy-{TOKEN}"),
        ("network", f"openhora-script-in-{TOKEN}"), ("network", f"openhora-script-out-{TOKEN}")], "the build container was not there: not an error"
    assert tool.known == {f"openhora-script-run-{OTHER}", f"openhora-script-in-{OTHER}"} and all(r["run"] == "script:" + TOKEN for r in done["removed"])


def test_a_dry_run_sends_nothing_and_a_token_that_is_not_16_hex_removes_nothing():
    tool = Tool(known=[f"openhora-script-run-{TOKEN}"])
    dry = orphans.remove_runs(tool, ["script:" + TOKEN], dry_run=True)
    assert tool.calls == [] and len(dry["removed"]) == 5 and all(r["dry_run"] for r in dry["removed"])
    for bad in ("script:", "script:xyz", "script:../etc", "script:" + TOKEN + "0", "script:ABCDEF0123456789"):
        assert orphans.remove_runs(tool, [bad]) == {"removed": [], "kept": [], "problem": None}
    assert tool.calls == []


def test_the_eval_sweep_still_never_selects_these_names_by_itself():
    assert orphans.run_of_name("container", f"openhora-script-run-{TOKEN}") is None and orphans.run_of_name("network", f"openhora-script-in-{TOKEN}") is None
