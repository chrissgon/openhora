"""Tests of the contained run (ops.contained_run, the terminal's `contained-run`, `platforms=` of lab.run_skill): one run of
one skill of an area agent's pack, in the eval container, for a caller that is not a task. Each of the four restrictions of
"The contained run" in contracts/runtime.md has its test here (R1 to R4 below). Offline: the stand-in tree and adapter of
runtime/tests/standin_tree.py, with the adapter's last lines extended by this file (it records the model it was started
with, the variables it saw and, when a test asks, a reply it makes); every name and every credential-shaped text is invented
and built at run time.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_contained_run.py
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

import standin_tree as st

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
cli = st.load("cli")
plan = st.load("plan")
project_config = st.load("project_config")

GIT_ENV = {"GIT_AUTHOR_NAME": "Demo Person", "GIT_AUTHOR_EMAIL": "demo@example.com",
           "GIT_COMMITTER_NAME": "Demo Person", "GIT_COMMITTER_EMAIL": "demo@example.com",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
# The stand-in adapter's own lines, then: the model it was started with ($6), a reply made by the test (reply.txt), and
# the environment it saw.
EXTRA = '''
echo "$6" >> "$here/models.txt"
[ -f "$here/reply.txt" ] && cp "$here/reply.txt" "$out/response.md"
env > "$out/env.txt"
'''
SOCIAL = "demo-social"
KEY = "STANDIN_KEY"
PUBLISHER_KEY = "DEMO_NET_PUBLISHER_TOKEN"


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    monkeypatch.setattr(ops_core, "_own_key", lambda: (None, None))  # never the real secret store
    # A skill like mkt-engage: it declares the runtime's configuration as an input, and a file under docs/ it writes.
    st.skill(built["tree"], SOCIAL, "docs/workbench/state.md, docs/brand/voice.md, docs/workbench/runtime.json",
             "docs/marketing/engagement-log.jsonl", area="marketing")
    (built["adapter"] / "run-prompt.sh").write_text(st.ADAPTER + EXTRA, encoding="utf-8")
    monkeypatch.setattr(plan, "resolve_pack", lambda pack, root: [SOCIAL, "demo-asks"] if pack == "social" else [])
    project = built["project"]
    config = project / "docs" / "workbench" / "runtime.json"
    data = json.loads(config.read_text())
    # `model` and `harness` are the first runtime's keys: the proof decides the model, never these.
    data.update(area_agents={"marketing": {"pack": "social"}}, model="configured-model", harness="configured-harness")
    config.write_text(json.dumps(data), encoding="utf-8")
    write(project, "docs/brand/voice.md", "# Voice\n")
    write(project, "docs/marketing/engagement-log.jsonl", "{}\n")
    ops.accept_config(str(project), project_config.load(str(project))["sha256"])
    return {**built, "path": str(project), "out": tmp_path / "out"}


def write(project: Path, rel: str, text: str) -> Path:
    path = project / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def checkout(project: Path) -> None:
    for args in (("init", "-q"), ("add", "-A"), ("commit", "-q", "-m", "the project")):
        subprocess.run(["git", "-C", str(project), *args], check=True, capture_output=True, timeout=60,
                       env={**os.environ, **GIT_ENV})


def contained(tree, skill=SOCIAL, prompt="Handle the comment.\n", **more) -> dict:
    return ops.contained_run(tree["path"], skill, prompt, str(tree["out"]), **more)


def seen_files(result: dict) -> list:
    """The files the stand-in saw in the copy, without the staged skill."""
    listed = (Path(result["run_dir"]) / "outputs" / "files.txt").read_text(encoding="utf-8").splitlines()
    return [line for line in listed if not line.startswith("./.h/")]


def tree_hashes(project: Path) -> dict:
    return {str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(project.rglob("*")) if p.is_file() and ".git" not in p.parts}


def models(tree) -> list:
    path = tree["adapter"] / "models.txt"
    return path.read_text().split() if path.is_file() else []


# R1. A malicious comment reaches only the copy with that agent's documents.

def test_a_contained_social_run_sees_only_the_artifacts_its_skill_declares(tree):
    project = tree["project"]
    write(project, "src/app.py", "print('app')\n")                  # a versioned file the skill does not declare
    write(project, "docs/brand/other.md", "# Other\n")              # a document the skill does not declare
    write(project, ".workbench-local/notes.json", "{}\n")           # work data the skill does not declare
    checkout(project)
    write(project, "scratch.txt", "not tracked\n")
    result = contained(tree)
    assert result["status"] == "ok"
    assert sorted(seen_files(result)) == ["./docs/brand/voice.md", "./docs/marketing/engagement-log.jsonl",
                                          "./docs/workbench/state.md"]
    assert "./docs/workbench/runtime.json" not in seen_files(result)  # declared as an input, never entered
    assert "./AGENTS.md" not in seen_files(result)                    # the project's AGENTS.md: only when declared
    assert result["run_dir"] == os.path.join(str(tree["data"]), "contained-runs", "1")


# R2. The model can read, answer and run commands in the container, with no credential.

def test_no_credential_but_the_model_s_own_enters_a_contained_social_run(tree, monkeypatch):
    real = lab.reference
    monkeypatch.setattr(lab, "reference", lambda tier="strong": {**real(tier), "pass_env": [KEY]})
    monkeypatch.setenv(KEY, "invented-model-key-0123456789")
    monkeypatch.setenv(PUBLISHER_KEY, "invented-publisher-token-9876543210")
    monkeypatch.setenv("VCS_GITHUB_TOKEN", "invented-code-token-5555555555")
    result = contained(tree)
    assert result["status"] == "ok"
    env = (Path(result["run_dir"]) / "outputs" / "env.txt").read_text(encoding="utf-8")
    assert f"{KEY}=" in env                      # the model's own variable travels, as a lab run passes it
    for word in (PUBLISHER_KEY, "invented-publisher-token", "VCS_GITHUB_TOKEN", "invented-code-token"):
        assert word not in env, word
    assert "invented-model-key-0123456789" not in env  # and its value is replaced in everything the run left


# R3. What it can spend is bounded.

def test_a_contained_social_run_is_one_attempt_within_its_time_limit_and_never_on_the_open_network(tree, monkeypatch):
    seen = []
    real = lab.run_skill
    monkeypatch.setattr(lab, "run_skill", lambda *a, **k: seen.append(k) or real(*a, **k))
    # A skill that requires the web and was measured with it would route to the web: a contained run is never on it.
    route = ops.proof_rules.route
    monkeypatch.setattr(ops.proof_rules, "route", lambda *a, **k: {**route(*a, **k), "web": True})
    st.fail(tree["adapter"], "adapter", 1)
    failed = contained(tree, timeout=30)
    assert failed["status"] == "failed" and failed["failure"]["kind"] == "adapter"
    assert st.calls(tree["adapter"]) == ["none 1"]  # the lab's own retries are off: one call, not three
    assert seen[0]["web"] is False and seen[0]["retries"] == 0 and seen[0]["timeout"] == 30
    st.fail(tree["adapter"], "timeout", 9)
    slow = contained(tree, timeout=1)
    assert slow["status"] == "failed" and slow["failure"]["kind"] == "timeout"
    assert len(st.calls(tree["adapter"])) == 2 and seen[1]["timeout"] == 1
    assert all(k["web"] is False and k["retries"] == 0 for k in seen)
    timing = json.loads((tree["out"] / "timing.json").read_text())
    assert timing["exit_code"] == 1


def test_the_model_of_a_contained_social_run_comes_from_the_proof_never_from_the_configuration(tree):
    config = json.loads((tree["project"] / "docs" / "workbench" / "runtime.json").read_text())
    assert config["model"] == "configured-model" and config["harness"] == "configured-harness"
    result = contained(tree)
    assert (result["tier"], result["model"], result["adapter"]) == ("strong", "m", "h")
    assert models(tree) == ["m"]  # the model the adapter was started with: the gate file's, by the proof
    assert "configured-model" not in (tree["out"] / "timing.json").read_text()


# R4. Something can leave only through the reply.

def test_nothing_but_the_reply_leaves_a_contained_social_run(tree):
    project = tree["project"]
    write(project, "docs/business/market.md", "# Market\n")
    before = tree_hashes(project)
    # demo-asks writes four files into its copy when the prompt carries an answer: three created, the state file changed.
    result = contained(tree, skill="demo-asks", prompt="Go on.\n--- the user's answer 1 ---\nPortugal.\n")
    assert result["status"] == "ok" and result["ignored_changes"] == 4
    assert (Path(result["run_dir"]) / "cwd" / "docs" / "business" / "market.md").is_file()  # it did write, in the copy
    assert tree_hashes(project) == before                                                   # and none of it came back
    assert sorted(os.listdir(tree["out"])) == ["response.md", "timing.json"]
    assert not (project / ".h").exists() and not (project / "notes.txt").exists()
    assert (tree["out"] / "response.md").read_text(encoding="utf-8").startswith("- Analysis: docs/business/market.md")


def test_the_reply_passes_the_credential_scan_before_it_is_written_out(tree):
    token = "AKIA" + "Q" * 16  # a text in a credential's format, built at run time
    reply = f"The decision is below.\nthe key is {token}\nDone.\n"
    (tree["adapter"] / "reply.txt").write_text(reply, encoding="utf-8")
    result = contained(tree)
    written = (tree["out"] / "response.md").read_text(encoding="utf-8")
    assert token not in written and "<line removed: it held what looks like a credential" in written
    assert written.startswith("The decision is below.\n") and written.endswith("\nDone.\n")
    assert token not in json.dumps(result) and token not in (tree["out"] / "timing.json").read_text()
    # What the model wrote stays in the run folder, which stays on the person's machine; the scan guards what leaves it.
    assert token in (Path(result["run_dir"]) / "outputs" / "response.md").read_text(encoding="utf-8")


# The proof of the container: the platform's reference, the image, the cost.

def _platforms(tree, *names: str) -> Path:
    folder = tree["tree"] / "shared" / "references" / "platforms"
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / f"{name}.md").write_text(f"# {name}\n", encoding="utf-8")
    (folder / "demo-net.json").write_text("{}\n", encoding="utf-8")
    return folder


def test_the_platform_s_reference_is_staged_as_the_lab_stages_it_for_a_case(tree):
    folder = _platforms(tree, "demo-net", "other-net")
    path = tree["path"]
    named = contained(tree, platforms=["demo-net"])        # a skill that cites no platform folder, and a named platform
    listed = (Path(named["run_dir"]) / "outputs" / "files.txt").read_text(encoding="utf-8").splitlines()
    assert "./.h/shared/references/platforms/demo-net.md" in listed and "./.h/shared/references/platforms/demo-net.json" in listed
    assert "./.h/shared/references/platforms/other-net.md" not in listed
    # A skill that cites the folder keeps every platform it is given today; the named one is added, never in their place.
    skill = tree["tree"] / "skills" / SOCIAL / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\nRead `../../shared/references/platforms/<platform>.md`.\n",
                     encoding="utf-8")
    cited = contained(tree, platforms=["demo-net"])
    listed = (Path(cited["run_dir"]) / "outputs" / "files.txt").read_text(encoding="utf-8").splitlines()
    assert {"./.h/shared/references/platforms/demo-net.md", "./.h/shared/references/platforms/other-net.md"} <= set(listed)
    plain = contained(tree)                                  # none named: only what the skill cites, as before
    listed = (Path(plain["run_dir"]) / "outputs" / "files.txt").read_text(encoding="utf-8").splitlines()
    assert "./.h/shared/references/platforms/other-net.md" in listed
    # What a run does to a staged reference never comes back: the checkout's own file is as it was.
    assert (folder / "demo-net.md").read_text(encoding="utf-8") == "# demo-net\n"
    assert not (Path(path) / ".h").exists() and not (Path(path) / "shared").exists()
    # A name with no reference is refused before any call.
    calls = len(st.calls(tree["adapter"]))
    with pytest.raises(ops.OpsError) as refused:
        contained(tree, platforms=["no-such-net"])
    assert refused.value.code == 3 and "no-such-net" in str(refused.value) and len(st.calls(tree["adapter"])) == calls


def test_a_missing_image_is_a_refusal_and_never_a_build(tree, monkeypatch):
    called = []

    class Executor:
        @staticmethod
        def names():
            return {"image": "wb-eval:invented"}

        @staticmethod
        def docker(*args, check=True, **kwargs):
            called.append(args[:2])
            return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "No such image"})()

        @staticmethod
        def ensure():
            called.append(("ensure",))
            return {}

    er = lab.load()
    monkeypatch.setattr(er, "EXECUTOR", "container")
    monkeypatch.setattr(er, "load_executor", lambda: Executor)
    with pytest.raises(ops.OpsError) as refused:
        contained(tree)
    assert refused.value.code == 3 and "never builds it" in str(refused.value) and str(refused.value).startswith("container:")
    assert called == [("image", "inspect")] and st.calls(tree["adapter"]) == []
    assert not tree["out"].exists()  # nothing was written out


def test_the_cost_of_a_subscription_run_is_written_as_unknown_and_a_metered_run_keeps_it(tree, monkeypatch):
    strong = contained(tree)
    assert strong["tier"] == "strong"
    timing = json.loads((tree["out"] / "timing.json").read_text())
    assert timing == {"total_tokens": 100, "duration_ms": 5, "exit_code": 0, "cost_usd": None}  # the adapter reported 0.01
    # A run on a metered credential keeps the adapter's figure (ADJ-R3): the runtime's own capped key for the floor model is one.
    real = lab.reference
    monkeypatch.setattr(lab, "reference", lambda tier="strong": {**real(tier), "pass_env": ["STANDIN_FLOOR_PASS"] if tier == "floor" else []})
    monkeypatch.setenv("STANDIN_FLOOR_PASS", "invented-value-never-shown")
    monkeypatch.setattr(lab, "standing", lambda skill: {
        "skill": skill, "version": "0.1.0",
        "models": {"m": {"band": "reliable", "cause": None, "score": 0.9, "mean": 0.95, "runs": 6},
                   "fm": {"band": "reliable", "cause": None, "score": 0.9, "mean": 0.95, "runs": 6}},
        "tiers": {"strong": {"model": "m", "adapter": "h"}, "floor": {"model": "fm", "adapter": "h"}},
        "web_cases": [], "evidence_images": [st.STANDIN_IMAGE]})
    monkeypatch.setattr(lab, "proof_inputs", lambda skill: "standin-floor-" + skill)
    monkeypatch.setattr(ops_core, "_floor_key", lambda: {"value": None, "source": "lab", "reason": None})
    floor = contained(tree)
    assert floor["tier"] == "floor"  # (the stand-in names one model for both tiers; the tier is what the proof chose)
    assert json.loads((tree["out"] / "timing.json").read_text())["cost_usd"] == 0.01


# What the package adds to the four: scope, the configuration's hash, the terminal's command.

def test_a_skill_outside_every_pack_of_the_configuration_is_refused_and_nothing_runs(tree, monkeypatch):
    for skill, why in (("demo-writes", "pack of no enabled area agent"), ("no-such-skill", "not a skill of this checkout"),
                       ("../demo-asks", "not a skill of this checkout")):
        with pytest.raises(ops.OpsError, match=why) as refused:
            contained(tree, skill=skill)
        assert refused.value.code == 2, skill
    config = tree["project"] / "docs" / "workbench" / "runtime.json"
    data = json.loads(config.read_text())
    data["area_agents"] = {"marketing": {"pack": "social", "enabled": False}}      # a disabled agent puts nothing in scope
    config.write_text(json.dumps(data), encoding="utf-8")
    ops.accept_config(tree["path"], project_config.load(tree["path"])["sha256"])
    with pytest.raises(ops.OpsError, match="pack of no enabled area agent"):
        contained(tree)
    del data["area_agents"]                                                         # none at all: no skill is in scope
    config.write_text(json.dumps(data), encoding="utf-8")
    ops.accept_config(tree["path"], project_config.load(tree["path"])["sha256"])
    with pytest.raises(ops.OpsError, match="pack of no enabled area agent"):
        contained(tree)
    assert st.calls(tree["adapter"]) == [] and not tree["out"].exists()


def test_a_skill_with_no_whole_runtime_manifest_is_refused(tree):
    (tree["tree"] / "skills" / SOCIAL / "evals" / "runtime-manifest.json").unlink()
    with pytest.raises(ops.OpsError, match="runtime manifest") as refused:
        contained(tree)
    assert refused.value.code == 2 and st.calls(tree["adapter"]) == []


def test_a_configuration_the_person_did_not_accept_stops_a_contained_run(tree):
    config = tree["project"] / "docs" / "workbench" / "runtime.json"
    config.write_text(config.read_text().replace("configured-model", "another-model"), encoding="utf-8")
    with pytest.raises(ops.OpsError, match="accept-config") as refused:
        contained(tree)
    assert refused.value.code == 3 and st.calls(tree["adapter"]) == []


def test_the_prompt_is_the_text_given_byte_for_byte_and_each_run_has_its_own_folder(tree):
    text = "This task comes from the agent runtime.\n\n  Platform: demo-net\r\nlast line, no space at the end \n"
    first = contained(tree, prompt=text)
    second = contained(tree, prompt=text)
    assert (Path(first["run_dir"]) / "prompt.md").read_bytes() == text.encode("utf-8")
    assert [Path(first["run_dir"]).name, Path(second["run_dir"]).name] == ["1", "2"]
    with pytest.raises(ops.OpsError, match="prompt is empty"):
        contained(tree, prompt="  \n")
    for bad in ({"platforms": "demo-net"}, {"platforms": [3]}, {"timeout": 0}, {"timeout": "9"}, {"timeout": True}):
        with pytest.raises(ops.OpsError) as refused:
            contained(tree, **bad)
        assert refused.value.code == 2, bad


def test_the_terminal_command_prints_the_result_and_exits_0_when_the_model_answered_and_1_when_it_did_not(tree, capsys):
    prompt = tree["out"].parent / "prompt.txt"
    prompt.write_text("Handle the comment.\n", encoding="utf-8")
    _platforms(tree, "demo-net")
    argv = ["contained-run", "--project", tree["path"], "--skill", SOCIAL, "--prompt-file", str(prompt), "--out", str(tree["out"]),
            "--platform", "demo-net", "--timeout-seconds", "30"]
    assert cli.main(argv) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "ok" and printed["failure"] is None and sorted(printed) == [
        "adapter", "failure", "ignored_changes", "model", "run_dir", "status", "tier"]
    assert "./.h/shared/references/platforms/demo-net.md" in (Path(printed["run_dir"]) / "outputs" / "files.txt").read_text()
    assert (tree["out"] / "response.md").is_file() and (tree["out"] / "timing.json").is_file()
    st.fail(tree["adapter"], "adapter", 9)
    assert cli.main(argv[:-4]) == 1                    # no platform, no time limit given: the gate file's
    assert json.loads(capsys.readouterr().out)["failure"]["kind"] == "adapter"
    capsys.readouterr()
    assert cli.main(["contained-run", "--project", tree["path"], "--skill", "demo-writes", "--prompt-file", str(prompt),
                     "--out", str(tree["out"])]) == 2                                          # outside every pack
    assert "pack of no enabled area agent" in capsys.readouterr().err
    assert cli.main(["contained-run", "--project", tree["path"], "--skill", SOCIAL, "--prompt-file", str(prompt) + ".missing",
                     "--out", str(tree["out"])]) == 2                                          # a usage error
    assert cli.main(argv[:-4] + ["--platform", "no-such-net"]) == 3                            # no reference for it
    assert "no-such-net" in capsys.readouterr().err
    with pytest.raises(cli.Usage, match="contained-run needs --out"):
        cli.run(["contained-run", "--project", tree["path"], "--skill", SOCIAL, "--prompt-file", str(prompt)])


def test_a_platform_named_to_the_lab_is_added_to_the_ones_a_skill_cites_and_a_bad_name_is_refused_before_any_call(tree, tmp_path):
    _platforms(tree, "demo-net", "other-net")

    def run(**more):
        with lab.session():
            return lab.run_skill(SOCIAL, "please\n", [], str(tmp_path / "data" / f"run-{len(list((tmp_path / 'data').glob('run-*')))}"),
                                 **more)

    def staged(result):
        listed = (Path(result["outputs"]) / "files.txt").read_text(encoding="utf-8")
        return sorted(line.rsplit("/", 1)[1] for line in listed.splitlines() if "/references/platforms/" in line)

    assert staged(run()) == [] and staged(run(platforms=None)) == [] and staged(run(platforms=[])) == []
    assert staged(run(platforms=["other-net", "demo-net", "demo-net"])) == ["demo-net.json", "demo-net.md", "other-net.md"]
    for bad in ("demo-net", [1], ["Demo Net"], ["../x"], ["no-such-net"]):
        with pytest.raises(lab.LabError) as refused:
            run(platforms=bad)
        assert refused.value.kind == "config", bad
    assert len(st.calls(tree["adapter"])) == 4
