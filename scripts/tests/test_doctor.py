"""Tests for scripts/doctor.py: a provider name from the environment is validated before it runs.

Run: uv run --with pytest pytest scripts/tests
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "doctor.py"
spec = importlib.util.spec_from_file_location("doctor", SCRIPT)
doctor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(doctor)




def test_a_name_from_the_environment_that_is_not_a_provider_is_not_run(monkeypatch):
    ran = []
    monkeypatch.setattr(doctor.subprocess, "run", lambda *a, **k: ran.append(a))
    for impl in ("../../tmp/x", "/tmp/x", "auth", "LAUNCHD", "nope"):
        monkeypatch.setenv("SCHEDULER_PROVIDER", impl)
        status, detail = doctor.check_class("scheduler:job")
        assert status == "missing" and "is not a provider" in detail, impl
    assert doctor.check_class("../x:y")[0] == "unknown"
    assert ran == []


def test_harness_name_is_validated():
    r = subprocess.run([sys.executable, str(SCRIPT), "--harness", "../providers"], capture_output=True, text=True)
    assert r.returncode == 2


def test_integration_class_maps_to_its_service_folder():
    assert doctor.provider_folder("integration:vcs") == "vcs"
    assert doctor.provider_folder("publisher:linkedin") == "publisher"
    assert doctor.provider_folder("scheduler:job") == doctor.provider_folder("scheduler") == "scheduler"
    assert doctor.provider_folder("reader:email") == doctor.provider_folder("mailbox") == "mailbox"
    assert doctor.provider_folder("teleporter") is None and doctor.provider_folder("reader:rss") is None


def test_the_contract_says_which_skills_the_doctor_reads_and_who_runs_it():
    # RS6: the contract said the doctor lists the classes "the installed skills require" (it reads the checkout's
    # own skills/) and that flows run it, which an installed skill cannot.
    text = (Path(doctor.ROOT) / "contracts/environment.md").read_text(encoding="utf-8")
    (paragraph,) = [p for p in text.split("\n\n") if p.startswith("`python3 scripts/doctor.py")]
    assert "the installed skills require" not in paragraph and "Flows run it" not in paragraph
    assert "its own `skills/` folder" in paragraph and "a skill never depends on it" in paragraph
    assert "through `uv run`" in paragraph


def test_only_what_the_report_uses_is_left():
    # RS5: env_provider, known_providers and check_provider were called by nothing but these tests.
    for name in ("env_provider", "known_providers", "check_provider"):
        assert not hasattr(doctor, name), name


def test_without_uv_a_provider_is_missing_and_never_run_with_the_callers_interpreter(monkeypatch):
    # RS5: without uv the doctor ran `python3 <provider>`, against providers/CONTRACT.md ("never with the
    # caller's interpreter"): a provider's pinned dependencies are not there.
    ran = []
    monkeypatch.setattr(doctor.subprocess, "run", lambda cmd, **k: ran.append(cmd))
    monkeypatch.setattr(doctor, "_which", lambda name: False)
    for name in [n for n in list(doctor.os.environ) if n.endswith("_PROVIDER")]:
        monkeypatch.delenv(name)
    status, detail = doctor.check_class("integration:vcs")
    assert status == "missing" and "uv" in detail and ran == []


def test_vcs_provider_runs_its_check_through_uv(monkeypatch):
    ran = []

    class Done:
        returncode, stdout, stderr = 0, "{}", ""

    monkeypatch.setattr(doctor.subprocess, "run", lambda cmd, **k: ran.append(cmd) or Done())
    monkeypatch.setattr(doctor, "_which", lambda name: name == "uv")
    for name in [n for n in list(doctor.os.environ) if n.endswith("_PROVIDER")]:
        monkeypatch.delenv(name)
    status, detail = doctor.check_class("integration:vcs")
    assert status == "provider" and detail.endswith("providers/vcs/github.py")
    assert ran[0] == ["uv", "run", str(Path(doctor.PROVIDERS) / "vcs" / "github.py"), "--check"]
    monkeypatch.setenv("INTEGRATION_VCS_PROVIDER", "gitlab")
    assert doctor.check_class("integration:vcs")[0] == "missing" and len(ran) == 1


def test_a_class_is_checked_through_the_resolution_function(monkeypatch):
    ran = []

    class Done:
        returncode, stdout, stderr = 0, "{}", ""

    monkeypatch.setattr(doctor.subprocess, "run", lambda cmd, **k: ran.append(cmd) or Done())
    for name in [n for n in list(doctor.os.environ) if n.endswith("_PROVIDER")]:
        monkeypatch.delenv(name)
    # No variable is set: the only store provider resolves, and the scheduler follows the platform.
    assert doctor.check_class("store:runtime") == ("provider", "sqlite (only-implementation): providers/store/sqlite.py")
    monkeypatch.setattr(doctor.sys, "platform", "linux")
    assert doctor.check_class("scheduler:job")[1] == "systemd (platform-default): providers/scheduler/systemd.py"
    monkeypatch.setenv("SCHEDULER_PROVIDER", "launchd")
    assert doctor.check_class("scheduler:job")[1] == "SCHEDULER_PROVIDER=launchd: providers/scheduler/launchd.py"
    assert [c[-2:] for c in ran] == [[str(Path(doctor.PROVIDERS) / rel), "--check"] for rel in
                                     ("store/sqlite.py", "scheduler/systemd.py", "scheduler/launchd.py")]
    # Nothing to choose, or a name that is not a shipped provider: missing, and nothing is run.
    status, detail = doctor.check_class("sender:email")
    assert status == "missing" and "MAILER_PROVIDER" in detail
    monkeypatch.setenv("SCHEDULER_PROVIDER", "../x")
    assert doctor.check_class("scheduler:job")[0] == "missing" and len(ran) == 3
    # A skill that still declares an old bare name is checked as the class it became, and told so.
    monkeypatch.delenv("SCHEDULER_PROVIDER")
    assert doctor.check_class("scheduler") == ("provider", "systemd (platform-default): providers/scheduler/systemd.py "
                                               "(declared as scheduler, the old name of scheduler:job)")


def run_recorder(monkeypatch, returncode=0):
    ran = []

    class Done:
        stdout, stderr = "{}", "not ready"
    Done.returncode = returncode
    monkeypatch.setattr(doctor.subprocess, "run", lambda cmd, **k: ran.append(cmd) or Done())
    for name in [n for n in list(doctor.os.environ) if n.endswith("_PROVIDER")]:
        monkeypatch.delenv(name)
    return ran


def test_a_class_with_a_parameter_is_checked_for_its_platform(monkeypatch):
    """RS2: the doctor ran the only publisher's --check for any platform and printed `provider`."""
    ran = run_recorder(monkeypatch)
    status, detail = doctor.check_class("publisher:linkedin")
    assert status == "provider" and ran[0][-3:] == ["--check", "--platform", "linkedin"]
    status, detail = doctor.check_class("publisher:a-platform-nobody-serves")
    assert status == "missing" and "serves a-platform-nobody-serves" in detail and len(ran) == 1
    # The placeholder form asks for no platform; a class with a fixed target passes none.
    assert doctor.check_class("publisher:<platform>")[0] == "provider" and ran[1][-1] == "--check"
    assert doctor.check_class("store:runtime")[0] == "provider" and ran[2][-1] == "--check"


def test_every_failing_check_is_missing_whatever_its_exit_code(monkeypatch):
    for code in (1, 2, 3):
        run_recorder(monkeypatch, returncode=code)
        status, detail = doctor.check_class("store:runtime")
        assert status == "missing" and f"--check exit {code}: not ready" in detail


def test_a_class_the_resolver_does_not_know_is_reported_as_unknown_without_a_traceback(monkeypatch, capsys):
    """RS3: secrets_report raised UnknownClass for a class the resolution function did not have."""
    run_recorder(monkeypatch)
    monkeypatch.setitem(sys.modules, "keyring", None)  # the secrets report never reaches the OS secret store here
    declared = {"teleporter": ["eng-demo"], "reader:rss": ["eng-demo"], "store:runtime": ["eng-demo"],
                "mailbox": ["mkt-demo"]}
    monkeypatch.setattr(doctor, "collect_requires", lambda: declared)
    assert doctor.check_class("teleporter")[0] == "unknown" and "unknown class" in doctor.check_class("teleporter")[1]
    rows = doctor.secrets_report(declared)  # no exception
    readers = {c for row in rows for c in row["classes"]}
    assert "teleporter" not in readers and "reader:rss" not in readers and "mailbox" in readers
    assert doctor.main(["--json"]) == 0
    report = doctor.json.loads(capsys.readouterr().out)
    assert {c: r["status"] for c, r in report["classes"].items()} == {
        "teleporter": "unknown", "reader:rss": "unknown", "store:runtime": "provider", "mailbox": "provider"}
    assert report["missing"] == 2
    assert doctor.main(["--strict"]) == 1


def test_the_secrets_report_names_the_store_service_that_answered(monkeypatch):
    """The compatibility stage of the rename (T23): a secret stored under the old service is found and says so."""
    import types
    held = {("ai-workbench", "github"): "zz-not-a-real-value-41", ("openhora", "notion"): "zz-not-a-real-value-41"}
    fake = types.ModuleType("keyring")
    fake.get_password = lambda service, username: held.get((service, username))
    monkeypatch.setitem(sys.modules, "keyring", fake)
    for name in ("VCS_GITHUB_TOKEN", "GITHUB_TOKEN", "NOTION_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    rows = {row["name"]: row for row in doctor.secrets_report({})}
    assert rows["VCS_GITHUB_TOKEN"]["found"] and rows["VCS_GITHUB_TOKEN"]["service"] == "ai-workbench (legacy)"
    assert rows["NOTION_TOKEN"]["found"] and rows["NOTION_TOKEN"]["service"] == "openhora"
    assert "zz-not-a-real-value-41" not in json.dumps(list(rows.values()))
