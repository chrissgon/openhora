"""The transcriber provider (providers/transcriber/whispercpp.py), offline: docker is a fake binary on PATH, the speech is
fictional, and no test starts a container, builds an image or reaches a network. One live test is skipped unless
OPENHORA_TRANSCRIBER_LIVE=1 and the image and the tiny model exist."""
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import wave

import pytest

import transcriber_kit as kit

PROVIDER_FILE = kit.PROVIDER_DIR / "whispercpp.py"
ID = "sha256:" + "a" * 64


def built(world, image_id=ID, record=True, labels=None):
    """The image as `build` leaves it: known to the fake docker, with the labels of this folder's definition, and recorded."""
    p = world.provider
    tag_, commit = p.dockerfile_pins()
    image = {"id": image_id, "labels": labels or {p.LABEL_DEFINITION: p.definition_hash(), p.LABEL_TAG: tag_, p.LABEL_COMMIT: commit}}
    world.fake.update(images={p.image_tag(): image})
    folder = world.state / "transcriber"
    folder.mkdir(mode=0o700, exist_ok=True)
    if record:
        (folder / p.BUILD_RECORD).write_text(json.dumps({"image_id": image_id}))
    elif (folder / p.BUILD_RECORD).exists():
        (folder / p.BUILD_RECORD).unlink()
    return image


def will_write(world, doc, exit_code=0, **extra):
    run = {"exit": exit_code, "write": {"transcript.json": json.dumps(doc), "input_duration.txt": "5.9\n",
                                         "audio_duration.txt": "5.88\n"}}
    run.update(extra)
    world.fake.update(run=run)


def transcribe(world, *extra, language="en", model="demo", mode=None):
    args = ["transcribe", "--in", str(world.input), "--model", model, "--language", language, "--out", str(world.out),
            "--models-dir", str(world.models)]
    if mode:
        args += ["--timestamps", mode]
    return world.provider.main(args + list(extra))


def stdout_json(capsys):
    return json.loads(capsys.readouterr().out)


# --- the container: every limit is in the command ------------------------------------------------------------------


def option(argv, flag):
    """The value that follows a flag."""
    return argv[argv.index(flag) + 1]


def test_the_exact_docker_command(provider):
    argv = provider.container_argv("openhora-whisper-x", ID, "/data/in.mp4", "/models/ggml-small.bin", "/data/work", threads=4,
                                   language="pt", mode="dtw", preset="small", max_seconds=180, memory_mb=2048, cpus=4,
                                   platform="darwin")
    assert argv == [
        "docker", "run", "--rm", "--init", "--pull", "never", "--name", "openhora-whisper-x",
        "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", "256", "--memory", "2048m", "--memory-swap", "2048m", "--cpus", "4",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m",
        "--tmpfs", "/scratch:rw,noexec,nosuid,nodev,size=256m,mode=1777",
        "-v", "/data/in.mp4:/in/input:ro", "-v", "/models/ggml-small.bin:/models/model.bin:ro", "-v", "/data/work:/out:rw",
        ID, "4", "pt", "dtw", "small", "180"]


def test_on_linux_the_container_runs_as_the_callers_ids(provider):
    argv = provider.container_argv("n", ID, "/i", "/m", "/o", threads=1, language="en", mode="word", preset=None,
                                   max_seconds=10, memory_mb=1024, cpus=1, platform="linux")
    assert option(argv, "--user") == f"{os.getuid()}:{os.getgid()}"
    assert argv[-5:] == ["1", "en", "word", "-", "10"]


def test_the_run_the_provider_starts_has_no_network_no_environment_and_three_mounts(world, capsys):
    built(world)
    will_write(world, kit.speech())
    assert transcribe(world) == 0
    (argv,) = world.fake.runs()
    assert option(argv, "--network") == "none" and "--read-only" in argv
    assert option(argv, "--cap-drop") == "ALL" and option(argv, "--security-opt") == "no-new-privileges"
    assert option(argv, "--memory") == option(argv, "--memory-swap") == "1536m"   # the model's limit, swap included
    assert option(argv, "--pids-limit") == "256" and option(argv, "--pull") == "never"
    for forbidden in ("-e", "--env", "--env-file", "--privileged", "--network=host", "-p", "--publish", "--volumes-from",
                      "--device", "--cap-add", "--pid", "--ipc", "--userns"):
        assert forbidden not in argv
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
    assert len(mounts) == 3
    assert [m for m in mounts if m.endswith(":rw")] == [m for m in mounts if m.endswith(":/out:rw")]   # one folder is writable
    assert any(m.endswith(":/in/input:ro") for m in mounts) and any(m.endswith(":/models/model.bin:ro") for m in mounts)
    assert ID in argv   # run by id: the tag could be pointed at another image


def test_the_docker_client_gets_no_credential_from_the_environment(world, monkeypatch):
    built(world)
    will_write(world, kit.speech())
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "NOTION_TOKEN", "PASSWORD"):
        monkeypatch.setenv(name, "fictional-secret-value")
    assert transcribe(world) == 0
    for call in world.fake.calls():
        assert not [n for n in call["env"] if re.search(r"KEY|TOKEN|SECRET|PASSWORD", n)], call["env"]


def test_the_provider_reads_no_secret_store():
    text = PROVIDER_FILE.read_text(encoding="utf-8")
    assert "resolver" not in text and "keychain" not in text.lower() and "getpass" not in text
    assert "environ[" not in text   # the environment is read only by name, through get() and the allow list


def test_a_dry_run_shows_the_command_and_calls_nothing(world, capsys):
    assert transcribe(world, "--dry-run") == 0
    out = stdout_json(capsys)
    assert out["dry_run"] is True and out["command"][:2] == ["docker", "run"] and "--network" in out["command"]
    assert world.fake.calls() == [] and not world.out.exists()


# --- the model: pinned, hashed before any run ----------------------------------------------------------------------


def test_a_model_that_differs_from_its_pin_is_refused_before_any_run(world, capsys):
    built(world)
    will_write(world, kit.speech())
    (world.models / "ggml-demo.bin").write_bytes(b"another file, same name")
    assert transcribe(world) == 1
    assert "pinned sha256" in capsys.readouterr().err
    assert world.fake.runs() == [] and not world.out.exists()


def test_a_model_without_a_pin_is_refused_until_it_is_pinned(world, capsys):
    built(world)
    (world.models / "ggml-later.bin").write_bytes(b"anything")
    assert transcribe(world, model="later") == 3
    assert "no pinned sha256" in capsys.readouterr().err
    assert world.fake.runs() == []


def test_a_missing_model_is_not_configured_and_an_unknown_one_is_a_usage_error(world, capsys):
    built(world)
    (world.models / "ggml-demo.bin").unlink()
    assert transcribe(world) == 3
    assert transcribe(world, model="nonesuch") == 2
    assert world.fake.runs() == []


def test_a_model_that_is_a_link_is_refused(world, tmp_path):
    built(world)
    target = tmp_path / "elsewhere.bin"
    target.write_bytes(b"fictional model weights")
    (world.models / "ggml-demo.bin").unlink()
    (world.models / "ggml-demo.bin").symlink_to(target)
    assert transcribe(world) == 3 and world.fake.runs() == []


# --- build: only with the person's word ----------------------------------------------------------------------------


def test_build_without_confirmed_is_refused_and_touches_nothing(world, capsys):
    assert world.provider.main(["build"]) == 2
    assert "--confirmed" in capsys.readouterr().err
    assert world.fake.calls() == [] and not (world.state / "transcriber").exists()


def test_a_build_dry_run_prints_the_command_and_calls_nothing(world, capsys):
    assert world.provider.main(["build", "--dry-run"]) == 0
    out = stdout_json(capsys)
    p = world.provider
    assert out["dry_run"] is True and out["image"] == p.image_tag() and out["command"][:2] == ["docker", "build"]
    assert f"DEFINITION_HASH={p.definition_hash()}" in out["command"] and world.fake.calls() == []


def test_a_confirmed_build_runs_docker_build_and_records_the_image(world, capsys):
    p = world.provider
    tag_, commit = p.dockerfile_pins()
    world.fake.update(build={"id": ID, "tag": tag_, "commit": commit})
    assert p.main(["build", "--confirmed"]) == 0
    out = stdout_json(capsys)
    assert out["image_id"] == ID and out["whisper_cpp_tag"] == tag_ and out["whisper_cpp_commit"] == commit
    (build,) = [c["argv"] for c in world.fake.calls() if c["argv"][0] == "build"]
    assert option(build, "--tag") == p.image_tag() and option(build, "--file").endswith("providers/transcriber/Dockerfile")
    assert build[-1] == str(kit.PROVIDER_DIR)   # the context is this folder (.dockerignore lets only transcribe.sh in)
    record = world.state / "transcriber" / p.BUILD_RECORD
    assert json.loads(record.read_text())["image_id"] == ID and (record.stat().st_mode & 0o777) == 0o600
    assert p.main(["--check"]) == 0   # and the check now passes


def test_a_failed_build_records_nothing(world, capsys):
    world.fake.update(build={"exit": 1})
    assert world.provider.main(["build", "--confirmed"]) == 1
    assert not (world.state / "transcriber" / world.provider.BUILD_RECORD).exists()


# --- check ---------------------------------------------------------------------------------------------------------


def test_check_reads_docker_the_image_and_the_model(world, capsys, monkeypatch):
    p = world.provider
    monkeypatch.setenv("PATH", "/nonexistent")
    assert p.main(["--check"]) == 3 and "docker is not installed" in capsys.readouterr().err
    monkeypatch.setenv("PATH", f"{world.fake.folder}{os.pathsep}/usr/bin:/bin")
    world.fake.update(daemon_down=True)
    assert p.main(["--check"]) == 3 and "daemon" in capsys.readouterr().err
    world.fake.update(daemon_down=False)
    assert p.main(["--check"]) == 3 and "is not built" in capsys.readouterr().err
    built(world, labels={p.LABEL_DEFINITION: "0" * 64})
    assert p.main(["--check"]) == 3 and "not built from the definition" in capsys.readouterr().err
    built(world, record=False)
    assert p.main(["--check"]) == 3 and "recorded" in capsys.readouterr().err
    built(world)
    (world.state / "transcriber" / p.BUILD_RECORD).write_text(json.dumps({"image_id": "sha256:" + "b" * 64}))
    assert p.main(["--check"]) == 3     # the tag now names another image than the one that was built
    capsys.readouterr()
    built(world)
    assert p.main(["--check"]) == 0
    assert stdout_json(capsys)["image"]["id"] == ID
    assert p.main(["--check", "--model", "demo", "--models-dir", str(world.models)]) == 0
    assert stdout_json(capsys)["model"]["sha256"] == hashlib.sha256(b"fictional model weights").hexdigest()
    (world.models / "ggml-demo.bin").write_bytes(b"damaged")
    assert p.main(["--check", "--model", "demo", "--models-dir", str(world.models)]) == 1
    assert world.fake.runs() == []   # a check never starts a container


def test_models_lists_the_pins_and_hashes_nothing(world, capsys):
    assert world.provider.main(["models", "--models-dir", str(world.models)]) == 0
    rows = {m["name"]: m for m in stdout_json(capsys)["models"]}
    assert rows["demo"]["file_status"] == "present" and rows["later"]["file_status"] == "unpinned"
    assert world.fake.calls() == []


# --- a run: success, limits, failures ------------------------------------------------------------------------------


def test_a_run_writes_the_transcript_with_its_facts_and_prints_no_words(world, capsys):
    built(world)
    will_write(world, kit.speech())
    assert transcribe(world, language="en") == 0
    printed = capsys.readouterr().out
    assert "Hello" not in printed and "Ana" not in printed   # counts, never the text
    doc = json.loads(world.out.read_text(encoding="utf-8"))
    assert [w["text"] for w in doc["words"]] == ["Hello", "there,", "Ana.", "We'll", "meet", "at", "six."]
    facts = doc["facts"]
    assert facts["image_id"] == ID and facts["model"]["name"] == "demo" and facts["timestamps"] == "word"
    assert facts["model"]["sha256"] == hashlib.sha256(b"fictional model weights").hexdigest()
    assert facts["whisper_cpp_tag"] == world.provider.dockerfile_pins()[0] and facts["flags"][:3] == ["-np", "-ng", "-ojf"]
    assert facts["language_requested"] == "en" and facts["wall_seconds"] >= 0 and facts["input_duration"] == 5.9
    assert doc["duration"] == 5.88 and facts["words_without_timing"] == 0 and facts["dropped_annotations"] == 1
    assert (world.out.stat().st_mode & 0o777) == 0o600
    assert sorted(p.name for p in world.out.parent.iterdir()) == ["transcript.json"]   # the work folder and the temp file are gone


def test_the_dtw_mode_passes_its_flags_and_the_models_preset(world, capsys):
    built(world)
    will_write(world, kit.speech(dtw=True))
    assert transcribe(world, mode="dtw") == 0
    (argv,) = world.fake.runs()
    assert argv[-4:] == ["en", "dtw", "small", "300"]
    doc = json.loads(world.out.read_text(encoding="utf-8"))
    assert doc["facts"]["flags"][-3:] == ["-nfa", "-dtw", "small"]
    assert doc["words"][0]["start"] == 0.33 and doc["words"][0]["end"] == 0.75   # ends where the next word begins


def test_a_timeout_removes_the_container_by_name(world, monkeypatch, capsys):
    built(world)
    will_write(world, kit.speech(), sleep=30)
    monkeypatch.setattr(world.provider, "MIN_TIMEOUT", 1)
    began = time.monotonic()
    assert transcribe(world, "--timeout", "1") == 1
    assert time.monotonic() - began < 15
    assert "ran over 1 s" in capsys.readouterr().err
    (run,) = world.fake.runs()
    removals = [c["argv"] for c in world.fake.calls() if c["argv"][:2] == ["rm", "-f"]]
    assert removals == [["rm", "-f", option(run, "--name")]]
    assert not world.out.exists() and sorted(p.name for p in world.out.parent.iterdir()) == []   # no work folder left


def test_stopping_the_provider_removes_the_container(world):
    """SIGTERM (or SIGINT) while the container runs: the container is removed by name and the verb ends with a refusal."""
    p = world.provider
    world.fake.update(run={"sleep": 30})
    argv = ["docker", "run", "--name", "openhora-whisper-stop", "-v", f"{world.tmp}:/out:rw"]
    timer = threading.Timer(1, os.kill, (os.getpid(), signal.SIGTERM))
    timer.start()
    try:
        with pytest.raises(p.Refusal) as stopped:
            p.run_container(argv, "openhora-whisper-stop", 30)
    finally:
        timer.cancel()
    assert stopped.value.kind == "failed" and "stopped" in stopped.value.reason
    assert ["rm", "-f", "openhora-whisper-stop"] in [c["argv"] for c in world.fake.calls()]


def test_the_command_line_exit_codes(tmp_path):
    base = dict(os.environ, PATH="/nonexistent", OPENHORA_STATE_DIR=str(tmp_path))

    def run(*args):
        return subprocess.run([sys.executable, str(PROVIDER_FILE), *args], env=base, capture_output=True, text=True)

    assert run("--help").returncode == 0 and "transcriber:speech" in run("--help").stdout
    assert run().returncode == 2
    assert run("build").returncode == 2                      # no --confirmed
    check = run("--check")
    assert check.returncode == 3 and "docker is not installed" in check.stderr and check.stdout == ""


def test_an_input_longer_than_the_limit_is_a_usage_error(world, capsys):
    built(world)
    will_write(world, kit.speech(), exit_code=20)
    assert transcribe(world, "--max-seconds", "30") == 2
    assert "longer than --max-seconds (30)" in capsys.readouterr().err and not world.out.exists()


def test_a_failed_container_reports_the_tail_of_its_stderr(world, capsys):
    built(world)
    will_write(world, kit.speech(), exit_code=1, stderr="x" * 1000 + " Stream map '0:a:0' matches no streams.\n")
    assert transcribe(world) == 1
    err = capsys.readouterr().err
    assert "matches no streams" in err and len(err) < 600 and not world.out.exists()


def test_a_run_refuses_an_image_that_was_not_built_or_was_replaced(world, capsys):
    will_write(world, kit.speech())
    assert transcribe(world) == 3 and world.fake.runs() == []
    built(world)
    (world.state / "transcriber" / world.provider.BUILD_RECORD).write_text(json.dumps({"image_id": "sha256:" + "c" * 64}))
    assert transcribe(world) == 3 and world.fake.runs() == []


@pytest.mark.parametrize("flags", [["--language", "PT-br"], ["--timestamps", "fast"], ["--threads", "0"], ["--threads", "99"],
                                    ["--timeout", "5"], ["--max-seconds", "99999"], ["--memory-mb", "8"]])
def test_bad_arguments_are_usage_errors(world, flags, capsys):
    built(world)
    args = ["transcribe", "--in", str(world.input), "--model", "demo", "--language", "en", "--out", str(world.out),
            "--models-dir", str(world.models)]
    for i in range(0, len(flags), 2):
        if flags[i] in args:
            args[args.index(flags[i]) + 1] = flags[i + 1]
        else:
            args += flags[i:i + 2]
    try:
        code = world.provider.main(args)
    except SystemExit as e:   # argparse's own refusal of a choice
        code = e.code
    assert code == 2 and world.fake.runs() == []


def test_the_input_and_the_output_are_checked(world, tmp_path):
    built(world)
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    assert world.provider.main(["transcribe", "--in", str(empty), "--model", "demo", "--language", "en", "--out", str(world.out)]) == 2
    assert world.provider.main(["transcribe", "--in", str(world.input), "--model", "demo", "--language", "en",
                                "--out", str(tmp_path / "missing" / "t.json")]) == 2
    assert world.provider.main(["transcribe", "--in", str(world.input), "--model", "demo", "--language", "en",
                                "--out", str(tmp_path / "t.txt")]) == 2
    link = tmp_path / "out" / "link.json"
    link.symlink_to(tmp_path / "somewhere.json")
    assert world.provider.main(["transcribe", "--in", str(world.input), "--model", "demo", "--language", "en", "--out", str(link)]) == 2
    assert world.fake.runs() == []


# --- whisper's JSON -> the transcript -------------------------------------------------------------------------------


def parse(provider, doc, mode="word"):
    return provider.parse_whisper(doc, mode)


def test_words_are_joined_from_tokens_with_their_times_and_segments(provider):
    language, segments, words, counts = parse(provider, kit.speech())
    assert language == "en"
    assert [w["text"] for w in words] == ["Hello", "there,", "Ana.", "We'll", "meet", "at", "six."]
    assert [w["index"] for w in words] == list(range(7))
    assert words[0] == {"index": 0, "text": "Hello", "start": 0.32, "end": 0.72, "segment": 0, "probability": 0.98}
    assert (words[1]["start"], words[1]["end"]) == (0.72, 1.1)                  # "there" + ","
    assert words[1]["probability"] == 0.75 and words[2]["probability"] == 0.65   # the mean of the tokens
    assert words[3]["text"] == "We'll" and (words[3]["start"], words[3]["end"]) == (4.1, 4.7)
    assert [w["segment"] for w in words] == [0, 0, 0, 2, 2, 2, 2]
    assert [(s["index"], s["first_word"], s["last_word"]) for s in segments] == [(0, 0, 2), (1, None, None), (2, 3, 6)]
    assert segments[0]["text"] == "Hello there, Ana." and (segments[0]["start"], segments[0]["end"]) == (0.0, 2.4)
    assert counts == {"words_without_timing": 0, "clamped_words": 0, "dropped_annotations": 1}


def test_a_note_that_spans_words_and_a_music_sign_are_dropped(provider):
    seg = kit.segment(" [ Silence ] ♪ ok", 0, 1000, [
        kit.token(" [", 0, 50), kit.token(" Silence", 50, 400), kit.token(" ]", 400, 450), kit.token(" ♪", 450, 500),
        kit.token(" ok", 500, 900)])
    _, segments, words, counts = parse(provider, kit.document([seg]))
    assert [w["text"] for w in words] == ["ok"] and counts["dropped_annotations"] == 2
    assert segments[0]["first_word"] == 0


def test_a_word_whisper_could_not_time_is_estimated_and_marked(provider):
    seg = kit.segment(" one two three", 1000, 3000, [
        kit.token(" one", 1000, 1500), kit.token(" two"), kit.token(" three", 2000, 2800)])
    _, _, words, counts = parse(provider, kit.document([seg]))
    assert (words[1]["start"], words[1]["end"], words[1]["estimated"]) == (1.5, 2.0, True)
    assert "estimated" not in words[0] and counts["words_without_timing"] == 1


def test_an_end_before_its_start_is_clamped_and_counted(provider):
    seg = kit.segment(" odd", 1000, 2000, [kit.token(" odd", 1500, 1200)])
    _, _, words, counts = parse(provider, kit.document([seg]))
    assert (words[0]["start"], words[0]["end"]) == (1.5, 1.5) and counts["clamped_words"] == 1


def test_the_ml1_mode_reads_one_word_segments(provider):
    segs = [kit.segment(" Hello", 0, 700, [kit.token(" Hello", 300, 700)]),
            kit.segment(" there", 700, 1500, [kit.token(" there", 700, 1100), kit.token("[_TT_75]", 1500, 1500)])]
    _, segments, words, _ = parse(provider, kit.document(segs), "ml1")
    assert [(w["text"], w["segment"]) for w in words] == [("Hello", 0), ("there", 1)] and len(segments) == 2


def test_the_dtw_mode_uses_the_dtw_start_and_ends_a_word_where_the_next_begins(provider):
    _, _, words, _ = parse(provider, kit.speech(dtw=True), "dtw")
    assert (words[0]["start"], words[0]["end"]) == (0.33, 0.75)       # t_dtw is in 10 ms units
    assert (words[2]["start"], words[2]["end"]) == (1.2, 1.76)         # the last word of a segment ends with its last token
    assert [w["text"] for w in words][3] == "We'll"


def test_a_word_without_a_dtw_time_fails_the_run_instead_of_getting_a_guess(provider):
    with pytest.raises(provider.Refusal) as caught:
        parse(provider, kit.speech(dtw=False), "dtw")   # every t_dtw is -1, as when flash attention switched DTW off
    assert caught.value.kind == "failed" and "DTW" in caught.value.reason


@pytest.mark.parametrize("raw", [{}, {"transcription": "x"}, {"transcription": [{"offsets": {"from": 0}}]},
                                 {"transcription": [{"offsets": {"from": 0, "to": 1}, "text": "x"}]}])
def test_a_document_that_is_not_ojf_is_refused(provider, raw):
    with pytest.raises(provider.Refusal):
        parse(provider, raw)


def test_whisper_json_with_invalid_utf8_is_read_not_crashed(world, capsys):
    built(world)
    bad = json.dumps(kit.speech(), ensure_ascii=False).replace("Hello", "Hellé").encode("utf-8") + b"\n"
    world.fake.update(run={"exit": 0, "write": {"transcript.json": bad.decode("utf-8"), "input_duration.txt": "5.9",
                                                 "audio_duration.txt": "5.9"}})
    assert transcribe(world) == 0


# --- the schema ----------------------------------------------------------------------------------------------------

SCHEMA = json.loads((kit.PROVIDER_DIR / "transcript.schema.json").read_text(encoding="utf-8"))


def schema_errors(value, schema, path="$"):
    """The few keywords the schema uses: type, const, enum, required, properties, additionalProperties, items, minimum,
    maximum, minLength, pattern, and nullable types as a list. Enough to hold the schema and check_transcript together."""
    errors = []
    types = schema.get("type")
    kinds = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "boolean": bool, "null": type(None)}
    if types:
        wanted = types if isinstance(types, list) else [types]
        ok = any(isinstance(value, kinds[t]) and not (t in ("integer", "number") and isinstance(value, bool)) and
                 not (t == "integer" and isinstance(value, float)) for t in wanted)
        if not ok:
            return [f"{path}: type {types}"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: const")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: enum")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: maximum")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: minLength")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: pattern")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing {key}")
        props = schema.get("properties", {})
        for key, item in value.items():
            if key in props:
                errors += schema_errors(item, props[key], f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected {key}")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            errors += schema_errors(item, schema["items"], f"{path}[{i}]")
    return errors


def a_transcript(p):
    facts = {"provider": "whisper.cpp", "whisper_cpp_tag": "v0.0.0", "whisper_cpp_commit": "0" * 40, "image_id": ID,
             "model": {"name": "demo", "file": "ggml-demo.bin", "sha256": "1" * 64}, "timestamps": "word",
             "flags": ["-np"], "input_duration": 5.9, "wall_seconds": 1.5}
    return p.build_transcript(kit.speech(), "word", requested="en", duration=5.88, facts=facts)


def test_a_produced_transcript_satisfies_the_schema_and_the_checker(provider):
    doc = a_transcript(provider)
    assert schema_errors(doc, SCHEMA) == []
    provider.check_transcript(doc)


def mutate_index(doc):
    doc["words"][2]["index"] = 5


def mutate_negative(doc):
    doc["words"][0]["start"] = -0.1


def mutate_end_before_start(doc):
    doc["words"][0]["end"] = doc["words"][0]["start"] - 0.5


def mutate_probability(doc):
    doc["words"][0]["probability"] = 1.5


def mutate_language(doc):
    doc["language"] = "English"


def mutate_version(doc):
    doc["schema_version"] = 2


def mutate_empty_text(doc):
    doc["words"][0]["text"] = ""


def mutate_extra_key(doc):
    doc["words"][0]["note"] = "x"


@pytest.mark.parametrize("mutate", [mutate_negative, mutate_probability, mutate_language, mutate_version, mutate_empty_text,
                                    mutate_extra_key])
def test_the_schema_and_the_checker_refuse_the_same_documents(provider, mutate):
    doc = a_transcript(provider)
    mutate(doc)
    assert schema_errors(doc, SCHEMA) != []
    with pytest.raises(provider.Refusal):
        provider.check_transcript(doc)


@pytest.mark.parametrize("mutate", [mutate_index, mutate_end_before_start])
def test_the_checker_holds_what_a_schema_cannot_say(provider, mutate):
    doc = a_transcript(provider)
    mutate(doc)
    with pytest.raises(provider.Refusal):
        provider.check_transcript(doc)


def test_the_schema_carries_indices_for_words_and_segments():
    word, segment = SCHEMA["properties"]["words"]["items"], SCHEMA["properties"]["segments"]["items"]
    assert {"index", "text", "start", "end", "segment"} <= set(word["required"]) and "probability" in word["properties"]
    assert {"index", "start", "end", "text", "first_word", "last_word"} <= set(segment["required"])
    assert {"language", "duration", "facts"} <= set(SCHEMA["required"])


# --- the definition: Dockerfile, script, models --------------------------------------------------------------------


def test_the_dockerfile_pins_its_base_by_digest_and_whisper_by_tag_and_commit(provider):
    text = (kit.PROVIDER_DIR / "Dockerfile").read_text(encoding="utf-8")
    froms = re.findall(r"^FROM (\S+)", text, re.M)
    assert len(froms) == 2 and all(re.fullmatch(r"debian@sha256:[0-9a-f]{64}", f) for f in froms)
    tag_, commit = provider.dockerfile_pins()
    assert re.fullmatch(r"v\d+\.\d+\.\d+", tag_) and re.fullmatch(r"[0-9a-f]{40}", commit)
    assert 'test "$(git -C /src rev-parse HEAD)" = "${WHISPER_CPP_COMMIT}"' in text   # a moved tag fails the build
    assert re.search(r"^ARG DEBIAN_SNAPSHOT=\d{8}T\d{6}Z$", text, re.M)


def test_the_image_holds_no_model_no_secret_and_runs_as_a_non_root_user():
    text = (kit.PROVIDER_DIR / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^USER 10001:10001$", text, re.M) and "ENTRYPOINT" in text
    assert not re.search(r"ggml-[a-z0-9.-]+\.bin|huggingface|\.gguf", text)   # no model baked in, none fetched
    assert not re.search(r"^(ENV|ARG) \w*(KEY|TOKEN|SECRET|PASSWORD)", text, re.M | re.I)
    runtime = text.split("AS build", 1)[1].split("\nFROM ", 1)[1]
    assert "build-essential" not in runtime and "git" not in runtime.split("RUN", 2)[1] and "ffmpeg" in runtime
    assert (kit.PROVIDER_DIR / ".dockerignore").read_text().split() == ["*", "!transcribe.sh"]


def test_the_definition_hash_changes_with_any_file_of_the_definition(provider, tmp_path):
    for name in provider.DEFINITION_FILES:
        (tmp_path / name).write_bytes((kit.PROVIDER_DIR / name).read_bytes())
    base = provider.definition_hash(tmp_path)
    assert base == provider.definition_hash(kit.PROVIDER_DIR)
    for name in provider.DEFINITION_FILES:
        original = (tmp_path / name).read_bytes()
        (tmp_path / name).write_bytes(original + b"\n# changed\n")
        assert provider.definition_hash(tmp_path) != base, name
        (tmp_path / name).write_bytes(original)


@pytest.mark.parametrize("mode", ["word", "ml1", "dtw"])
def test_the_script_passes_the_flags_the_provider_records(provider, mode):
    script = (kit.PROVIDER_DIR / "transcribe.sh").read_text(encoding="utf-8")
    flags = provider.whisper_flags(mode, "small", "pt", 4)
    for flag in [f for f in flags if f.startswith("-") and not re.fullmatch(r"-\d+", f) and f not in ("-l", "-t", "-dtw")]:
        assert flag in script, flag
    assert "-l \"$language\"" in script and "-t \"$threads\"" in script and "-dtw \"$preset\"" in script
    assert flags[:3] == ["-np", "-ng", "-ojf"] and ("-dtw" in flags) == (mode == "dtw")


def test_the_script_is_valid_shell_and_bounds_its_inputs():
    script = kit.PROVIDER_DIR / "transcribe.sh"
    assert subprocess.run(["sh", "-n", str(script)], capture_output=True).returncode == 0
    text = script.read_text(encoding="utf-8")
    assert "-protocol_whitelist file,pipe" in text and "exit 20" in text and "> /dev/null" in text and "-np" in text
    assert os.access(script, os.X_OK)


def test_the_models_are_pinned_with_hashes_sizes_and_sources():
    doc = json.loads((kit.PROVIDER_DIR / "models.json").read_text(encoding="utf-8"))
    models = {m["name"]: m for m in doc["models"]}
    assert {"small", "medium", "large-v3-turbo"} <= set(models) and len(models) == len(doc["models"])
    for m in models.values():
        assert re.fullmatch(r"[0-9a-f]{64}", m["sha256"]) and m["size"] > 1_000_000 and m["memory_mb"] >= 1024
        assert m["url"] == f"https://huggingface.co/ggerganov/whisper.cpp/resolve/{doc['source_revision']}/{m['file']}"
        assert re.fullmatch(r"[0-9a-f]{40}", doc["source_revision"]) and m["file"] == f"ggml-{m['name']}.bin"
        assert m["dtw_preset"] in {"tiny", "base", "small", "medium", "large.v3", "large.v3.turbo"}


# --- the class resolves to this provider ----------------------------------------------------------------------------


def test_transcriber_speech_resolves_to_the_provider():
    sys.path.insert(0, str(kit.REPO / "providers"))
    try:
        import resolve
    finally:
        sys.path.pop(0)
    assert resolve.variables("transcriber:speech") == ["TRANSCRIBER_SPEECH_PROVIDER", "TRANSCRIBER_PROVIDER"]
    got = resolve.resolve("transcriber:speech", root=kit.REPO, env={})
    assert got["implementation"] == "whispercpp" and got["path"] == str(PROVIDER_FILE)
    assert resolve.interpreter_for(got["path"]) == [sys.executable]   # no dependency: it runs on the caller's interpreter


# --- live: skipped where the image or the model is absent -------------------------------------------------------------


@pytest.mark.skipif(os.environ.get("OPENHORA_TRANSCRIBER_LIVE") != "1",
                    reason="live test: needs OPENHORA_TRANSCRIBER_LIVE=1, the image built (`build --confirmed`) and "
                           "ggml-tiny.bin in the models folder; no whisper.cpp runs in the offline suite")
def test_a_three_second_synthetic_wav_transcribes_with_the_real_image(tmp_path):
    path = tmp_path / "tone.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000 * 3)
    out = tmp_path / "t.json"
    done = subprocess.run([sys.executable, str(PROVIDER_FILE), "transcribe", "--in", str(path), "--model", "tiny",
                           "--language", "en", "--out", str(out), "--max-seconds", "10"], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["schema_version"] == 1 and 2.9 < doc["duration"] < 3.1
