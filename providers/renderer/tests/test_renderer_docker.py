"""The host side: the container's limits, the job folder, what is read back from the container as untrusted, the image, the build and
the pin. A fake docker stands in for the client (providers/transcriber's pattern); the end-to-end tests make it run the container's
entry point on the host with a local Chromium. Every limit of the container has a test named after it."""
from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

import renderer_kit as K
import docker_kit as DK
import _docker as D
import _browser as B
from _text import Refusal

needs_all = pytest.mark.skipif(not (K.HAVE_FFMPEG and K.BROWSER), reason=K.SKIP_MEDIA + "; " + K.SKIP_BROWSER)


@pytest.fixture
def world(tmp_path):
    (tmp_path / "home").mkdir()
    return DK.World(tmp_path)


def sample_argv(**over):
    args = dict(job_dir="/s/job/in", out_dir="/s/job/out", recording="/s/rec.mp4", memory_mb=6144, cpus=4, scratch_mb=2048, deadline=1000, platform="linux")
    args.update(over)
    return D.container_argv("openhora-renderer-abc", "sha256:" + "cd" * 32, ["--result", "/out/result.json", "selfcheck"], **args)


# ---------------------------------------------------------------- the limits of the container, one test each

def test_the_container_has_no_network_a_read_only_root_no_capability_and_no_new_privileges():
    argv = sample_argv()
    assert argv[:3] == ["docker", "run", "--rm"]
    assert argv[argv.index("--network") + 1] == "none" and "--read-only" in argv
    assert argv[argv.index("--cap-drop") + 1] == "ALL" and argv[argv.index("--security-opt") + 1] == "no-new-privileges"
    for flag in ("--privileged", "--cap-add", "--device", "--pid", "--ipc", "--userns", "--net", "host", "-e", "--env", "--env-file", "--volumes-from"):
        assert flag not in argv, flag


def test_the_container_is_limited_in_processes_memory_swap_and_cpus_and_has_an_init():
    argv = sample_argv(memory_mb=4096, cpus=3)
    assert argv[argv.index("--pids-limit") + 1] == str(D.PIDS_LIMIT)
    assert argv[argv.index("--memory") + 1] == "4096m" and argv[argv.index("--memory-swap") + 1] == "4096m"     # no swap beyond the memory
    assert argv[argv.index("--cpus") + 1] == "3" and "--init" in argv


def test_the_scratch_and_tmp_are_memory_backed_with_no_exec_no_suid_no_devices():
    argv = sample_argv(scratch_mb=1500)
    tmpfs = [argv[i + 1] for i, a in enumerate(argv) if a == "--tmpfs"]
    assert len(tmpfs) == 2 and all("noexec" in t and "nosuid" in t and "nodev" in t for t in tmpfs)
    assert any(t.startswith("/scratch:") and "size=1500m" in t for t in tmpfs) and any(t.startswith("/tmp:") for t in tmpfs)


def test_the_image_is_never_pulled_is_run_by_its_id_and_is_labelled_for_reaping():
    argv = sample_argv()
    assert argv[argv.index("--pull") + 1] == "never"
    image_at = argv.index("sha256:" + "cd" * 32)
    assert argv[image_at + 1:] == ["--result", "/out/result.json", "selfcheck"]
    assert argv[argv.index("--name") + 1] == "openhora-renderer-abc"
    labels = [argv[i + 1] for i, a in enumerate(argv) if a == "--label"]
    assert "org.openhora.renderer=1" in labels and "org.openhora.renderer.deadline=1000" in labels


def test_exactly_three_folders_are_mounted_the_recording_and_the_job_read_only_the_output_read_write():
    argv = sample_argv()
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
    assert mounts == ["/s/rec.mp4:/in/recording:ro", "/s/job/in:/job:ro", "/s/job/out:/out:rw"]
    assert "--mount" not in argv
    assert [argv[i + 1] for i, a in enumerate(argv) if a == "-v"] != [] and not any("--tmpfs" == a for a in argv[argv.index("-v"):argv.index("sha256:" + "cd" * 32)])
    no_recording = sample_argv(recording=None)
    assert [no_recording[i + 1] for i, a in enumerate(no_recording) if a == "-v"] == ["/s/job/in:/job:ro", "/s/job/out:/out:rw"]


def test_on_linux_the_container_runs_as_the_callers_numeric_user_elsewhere_the_image_user():
    assert sample_argv(platform="linux")[sample_argv(platform="linux").index("--user") + 1] == "%d:%d" % (os.getuid(), os.getgid())
    assert "--user" not in sample_argv(platform="darwin")


@pytest.mark.parametrize("bad", ["relative/path.mp4", "/a:b/c.mp4", "/a/b\nc.mp4", "/a/b\x00c", "/a/b\x1bc"])
def test_a_colon_a_control_character_or_a_relative_path_in_a_mounted_path_is_refused(bad):
    with pytest.raises(Refusal) as e:
        sample_argv(recording=bad)
    assert e.value.code == "bad_mount_path"
    with pytest.raises(Refusal):
        sample_argv(job_dir=bad)


def test_a_mounted_recording_with_a_colon_is_a_usage_error_and_no_container_starts(world, tmp_path):
    odd = tmp_path / "a:b.mp4"
    odd.write_bytes(b"x")
    rc, out, err = world.host("analyse", "--in", odd)
    assert rc == 2 and err.startswith("refused: bad_mount_path") and world.runs() == []


def test_a_recording_that_is_a_link_or_a_folder_is_not_mounted(world, tmp_path):
    real = tmp_path / "real.mp4"
    real.write_bytes(b"x")
    link = tmp_path / "link.mp4"
    os.symlink(real, link)
    for bad in (link, tmp_path, tmp_path / "missing.mp4"):
        rc, out, err = world.host("analyse", "--in", bad)
        assert rc == 1 and err.startswith("refused: input_unreadable recording"), (bad, err)
    assert world.runs() == []


def test_no_variable_of_the_host_reaches_the_docker_client_but_the_few_it_needs(world):
    rc, out, err = world.host("--check", env={name: "planted" for name in ("SECRET_API_TOKEN", "AWS_ACCESS_KEY_ID", "OPENAI_API_KEY")})
    assert rc == 0, err
    seen = set().union(*[set(c["env"]) for c in world.calls()])
    assert not {"SECRET_API_TOKEN", "AWS_ACCESS_KEY_ID", "OPENAI_API_KEY", "OPENHORA_STATE_DIR"} & seen
    assert seen <= set(D.DOCKER_CLIENT_ENV) | {"__CF_USER_TEXT_ENCODING", "PWD", "SHLVL", "_", "LC_CTYPE", "LANG"}


def test_the_cpus_are_clamped_to_the_daemons_and_the_memory_and_scratch_to_their_bounds(world, tmp_path):
    world.cfg["ncpu"] = 2
    world.cfg["run"] = "files"
    world.cfg["files"] = {"result.json": {"text": json.dumps({"ok": True})}}
    world.save()
    rc, out, err = world.host("check", "--edl", K.write_json(tmp_path / "e.json", {}), "--beats", K.write_json(tmp_path / "b.json", {}),
                              "--vocabulary", K.VOCABULARY, "--cpus", "99", "--memory-mb", "99999999", "--scratch-mb", "1")
    argv = world.runs()[0]["argv"]
    assert argv[argv.index("--cpus") + 1] == "2" and argv[argv.index("--memory") + 1] == "%dm" % D.MAX_MEMORY_MB
    assert any(t.startswith("/scratch:rw") and "size=64m" in t for t in (argv[i + 1] for i, a in enumerate(argv) if a == "--tmpfs"))
    world.host("check", "--edl", tmp_path / "e.json", "--beats", tmp_path / "b.json", "--vocabulary", K.VOCABULARY, "--memory-mb", "10")
    assert world.runs()[1]["argv"][world.runs()[1]["argv"].index("--memory") + 1] == "%dm" % D.MIN_MEMORY_MB


def test_the_daemon_must_be_local(world):
    for host in ("tcp://10.0.0.5:2375", "ssh://me@server"):
        rc, out, err = world.host("--check", env={"DOCKER_HOST": host})
        assert rc == 3 and err.startswith("refused: docker_daemon_not_local"), err
    world.cfg["context"] = "tcp://remote:2376"
    world.save()
    rc, out, err = world.host("--check")
    assert rc == 3 and "docker_daemon_not_local" in err
    assert world.runs() == []


def test_a_stopped_daemon_or_a_missing_docker_is_not_configured(world, tmp_path):
    world.cfg["down"] = True
    world.save()
    rc, out, err = world.host("--check")
    assert rc == 3 and err.startswith("refused: docker_not_answering") and "start the Docker daemon" in err
    rc, out, err = world.host("--check", env={"PATH": "/usr/bin:/bin"})
    assert rc == 3 and err.startswith("refused: docker_missing")


# ---------------------------------------------------------------- the image

def test_a_missing_stale_or_swapped_image_is_not_configured_and_no_container_starts(world, tmp_path):
    world.cfg["images"] = {}
    world.save()
    rc, out, err = world.host("--check")
    assert rc == 3 and err.startswith("refused: image_not_built") and "ffmpeg.py build --confirmed" in err
    world.install_image(definition="0" * 64)
    world.save()
    rc, out, err = world.host("--check")
    assert rc == 3 and err.startswith("refused: image_stale")
    world.install_image()
    world.cfg["images"][D.image_tag()]["Id"] = "sha256:" + "ee" * 32                  # the tag now points at another image than the recorded one
    world.save()
    rc, out, err = world.host("--check")
    assert rc == 3 and err.startswith("refused: image_not_recorded")
    assert world.runs() == []


def test_the_definition_covers_the_modules_templates_fonts_and_data_and_not_the_host_side_or_the_tests():
    files = D.definition_files()
    assert {"Dockerfile", ".dockerignore", "_inner.py", "_render.py", "_cdp.py", "_fetch_browser.py", "templates/keyword.html", "templates/pins.json",
            "assets/fonts/allowlist.json", "browser-pin.json", "renderer-presets.json"} <= set(files)
    assert not any(f in files for f in ("ffmpeg.py", "_docker.py", "_browser.py", "README.md")) and not any(f.startswith("tests/") for f in files)


def test_changing_a_template_or_a_module_changes_the_image_tag(tmp_path):
    copy = tmp_path / "r"
    import shutil
    shutil.copytree(K.RENDERER, copy, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    before = D.image_tag(str(copy))
    (copy / "templates" / "list.html").write_text((copy / "templates" / "list.html").read_text() + " ")
    assert D.image_tag(str(copy)) != before
    middle = D.image_tag(str(copy))
    (copy / "_media.py").write_text((copy / "_media.py").read_text() + "\n# x\n")
    assert D.image_tag(str(copy)) != middle
    last = D.image_tag(str(copy))
    (copy / "_docker.py").write_text((copy / "_docker.py").read_text() + "\n# x\n")      # the host side is not in the image
    assert D.image_tag(str(copy)) == last


def test_check_runs_the_images_self_check_and_reports_the_sandbox_it_has(world):
    rc, out, err = world.host("--check")
    if not K.BROWSER:
        pytest.skip(K.SKIP_BROWSER)
    assert rc == 0, err
    assert out["ok"] and out["image"]["tag"] == D.image_tag() and out["selfcheck"]["ffmpeg"].startswith("ffmpeg") and out["selfcheck"]["browser"]
    assert out["daemon"] == {"cpus": 8, "architecture": "aarch64"} and out["browser_sandbox"] == "on"      # on the host a browser keeps its sandbox
    [run] = world.runs()
    assert run["argv"][-3:] == ["--result", "/out/result.json", "selfcheck"]


# ---------------------------------------------------------------- the build and the pin

def pin_with_sha(tmp_path):
    pin = json.loads((K.RENDERER / "browser-pin.json").read_text())
    for spec in pin["platforms"].values():
        spec["sha256"] = "a" * 64
    return pin


def test_build_is_the_persons_command_needs_the_sha256_and_downloads_nothing_itself(world):
    rc, out, err = world.host("build")
    assert rc == 2 and "--confirmed" in err and world.calls() == []
    rc, out, err = world.host("build", "--confirmed")
    assert rc == 3 and err.startswith("refused: pin_incomplete") and "pin-browser --confirmed" in err and not [c for c in world.calls() if c["argv"][:1] == ["build"]]
    rc, out, err = world.host("build", "--dry-run")
    assert rc == 0 and out["dry_run"] is True and out["chrome_sha256_pinned"] is False and out["platform"] == "linux-arm64"
    command = out["command"]
    assert command[:2] == ["docker", "build"] and "--pull" not in command and any(a.startswith("CHROME_URL=https://storage.googleapis.com/chrome-for-testing-public/") for a in command)
    assert [c for c in world.calls() if c["argv"][:1] == ["build"]] == []


def test_a_confirmed_build_with_a_pinned_archive_records_the_image_and_passes_the_pin_as_build_arguments(world, tmp_path, monkeypatch):
    world.cfg["images"] = {}
    world.save()
    (world.state / "renderer" / "image.json").unlink()
    pin = pin_with_sha(tmp_path)
    monkeypatch.setattr(B, "load_pin", lambda path=None: pin)
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(world.state))
    monkeypatch.setenv("DOCKER_CONFIG", str(world.config))
    monkeypatch.setenv("PATH", "%s:%s" % (world.bin, os.environ["PATH"]))
    result = D.build(pin, "linux-arm64", confirmed=True, dry_run=False)
    assert result["ok"] and result["image"] == D.image_tag()
    record = json.loads((world.state / "renderer" / "image.json").read_text())
    assert record["image_tag"] == D.image_tag() and record["chrome_version"] == "155.0.8059.39" and stat.S_IMODE((world.state / "renderer" / "image.json").stat().st_mode) == 0o600
    built = json.loads((world.config / "fake.json").read_text())["built_with"]
    assert built["CHROME_SHA256"] == "a" * 64 and built["CHROME_SIZE"] == "124553121" and built["CHROME_MD5"] == "1b40e7a8dfd195ccc27a9608d516ff75"
    assert D.check_image()["tag"] == D.image_tag()


def test_a_failed_build_records_nothing(world, tmp_path, monkeypatch):
    world.cfg["images"] = {}
    world.cfg["build_rc"] = 1
    world.save()
    (world.state / "renderer" / "image.json").unlink()
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(world.state))
    monkeypatch.setenv("DOCKER_CONFIG", str(world.config))
    monkeypatch.setenv("PATH", "%s:%s" % (world.bin, os.environ["PATH"]))
    with pytest.raises(Refusal) as e:
        D.build(pin_with_sha(tmp_path), "linux64", confirmed=True, dry_run=False)
    assert e.value.code == "build_failed" and not (world.state / "renderer" / "image.json").exists()


def test_the_dockerfile_pins_what_it_says_it_pins():
    text = (K.RENDERER / "Dockerfile").read_text()
    assert "FROM debian@sha256:" in text and ":latest" not in text and "snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}" in text
    assert "debian-security/${DEBIAN_SNAPSHOT}" in text and "ARG DEBIAN_SNAPSHOT=2026" in text
    assert "_fetch_browser.py" in text and "CHROME_SHA256" in text and 'USER 10001:10001' in text and 'ENTRYPOINT ["python3", "-I", "/opt/renderer/_inner.py"]' in text
    assert "org.openhora.definition" in text and "RENDERER_IN_CONTAINER=1" in text and "/etc/openhora-renderer-image" in text
    assert "--no-sandbox" not in text.replace("with --no-sandbox INSIDE", "")            # the flag lives in the driver, not in the image definition
    ignore = (K.RENDERER / ".dockerignore").read_text().split("\n")
    assert ignore[0] == "*" and "!templates" in ignore and "!assets" in ignore and "tests" not in "".join(ignore).replace("!", "")
    sha = lambda f: f in text
    assert sha("ca-certificates") and not any(x in text for x in ("curl ", "wget ", "git clone", "apt-get upgrade"))


# ---------------------------------------------------------------- reading the container's output as untrusted

def run_with_files(world, tmp_path, files, rc=0):
    world.cfg["run"] = "files"
    world.cfg["files"] = files
    world.cfg["rc"] = rc
    world.save()
    return world.host("check", "--edl", K.write_json(tmp_path / "e.json", {}), "--beats", K.write_json(tmp_path / "b.json", {}), "--vocabulary", K.VOCABULARY)


def test_a_result_that_is_missing_garbage_or_a_link_is_a_closed_failure(world, tmp_path):
    cases = [({}, "container_failed"), ({"result.json": {"text": "not json"}}, "container_failed"), ({"result.json": {"text": "[1]"}}, "container_failed"),
             ({"result.json": {"kind": "link", "target": "/etc/passwd"}}, "container_failed"), ({"result.json": {"kind": "fifo"}}, "container_failed"),
             ({"result.json": {"kind": "big", "size": D.MAX_RESULT_BYTES + 1}}, "container_failed")]
    for files, code in cases:
        rc, out, err = run_with_files(world, tmp_path, files)
        assert rc == 1 and (err.startswith("refused: " + code) or err.startswith("refused: container_")), (files, err)


def test_what_the_container_leaves_in_its_output_folder_is_looked_at_before_it_is_read(world, tmp_path):
    rc, out, err = run_with_files(world, tmp_path, {"result.json": {"text": '{"ok": true}'}, "x": {"kind": "link", "target": "/etc/hosts"}})
    assert rc == 1 and err.startswith("refused: container_left_non_regular_file")
    rc, out, err = run_with_files(world, tmp_path, {"result.json": {"text": '{"ok": true}'}, "f": {"kind": "fifo"}})
    assert rc == 1 and err.startswith("refused: container_left_non_regular_file")
    many = {"result.json": {"text": '{"ok": true}'}}
    many.update({"f%d" % k: {"text": "x"} for k in range(D.MAX_OUT_ENTRIES + 1)})
    rc, out, err = run_with_files(world, tmp_path, many)
    assert rc == 1 and err.startswith("refused: container_left_too_much")


def test_a_refusal_inside_the_container_is_the_same_refusal_outside_with_the_same_exit_code_and_only_closed_words(world, tmp_path):
    refusal = {"ok": False, "code": "credential_shaped", "field": "edl.words[4]", "problems": [{"beat": 3, "field": "text", "code": "text_too_long"}]}
    rc, out, err = run_with_files(world, tmp_path, {"result.json": {"text": json.dumps(refusal)}}, rc=1)
    assert rc == 1 and err.splitlines()[0] == "refused: credential_shaped edl.words[4]" and "beat 3 text text_too_long" in err and out["code"] == "credential_shaped"
    rc, out, err = run_with_files(world, tmp_path, {"result.json": {"text": json.dumps({"ok": False, "code": "browser_not_found", "field": "browser"})}}, rc=3)
    assert rc == 3
    hostile = {"ok": False, "code": "ghp_" + "x" * 36 + " and more text", "field": "a secret that is long and has spaces; rm -rf /" * 3, "problems": []}
    rc, out, err = run_with_files(world, tmp_path, {"result.json": {"text": json.dumps(hostile)}}, rc=1)
    assert rc == 1 and err.startswith("refused: container_failed") and "ghp_" not in err and "rm -rf" not in err and "ghp_" not in json.dumps(out)


def test_a_container_that_died_without_a_result_is_named_as_killed_when_it_was_out_of_memory(world, tmp_path):
    rc, out, err = run_with_files(world, tmp_path, {}, rc=137)
    assert rc == 1 and err.startswith("refused: container_killed")


def test_a_file_copied_out_is_capped_hashed_and_never_follows_a_link(tmp_path):
    src = tmp_path / "a.bin"
    src.write_bytes(b"hello")
    import hashlib
    good = hashlib.sha256(b"hello").hexdigest()
    dest = tmp_path / "d" / "out.bin"
    assert D.copy_out(str(src), str(dest), max_bytes=100, mode=0o400, expect_sha256=good, exclusive=True) == "written"
    assert stat.S_IMODE(dest.stat().st_mode) == 0o400
    assert D.copy_out(str(src), str(dest), max_bytes=100, mode=0o400, expect_sha256=good, exclusive=True) == "replayed"
    other = tmp_path / "b.bin"
    other.write_bytes(b"other")
    with pytest.raises(Refusal) as e:
        D.copy_out(str(other), str(dest), max_bytes=100, mode=0o400, exclusive=True)
    assert e.value.code == "name_collision" and dest.read_bytes() == b"hello"
    with pytest.raises(Refusal) as e:
        D.copy_out(str(src), str(tmp_path / "x"), max_bytes=3, mode=0o600)
    assert e.value.code == "container_file_not_regular"
    with pytest.raises(Refusal) as e:
        D.copy_out(str(src), str(tmp_path / "y"), max_bytes=100, mode=0o600, expect_sha256="0" * 64)
    assert e.value.code == "container_file_differs" and not (tmp_path / "y").exists()
    link = tmp_path / "link"
    os.symlink(src, link)
    with pytest.raises(Refusal):
        D.copy_out(str(link), str(tmp_path / "z"), max_bytes=100, mode=0o600)
    os.mkfifo(tmp_path / "fifo")
    with pytest.raises(Refusal):
        D.copy_out(str(tmp_path / "fifo"), str(tmp_path / "w"), max_bytes=100, mode=0o600)
    assert not [p for p in (tmp_path / "d").iterdir() if p.name.startswith(".copy-")]       # no temporary file is left


# ---------------------------------------------------------------- the timeout, a stop, and what a killed run leaves

def test_a_container_past_its_timeout_is_removed_by_name_after_the_client_is_killed(world, tmp_path, monkeypatch):
    world.cfg["run"] = "sleep"
    world.save()
    monkeypatch.setenv("DOCKER_CONFIG", str(world.config))
    monkeypatch.setenv("PATH", "%s:%s" % (world.bin, os.environ["PATH"]))
    argv = sample_argv()
    started = time.time()
    with pytest.raises(Refusal) as e:
        D.run_container(argv, "openhora-renderer-abc", 1.5)
    assert e.value.code == "time_limit" and time.time() - started < 30
    calls = [c["argv"] for c in world.calls()]
    assert ["rm", "-f", "openhora-renderer-abc"] in calls


def test_a_stop_signal_removes_the_container_and_the_job_folder(world, tmp_path):
    world.cfg["run"] = "sleep"
    world.save()
    proc = subprocess.Popen([sys.executable, str(K.HOST), "check", "--edl", K.write_json(tmp_path / "e.json", {}), "--beats", K.write_json(tmp_path / "b.json", {}),
                             "--vocabulary", str(K.VOCABULARY)], env={**os.environ, **world.env()}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for _ in range(100):
        if world.runs():
            break
        time.sleep(0.1)
    assert world.runs()
    name = world.runs()[0]["argv"][world.runs()[0]["argv"].index("--name") + 1]
    proc.send_signal(signal.SIGTERM)
    proc.communicate(timeout=30)
    assert ["rm", "-f", name] in [c["argv"] for c in world.calls()]
    work = world.state / "renderer" / "work"
    assert not [p for p in work.iterdir() if p.name.startswith(D.JOB_PREFIX)]


def test_reap_removes_containers_past_their_deadline_and_old_job_folders_but_not_a_live_run(world, tmp_path):
    now = int(time.time())
    world.cfg["ps"] = "aaaaaaaaaaaa %d\nbbbbbbbbbbbb %d\ncccccccccccc \nnot-an-id 5\n" % (now - 10, now + 3600)
    world.save()
    work = world.state / "renderer" / "work"
    work.mkdir(parents=True, mode=0o700)
    old, young = work / (D.JOB_PREFIX + "old"), work / (D.JOB_PREFIX + "young")
    for p in (old, young):
        p.mkdir()
    os.utime(old, (now - 99999, now - 99999))
    rc, out, err = world.host("reap")
    assert rc == 0, err
    assert out["containers_removed"] == ["aaaaaaaaaaaa", "cccccccccccc"] and out["folders_removed"] == 1
    assert not old.exists() and young.exists()
    assert ["rm", "-f", "bbbbbbbbbbbb"] not in [c["argv"] for c in world.calls()]


def test_the_state_folders_are_private(world, tmp_path):
    (world.state).chmod(0o755)
    rc, out, err = world.host("reap")
    assert rc == 0 and stat.S_IMODE(world.state.stat().st_mode) == 0o700 and "now 0700" in err


# ---------------------------------------------------------------- end to end through the fake docker

@needs_all
def test_the_whole_host_side_end_to_end_with_the_entry_point_run_by_the_fake_docker(world, tmp_path):
    tr = K.build_transcript(K.SHORT_SENTENCES)
    src = tmp_path / "rec.mp4"
    K.make_source(src, tr)
    asset = tmp_path / "asset.png"
    K.make_asset(asset)
    (tmp_path / "post.md").write_text(K.SHORT_POST)
    transcript = K.write_json(tmp_path / "t.json", tr)
    rc, out, err = world.host("analyse", "--in", src, "--out", tmp_path / "analysis.json")
    assert rc == 0, err
    assert (tmp_path / "analysis.json").exists() and oct((tmp_path / "analysis.json").stat().st_mode & 0o777) == "0o600" and out["has_audio"] is True
    rc, out, err = world.host("base", "--transcript", transcript, "--analysis", tmp_path / "analysis.json", "--out", tmp_path / "edl.json")
    assert rc == 0, err
    rc, out, err = world.host("align", "--post", tmp_path / "post.md", "--transcript", transcript, "--checker", K.CHECKER, "--vocabulary", K.VOCABULARY,
                              "--out", tmp_path / "beats.json")
    assert rc == 0 and out["slots"] == ["beat3", "beat4"], err
    rc, out, err = world.host("check", "--edl", tmp_path / "edl.json", "--beats", tmp_path / "beats.json", "--vocabulary", K.VOCABULARY, "--platform-file", K.INSTAGRAM)
    assert rc == 0 and out["ok"], err
    render = ["render", "--edl", tmp_path / "edl.json", "--beats", tmp_path / "beats.json", "--in", src, "--out", tmp_path / "out", "--platform-file", K.INSTAGRAM,
              "--vocabulary", K.VOCABULARY, "--asset", "3=%s" % asset, "--asset", "4=%s" % asset, "--cover-out", tmp_path / "cover.png", "--cover-offset-ms", "1000", "--jobs", "2"]
    rc, dry, err = world.host(*render, "--dry-run")
    assert rc == 0 and dry["dry_run"] is True and dry["command"][:2] == ["docker", "run"] and not (tmp_path / "out").exists()
    before = len(world.runs())
    rc, out, err = world.host(*render)
    assert rc == 0, err
    path = Path(out["path"])
    assert path.parent == tmp_path / "out" and path.name == "render-%s.mp4" % out["sha256"][:12] and stat.S_IMODE(path.stat().st_mode) == 0o400
    assert out["image"]["id"] == "sha256:" + "cd" * 32 and "ffmpeg_argv" not in out and out["replayed"] is False and out["cover"]["path"] == str(tmp_path / "cover.png")
    assert (tmp_path / "cover.png").read_bytes()[:4] == b"\x89PNG"
    run = world.runs()[before]["argv"]
    assert run[run.index("--network") + 1] == "none" and [run[i + 1] for i, a in enumerate(run) if a == "-v"][0] == "%s:/in/recording:ro" % src
    again = world.host(*render)
    assert again[0] == 0 and again[1]["sha256"] == out["sha256"] and again[1]["replayed"] is True
    work = world.state / "renderer" / "work"
    assert not [p for p in work.iterdir() if p.name.startswith(D.JOB_PREFIX)]            # every job folder is gone
    rc, c, err = world.host("cover", "--in", path, "--offset-ms", "500", "--out", tmp_path / "c2.png")
    assert rc == 0 and (tmp_path / "c2.png").exists()
