"""The hook runs the fast set with sized xdist workers (`-n "$workers"`); the test jobs of the workflow run pytest in parallel in shards
(pytest-xdist, `-n auto`), and the one required job `tests` runs none.

Offline. Reads the text of `.githooks/pre-commit` and `.github/workflows/checks.yml`.

Run: uv run --with pytest pytest scripts/tests/test_hook_parallel.py
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENV_PREFIX = "env -u GIT_DIR -u GIT_INDEX_FILE -u GIT_WORK_TREE -u GIT_PREFIX"


def job_block(name):
    """The text of one job of checks.yml, from its key to the next job's key."""
    text = (REPO / ".github" / "workflows" / "checks.yml").read_text()
    jobs = text[re.search(r"^jobs:\s*$", text, re.M).end():]
    names = re.findall(r"^  ([\w-]+):\s*$", jobs, re.M)
    blocks = re.split(r"^  [\w-]+:\s*$", jobs, flags=re.M)[1:]
    block = dict(zip(names, blocks))[name]
    # The comment above the next job's key falls at the end of this block: leave comments out.
    return "\n".join(line for line in block.splitlines() if not line.lstrip().startswith("#"))


def test_the_hook_runs_pytest_with_sized_xdist_workers_under_the_clean_git_environment():
    hook = (REPO / ".githooks" / "pre-commit").read_text()
    lines = hook.splitlines()
    index = [i for i, line in enumerate(lines) if "pytest -q" in line and "uv run" in line]
    assert len(index) == 1
    line = lines[index[0]]
    assert '-n "$workers"' in line and "-n auto" not in line and "--with pytest-xdist==3.8.0" in line
    assert "--with pytest==9.1.1" in line
    # the workers come from the slot helper, set before the run, and a bad value stops the hook with a message
    sizing = [l for l in lines if l.strip().startswith('workers="$(python3 scripts/test_slots.py --workers)"')]
    assert len(sizing) == 1 and "|| fail" in sizing[0] and lines.index(sizing[0]) < index[0]
    # The prefix that clears git's variables sits on the line before and continues onto the pytest line.
    previous = lines[index[0] - 1]
    assert previous.strip().startswith(ENV_PREFIX) and previous.endswith(" \\")  # no space after the backslash
    assert "python3 scripts/test_slots.py -- uv run" in line  # the run takes one of the machine's test slots first


def hook_problems(hook):
    """What is wrong with a text of the hook: the selection by default, the fast set missing, the workers not sized, a phase not timed."""
    code = [line for line in hook.splitlines() if not line.lstrip().startswith("#")]
    text = "\n".join(code)
    found = []
    fast = [l for l in code if "select_tests.py --files-from - --direct" in l]
    full = [l for l in code if "select_tests.py --files-from -)" in l]
    if len(fast) != 1 or len(full) != 1 or "--direct" in full[0]:
        found.append("the fast set and the full selection are not one line each")
    elif not ('"${WB_HOOK_FULL:-}" == "1"' in text and text.index("WB_HOOK_FULL") < text.index("--direct")):
        found.append("the selection is not behind WB_HOOK_FULL=1")
    if '-n "$workers"' not in text or "-n auto" in text or 'workers="$(python3 scripts/test_slots.py --workers)"' not in text:
        found.append("the workers are not sized by the slot helper")
    found += ["phase not timed: " + phase for phase in ("validate", "security scan", "tests") if 'phase_done "%s"' % phase not in text]
    return found


def test_the_hook_runs_the_fast_set_by_default_and_the_selection_only_when_asked():
    assert hook_problems((REPO / ".githooks" / "pre-commit").read_text()) == []


def test_vacuity_a_hook_that_runs_the_selection_by_default_or_does_not_size_the_workers_or_hides_a_phase_is_caught():
    hook = (REPO / ".githooks" / "pre-commit").read_text()
    assert hook_problems(hook) == []
    plants = {
        "the fast set is always the selection": hook.replace(" --files-from - --direct", " --files-from -"),
        "the selection is not behind the variable": hook.replace('"${WB_HOOK_FULL:-}" == "1"', '"${OTHER:-}" == "1"'),
        "the workers are auto": hook.replace('-n "$workers"', "-n auto"),
        "a phase is not timed": hook.replace('phase_done "security scan"', "true"),
    }
    for name, planted in plants.items():
        assert planted != hook, name
        assert hook_problems(planted), name


def test_the_hook_tells_a_missing_slot_from_pytests_own_exit_codes_and_reads_type_changes():
    hook = (REPO / ".githooks" / "pre-commit").read_text()
    assert "status -eq 75" in hook and "status -eq 3" not in hook  # 3 is pytest's internal error; the slot helper exits 75
    assert "--diff-filter=ACMRDT" in hook


def test_the_jobs_that_run_pytest_do_it_in_parallel_with_a_time_limit_and_the_aggregator_runs_none():
    # the shards run pytest through the launcher, so the command reads `shard_tests.py ... -- -q -n auto`
    for name, limit in (("python39", 40), ("tests-shard", 30)):
        block = job_block(name)
        assert re.search(r"^    timeout-minutes: %d\s*$" % limit, block, re.M), name
        assert "--with pytest-xdist==3.8.0" in block, name
        assert re.search(r"-q -n auto\b", block), name
        assert "--durations=40" in block, name
        assert "scripts/shard_tests.py" in block, name
    aggregator = job_block("tests")
    assert "pytest" not in aggregator and re.search(r"^    timeout-minutes: 5\s*$", aggregator, re.M)


def steps_of(text):
    """The steps of one workflow text (a job block, comments left out), each as its own text, from its `- name:` line to the next."""
    return ["      - name:" + chunk for chunk in re.split(r"^      - name:", text, flags=re.M)[1:]]


def flag_problems(text):
    """What is wrong with the pytest flags of the steps of a workflow text. A step that starts pytest through the launcher (the shards), or
    runs `pytest -q -n auto` (the nightly's Python 3.9 job), keeps `--assert=plain` (collecting without assertion rewriting is most of the
    collection time) and `--dist worksteal`; a step that runs the failures again (`--lf`) keeps neither and rewrites, since its point is the
    detail; the hook never has either."""
    found = []
    for step in steps_of(text):
        name = step.splitlines()[0].strip()
        if "--lf" in step:
            found += [name + ": the re-run has " + flag for flag in ("--assert=plain", "--dist worksteal", "-n auto") if flag in step]
        elif "shard_tests.py" in step or re.search(r"\bpytest -q -n auto\b", step):
            found += [name + ": no " + flag for flag in ("--assert=plain", "--dist worksteal") if flag not in step]
    return found


def test_the_ci_runs_collect_without_assertion_rewriting_and_steal_work_and_the_failure_reruns_keep_the_detail():
    # the three run steps of checks.yml (two in tests-shard, one in python39) and the two of the nightly: the flag sits right after `-n auto`
    checks = [job_block("tests-shard"), job_block("python39")]
    for block in checks:
        assert flag_problems(block) == []
    runs = [step for block in checks for step in steps_of(block) if "shard_tests.py" in step]
    assert len(runs) == 3 and all("-q -n auto --assert=plain --dist worksteal -o faulthandler_timeout=120" in step for step in runs)
    nightly = (REPO / ".github" / "workflows" / "nightly.yml").read_text()
    nightly = "\n".join(line for line in nightly.splitlines() if not line.lstrip().startswith("#"))
    assert flag_problems(nightly) == []
    assert len([step for step in steps_of(nightly) if "-q -n auto --assert=plain --dist worksteal" in step]) == 2
    assert "--reruns 3" in nightly and "-rfER" in nightly  # the nightly's own reruns and failure report stay
    # the failures again: two steps in the shards, one in python39, none of them with the flags
    assert len([step for block in checks for step in steps_of(block) if "--lf --lfnf=none" in step]) == 3


def test_the_hook_and_the_by_hand_command_keep_assertion_rewriting_and_the_default_schedule():
    hook = (REPO / ".githooks" / "pre-commit").read_text()
    assert "--assert=plain" not in hook and "worksteal" not in hook
    agents = (REPO / "AGENTS.md").read_text()
    assert "--assert=plain" in agents and "--dist worksteal" in agents  # the text that says where they apply


def test_vacuity_a_run_step_without_the_flags_or_a_rerun_with_them_is_caught():
    block = job_block("tests-shard")
    assert flag_problems(block) == []
    plants = {
        "no plain": block.replace("--assert=plain ", "", 1),
        "no worksteal": block.replace("--dist worksteal ", "", 1),
        "the re-run is plain": block.replace("pytest -q --lf --lfnf=none", "pytest -q --assert=plain --lf --lfnf=none", 1),
        "the re-run is parallel": block.replace("pytest -q --lf --lfnf=none", "pytest -q -n auto --lf --lfnf=none", 1),
    }
    for name, planted in plants.items():
        assert planted != block, name
        assert len(flag_problems(planted)) == 1, name


def test_the_tests_shards_have_the_whole_suite_mode_with_the_full_fuzz_and_a_longer_limit():
    block = job_block("tests-shard")
    assert re.search(r"^    timeout-minutes: 30\s*$", block, re.M)
    whole = block[block.index("- name: Scanner and provider tests, the whole suite"):block.index("- name: Selected scanner")]
    assert 'WB_FULL_FUZZ: "1"' in whole and "$(python3 scripts/test_dirs.py)" in whole
    assert "select_tests" not in whole  # the whole suite is not a selection
    assert "pytest-xdist==3.8.0" in whole and "-n auto" in whole and "--durations=40" in whole and "scripts/shard_tests.py" in whole


def test_the_selected_mode_runs_what_the_selector_prints_and_never_the_full_fuzz():
    block = job_block("tests-shard")
    selected = block[block.index("- name: Choose the tests"):block.index("- name: Scanner and provider tests")]
    run = block[block.index("- name: Selected scanner"):]
    assert 'python3 scripts/select_tests.py --base "$BASE_SHA"' in selected and "fetch-depth: 0" in block
    assert "test_dirs.py" not in selected and "WB_FULL_FUZZ" not in selected and "WB_FULL_FUZZ" not in run
    assert 'python scripts/shard_tests.py --shard "$SHARD/3"' in run and '$(cat "$RUNNER_TEMP/selected-tests.txt")' in run


def test_only_the_python39_job_leaves_out_the_javascript_only_interface_tests():
    assert 'WB_SKIP_JS_ONLY_TESTS: "1"' in job_block("python39")
    assert "WB_SKIP_JS_ONLY_TESTS" not in job_block("tests")
    assert "WB_SKIP_JS_ONLY_TESTS" not in job_block("tests-shard")
