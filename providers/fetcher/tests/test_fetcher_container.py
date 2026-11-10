"""The box's network helpers, `in_reference` and the reap of labelled networks, against a fake docker script. Offline."""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

import pytest

PROVIDERS = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("workbench_container_for_networks", PROVIDERS / "_container.py")
box = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = box
_spec.loader.exec_module(box)

FAKE = r'''#!{python}
import json, os, sys
state = {state!r}
args = sys.argv[1:]
open(os.path.join(state, "log.jsonl"), "a").write(json.dumps(args) + "\n")
if args[:2] == ["network", "create"]:
    sys.exit(1 if os.path.exists(os.path.join(state, "fail-create")) else 0)
if args[:2] == ["network", "connect"]:
    sys.exit(1 if os.path.exists(os.path.join(state, "fail-connect")) else 0)
if args[:2] == ["network", "rm"]:
    sys.exit(1)
if args[:2] == ["network", "ls"]:
    sys.stdout.write(open(os.path.join(state, "networks")).read() if os.path.exists(os.path.join(state, "networks")) else "")
    sys.exit(0)
if args[0] == "ps":
    sys.exit(0)
sys.exit(2)
'''


@pytest.fixture
def fake(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    script = bin_ / "docker"
    script.write_text(FAKE.format(python=sys.executable, state=str(state)))
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", str(bin_) + os.pathsep + os.environ.get("PATH", ""))

    class Tool:
        def log(self):
            path = state / "log.jsonl"
            return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

        def set(self, name, text=""):
            (state / name).write_text(text)
    return Tool()


NET = "openhora-fetch-in-0123456789ab"


def test_create_network_labels_it_and_makes_an_internal_one_only_when_asked(fake):
    box.create_network(NET, True, "org.openhora.fetcher", 1760000000)
    box.create_network("openhora-fetch-out-0123456789ab", False, "org.openhora.fetcher", 1760000000)
    inner, outer = fake.log()
    assert inner == ["network", "create", "--driver", "bridge", "--internal", "--label", "org.openhora.fetcher=1", "--label",
                     "org.openhora.fetcher.deadline=1760000000", NET]
    assert "--internal" not in outer and outer[-1] == "openhora-fetch-out-0123456789ab"


@pytest.mark.parametrize("name", ["bridge", "openhora-fetch-in-zzz", "x; rm -rf /", ""])
def test_the_network_helpers_refuse_a_name_that_is_not_a_fetch_network(fake, name):
    with pytest.raises(box.ContainerError) as caught:
        box.create_network(name, True, "org.openhora.fetcher", 1)
    assert caught.value.code == "bad_network"
    with pytest.raises(box.ContainerError):
        box.connect_network(name, "openhora-fetch-proxy-0123456789ab")
    box.remove_network(name)
    assert fake.log() == []


def test_connect_refuses_a_container_name_with_odd_characters_and_reports_a_docker_refusal(fake):
    with pytest.raises(box.ContainerError) as caught:
        box.connect_network(NET, "a b")
    assert caught.value.code == "bad_network"
    box.connect_network(NET, "openhora-fetch-proxy-0123456789ab")
    assert fake.log()[-1] == ["network", "connect", NET, "openhora-fetch-proxy-0123456789ab"]
    fake.set("fail-connect")
    with pytest.raises(box.ContainerError) as caught:
        box.connect_network(NET, "openhora-fetch-proxy-0123456789ab")
    assert caught.value.code == "network_failed"
    fake.set("fail-create")
    with pytest.raises(box.ContainerError) as caught:
        box.create_network(NET, True, "org.openhora.fetcher", 1)
    assert caught.value.code == "network_failed"


def test_remove_network_never_raises(fake, monkeypatch, tmp_path):
    box.remove_network(NET)          # the fake answers 1
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    box.remove_network(NET)


def test_reap_removes_the_labelled_networks_past_their_deadline_after_the_containers(fake):
    fake.set("networks", "aaaaaaaaaaaa 500\nbbbbbbbbbbbb 5000\ncccccccccccc\nnot-an-id 1\n")
    box.reap("org.openhora.fetcher", now=1000)
    commands = fake.log()
    assert commands[0][0] == "ps" and commands[1][:2] == ["network", "ls"]
    assert commands[1][3] == "label=org.openhora.fetcher=1"
    removed = [c[2] for c in commands if c[:2] == ["network", "rm"]]
    assert removed == ["aaaaaaaaaaaa", "cccccccccccc"]


def test_reap_does_not_fail_when_the_network_list_is_not_available(fake):
    assert box.reap("org.openhora.job", now=1) == []


def make_store(tmp_path, mode=0o400):
    store = tmp_path / "store"
    (store / "ref1" / "deep").mkdir(parents=True)
    marker = store / ".openhora-reference"
    marker.write_text("x")
    marker.chmod(mode)
    return store


def test_in_reference_is_true_for_the_store_a_folder_and_a_file_under_it_and_for_the_marker(tmp_path):
    store = make_store(tmp_path)
    (store / "ref1" / "deep" / "video.mp4").write_bytes(b"x")
    for path in (store, store / "ref1", store / "ref1" / "deep" / "video.mp4", store / ".openhora-reference", store / "ref1" / "missing.mp4"):
        assert box.in_reference(str(path)) is True


def test_in_reference_is_false_outside_a_store_and_for_a_marker_that_is_not_a_regular_file(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "a.mp4").write_bytes(b"x")
    assert box.in_reference(str(plain / "a.mp4")) is False and box.in_reference(str(plain)) is False
    odd = tmp_path / "odd"
    (odd / "sub").mkdir(parents=True)
    (odd / ".openhora-reference").mkdir()
    assert box.in_reference(str(odd / "sub")) is False
    assert box.in_reference(None) is False and box.in_reference("\0") is False


def test_in_reference_follows_a_link_to_the_real_path(tmp_path):
    store = make_store(tmp_path)
    (store / "ref1" / "video.mp4").write_bytes(b"x")
    link = tmp_path / "innocent.mp4"
    link.symlink_to(store / "ref1" / "video.mp4")
    assert box.in_reference(str(link)) is True


def test_the_marker_name_is_the_one_the_documentation_names():
    assert box.REFERENCE_MARKER == ".openhora-reference"
