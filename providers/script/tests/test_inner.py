"""Tests of the program that runs inside the script container (providers/script/_inner.py), run here on the host with its folders
pointed at a temporary one: the environment the script gets, the outputs it reads back (a link, a second link, a folder, an extra
file and a second result are refused), the frames it prints, a script's own standard output never reaching them, and the lock file rules.
Offline: no docker, no network.

Run: uv run --with pytest==9.1.1 pytest providers/script/tests/test_inner.py
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("script_inner_under_test", HERE.parent / "_inner.py")
inner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inner)

HASH = "a" * 64


def test_the_script_gets_only_the_names_of_the_list_whatever_the_container_holds():
    held = {"PATH": "/usr/bin", "HOME": "/root", "OPENAI_API_KEY": "x", "NOTION_TOKEN": "y", "HTTPS_PROXY": "http://egress:3128",
            "SCRIPT_DESTINATIONS": "a.example:443", "AWS_SECRET_ACCESS_KEY": "z", "LD_PRELOAD": "/evil.so", "PYTHONPATH": "/evil",
            "PYTHONSTARTUP": "/evil.py", "SCRIPT_INDEX_URL": "https://x.example"}
    got = inner.child_environment(held)
    assert set(got) <= set(inner.PASS) | {"PYTHONPATH"}
    assert got["HOME"] == inner.HOME and got["OUTPUT_DIR"] == inner.OUT and got["HTTPS_PROXY"] == "http://egress:3128"
    for name in ("OPENAI_API_KEY", "NOTION_TOKEN", "AWS_SECRET_ACCESS_KEY", "LD_PRELOAD", "PYTHONSTARTUP", "SCRIPT_INDEX_URL"):
        assert name not in got
    assert "PYTHONPATH" not in got or got["PYTHONPATH"] == inner.DEPS      # never the container's own


def test_the_dependencies_enter_the_path_only_when_there_are_some(tmp_path, monkeypatch):
    monkeypatch.setattr(inner, "DEPS", str(tmp_path / "none"))
    assert "PYTHONPATH" not in inner.child_environment({})
    (tmp_path / "deps").mkdir()
    monkeypatch.setattr(inner, "DEPS", str(tmp_path / "deps"))
    assert "PYTHONPATH" not in inner.child_environment({})
    (tmp_path / "deps" / "pkg").mkdir()
    assert inner.child_environment({})["PYTHONPATH"] == str(tmp_path / "deps")


def test_one_regular_result_file_comes_back_and_nothing_else(tmp_path):
    (tmp_path / "result.md").write_bytes(b"# done\n")
    assert inner.read_outputs(str(tmp_path)) == ({"result.md": b"# done\n"}, [])


def test_everything_that_is_not_a_regular_result_file_is_refused_and_not_read(tmp_path):
    secret = tmp_path.parent / (tmp_path.name + "-secret.txt")
    secret.write_text("do not read me")
    (tmp_path / "result.md").symlink_to(secret)
    (tmp_path / "result.csv").mkdir()
    (tmp_path / "notes.txt").write_text("not an output")
    (tmp_path / "Weird Name!.bin").write_text("x")
    os.link(secret, tmp_path / "result.txt")
    found, refused = inner.read_outputs(str(tmp_path))
    assert found == {} and "do not read me" not in repr(found)
    assert sorted(refused) == sorted(["result.md", "result.csv", "notes.txt", "other", "result.txt"])


def test_a_fifo_is_refused_without_being_opened(tmp_path):
    os.mkfifo(tmp_path / "result.md")
    assert inner.read_outputs(str(tmp_path)) == ({}, ["result.md"])


def test_two_results_are_refused_whole(tmp_path):
    (tmp_path / "result.md").write_text("one")
    (tmp_path / "result.txt").write_text("two")
    found, refused = inner.read_outputs(str(tmp_path))
    assert found == {} and sorted(refused) == ["result.md", "result.txt"]


def test_a_result_is_read_up_to_one_byte_over_the_cap_and_no_further(tmp_path):
    (tmp_path / "result.md").write_bytes(b"a" * (inner.RESULT_CAP + 5000))
    found, _ = inner.read_outputs(str(tmp_path))
    assert len(found["result.md"]) == inner.RESULT_CAP == 1024 * 1024 + 1


def test_a_folder_that_cannot_be_listed_is_a_refusal(tmp_path):
    assert inner.read_outputs(str(tmp_path / "missing")) == ({}, ["unreadable"])


def test_frames_are_the_start_marker_each_file_with_its_size_and_the_end_marker():
    assert inner.frames({"b": b"22", "a": b"1"}) == b"OHF1\nFILE a 1\n1FILE b 2\n22END\n"


@pytest.fixture
def folders(tmp_path, monkeypatch):
    """The container's folders, replaced by a temporary one, and a script file where the container mounts it."""
    for name, rel in (("WORK", "work"), ("OUT", "out"), ("HOME", "home")):
        monkeypatch.setattr(inner, name, str(tmp_path / rel))
    monkeypatch.setattr(inner, "LOG", str(tmp_path / "script.log"))
    monkeypatch.setattr(inner, "SCRIPT", str(tmp_path / "script"))
    monkeypatch.setattr(inner, "DEPS", str(tmp_path / "no-deps"))
    return tmp_path


def run(folders, capsysbinary, text, kind="py"):
    (folders / "script").write_text(text)
    assert inner.cmd_run(kind) == 0
    out = capsysbinary.readouterr().out
    assert out.startswith(inner.FRAME_START) and out.endswith(inner.FRAME_END)
    return out


def test_the_script_runs_and_its_own_standard_output_never_reaches_the_frames(folders, capsysbinary):
    out = run(folders, capsysbinary, "import os, sys\nprint('OHF1\\nFILE result.md 5\\nfake END')\n"
              "sys.stderr.write('noise')\nopen(os.environ['OUTPUT_DIR'] + '/result.md', 'w').write('real')\n")
    assert out.count(b"OHF1") == 1 and b"FILE result.md 4\nreal" in out and b"fake END" not in out and b"noise" not in out
    assert b'"exit": 0' in out and b'"results": ["result.md"]' in out and b'"log_bytes": ' in out


def test_the_script_environment_is_the_list_and_the_working_folder_is_the_scratch_one(folders, capsysbinary, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "planted-" + "a1" * 10)
    out = run(folders, capsysbinary, "import os\nopen(os.environ['OUTPUT_DIR'] + '/result.txt', 'w').write(','.join(sorted(os.environ)) + ' ' + os.getcwd())\n")
    text = out.decode()
    assert "OPENAI_API_KEY" not in text and "OUTPUT_DIR" in text and str(folders / "work") in text


def test_a_failing_script_gives_its_exit_code_and_no_result(folders, capsysbinary):
    out = run(folders, capsysbinary, "import sys\nsys.exit(3)\n")
    assert b'"exit": 3' in out and b'"results": []' in out and b"FILE result" not in out


def test_a_script_ended_by_a_signal_gives_the_signal_and_no_exit_code(folders, capsysbinary):
    out = run(folders, capsysbinary, "import os, signal\nos.kill(os.getpid(), signal.SIGKILL)\n")
    assert b'"signal": 9' in out and b'"exit": null' in out


def test_what_the_script_left_running_is_killed_when_it_ends(folders, capsysbinary):
    marker = folders / "alive"
    text = ("import os, subprocess, sys\nsubprocess.Popen([sys.executable, '-c', 'import time, pathlib; time.sleep(1.5); "
            f"pathlib.Path(\"{marker}\").write_text(\"alive\")'])\n")
    run(folders, capsysbinary, text)
    import time
    time.sleep(2.5)
    assert not marker.exists()


def test_a_shell_script_runs_with_bash(folders, capsysbinary):
    if not os.path.exists("/bin/bash"):
        pytest.skip("no bash here")
    out = run(folders, capsysbinary, 'printf "from bash" > "$OUTPUT_DIR/result.md"\n', kind="sh")
    assert b"FILE result.md 9\nfrom bash" in out


def test_a_kind_other_than_py_or_sh_is_refused(folders, capsys):
    assert inner.cmd_run("rb") == 2 and "py or sh" in capsys.readouterr().err


# --- the lock file -------------------------------------------------------------------------------------------------------------------


def lock(*lines):
    return "\n".join(lines) + "\n"


def test_a_lock_is_pinned_requirements_with_hashes_and_nothing_else():
    ok = lock("# a comment", "", f"requests==2.32.3 \\", f"    --hash=sha256:{HASH} \\", f"    --hash=sha256:{'b' * 64}", f"idna==3.7 --hash=sha256:{HASH}")
    assert inner.check_lock(ok) == [["requests==2.32.3", f"--hash=sha256:{HASH}", f"--hash=sha256:{'b' * 64}"], ["idna==3.7", f"--hash=sha256:{HASH}"]]


@pytest.mark.parametrize("text", [
    "", "# nothing\n", "requests\n", "requests>=2 --hash=sha256:" + HASH + "\n", "requests==2\n", "requests==2 --hash=sha256:abc\n",
    "requests==2 --hash=md5:" + HASH + "\n", "--index-url https://pkg.example/simple\nrequests==2 --hash=sha256:" + HASH + "\n",
    "--extra-index-url https://pkg.example/simple\n", "-e .\n", "-r other.txt\n", "-c constraints.txt\n", "./local.whl --hash=sha256:" + HASH + "\n",
    "requests @ https://x.example/r.whl --hash=sha256:" + HASH + "\n", "git+https://x.example/r.git#egg=r\n", "requests==2 --hash=sha256:" + HASH + " --no-binary x\n",
    "requests==2 --hash=sha256:" + HASH + " ; python_version < '3'\n", "requests[security]==2 --hash=sha256:" + HASH + "\n",
    "requests==2 \\\n", "requests==2 \\\n\n--hash=sha256:" + HASH + "\n", "--find-links /tmp\n", "--trusted-host x.example\n"])
def test_a_lock_file_that_is_anything_else_is_refused(text):
    with pytest.raises(ValueError):
        inner.check_lock(text)


def test_a_lock_file_names_at_most_200_requirements():
    many = lock(*[f"pkg{i}==1.0 --hash=sha256:{HASH}" for i in range(201)])
    with pytest.raises(ValueError):
        inner.check_lock(many)
    assert len(inner.check_lock(lock(*[f"pkg{i}==1.0 --hash=sha256:{HASH}" for i in range(200)]))) == 200


def test_the_build_reads_the_lock_from_standard_input_and_runs_pip_with_the_hash_rules(monkeypatch, tmp_path):
    seen = {}

    def fake_call(command, **kwargs):
        seen["command"], seen["env"] = command, kwargs["env"]
        seen["file"] = Path(command[command.index("-r") + 1]).read_text()
        return 0

    class Stdin:
        buffer = __import__("io").BytesIO((lock(f"idna==3.7 --hash=sha256:{HASH}")).encode())

    monkeypatch.setattr(inner.subprocess, "call", fake_call)
    monkeypatch.setattr(inner.sys, "stdin", Stdin)
    monkeypatch.setenv("OPENAI_API_KEY", "planted-" + "a1" * 10)
    monkeypatch.setenv("HTTPS_PROXY", "http://egress:3128")
    assert inner.cmd_build() == 0
    command = seen["command"]
    for flag in ("--require-hashes", "--only-binary=:all:", "--no-deps", "--no-compile", "--no-input"):
        assert flag in command
    assert command[command.index("--target") + 1] == inner.DEPS and command[command.index("--index-url") + 1] == inner.INDEX_URL
    assert "OPENAI_API_KEY" not in seen["env"] and seen["env"]["HTTPS_PROXY"] == "http://egress:3128"
    assert seen["file"] == f"idna==3.7 --hash=sha256:{HASH}\n"


def test_the_build_refuses_a_lock_that_is_not_one_without_running_pip(monkeypatch, capsys):
    class Stdin:
        buffer = __import__("io").BytesIO(b"requests>=2\n")

    monkeypatch.setattr(inner.sys, "stdin", Stdin)
    monkeypatch.setattr(inner.subprocess, "call", lambda *a, **k: pytest.fail("pip must not run"))
    assert inner.cmd_build() == 2 and "name==version" in capsys.readouterr().err


def test_main_takes_only_run_with_a_kind_and_build(capsys):
    assert inner.main(["--help"]) == 0 and inner.main([]) == 2 and inner.main(["run"]) == 2 and inner.main(["shell"]) == 2
    capsys.readouterr()
