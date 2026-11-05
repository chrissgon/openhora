"""Tests of evals/local_models.py: the configuration file of the local models, the identity of a model (the hash of its weights),
the reading of a GGUF header and the check that the weights did not change. No docker, no server, no real model: the weights
are small files written here in the GGUF layout.

Run: uv run --with pytest pytest evals/tests/test_local_models.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "local_models.py"
spec = importlib.util.spec_from_file_location("local_models_under_test", SCRIPT)
lm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lm)
EVIDENCE = importlib.util.spec_from_file_location("evidence_lines_for_local_models", Path(__file__).resolve().parents[1] / "evidence_lines.py")
el = importlib.util.module_from_spec(EVIDENCE)
EVIDENCE.loader.exec_module(el)


def put(value, kind):
    if kind == "str":
        data = value.encode()
        return struct.pack("<I", 8) + struct.pack("<Q", len(data)) + data
    if kind == "u32":
        return struct.pack("<I", 4) + struct.pack("<I", value)
    if kind == "u16":
        return struct.pack("<I", 2) + struct.pack("<H", value)
    if kind == "strs":
        body = b"".join(struct.pack("<Q", len(v)) + v.encode() for v in value)
        return struct.pack("<I", 9) + struct.pack("<I", 8) + struct.pack("<Q", len(value)) + body
    if kind == "f32s":
        return struct.pack("<I", 9) + struct.pack("<I", 6) + struct.pack("<Q", len(value)) + struct.pack(f"<{len(value)}f", *value)
    raise AssertionError(kind)


def gguf(path, *, arch="llama", context=4096, file_type=15, version=3, extra=(), padding=b"\0" * 64):
    """A file in the GGUF layout with the keys the reader asks for, an array of strings and one of floats it must pass over."""
    items = [("general.architecture", arch, "str")] if arch else []
    items += [("tokenizer.ggml.tokens", [f"tok{i}" for i in range(50)], "strs")]
    if context is not None:
        items += [(f"{arch}.context_length", context, "u32")]
    items += [("tokenizer.ggml.scores", [0.5] * 20, "f32s")]
    if file_type is not None:
        items += [("general.file_type", file_type, "u32")]
    items += list(extra)
    body = b"".join(struct.pack("<Q", len(k.encode())) + k.encode() + put(v, kind) for k, v, kind in items)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(b"GGUF" + struct.pack("<I", version) + struct.pack("<QQ", 0, len(items)) + body + padding)
    return Path(path)


@pytest.fixture()
def weights(tmp_path):
    return gguf(tmp_path / "example-coder.gguf")


def entry(path, **changes):
    return {"weights": str(path), "context": 4096, "memory_gb": 8, **changes}


def write_config(tmp_path, models):
    path = tmp_path / "local-models.json"
    path.write_text(json.dumps({"models": models}))
    return str(path)


# --- the configuration file ----------------------------------------------------------------------------------------

def test_the_configuration_of_a_model_has_the_defaults_the_docs_state(tmp_path, weights):
    config = lm.load_config(write_config(tmp_path, {"example-coder": entry(weights)}), root=str(tmp_path / "checkout"))
    assert config == {"example-coder": {"weights": str(weights), "context": 4096, "memory_gb": 8, "accelerator": "cpu", "cpus": None,
                                        "parallel": 1, "timeout_seconds": None, "load_timeout_seconds": 900}}
    full = entry(weights, accelerator="cuda", cpus=6, parallel=2, timeout_seconds=3600, load_timeout_seconds=1200)
    assert lm.check_entry("example-coder", full, root=str(tmp_path / "checkout"))["load_timeout_seconds"] == 1200


def test_a_relative_xdg_config_home_is_ignored(tmp_path):
    assert lm.config_path({"XDG_CONFIG_HOME": "relative/dir", "HOME": str(tmp_path)}) == os.path.join(
        os.path.expanduser("~"), ".config", "openhora", "local-models.json")
    assert lm.config_path({"XDG_CONFIG_HOME": ""}).endswith(os.path.join(".config", "openhora", "local-models.json"))
    assert os.path.isabs(lm.config_path({"XDG_CONFIG_HOME": "relative/dir"}))


def test_a_path_that_docker_would_read_as_more_than_a_path_is_refused(tmp_path):
    for name in ("a:b.gguf", "a:ro.gguf", "new\nline.gguf"):
        path = gguf(tmp_path / "w" / name)
        with pytest.raises(lm.LocalModelError, match="colon or a newline"):
            lm.check_entry("example-coder", entry(path), root=str(tmp_path / "checkout"))


def test_the_configuration_file_lives_outside_the_repository_by_default(tmp_path):
    assert lm.config_path({"XDG_CONFIG_HOME": str(tmp_path)}) == str(tmp_path / "openhora" / "local-models.json")
    assert lm.config_path({"WB_LOCAL_MODELS_FILE": str(tmp_path / "x.json"), "XDG_CONFIG_HOME": "/nope"}) == str(tmp_path / "x.json")
    assert lm.config_path({"HOME": "/h"}).endswith(os.path.join(".config", "openhora", "local-models.json"))


@pytest.mark.parametrize("changes, reason", [
    ({"surprise": 1}, "unknown key: surprise"),
    ({"weights": "relative/model.gguf"}, "weights must be an absolute path"),
    ({"weights": None}, "weights must be an absolute path"),
    ({"context": "4096"}, "context must be a whole number"),
    ({"context": True}, "context must be a whole number"),
    ({"context": 4}, "context must be a whole number"),
    ({"memory_gb": 0}, "memory_gb must be a whole number"),
    ({"cpus": 0}, "cpus must be a whole number"),
    ({"parallel": 9}, "parallel must be a whole number"),
    ({"timeout_seconds": 5}, "timeout_seconds must be a whole number"),
    ({"load_timeout_seconds": 1501}, "load_timeout_seconds must be a whole number"),
    ({"accelerator": "tpu"}, "accelerator must be one of cpu, cuda"),
])
def test_each_bad_value_of_an_entry_is_refused_with_its_reason(tmp_path, weights, changes, reason):
    with pytest.raises(lm.LocalModelError, match=reason):
        lm.check_entry("example-coder", entry(weights, **changes), root=str(tmp_path / "checkout"))


@pytest.mark.parametrize("missing", ["weights", "context", "memory_gb"])
def test_what_is_about_the_machine_is_required_and_never_guessed(tmp_path, weights, missing):
    e = entry(weights)
    del e[missing]
    with pytest.raises(lm.LocalModelError, match=f"needs {missing}.*never guessed"):
        lm.check_entry("example-coder", e, root=str(tmp_path / "checkout"))


@pytest.mark.parametrize("name", ["Example", "-x", "a b", "", "x" * 65, "ex/ample", "ex@ample"])
def test_a_name_that_is_not_one_is_refused(tmp_path, weights, name):
    with pytest.raises(lm.LocalModelError, match="not a local model name"):
        lm.check_entry(name, entry(weights), root=str(tmp_path / "checkout"))


def test_a_link_a_directory_a_missing_file_and_a_file_that_is_not_gguf_by_name_are_refused(tmp_path, weights):
    root = str(tmp_path / "checkout")
    link = tmp_path / "link.gguf"
    os.symlink(weights, link)
    with pytest.raises(lm.LocalModelError, match="is a link"):
        lm.check_entry("example-coder", entry(link), root=root)
    folder = tmp_path / "folder.gguf"
    folder.mkdir()
    with pytest.raises(lm.LocalModelError, match="not a regular file"):
        lm.check_entry("example-coder", entry(folder), root=root)
    with pytest.raises(lm.LocalModelError, match="not a regular file"):
        lm.check_entry("example-coder", entry(tmp_path / "absent.gguf"), root=root)
    other = tmp_path / "model.bin"
    other.write_bytes(b"x")
    with pytest.raises(lm.LocalModelError, match="must be a .gguf file"):
        lm.check_entry("example-coder", entry(other), root=root)


def test_weights_inside_the_checkout_are_refused(tmp_path):
    checkout = tmp_path / "checkout"
    (checkout / "models").mkdir(parents=True)
    inside = gguf(checkout / "models" / "m.gguf")
    with pytest.raises(lm.LocalModelError, match="inside the workbench checkout"):
        lm.check_entry("example-coder", entry(inside), root=str(checkout))
    # a link into the checkout from outside is refused too (the file itself must not be a link, and the real path is looked at)
    assert lm.inside_checkout(str(inside), str(checkout)) and not lm.inside_checkout(str(tmp_path / "elsewhere.gguf"), str(checkout))


def test_the_file_is_read_strictly(tmp_path, weights):
    path = tmp_path / "c.json"
    for text, reason in (("not json", "not valid JSON"), ('{"models": []}', "must be"), ('{"models": {}, "extra": 1}', "must be"),
                         ('[]', "must be")):
        path.write_text(text)
        with pytest.raises(lm.LocalModelError, match=reason):
            lm.load_config(str(path))
    with pytest.raises(lm.LocalModelError, match="there is no local models file"):
        lm.load_config(str(tmp_path / "absent.json"))


# --- the GGUF header --------------------------------------------------------------------------------------------------

def test_the_header_gives_the_architecture_the_file_type_and_the_trained_context(weights):
    h = lm.read_header(str(weights))
    assert (h["version"], h["architecture"], h["file_type"], h["file_type_id"], h["context_length"], h["split"]) == (
        3, "llama", "MOSTLY_Q4_K_M", 15, 4096, False)
    assert lm.read_header(str(gguf(weights.parent / "v2.gguf", version=2)))["version"] == 2


def test_a_file_type_the_table_lacks_or_a_file_without_one_is_unknown(tmp_path):
    assert lm.read_header(str(gguf(tmp_path / "a.gguf", file_type=999)))["file_type"] == "unknown"
    assert lm.read_header(str(gguf(tmp_path / "b.gguf", file_type=None)))["file_type"] == "unknown"
    assert lm.read_header(str(gguf(tmp_path / "c.gguf", context=None)))["context_length"] is None


def test_a_file_that_is_not_gguf_is_refused(tmp_path):
    bad = tmp_path / "bad.gguf"
    bad.write_bytes(b"GGML" + b"\0" * 100)
    with pytest.raises(lm.LocalModelError, match="not a GGUF file"):
        lm.read_header(str(bad))
    bad.write_bytes(b"")
    with pytest.raises(lm.LocalModelError, match="not a GGUF file"):
        lm.read_header(str(bad))
    with pytest.raises(lm.LocalModelError, match="GGUF version 1"):
        lm.read_header(str(gguf(tmp_path / "v1.gguf", version=1)))
    with pytest.raises(lm.LocalModelError, match="no general.architecture"):
        lm.read_header(str(gguf(tmp_path / "noarch.gguf", arch=None)))


def test_a_truncated_header_is_refused_and_a_corrupt_count_is_not_followed(tmp_path, weights):
    cut = tmp_path / "cut.gguf"
    cut.write_bytes(weights.read_bytes()[:90])
    with pytest.raises(lm.LocalModelError, match="ends inside its header|runs past"):
        lm.read_header(str(cut))
    huge = tmp_path / "huge.gguf"
    huge.write_bytes(b"GGUF" + struct.pack("<I", 3) + struct.pack("<QQ", 0, 1 << 40))
    with pytest.raises(lm.LocalModelError, match="more keys than any real file"):
        lm.read_header(str(huge))


def test_a_split_model_is_refused_by_its_name_and_by_its_header(tmp_path):
    named = gguf(tmp_path / "model-00001-of-00004.gguf")
    with pytest.raises(lm.LocalModelError, match="one part of a split model"):
        lm.check_weights(str(named), 4096)
    keyed = gguf(tmp_path / "model.gguf", extra=[("split.count", 4, "u16")])
    with pytest.raises(lm.LocalModelError, match="one part of a split model"):
        lm.check_weights(str(keyed), 4096)


def test_a_declared_context_above_the_trained_one_is_refused(weights):
    assert lm.check_weights(str(weights), 4096)["context_length"] == 4096
    with pytest.raises(lm.LocalModelError, match="declared context 8192 is above the 4096"):
        lm.check_weights(str(weights), 8192)


def test_the_file_type_names_are_the_ones_an_evidence_line_may_carry():
    assert tuple(el.LOCAL_FILE_TYPES) == tuple(lm.FILE_TYPE_NAMES)
    assert lm.FILE_TYPES[15] == "MOSTLY_Q4_K_M" and lm.FILE_TYPES[32] == "MOSTLY_BF16" and 4 not in lm.FILE_TYPES


# --- the identity ---------------------------------------------------------------------------------------------------------

def test_the_id_is_the_name_and_the_first_twelve_characters_of_the_hash_of_the_file(tmp_path, weights):
    import hashlib
    config = lm.load_config(write_config(tmp_path, {"example-coder": entry(weights)}), root=str(tmp_path / "checkout"))
    spec = lm.resolve("example-coder", None, config)
    digest = hashlib.sha256(weights.read_bytes()).hexdigest()
    assert spec["id"] == f"local/example-coder@{digest[:12]}" and spec["weights_sha256"] == digest
    assert spec["alias"] == f"example-coder@{digest[:12]}" and spec["file_type"] == "MOSTLY_Q4_K_M" and spec["trained_context"] == 4096
    assert spec["size"] == weights.stat().st_size and spec["stat"] == lm.stat_of(str(weights))
    assert lm.is_local(spec["id"]) and lm.is_local("local/example-coder") and not lm.is_local("example-coder")
    assert lm.parse_id(spec["id"]) == ("example-coder", digest[:12]) and lm.parse_id("local/example-coder") == ("example-coder", None)
    with pytest.raises(lm.LocalModelError, match="not a local model id"):
        lm.parse_id("local/Example")


def test_a_typed_hash_that_does_not_match_is_refused_and_a_changed_file_is_another_model(tmp_path, weights):
    config = lm.load_config(write_config(tmp_path, {"example-coder": entry(weights)}), root=str(tmp_path / "checkout"))
    first = lm.resolve("example-coder", None, config)
    assert lm.resolve("example-coder", first["id"].split("@")[1], config)["id"] == first["id"]
    with pytest.raises(lm.LocalModelError, match="not @000000000000"):
        lm.resolve("example-coder", "000000000000", config)
    gguf(weights, context=4096, file_type=7)  # the same name, other bytes
    second = lm.resolve("example-coder", None, config)
    assert second["id"] != first["id"]
    with pytest.raises(lm.LocalModelError, match="not in the local models file"):
        lm.resolve("absent", None, config)


def test_the_memory_of_the_machine_must_be_above_the_size_of_the_weights(tmp_path, weights, monkeypatch):
    config = lm.load_config(write_config(tmp_path, {"example-coder": entry(weights, memory_gb=1)}), root=str(tmp_path / "checkout"))
    monkeypatch.setattr(lm.os.path, "getsize", lambda p: 2 << 30)
    with pytest.raises(lm.LocalModelError, match="memory_gb 1 is not above"):
        lm.resolve("example-coder", None, config)


def test_the_file_is_hashed_in_blocks_and_its_stat_is_taken_with_the_hash(weights):
    import hashlib
    whole = hashlib.sha256(weights.read_bytes()).hexdigest()
    for block in (1, 7, 1 << 20):
        got = lm.hash_weights(str(weights), block)
        assert got["sha256"] == whole and got["stat"] == lm.stat_of(str(weights)) and got["seconds"] >= 0


def test_a_change_of_the_file_is_seen_by_its_device_inode_size_and_modification_time(tmp_path, weights):
    stat = lm.stat_of(str(weights))
    lm.assert_unchanged(str(weights), stat)  # nothing changed
    os.utime(weights, ns=(stat[3] + 10**9, stat[3] + 10**9))  # only the modification time
    with pytest.raises(lm.LocalModelError, match="the weights changed during the event"):
        lm.assert_unchanged(str(weights), stat)
    stat = lm.stat_of(str(weights))
    with open(weights, "ab") as f:  # the size
        f.write(b"x")
    with pytest.raises(lm.LocalModelError, match="changed during the event"):
        lm.assert_unchanged(str(weights), stat)
    stat = lm.stat_of(str(weights))
    other = tmp_path / "other.gguf"  # the same bytes in another file put in its place: another inode
    other.write_bytes(weights.read_bytes())
    os.utime(other, ns=(stat[3], stat[3]))
    os.replace(other, weights)
    with pytest.raises(lm.LocalModelError, match="changed during the event"):
        lm.assert_unchanged(str(weights), stat)
    os.remove(weights)
    with pytest.raises(lm.LocalModelError, match="cannot be read any more"):
        lm.assert_unchanged(str(weights), stat)


def test_a_file_that_changes_while_it_is_hashed_is_refused(weights, monkeypatch):
    real, calls = lm.stat_of, []

    def moving(path):
        calls.append(path)
        stat = real(path)
        return stat if len(calls) == 1 else [*stat[:3], stat[3] + 1]
    monkeypatch.setattr(lm, "stat_of", moving)
    with pytest.raises(lm.LocalModelError, match="changed while it was hashed"):
        lm.hash_weights(str(weights))


# --- the command ----------------------------------------------------------------------------------------------------------

def test_check_prints_what_an_entry_resolves_to_and_says_the_hash_rate(tmp_path, weights):
    config = write_config(tmp_path, {"example-coder": entry(weights)})
    r = subprocess.run([sys.executable, str(SCRIPT), "check", "example-coder"], capture_output=True, text=True,
                       env={**os.environ, "WB_LOCAL_MODELS_FILE": config})
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["id"].startswith("local/example-coder@") and out["file_type"] == "MOSTLY_Q4_K_M" and out["trained_context"] == 4096
    assert out["size_bytes"] == weights.stat().st_size and "MiB/s" in r.stderr
    bad = subprocess.run([sys.executable, str(SCRIPT), "check", "absent"], capture_output=True, text=True,
                         env={**os.environ, "WB_LOCAL_MODELS_FILE": config})
    assert bad.returncode == 1 and "not in the local models file" in bad.stderr
    assert subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True).returncode == 0
