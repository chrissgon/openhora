"""The hook and the two test jobs of the workflow run pytest in parallel (pytest-xdist, `-n auto`).

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


def test_the_hook_runs_pytest_with_xdist_under_the_clean_git_environment():
    lines = (REPO / ".githooks" / "pre-commit").read_text().splitlines()
    index = [i for i, line in enumerate(lines) if "pytest -q" in line and "uv run" in line]
    assert len(index) == 1
    line = lines[index[0]]
    assert "-n auto" in line and "--with pytest-xdist==3.8.0" in line
    assert "--with pytest==9.1.1" in line
    # The prefix that clears git's variables sits on the line before and continues onto the pytest line.
    previous = lines[index[0] - 1]
    assert previous.strip().startswith(ENV_PREFIX) and previous.endswith(" \\")  # no space after the backslash
    assert "python3 scripts/test_slots.py -- uv run" in line  # the run takes one of the machine's test slots first


def test_the_tests_and_python39_jobs_run_pytest_in_parallel_with_a_time_limit():
    for name, limit in (("tests", 45), ("python39", 25)):
        block = job_block(name)
        assert re.search(r"^    timeout-minutes: %d\s*$" % limit, block, re.M), name
        assert "--with pytest-xdist==3.8.0" in block, name
        assert re.search(r"pytest -q -n auto\b", block), name
        assert "--durations=20" in block, name


def test_the_tests_job_has_the_whole_suite_mode_with_the_full_fuzz_and_a_longer_limit():
    block = job_block("tests")
    assert re.search(r"^    timeout-minutes: 45\s*$", block, re.M)
    whole = block[block.index("- name: Scanner and provider tests, the whole suite"):]
    assert 'WB_FULL_FUZZ: "1"' in whole and "$(python3 scripts/test_dirs.py)" in whole
    assert "select_tests" not in whole  # the whole suite is not a selection
    assert "pytest-xdist==3.8.0" in whole and re.search(r"pytest -q -n auto\b", whole) and "--durations=20" in whole


def test_the_selected_mode_runs_what_the_selector_prints_and_never_the_full_fuzz():
    block = job_block("tests")
    selected = block[block.index("- name: Choose the tests"):block.index("- name: Scanner and provider tests, the whole suite")]
    assert 'python3 scripts/select_tests.py --base "$BASE_SHA"' in selected and "fetch-depth: 0" in block
    assert "test_dirs.py" not in selected and "WB_FULL_FUZZ" not in selected


def test_only_the_python39_job_leaves_out_the_javascript_only_interface_tests():
    assert 'WB_SKIP_JS_ONLY_TESTS: "1"' in job_block("python39")
    assert "WB_SKIP_JS_ONLY_TESTS" not in job_block("tests")
