"""Tests of the dispatcher's entry for the scheduler (stage 6, WP-6.7): runtime/dispatcher.py started as a subprocess
from a copy outside the checkout, as the scheduler starts it, with a stand-in checkout; and the operation pin.
Offline; no docker, no model, nothing scheduled.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_dispatcher_entry.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys

import pytest

import standin_tree as st

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")

# A stand-in checkout: its ops.py marks that it was imported, and answers poll and dispatch.
STANDIN_OPS = '''import json, os
open(os.environ["ENTRY_MARKER"], "a").write("loaded\\n")
class OpsError(Exception):
    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code
def poll(project):
    return {"job": "poll", "project": project, "first_on_path": os.environ["PATH"].split(os.pathsep)[0]}
def dispatch(project):
    return {"job": "work", "project": project}
'''
STANDIN_LAB = '''def reference(tier="strong"):
    return {"tier": tier, "model": "m"}
def credential_missing(tier):
    return []
'''


@pytest.fixture
def setup(tmp_path):
    bench, project, data, job = (tmp_path / name for name in ("bench", "project", "data", "job"))
    (bench / "runtime").mkdir(parents=True)
    (bench / "runtime" / "ops.py").write_text(STANDIN_OPS, encoding="utf-8")
    (bench / "runtime" / "lab.py").write_text(STANDIN_LAB, encoding="utf-8")
    (project / "docs" / "workbench").mkdir(parents=True)
    tools = tmp_path / "tools"
    tools.mkdir()
    config = project / "docs" / "workbench" / "runtime.json"
    config.write_text(json.dumps({"workbench": str(bench), "data_dir": str(data), "store_db": str(data / "t.sqlite"),
                                  "path": [str(tools)]}), encoding="utf-8")
    job.mkdir()
    entry = job / "dispatcher.py"
    shutil.copyfile(st.RUNTIME / "dispatcher.py", entry)  # the scheduler runs a copy kept in its job folder
    pin = data / "dispatch-pin.json"
    data.mkdir()
    write_pin(pin, config)
    return {"bench": bench, "project": project, "config": config, "entry": entry, "pin": pin, "tools": tools,
            "marker": tmp_path / "loaded.txt"}


def write_pin(pin, config) -> None:
    digest = hashlib.sha256(config.read_bytes()).hexdigest()
    pin.write_text(json.dumps({"runtime_json": {"path": str(config), "sha256": digest},
                               "pinned_at": "2026-10-06T00:00:00+00:00"}), encoding="utf-8")


def start(setup, *args) -> subprocess.CompletedProcess:
    env = dict(os.environ, ENTRY_MARKER=str(setup["marker"]))
    return subprocess.run([sys.executable, str(setup["entry"]), *args], capture_output=True, text=True, timeout=60,
                          cwd=str(setup["project"]), env=env)


def test_a_copy_of_the_entry_alone_loads_the_checkout_the_configuration_names(setup):
    for verb, job in (("poll", "poll"), ("work", "work")):
        done = start(setup, verb, "--project", str(setup["project"]), "--pin", str(setup["pin"]))
        assert done.returncode == 0, done.stderr
        assert json.loads(done.stdout)["job"] == job
    assert setup["marker"].read_text().count("loaded") == 2


def test_a_changed_configuration_is_refused_before_any_code_of_the_checkout_is_loaded(setup):
    setup["config"].write_text(setup["config"].read_text().replace("}", ', "max_cost_usd_per_run": 9}'), encoding="utf-8")
    done = start(setup, "work", "--project", str(setup["project"]), "--pin", str(setup["pin"]))
    assert done.returncode == 3 and done.stdout == ""
    assert "changed since the job was approved" in done.stderr and "accept-config" in done.stderr
    assert not setup["marker"].exists()  # nothing of the checkout was imported
    assert start(setup, "work", "--project", str(setup["project"]), "--pin", str(setup["pin"]) + ".missing").returncode == 3
    assert not setup["marker"].exists()


def test_a_pin_of_another_project_is_refused(setup, tmp_path):
    other = tmp_path / "other" / "docs" / "workbench" / "runtime.json"
    other.parent.mkdir(parents=True)
    other.write_bytes(setup["config"].read_bytes())  # the same bytes, another project
    write_pin(setup["pin"], other)
    done = start(setup, "poll", "--project", str(setup["project"]), "--pin", str(setup["pin"]))
    assert done.returncode == 3 and "changed since the job was approved" in done.stderr
    assert not setup["marker"].exists()


def test_the_folders_of_path_come_first_for_what_the_entry_starts(setup):
    done = start(setup, "poll", "--project", str(setup["project"]), "--pin", str(setup["pin"]))
    assert json.loads(done.stdout)["first_on_path"] == str(setup["tools"])


def test_the_command_file_starts_the_system_interpreter_and_snapshots_the_entry_and_the_pin(setup):
    done = start(setup, "command-file", "--job", "work", "--project", str(setup["project"]), "--pin", str(setup["pin"]))
    assert done.returncode == 0, done.stderr
    job = json.loads(done.stdout)
    assert job["argv"] == ["/usr/bin/python3", str(setup["entry"]), "work", "--project", str(setup["project"]),
                           "--pin", str(setup["pin"])]
    assert job["snapshot"] == [str(setup["entry"]), str(setup["pin"])] and job["cwd"] == str(setup["project"])
    assert not setup["marker"].exists()  # the command file loads nothing of the checkout
    assert start(setup, "command-file", "--job", "work", "--project", str(setup["project"])).returncode == 2


def test_the_poller_s_limit_is_five_minutes_and_the_worker_s_the_provider_s_maximum(setup):
    limits = {}
    for job in ("poll", "work"):
        done = start(setup, "command-file", "--job", job, "--project", str(setup["project"]), "--pin", str(setup["pin"]))
        limits[job] = json.loads(done.stdout)["timeout_minutes"]
    source = (st.REPO / "providers" / "scheduler" / "launchd.py").read_text(encoding="utf-8")
    maximum = int(re.search(r"DEFAULT_TIMEOUT_MINUTES, MAX_TIMEOUT_MINUTES = \d+, (\d+)", source).group(1))
    assert limits == {"poll": 5, "work": maximum}


def test_the_check_names_every_module_it_could_not_import(setup):
    (setup["bench"] / "runtime" / "broken.py").write_text("import no_such_module_anywhere\n", encoding="utf-8")
    (setup["bench"] / "runtime" / "handlers").mkdir()
    (setup["bench"] / "runtime" / "handlers" / "fine.py").write_text("VERBS = ('tick',)\n", encoding="utf-8")
    done = start(setup, "check", "--project", str(setup["project"]))
    report = json.loads(done.stdout)
    assert done.returncode == 1
    assert report["modules"]["broken.py"].startswith("ModuleNotFoundError") and report["modules"]["ops.py"] == "ok"
    assert report["modules"]["handlers/fine.py"] == "ok" and report["lab"] == "ok" and report["credential"] == "ok"
    assert set(report["tools"]) == {"docker", "uv", "git"} and report["executable"] == sys.executable
    assert report["secret_store"] == "ok" or "cannot read the secret store" in report["secret_store"]


def test_the_pin_is_written_only_for_an_accepted_configuration(tmp_path, monkeypatch):
    tree = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(tree["tree"]))
    project = str(tree["project"])
    with pytest.raises(ops.OpsError) as refused:
        ops.pin(project)
    assert refused.value.code == 3 and not (tree["data"] / "dispatch-pin.json").exists()
    digest = ops.project_config.load(project)["sha256"]
    ops.accept_config(project, digest)
    out = ops.pin(project)
    pinned = json.loads(open(out["pin"], encoding="utf-8").read())
    assert pinned["runtime_json"] == {"path": str(tree["project"] / "docs" / "workbench" / "runtime.json"), "sha256": digest}
    assert stat.S_IMODE(os.stat(out["pin"]).st_mode) == 0o600 and "command-file" in out["next"]
