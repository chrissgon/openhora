"""Tests of the eval container with a real docker daemon: what a run can and cannot reach. No model is called.

They build the images on first use (a few minutes) and are skipped unless WB_EVAL_DOCKER_TESTS=1:
  WB_EVAL_DOCKER_TESTS=1 uv run --with pytest pytest evals/tests/test_executor_docker.py
CI runs them in its own job, on Linux.

The image is built for the platform evidence is made on (executor.IMAGE_PLATFORM). On a machine of another
architecture, such as the CI job's, these tests build and run it for that machine's own architecture
instead (WB_EVAL_IMAGE_PLATFORM, set below): they test the definition, and no evidence comes from them.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("WB_EVAL_DOCKER_TESTS") != "1", reason="set WB_EVAL_DOCKER_TESTS=1 (needs docker)")

SCRIPT = Path(__file__).resolve().parents[1] / "executor.py"
spec = importlib.util.spec_from_file_location("executor", SCRIPT)
ex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ex)
spec = importlib.util.spec_from_file_location("eval_run_docker", SCRIPT.parent / "eval_run.py")
er = importlib.util.module_from_spec(spec)
spec.loader.exec_module(er)
REPO = SCRIPT.parents[1]
if os.environ.get("WB_EVAL_DOCKER_TESTS") == "1" and not os.environ.get(ex.PLATFORM_ENV):
    try:
        native = subprocess.run(["docker", "version", "--format", "{{.Server.Os}}/{{.Server.Arch}}"],
                                capture_output=True, text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        native = ""
    if native and native != ex.IMAGE_PLATFORM:
        os.environ[ex.PLATFORM_ENV] = native  # no emulation: the definition is what is under test here
PROVIDER = "https://openrouter.ai/api/v1/models"  # public, needs no key; on the proxy's list
OTHER = "https://github.com"  # reachable from anywhere; not on the list


@pytest.fixture(scope="module")
def environment():
    return ex.ensure()


@pytest.fixture
def root(tmp_path):
    folder = tmp_path / "eval-run"
    (folder / "case").mkdir(parents=True)
    (folder / "out").mkdir()
    return folder


def inside(root, script, network="none", env=None, pass_names=(), runner=None):
    # security-scan: allow shell-string -- every script is a literal of this test file, run inside the container
    argv, name = ex.command(["bash", "-c", script], str(root), cwd=str(root / "case"), env=env or {},
                            pass_names=pass_names, network=network, runner=runner)
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=180, env={**os.environ, **(env or {})})
    finally:
        ex.remove(name)


def code(url):
    return f"curl -s -m 15 -o /dev/null -w '%{{http_code}}' {url}"


def test_the_environment_names_the_definition_the_image_its_digest_and_its_platform(environment, root):
    assert environment["kind"] == "container" and environment["definition_sha256"] == ex.definition_hash()
    assert environment["image_id"].startswith("sha256:") and environment["image_digest"] == environment["image_id"]
    assert environment["image_platform"] == ex.image_platform()
    machine = {"linux/arm64": "aarch64", "linux/amd64": "x86_64"}[ex.image_platform()]
    assert inside(root, "uname -m").stdout.strip() == machine


def test_a_run_writes_in_its_folder_and_the_caller_owns_the_result(environment, root):
    r = inside(root, "echo made > note.txt && mkdir -p docs && echo x > docs/a.md && id -u")
    assert r.returncode == 0, r.stderr
    note = root / "case" / "note.txt"
    assert note.read_text() == "made\n"
    note.unlink()  # the caller can change and remove what a run made
    (root / "case" / "docs" / "a.md").unlink()


@pytest.mark.parametrize("harness", ["claude-code", "agents-dir"])
def test_a_run_sees_its_folder_and_the_one_adapter_script_and_nothing_else_of_the_workbench(environment, root, harness):
    runner = REPO / "adapters" / harness / "run-prompt.sh"
    r = inside(root, "find /wb | sort; echo --; ls -d /skill /wb/adapters /wb/shared 2>&1 | grep -c 'No such file'; "
                     "echo x >> /wb/run-prompt.sh 2>&1 | tail -1; head -c 19 /wb/run-prompt.sh; echo; "
                     "find / \\( -name AGENTS.md -o -name adapter.json -o -name SKILL.md -o -name README.md -path '*adapters*' \\) "
                     "-not -path '/proc/*' -not -path '/sys/*' -not -path '/dev/*' -not -path '/opt/runners/*' -not -path '/usr/*' 2>/dev/null | head -3; echo WB=$WB_EVAL_CONTAINER",
               runner=str(runner))
    assert r.returncode == 0, r.stderr
    listing, rest = r.stdout.split("--\n", 1)
    assert listing.split() == ["/wb", "/wb/run-prompt.sh"]  # the one file: not its folder, its README, its tests
    lines = rest.splitlines()
    assert lines[0] == "3"  # no /skill, no /wb/adapters, no /wb/shared
    assert "Read-only file system" in (r.stdout + r.stderr) and "#!/usr/bin/env bash" in rest
    assert lines[-1] == "WB=1" and not [l for l in lines if l.startswith("/")]  # no instruction file, manifest or skill anywhere
    r = inside(root, "ls /wb 2>&1 | grep -c 'No such file'")  # a setup command or the fixture commit: not even the script
    assert r.stdout.strip() == "1"


def test_without_a_network_nothing_is_reached(environment, root):
    r = inside(root, code(PROVIDER) + "; echo; " + code(OTHER))
    assert r.stdout.split() == ["000", "000"]


def test_through_the_proxy_only_the_providers_are_reached(environment, root):
    r = inside(root, code(PROVIDER) + "; echo; " + code(OTHER) + "; echo; "
                     + code("--noproxy '*' " + OTHER) + "; echo; " + code("--noproxy '*' https://1.1.1.1"), network="proxy")
    provider, other, direct, address = r.stdout.split()
    assert provider == "200" and other == "000" and direct == "000" and address == "000"


def test_a_case_that_may_use_the_web_gets_the_open_network(environment, root):
    r = inside(root, code(OTHER), network="open")
    assert r.stdout.strip() in ("200", "301", "302")


def test_a_secret_reaches_the_run_by_name_and_only_when_passed(environment, root):
    env = {"DEMO_NAMED": "named-value", "DEMO_UNNAMED": "unnamed-value"}
    r = inside(root, 'echo "named=$DEMO_NAMED unnamed=$DEMO_UNNAMED"', env=env, pass_names=["DEMO_NAMED"])
    assert r.stdout.strip() == "named=named-value unnamed="


def test_the_image_carries_the_pinned_tools(environment, root):
    r = inside(root, "claude --version; opencode --version; uv --version; git --version; python3 --version; "
                     "node --version; chromium --version; gh --version; file --version; patch --version")
    assert r.returncode == 0, r.stderr
    assert "2.1.283" in r.stdout and "1.18.32" in r.stdout and "0.12.19" in r.stdout and "v24.10.0" in r.stdout
    assert "gh version 2.102.0" in r.stdout and "GNU patch" in r.stdout and "magic file from" in r.stdout
    lock = (Path(ex.DEFINITION) / "runners" / "package-lock.json").read_text()
    assert '"version": "2.1.283"' in lock and '"version": "1.18.32"' in lock  # the lock file is what was installed


def test_the_code_hosts_tool_is_installed_and_signed_out(environment, root):
    r = inside(root, "gh auth status; echo status=$?; env | grep -c -i -E '^(GH|GITHUB)_' ; ls -A ~/.config 2>/dev/null | wc -l")
    out = (r.stdout + r.stderr).lower()
    assert "status=1" in out and "not logged in" in out, out
    assert r.stdout.split()[-2:] == ["0", "0"]  # no token variable, no stored configuration


def test_the_clock_the_locale_and_the_user_are_the_images_own(environment, root):
    host = {"TZ": "America/Sao_Paulo", "LANG": "pt_BR.UTF-8", "USER": "someone"}
    r = inside(root, 'echo "$TZ|$LANG|$USER|$PYTHONDONTWRITEBYTECODE|${DEBIAN_FRONTEND:-unset}|$(date +%Z)"; '
                     "python3 -c 'import locale, sys; print(sys.stdout.encoding, locale.getpreferredencoding())'", env=host)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.strip().splitlines()
    assert lines[0] == "UTC|C.UTF-8|eval|1|unset|UTC"
    assert lines[1].lower().replace("-", "") == "utf8 utf8"


def test_python_leaves_no_bytecode_in_the_case_folder(environment, root):
    r = inside(root, "printf 'X = 1\\n' > mod.py && python3 -c 'import mod; print(mod.X)' && find . -name '*.pyc' -o -name __pycache__ | wc -l")
    assert r.returncode == 0 and r.stdout.split() == ["1", "0"], r.stdout + r.stderr


def test_a_run_has_one_identity_for_its_commits_the_images(environment, root):
    host = {"GIT_AUTHOR_NAME": "someone", "GIT_AUTHOR_EMAIL": "s@host.example", "GIT_COMMITTER_NAME": "someone",
            "GIT_COMMITTER_EMAIL": "s@host.example", "GIT_ALLOW_PROTOCOL": "file"}
    r = inside(root, "git init -q . && echo x > f && git add f && git commit -q -m one && git log -1 --format='%an <%ae> / %cn <%ce>' "
                     "&& git branch --show-current && echo protocol=$GIT_ALLOW_PROTOCOL", env=host)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["Eval <eval@example.invalid> / Eval <eval@example.invalid>", "main", "protocol=file"]


def test_the_floor_runners_scratch_folder_can_be_written_by_the_run(environment, root):
    r = inside(root, "mkdir -p /tmp/opencode/work && echo ok > /tmp/opencode/work/pairs.json && cat /tmp/opencode/work/pairs.json "
                     "&& stat -c %a /tmp/opencode")
    assert r.returncode == 0 and r.stdout.split() == ["ok", "1777"], r.stdout + r.stderr


def test_a_run_holds_no_capability_cannot_gain_one_and_has_a_process_limit(environment, root):
    r = inside(root, "grep -E '^(CapEff|CapPrm|CapBnd|NoNewPrivs):' /proc/self/status; cat /sys/fs/cgroup/pids.max 2>/dev/null")
    assert r.returncode == 0, r.stderr
    status = dict(line.split(":") for line in r.stdout.splitlines() if ":" in line)
    assert int(status["CapEff"], 16) == 0 and int(status["CapPrm"], 16) == 0 and int(status["CapBnd"], 16) == 0
    assert status["NoNewPrivs"].strip() == "1"
    limits = [line for line in r.stdout.splitlines() if ":" not in line and line.strip()]
    assert limits == [str(ex.PIDS_LIMIT)]  # the cgroup's own limit, as the container sees it
    # The tools a run uses still work without them: a commit, a script, the browser.
    r = inside(root, "git init -q . && python3 -c 'print(1)' && chromium --headless --no-sandbox --disable-gpu --dump-dom about:blank 2>/dev/null | head -c 6")
    assert r.returncode == 0 and r.stdout.split()[0] == "1" and "<html" in r.stdout, r.stdout + r.stderr


def test_removing_a_container_by_name_ends_it(environment, root):
    argv, name = ex.command(["sleep", "300"], str(root))
    proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if ex.docker("ps", "-q", "--filter", f"name={name}").stdout.strip():
                break
            import time
            time.sleep(0.1)
        ex.remove(name)
        assert proc.wait(timeout=30) != 0
        assert not ex.docker("ps", "-aq", "--filter", f"name={name}").stdout.strip()
    finally:
        proc.kill()


def test_the_version_control_facts_are_read_in_a_container_with_no_network(environment, root):
    """The runner's own calls, as a real run makes them: the fixture commit, a setup, then the facts for the grader."""
    (root / "case" / "f.txt").write_text("x\n")
    quiet = {"root": str(root), "network": "none"}
    env = er.contained_env(str(root))
    er.isolate_git(str(root / "case"), env, box=quiet)
    er.run_setup(str(root / "case"), ["git init -q --bare /eval/origin.git && git remote add origin /eval/origin.git",
                                      "git checkout -q -b feature && echo y >> f.txt && git commit -q -am 'feature work' "
                                      "&& git push -q origin feature", "echo z > loose.md"], env, box=quiet)
    facts = er.version_control(str(root / "case"), env, box=quiet)
    assert "$ git status --short\n?? loose.md" in facts and "feature work" in facts and "fixture" in facts
    assert "* feature" in facts and "refs/heads/feature" in facts.split("$ git ls-remote --heads origin")[1]
    assert str(root) not in facts  # nothing of the host's paths


def demo_workbench(tmp_path):
    """A small workbench: a skill under test that cites one shared reference, and a dependency skill."""
    wb = tmp_path / "wb"
    skill, dep = wb / "skills" / "core-demo", wb / "skills" / "core-dep"
    for folder in (skill / "evals", skill / "scripts" / "tests", dep / "evals", wb / "shared" / "references", wb / "shared" / "scripts"):
        folder.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# demo\nWalk ../../shared/references/security.md.\n")
    (skill / "evals" / "evals.json").write_text('{"expected_output": "the answer"}')
    (skill / "scripts" / "check.py").write_text("print(1)\n")
    (skill / "scripts" / "tests" / "test_check.py").write_text("def test_x():\n    assert True\n")
    (dep / "SKILL.md").write_text("# dep\n")
    (dep / "evals" / "evals.json").write_text('{"expected_output": "another answer"}')
    for name in ("security.md", "other.md"):
        (wb / "shared" / "references" / name).write_text(name + "\n")
    (wb / "shared" / "scripts" / "tool.py").write_text("print(1)\n")
    return wb, skill, dep


def test_a_without_skill_container_has_no_path_that_holds_the_skill_or_the_shared_references(environment, root, tmp_path, monkeypatch):
    """The first of the three contamination checks: true by construction, asserted so that it stays true.
    The case folder is staged as a without-skill run's is, dependency skill included, and the container is
    started as a model run's is, with the one adapter script mounted."""
    wb, skill, dep = demo_workbench(tmp_path)
    monkeypatch.setattr(er, "ROOT", str(wb))
    monkeypatch.setattr(er.KIT, "ROOT", str(wb))
    staged, _ = er.stage_run(str(root / "case"), {"skills_dir": ".tool/skills", "settings": [".tool"]}, None, [str(dep)], {"id": 1})
    assert staged == [".tool/skills/core-dep"]
    search = ("find / \\( -name 'core-demo' -o -path '*shared/references*' -o -name security.md -o -name check.py \\) "
              "-not -path '/proc/*' -not -path '/sys/*' -not -path '/dev/*' -not -path '/usr/*' -not -path '/opt/*' 2>/dev/null | wc -l; "
              "grep -r -l 'Walk ../../shared/references/security.md' /eval /wb /home /tmp 2>/dev/null | wc -l; "
              "ls /eval/case/.tool/skills")
    r = inside(root, search, runner=str(REPO / "adapters" / "agents-dir" / "run-prompt.sh"), network="proxy")
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["0", "0", "core-dep"]
    # The same search finds both in the container of a with-skill run: the check can fail.
    er.stage_run(str(root / "case"), {"skills_dir": ".tool/skills", "settings": [".tool"]}, str(skill), [str(dep)], {"id": 1})
    r = inside(root, search, runner=str(REPO / "adapters" / "agents-dir" / "run-prompt.sh"), network="proxy")
    found, quoted = r.stdout.split()[:2]
    assert int(found) >= 3 and quoted == "1"


def test_a_run_reads_the_staged_skill_and_never_its_cases_its_tests_or_an_uncited_reference(environment, root, tmp_path, monkeypatch):
    """What the runner stages (eval_run.stage_run, as a real run calls it) is all a container holds of a skill."""
    wb, skill, dep = demo_workbench(tmp_path)
    monkeypatch.setattr(er, "ROOT", str(wb))
    monkeypatch.setattr(er.KIT, "ROOT", str(wb))
    staged, manifest = er.stage_run(str(root / "case"), {"skills_dir": ".tool/skills", "settings": [".tool"]}, str(skill), [str(dep)], {"id": 1})
    assert sorted(staged) == [".tool/shared", ".tool/skills/core-demo", ".tool/skills/core-dep"]
    r = inside(root, "cat .tool/skills/core-demo/SKILL.md | head -1; cat .tool/skills/core-demo/../../shared/references/security.md; "
                     "find / \\( -name evals.json -o -name 'test_check.py' -o -name other.md -o -name tool.py \\) "
                     "-not -path '/proc/*' -not -path '/sys/*' -not -path '/dev/*' -not -path '/usr/*' -not -path '/opt/*' 2>/dev/null | wc -l; find /eval -type l | wc -l")
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["#", "demo", "security.md", "0", "0"]




# --- checks that need no model, run where the runs run (the plan's item B9) ------------------------------

def test_a_name_outside_the_proxys_list_does_not_resolve_on_the_internal_network(environment, root):
    """A resolver that forwards would be a narrow channel out: on the internal network only the proxy's name resolves."""
    r = inside(root, f"getent hosts example.com; echo rc=$?; getent hosts openrouter.ai; echo rc=$?; "
                     f"getent hosts {ex.names()['proxy']} >/dev/null; echo rc=$?", network="proxy")
    assert [line for line in r.stdout.splitlines() if line.startswith("rc=")] == ["rc=2", "rc=2", "rc=0"], r.stdout


def skills_with_setup():
    import json
    found = []
    for path in sorted((REPO / "skills").glob("*/evals/evals.json")):
        cases = json.loads(path.read_text(encoding="utf-8")).get("evals") or []
        if any(c.get("setup") for c in cases):
            found.append(path.parents[1].name)
    return found


@pytest.mark.parametrize("skill", skills_with_setup())
def test_the_preflight_of_every_skill_runs_with_its_setup_in_the_container(environment, skill):
    """--check-cases leaves a case with setup commands unchecked; here they run, as a real run makes them."""
    r = subprocess.run([sys.executable, str(REPO / "evals" / "eval_run.py"), "--skill", skill, "--check-cases", "--with-setup"],
                       capture_output=True, text=True, timeout=900, env=os.environ)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["errors"] == [] and out["unchecked"] == [], out


STUB_CLAUDE = """#!/usr/bin/env bash
cat > /dev/null
sleep 300 &
echo $! > /eval/stub-child.pid
cat <<'EOF'
{"type": "assistant", "message": {"content": [{"type": "text", "text": "Reading first."}, {"type": "tool_use", "name": "Skill", "input": {"skill": "core-demo"}}]}}
{"type": "assistant", "message": {"content": [{"type": "text", "text": "The answer."}]}}
{"type": "result", "result": "The answer.", "num_turns": 2, "usage": {"input_tokens": 3, "output_tokens": 2}, "total_cost_usd": 0.0}
EOF
"""
STUB_OPENCODE = """#!/usr/bin/env bash
sleep 300 &
echo $! > /eval/stub-child.pid
echo "$OPENCODE_PERMISSION" > /eval/permission.txt
cat <<'EOF'
{"type": "step_start", "part": {}}
{"type": "text", "part": {"text": "Reading first."}}
{"type": "tool_use", "part": {"tool": "skill", "state": {"input": {"name": "core-demo"}}}}
{"type": "step_finish", "part": {"tokens": {"input": 3, "output": 2, "reasoning": 0, "cache": {"read": 0, "write": 0}}, "cost": 0}}
{"type": "step_start", "part": {}}
{"type": "text", "part": {"text": "The answer."}}
{"type": "step_finish", "part": {"tokens": {"input": 4, "output": 1, "reasoning": 0, "cache": {"read": 0, "write": 0}}, "cost": 0}}
EOF
"""


@pytest.mark.parametrize("harness, stub, name", [("claude-code", STUB_CLAUDE, "claude"), ("agents-dir", STUB_OPENCODE, "opencode")])
def test_each_run_prompt_sh_runs_in_the_image_with_a_stub_runner(environment, root, harness, stub, name):
    """The adapter's real shell, find, process groups and output files, in the image; the runner is a stub."""
    import json
    (root / "bin").mkdir()
    (root / "bin" / name).write_text(stub)
    (root / "bin" / name).chmod(0o755)
    (root / "prompt.md").write_text("Do the task.\n")
    runner = REPO / "adapters" / harness / "run-prompt.sh"
    r = inside(root, "export PATH=/eval/bin:$PATH; bash /wb/run-prompt.sh --prompt-file /eval/prompt.md --cwd /eval/case "
                     "--model m --out /eval/out; echo rc=$?; sleep 1; kill -0 $(cat /eval/stub-child.pid) 2>/dev/null "
                     "&& echo left-running || echo stopped", runner=str(runner), network="proxy")
    assert "rc=0" in r.stdout and r.stdout.strip().endswith("stopped"), r.stdout + r.stderr  # nothing it started outlives it
    out = root / "out"
    assert (out / "response.md").read_text().strip() == "The answer."  # the last message, not the narration
    assert "Reading first." in (out / "stream.jsonl").read_text()
    timing = json.loads((out / "timing.json").read_text())
    assert timing["skills_loaded"] == ["core-demo"] and timing["total_tokens"] in (5, 10) and timing["exit_code"] == 0
    if harness == "agents-dir":
        assert json.loads((root / "permission.txt").read_text()) == {"webfetch": "deny"}


STUB_ADAPTER = r"""
here="$(dirname "$0")"; out="$8"
if grep -q "You are grading" "$2"; then
  n="$(sed -n '/^## Assertions/,$p' "$2" | grep -c -E '^[0-9]+\. ')"
  python3 -c 'import json, sys; print(json.dumps([{"id": i + 1, "passed": True, "evidence": "e"} for i in range(int(sys.argv[1]))]))' "$n" > "$out/response.md"
  exit 0
fi
cd "$4" && echo made > made.md
echo "{\"total_tokens\": 1, \"duration_ms\": 1, \"cost_usd\": null, \"skills_loaded\": [\"core-demo\"]}" > "$out/timing.json"
echo "I did it." > "$out/response.md"
"""


def test_the_grading_path_with_a_stub_grader_runs_in_the_container_and_a_stub_run_leaves_no_file_under_skills(environment, tmp_path, monkeypatch, capsys):
    """A whole event, run as a real one is (the container, the staging, the facts, the grading call), with a
    stub adapter as runner and grader: it writes into its run folder's scratch tree and nothing under skills/."""
    import json
    wb, skill, dep = demo_workbench(tmp_path)
    (skill / "evals" / "evals.json").write_text(json.dumps({"evals": [{"id": 1, "prompt": "Write made.md.", "assertions": ["made.md exists", "b"]}]}))
    (skill / "SKILL.md").write_text('---\nname: core-demo\nmetadata:\n  version: "0.1"\n---\n# demo\n')
    adapter = wb / "adapters" / "stub"
    adapter.mkdir(parents=True)
    (adapter / "eval.json").write_text(json.dumps({"skills_dir": ".stub/skills", "settings": [".stub"]}))
    (adapter / "run-prompt.sh").write_text(STUB_ADAPTER)
    (wb / "evals").mkdir()
    (wb / "evals" / "grading-prompt.md").write_text((REPO / "evals" / "grading-prompt.md").read_text())
    (wb / "evals" / "eval-gate.json").write_text(json.dumps({  # the measurement is open: a stub run is a trial
        "strong_model": "m", "strong_harness": "stub", "floor_model": "f", "floor_harness": "stub", "floor_pass_env": [],
        "strong_pass_env": [], "grader": "m", "threshold": 0.8, "strong_tolerance": 0.05, "measurement_version": 5,
        "measurement_floor": 5, "runs": 1}))
    monkeypatch.setattr(er, "ROOT", str(wb))
    monkeypatch.setattr(er.KIT, "ROOT", str(wb))
    monkeypatch.setattr(er, "GRADING_TEMPLATE", str(wb / "evals" / "grading-prompt.md"))
    monkeypatch.setattr(er, "LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.setattr(er.KIT, "LOCK_DIR", str(tmp_path / "locks"))
    before = sorted(str(p) for p in (wb / "skills").rglob("*"))
    assert er.main(["--skill", "core-demo"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["complete"] is True and out["evidence"]["written"] is False and out["evidence"]["lines"] == 3
    assert sorted(str(p) for p in (wb / "skills").rglob("*")) == before  # nothing under skills/
    assert (wb / out["evidence"]["scratch"]).is_file() and "/scratch/skills/core-demo/" in out["evidence"]["scratch"]
    run = wb / out["iteration_dir"] / "eval-1" / "with_skill"
    facts = (run / "facts.md").read_text()
    assert "created:\n- made.md" in facts and "fixture" in facts  # the facts block, read in a container with no network
    assert json.loads((run / "grading.json").read_text())["summary"]["pass_rate"] == 1.0
    assert json.loads((run / "timing.json").read_text())["invoked"] is True
