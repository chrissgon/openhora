"""Offline tests of the optional keys of an evidence line: the run hash of eval_run.py (run_record_hash) and the
validation of "cost_usd" and "run_sha256" in a run line by eval_status.py. No model is called."""
import importlib.util
import os
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


er = load("eval_run_line_keys", "evals/eval_run.py")
es = load("eval_status_line_keys", "evals/eval_status.py")

TEST_ID = "20300102T030405Z-0a1b2c3d"
H = {c: c * 64 for c in "abcd"}


@pytest.fixture
def run_dir(tmp_path):
    folder = tmp_path / "run-1"
    (folder / "outputs").mkdir(parents=True)
    (folder / "cwd").mkdir()
    (folder / "prompt.md").write_text("the prompt\n")
    (folder / "facts.md").write_text("the facts\n")
    (folder / "outputs" / "response.md").write_text("the response\n")
    (folder / "cwd" / "a.txt").write_text("a file the run left\n")
    return folder


def test_the_run_hash_is_stable(run_dir):
    first = er.run_record_hash(str(run_dir))
    assert first == er.run_record_hash(str(run_dir)) and len(first) == 64


@pytest.mark.parametrize("rel", ["grading.json", "timing.json", "outputs/stream.jsonl", "regrade-1/grading.json"])
def test_what_a_regrading_does_not_read_leaves_the_run_hash_unchanged(run_dir, rel):
    first = er.run_record_hash(str(run_dir))
    path = run_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n")
    assert er.run_record_hash(str(run_dir)) == first


@pytest.mark.parametrize("rel", ["outputs/response.md", "cwd/a.txt"])
def test_one_byte_changed_in_what_a_regrading_reads_changes_the_run_hash(run_dir, rel):
    first = er.run_record_hash(str(run_dir))
    path = run_dir / rel
    data = bytearray(path.read_bytes())
    data[0] ^= 1
    path.write_bytes(bytes(data))
    assert er.run_record_hash(str(run_dir)) != first


def test_a_symbolic_link_inside_cwd_is_skipped(run_dir, tmp_path):
    first = er.run_record_hash(str(run_dir))
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside the run\n")
    os.symlink(outside / "secret.txt", run_dir / "cwd" / "link.txt")
    os.symlink(outside, run_dir / "cwd" / "linked-folder")
    os.symlink(run_dir / "cwd" / "missing", run_dir / "cwd" / "dangling")
    assert er.run_record_hash(str(run_dir)) == first
    shutil.rmtree(outside)
    assert er.run_record_hash(str(run_dir)) == first


def run_line(**changes):
    """A valid run line, built as test_eval_status.py builds one."""
    line = {"record": "run", "skill": "core-demo", "version": "1.0.0", "content_sha256": H["a"], "model": "s-model", "adapter": "h",
            "kind": "full", "test": TEST_ID, "date": "2030-01-02", "measurement_version": 5, "measurement_sha256": H["d"],
            "case": 1, "case_sha256": H["a"], "variant": "with", "outcome": "graded", "score": 0.5, "results": [1, 0]}
    line.update(changes)
    return line


def test_the_validator_accepts_a_run_line_with_cost_and_run_hash_and_one_with_neither():
    assert es.run_line_problems(run_line(cost_usd=0.15, run_sha256="0123456789abcdef" * 4)) == []
    assert es.run_line_problems(run_line(cost_usd=0)) == []
    assert es.run_line_problems(run_line()) == []


@pytest.mark.parametrize("change, why", [
    ({"cost_usd": -1}, "cost_usd must be a number, 0 or more"),
    ({"cost_usd": True}, "cost_usd must be a number, 0 or more"),
    ({"run_sha256": "abc"}, "run_sha256 must be 64 hexadecimal characters"),
])
def test_the_validator_refuses_a_cost_or_a_run_hash_outside_its_form(change, why):
    assert es.run_line_problems(run_line(**change)) == [why]


# --- package P2b: the CPU platform of a run, and where the image came from -----------------------------------------


def test_cpu_platform_is_an_optional_key_of_a_run_line_that_is_never_a_social_platform():
    assert "cpu_platform" in es.RUN_OPTIONAL and "platform" in es.RUN_OPTIONAL  # two keys: the social platform keeps its own
    for platform in ("linux/arm64", "linux/amd64", "linux/arm/v7"):
        assert es.run_line_problems(run_line(cpu_platform=platform)) == []
    assert es.run_line_problems(run_line()) == []  # the lines written before it have none


@pytest.mark.parametrize("value", ["arm64", "windows/amd64", "linux/", "", 5, None, "linux/arm64; rm"])
def test_a_cpu_platform_outside_its_form_is_refused(value):
    assert es.run_line_problems(run_line(cpu_platform=value)) == [
        "cpu_platform must be the CPU platform the run's container ran on, such as linux/arm64 or linux/amd64"]


def test_lines_of_a_social_platform_and_of_a_cpu_platform_do_not_mix():
    line = run_line(kind="partial", platform="chirp", cpu_platform="linux/amd64")
    assert es.run_line_problems(line) == []
    assert es.run_line_problems(run_line(platform="linux/amd64")) == ["platform must be a platform name",
                                                                       "a line of a platform's case runs in a partial test, with the skill only"][:1]


def test_a_run_lines_cpu_platform_must_be_the_image_platform_of_its_event_line():
    event = {"image_platform": "linux/amd64", "models": ["s-model"], "adapters": {"s-model": "h"}}
    message = "cpu_platform must equal the image_platform of the event line: the run ran in that image"
    about = lambda line: [p for p in es.run_line_problems(line, event) if p.startswith("cpu_platform")]  # the event is a stub: other keys differ
    assert about(run_line(cpu_platform="linux/amd64")) == []
    assert about(run_line(cpu_platform="linux/arm64")) == [message]
    assert about(run_line()) == []  # a line written before the key
