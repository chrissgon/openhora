"""Tests for the doctor's checks for a machine that runs unattended (package P-OPS): linger, the macOS file access of a scheduled job, free
disk, the log limits of the harness's proxies, the secret store, and the eval image's setup command. Every check is given a fake: no
loginctl, no docker, no keyring, no real folder is asked, and the real harness containers are never named.

Run: uv run --with pytest==9.1.1 pytest scripts/tests/test_doctor_ops.py
"""
from __future__ import annotations

import importlib.util
import json
import types
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("doctor_ops_under_test", SCRIPTS / "doctor_ops.py")
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)
spec2 = importlib.util.spec_from_file_location("doctor_for_ops_under_test", SCRIPTS / "doctor.py")
doctor = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(doctor)
GIB = 1024 ** 3


# --- linger -----------------------------------------------------------------------------------------------------------------------


def runner(code=0, out="", err=""):
    asked = []

    def run(argv, timeout=15):
        asked.append(argv)
        return code, out, err
    run.asked = asked
    return run


def test_linger_on_is_ok_and_the_command_asked_is_the_one_the_spec_names():
    run = runner(out="yes\n")
    got = ops.linger_check(user="deploy", system="Linux", run=run)
    assert got["status"] == "ok" and run.asked == [["loginctl", "show-user", "deploy", "--property=Linger", "--value"]]


def test_linger_off_warns_with_the_command_that_turns_it_on():
    got = ops.linger_check(user="deploy", system="Linux", run=runner(out="no\n"))
    assert got["status"] == "warn" and got["fix"] == "loginctl enable-linger deploy" and "does not run" in got["detail"]


def test_linger_that_loginctl_cannot_say_is_unverified_not_a_pass_and_not_a_failure():
    got = ops.linger_check(user="deploy", system="Linux", run=runner(code=127, err="loginctl cannot be run: FileNotFoundError"))
    assert got["status"] == "unverified" and "loginctl show-user deploy" in got["detail"]
    assert ops.linger_check(user="deploy", system="Linux", run=runner(out="maybe\n"))["status"] == "unverified"


def test_linger_does_not_apply_off_linux_and_runs_nothing_there():
    run = runner(out="yes")
    got = ops.linger_check(user="x", system="Darwin", run=run)
    assert got["status"] == "na" and run.asked == []


# --- the macOS file access of a scheduled job ------------------------------------------------------------------------------------


def test_sources_in_a_protected_place_are_unverified_and_the_requirement_and_the_settings_path_are_named(tmp_path):
    home = tmp_path / "home"
    folder = home / "Documents" / "sources"
    folder.mkdir(parents=True)
    got = ops.sources_access_check(str(folder), system="Darwin", home=str(home))
    assert got["status"] == "unverified"
    assert "~/Documents" in got["detail"] and "no query tells whether it was" in got["detail"]
    assert "System Settings > Privacy & Security > Full Disk Access" in got["fix"] and "this process can list it" in got["detail"]


@pytest.mark.parametrize("parts", [("Desktop",), ("Downloads",), ("Library", "Mobile Documents"), ("Library", "CloudStorage")])
def test_every_protected_place_of_the_home_folder_is_recognised(tmp_path, parts):
    home = tmp_path / "home"
    folder = home.joinpath(*parts, "sources")
    folder.mkdir(parents=True)
    assert ops.sources_access_check(str(folder), system="Darwin", home=str(home))["status"] == "unverified"


def test_sources_in_a_protected_place_that_this_process_cannot_even_list_warn(tmp_path):
    home = tmp_path / "home"
    (home / "Documents").mkdir(parents=True)

    def denied(path):
        raise PermissionError(1, "Operation not permitted")
    got = ops.sources_access_check(str(home / "Documents" / "sources"), system="Darwin", home=str(home), listdir=denied)
    assert got["status"] == "warn" and "cannot list it" in got["detail"] and "Full Disk Access" in got["fix"]


def test_sources_outside_the_protected_places_need_no_permission_and_the_check_says_it_read_the_path_only(tmp_path):
    home = tmp_path / "home"
    folder = home / "work" / "sources"
    folder.mkdir(parents=True)
    got = ops.sources_access_check(str(folder), system="Darwin", home=str(home))
    assert got["status"] == "ok" and "not by running a job" in got["detail"]


def test_the_macos_check_does_not_apply_elsewhere_and_without_a_project_it_does_not_guess():
    assert ops.sources_access_check("/srv/sources", system="Linux")["status"] == "na"
    assert ops.sources_access_check(None, system="Darwin")["status"] == "unverified"


# --- disk ----------------------------------------------------------------------------------------------------------------------------


def usage_of(free_by_path):
    def usage(path):
        for prefix, free in free_by_path.items():
            if str(path).startswith(prefix):
                return types.SimpleNamespace(free=free, total=free * 10, used=0)
        raise OSError(2, "No such file or directory")
    return usage


def test_free_disk_under_the_threshold_warns_and_names_what_to_do(tmp_path):
    data, sources = tmp_path / "data", tmp_path / "sources"
    data.mkdir()
    got = ops.disk_check({"data_dir": str(data), "sources_dir": str(sources)}, 5.0,
                         usage_of({str(data): 20 * GIB, str(tmp_path): 2 * GIB}))
    rows = {r["name"]: r for r in got["rows"]}
    assert got["status"] == "warn" and rows["data_dir"]["status"] == "ok" and rows["sources_dir"]["status"] == "warn"
    assert "under the 5 GiB threshold" in rows["sources_dir"]["detail"]
    assert "run_retention_days" in got["fix"]


def test_free_disk_over_the_threshold_is_ok_and_a_folder_that_does_not_exist_is_measured_on_its_parent(tmp_path):
    got = ops.disk_check({"data_dir": str(tmp_path / "not" / "made" / "yet"), "sources_dir": str(tmp_path)}, 5.0, usage_of({str(tmp_path): 50 * GIB}))
    assert got["status"] == "ok" and all(r["free_bytes"] == 50 * GIB for r in got["rows"]) and "fix" not in got


def test_the_threshold_is_the_one_given(tmp_path):
    assert ops.disk_check({"data_dir": str(tmp_path)}, 1.0, usage_of({str(tmp_path): 2 * GIB}))["status"] == "ok"
    assert ops.disk_check({"data_dir": str(tmp_path)}, 3.0, usage_of({str(tmp_path): 2 * GIB}))["status"] == "warn"
    assert ops.MIN_FREE_GIB == 5.0


def test_no_folder_given_is_unverified_and_an_unreadable_filesystem_is_not_a_pass(tmp_path):
    assert ops.disk_check({}, 5.0)["status"] == "unverified"
    def broken(path):
        raise OSError(5, "Input/output error")
    assert ops.disk_check({"data_dir": str(tmp_path)}, 5.0, broken)["status"] == "unverified"


# --- the log limits of the harness's proxies --------------------------------------------------------------------------------------


class FakeDocker:
    """`docker ps` and `docker inspect` of invented containers; records every command and answers nothing else."""

    def __init__(self, listing, logs, down=False):
        self.listing, self.logs, self.down, self.calls = listing, logs, down, []

    def __call__(self, *args):
        self.calls.append(args)
        if self.down:
            return 1, ""
        if args[0] == "ps":
            return 0, "\n".join(self.listing)
        if args[0] == "inspect":
            return 0, json.dumps(self.logs[args[-1]])
        raise AssertionError(f"the check ran a command it should not: {args}")


LIMITED = {"Type": "json-file", "Config": {"max-size": "10m", "max-file": "3"}}
UNLIMITED = {"Type": "json-file", "Config": {}}


def test_proxies_with_a_log_limit_pass_and_the_limit_is_read_from_docker_inspect():
    tool = FakeDocker(["wb-eval-proxy-aaaaaaaaaaaa", "wb-eval-keys-aaaaaaaaaaaa"],
                      {"wb-eval-proxy-aaaaaaaaaaaa": LIMITED, "wb-eval-keys-aaaaaaaaaaaa": LIMITED})
    got = ops.proxy_logs_check(tool)
    assert got["status"] == "ok" and "max-size=10m, max-file=3" in got["detail"]
    assert tool.calls[0][:4] == ("ps", "-a", "--filter", "label=wb.eval")
    assert [c[0] for c in tool.calls[1:]] == ["inspect", "inspect"]


def test_a_proxy_whose_log_has_no_size_limit_warns_and_names_it():
    tool = FakeDocker(["wb-eval-proxy-aaaaaaaaaaaa", "wb-eval-keys-aaaaaaaaaaaa"],
                      {"wb-eval-proxy-aaaaaaaaaaaa": LIMITED, "wb-eval-keys-aaaaaaaaaaaa": UNLIMITED})
    got = ops.proxy_logs_check(tool)
    assert got["status"] == "warn" and "wb-eval-keys-aaaaaaaaaaaa" in got["detail"] and "wb-eval-proxy-aaaaaaaaaaaa" not in got["detail"]
    assert "executor.py ensure" in got["fix"]
    for bad in ({"Type": "none", "Config": {}}, {"Type": "syslog", "Config": {"max-size": "1m"}}, "not json"):
        tool = FakeDocker(["wb-eval-proxy-aaaaaaaaaaaa"], {"wb-eval-proxy-aaaaaaaaaaaa": bad})
        assert ops.proxy_logs_check(tool)["status"] == "warn"


def test_a_run_s_own_containers_are_not_inspected_and_no_proxy_yet_is_fine():
    tool = FakeDocker(["wb-eval-run-0123456789abcdef", "wb-eval-held-x"], {})
    got = ops.proxy_logs_check(tool)
    assert got["status"] == "ok" and [c[0] for c in tool.calls] == ["ps"]


def test_without_docker_the_log_limits_are_unverified():
    assert ops.proxy_logs_check(FakeDocker([], {}, down=True))["status"] == "unverified"


# --- the secret store ---------------------------------------------------------------------------------------------------------------


def test_the_secret_store_states_are_told_apart():
    states = {"ok": "ok", "locked": "warn", "unavailable": "warn", "no-library": "unverified", "odd": "unverified"}
    for state, status in states.items():
        assert ops.secret_store_check(lambda s=state: {"state": s, "detail": "d"})["status"] == status, state
    locked = ops.secret_store_check(lambda: {"state": "locked", "detail": "d"})
    assert "locked or unavailable: unlock it" in locked["detail"] and "not missing" in locked["detail"] and "credentials directory" in locked["fix"]

    def boom():
        raise ImportError("no resolver")
    assert ops.secret_store_check(boom)["status"] == "unverified"


# --- the whole run, and the doctor's own output -------------------------------------------------------------------------------------


def test_run_all_reads_the_project_and_gives_every_check(tmp_path):
    cfg = {"data_dir": str(tmp_path / "data"), "sources_dir": str(tmp_path / "sources")}
    got = ops.run_all(project="/p", load_config=lambda p: cfg, tool=FakeDocker([], {}), run=runner(out="yes"), system="Linux",
                      usage=usage_of({str(tmp_path): 30 * GIB}), probe=lambda: {"state": "ok", "detail": ""}, image={"state": "published-present"})
    assert set(got) == {"linger", "sources_access", "disk", "proxy_logs", "secret_store", "image", "project"}
    assert got["linger"]["status"] == "ok" and got["disk"]["status"] == "ok" and got["sources_access"]["status"] == "na"
    assert got["project"]["status"] == "ok"
    bad = ops.run_all(project="/p", load_config=lambda p: (_ for _ in ()).throw(ValueError("runtime.json not found")), tool=FakeDocker([], {}),
                      run=runner(out="yes"), system="Linux", usage=usage_of({}), probe=lambda: {"state": "ok", "detail": ""})
    assert bad["project"]["status"] == "warn" and "runtime.json not found" in bad["project"]["detail"]


def test_the_image_setup_command_is_named_when_the_image_is_not_present():
    assert doctor.image_setup({"state": "published-present", "detail": "x"}) is None
    assert doctor.image_setup({"state": "local-only", "detail": "x"}) is None
    assert doctor.image_setup({"state": "published-not-pulled", "detail": "x"}) == "python3 scripts/image_lock.py pull"
    both = doctor.image_setup({"state": "missing", "detail": "wb-eval:abc is not built: run `python3 evals/executor.py ensure`"})
    assert "python3 scripts/image_lock.py pull" in both and "python3 evals/executor.py ensure" in both
    assert "start docker" in doctor.image_setup({"state": "missing", "detail": "the docker daemon cannot be reached"})
    assert "repair evals/image-lock.json" in doctor.image_setup({"state": "missing", "detail": "lock unreadable: x"})


def stub_doctor(monkeypatch, tmp_path, *, linger="no", docker=None):
    """The doctor's main with every outside thing replaced: no provider, no keyring, no docker, no loginctl."""
    monkeypatch.setattr(doctor, "collect_requires", lambda: {})
    monkeypatch.setattr(doctor, "image_state", lambda: {"state": "missing", "detail": "wb-eval:abc is not built"})
    monkeypatch.setattr(doctor, "secrets_report", lambda classes: [
        {"name": "A", "found": False, "state": "locked", "source": None, "service": None, "store": "locked", "detail": "d", "classes": [], "readers": ["x"], "set": "s"},
        {"name": "B", "found": False, "state": "missing", "source": None, "service": None, "store": "available", "detail": "", "classes": [], "readers": ["x"], "set": "s"}])
    monkeypatch.setattr(doctor, "store_probe", lambda: {"state": "locked", "detail": "d"})
    monkeypatch.setattr(doctor, "load_project_config", lambda p: {"data_dir": str(tmp_path), "sources_dir": str(tmp_path)})
    import platform
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    commands = []

    def fake_run(argv, timeout=15):
        commands.append(argv)
        if argv[0] == "loginctl":
            return 0, linger + "\n", ""
        if argv[0] == "docker":
            return (docker or FakeDocker([], {}))(*argv[1:])[0], "", ""
        raise AssertionError(argv)
    import doctor_ops as imported
    monkeypatch.setattr(imported, "_run", fake_run)
    monkeypatch.setattr(imported.shutil, "disk_usage", lambda path: types.SimpleNamespace(free=40 * GIB, total=0, used=0))
    return commands


def test_the_doctor_prints_the_unattended_checks_and_a_warning_fails_only_under_strict(monkeypatch, tmp_path, capsys):
    commands = stub_doctor(monkeypatch, tmp_path, linger="no")
    assert doctor.main(["--unattended", "--project", str(tmp_path)]) == 0
    err = capsys.readouterr().err
    assert "locked    A" in err and "missing   B" in err
    assert "warn       linger" in err and "fix: loginctl enable-linger" in err
    assert "setup: python3 scripts/image_lock.py pull (a published image)" in err
    assert doctor.main(["--unattended", "--project", str(tmp_path), "--strict"]) == 1
    assert ["loginctl"] == [c[0] for c in commands][:1]


def test_the_json_carries_the_unattended_key_the_image_setup_and_the_state_of_each_secret(monkeypatch, tmp_path, capsys):
    stub_doctor(monkeypatch, tmp_path, linger="yes")
    assert doctor.main(["--unattended", "--project", str(tmp_path), "--json", "--min-free-gib", "3"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert set(report["unattended"]) == {"linger", "sources_access", "disk", "proxy_logs", "secret_store", "image", "project"}
    assert report["unattended"]["linger"]["status"] == "ok" and report["unattended"]["secret_store"]["status"] == "warn"
    assert report["image"]["setup"].startswith("python3 scripts/image_lock.py pull")
    assert {s["name"]: s["state"] for s in report["secrets"]} == {"A": "locked", "B": "missing"}


def test_without_the_flag_the_doctor_runs_none_of_the_new_checks(monkeypatch, tmp_path, capsys):
    commands = stub_doctor(monkeypatch, tmp_path)
    assert doctor.main(["--json"]) == 0
    assert "unattended" not in json.loads(capsys.readouterr().out) and commands == []


def test_the_new_options_are_checked(capsys):
    assert doctor.main(["--project"]) == 2
    assert doctor.main(["--min-free-gib", "lots"]) == 2
    assert doctor.main(["--min-free-gib", "0"]) == 2


def test_the_summary_line_names_the_locked_secrets_apart_from_the_missing_ones(monkeypatch, tmp_path, capsys):
    stub_doctor(monkeypatch, tmp_path)
    assert doctor.main([]) == 0
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert summary["secrets_missing"] == ["B"] and summary["secrets_locked"] == ["A"]


def test_the_project_folders_are_read_from_runtime_json_and_only_absolute_paths_count(tmp_path):
    (tmp_path / "docs" / "workbench").mkdir(parents=True)
    file = tmp_path / "docs" / "workbench" / "runtime.json"
    file.write_text(json.dumps({"data_dir": "/srv/d", "sources_dir": "/srv/s", "other": 1}))
    assert doctor.load_project_config(str(tmp_path)) == {"data_dir": "/srv/d", "sources_dir": "/srv/s"}
    file.write_text(json.dumps({"data_dir": "relative", "sources_dir": "/srv/s"}))
    with pytest.raises(ValueError):
        doctor.load_project_config(str(tmp_path))
    with pytest.raises(OSError):
        doctor.load_project_config(str(tmp_path / "nowhere"))
