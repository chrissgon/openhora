#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""A model on the person's own machine: its configuration, its weights and its identity (backlog N14).

A local model is tested in the eval container like any other, but its server is a container of its own beside the run
(evals/executor.py, "A local model"). This file holds what is not docker: the person's configuration file, the reading of
the weights file's header, the hash that makes the model's identity, and the check that the file did not change. It is not
one of the measurement fingerprint's files: adding a model, or changing how it is described, changes nothing a hosted run
measures.

The configuration is a file outside the repository, $XDG_CONFIG_HOME/openhora/local-models.json, else
~/.config/openhora/local-models.json (WB_LOCAL_MODELS_FILE replaces both, for tests):

  {"models": {"<name>": {"weights": "/absolute/path/model.gguf", "context": 32768, "memory_gb": 24,
                         "accelerator": "cpu", "cpus": 8, "parallel": 1, "timeout_seconds": 1800,
                         "load_timeout_seconds": 900}}}

weights, context and memory_gb are required: they are about the person's machine and are never guessed. accelerator
(cpu or cuda; default cpu), cpus (default: the docker host's CPU count), parallel (how many runs of the event may run at
once on this machine; default 1), timeout_seconds (default: the gate file's) and load_timeout_seconds (default 900, at
most 1500) are optional. The file is read strictly: an unknown key, a relative path, a link, a file that is not a regular
file ending in .gguf, a path inside the checkout or a bad value is refused with its reason.

Identity. The model id of a local model is local/<name>@<first 12 hexadecimal characters of the weights' sha256>. The
person types local/<name>; the runner hashes the whole file once per event (streamed in 1 MiB blocks) and again on a
resumption. The file's (device, inode, size, modification time in nanoseconds) is taken with the hash and checked before
every server start and at the event's end: a change fails that run as infrastructure and makes the event a trial.

The header of the weights is read by a small parser (magic GGUF, versions 2 and 3): the architecture, the file type and
the trained context. A file that is not GGUF, a file split into parts, and a declared context above the trained one are
refused. The file types are named by a closed table copied from llama.cpp (enum llama_ftype, include/llama.h, lines 118
to 161 of tag b11277, commit eae11d2217fe9225d1aaba48773b6cca45ae4de9); a type the table lacks is "unknown".

Usage:
  python3 evals/local_models.py --help
  python3 evals/local_models.py check <name>      print the resolved id, the file type, the trained context and the size
                                                  as JSON (reads and hashes the file; no docker, no server)

Standard library only. Runs on Python 3.9.
"""
import hashlib
import json
import os
import re
import struct
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_ENV = "WB_LOCAL_MODELS_FILE"
NAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
ID_RE = re.compile(r"local/([a-z0-9][a-z0-9._-]{0,63})(?:@([0-9a-f]{12}))?")
KEYS_REQUIRED = ("weights", "context", "memory_gb")
KEYS_OPTIONAL = ("accelerator", "cpus", "parallel", "timeout_seconds", "load_timeout_seconds")
ACCELERATORS = ("cpu", "cuda")
LOAD_DEFAULT, LOAD_MAX = 900, 1500  # seconds; the cap is below the orphan grace of 1800 (runtime/orphans.py)
BLOCK = 1 << 20

# llama.cpp, include/llama.h, enum llama_ftype, tag b11277 (commit eae11d2217fe9225d1aaba48773b6cca45ae4de9), lines 118-161.
FILE_TYPES = {
    0: "ALL_F32", 1: "MOSTLY_F16", 2: "MOSTLY_Q4_0", 3: "MOSTLY_Q4_1", 7: "MOSTLY_Q8_0", 8: "MOSTLY_Q5_0", 9: "MOSTLY_Q5_1",
    10: "MOSTLY_Q2_K", 11: "MOSTLY_Q3_K_S", 12: "MOSTLY_Q3_K_M", 13: "MOSTLY_Q3_K_L", 14: "MOSTLY_Q4_K_S", 15: "MOSTLY_Q4_K_M",
    16: "MOSTLY_Q5_K_S", 17: "MOSTLY_Q5_K_M", 18: "MOSTLY_Q6_K", 19: "MOSTLY_IQ2_XXS", 20: "MOSTLY_IQ2_XS", 21: "MOSTLY_Q2_K_S",
    22: "MOSTLY_IQ3_XS", 23: "MOSTLY_IQ3_XXS", 24: "MOSTLY_IQ1_S", 25: "MOSTLY_IQ4_NL", 26: "MOSTLY_IQ3_S", 27: "MOSTLY_IQ3_M",
    28: "MOSTLY_IQ2_S", 29: "MOSTLY_IQ2_M", 30: "MOSTLY_IQ4_XS", 31: "MOSTLY_IQ1_M", 32: "MOSTLY_BF16", 36: "MOSTLY_TQ1_0",
    37: "MOSTLY_TQ2_0", 38: "MOSTLY_MXFP4_MOE", 39: "MOSTLY_NVFP4", 40: "MOSTLY_Q1_0", 41: "MOSTLY_Q2_0",
}
UNKNOWN_TYPE = "unknown"
FILE_TYPE_NAMES = tuple(sorted(set(FILE_TYPES.values()))) + (UNKNOWN_TYPE,)  # the closed list an evidence line may name

GGUF_VERSIONS = (2, 3)
HEADER_LIMIT = 1 << 28  # bytes the header may span: a parser never follows a corrupt count past this
KV_LIMIT = 1 << 20
STRING_LIMIT = 1 << 24
# value type -> size in bytes of a fixed-size value
FIXED = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
INTEGERS = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 10: "<Q", 11: "<q"}
STRING, ARRAY = 8, 9


class LocalModelError(ValueError):
    """The configuration, the weights file or its header cannot be used; the message says why, in one sentence."""


def config_path(env=None):
    env = os.environ if env is None else env
    explicit = (env.get(CONFIG_ENV) or "").strip()
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))
    base = (env.get("XDG_CONFIG_HOME") or "").strip() or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(os.path.abspath(base), "openhora", "local-models.json")


def inside_checkout(path, root=ROOT):
    """True when path is the checkout or inside it, by device and inode of each parent (links resolved), as
    evals/eval_status.py inside_checkout does."""
    try:
        top = os.stat(root)
    except OSError:
        return False
    here = os.path.realpath(path)
    while True:
        try:
            if os.path.samestat(os.stat(here), top):
                return True
        except OSError:
            pass
        parent = os.path.dirname(here)
        if parent == here:
            return False
        here = parent


def _whole(value, low, high):
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def check_entry(name, entry, root=ROOT):
    """The normalized entry of one model of the configuration, or LocalModelError. cpus stays None when the file does
    not give it (the docker host's count is asked of docker when a server starts). The weights file is looked at, not read."""
    where = f"local model {name!r}"
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise LocalModelError(f"{name!r} is not a local model name (lowercase letters, digits and . _ -, at most 64, starting with a letter or digit)")
    if not isinstance(entry, dict):
        raise LocalModelError(f"{where} must be an object")
    unknown = sorted(set(entry) - set(KEYS_REQUIRED) - set(KEYS_OPTIONAL))
    if unknown:
        raise LocalModelError(f"{where} has an unknown key: {', '.join(unknown)}")
    missing = [k for k in KEYS_REQUIRED if k not in entry]
    if missing:
        raise LocalModelError(f"{where} needs {', '.join(missing)}: they are about your machine and are never guessed")
    weights = entry["weights"]
    if not (isinstance(weights, str) and weights and os.path.isabs(weights)):
        raise LocalModelError(f"{where}: weights must be an absolute path")
    if not weights.endswith(".gguf"):
        raise LocalModelError(f"{where}: weights must be a .gguf file")
    if os.path.islink(weights):
        raise LocalModelError(f"{where}: weights is a link; give the path of the file itself")
    if not os.path.isfile(weights):
        raise LocalModelError(f"{where}: {weights} is not a regular file")
    if inside_checkout(weights, root):
        raise LocalModelError(f"{where}: weights is inside the workbench checkout; keep model files outside it")
    out = {"weights": weights}
    ranges = {"context": (16, 1 << 20), "memory_gb": (1, 4096), "cpus": (1, 512), "parallel": (1, 8),
              "timeout_seconds": (30, 86400), "load_timeout_seconds": (10, LOAD_MAX)}
    for key, (low, high) in ranges.items():
        if key in entry and not _whole(entry[key], low, high):
            raise LocalModelError(f"{where}: {key} must be a whole number from {low} to {high}")
    accelerator = entry.get("accelerator", "cpu")
    if accelerator not in ACCELERATORS:
        raise LocalModelError(f"{where}: accelerator must be one of {', '.join(ACCELERATORS)}")
    out.update(context=entry["context"], memory_gb=entry["memory_gb"], accelerator=accelerator,
               cpus=entry.get("cpus"), parallel=entry.get("parallel", 1), timeout_seconds=entry.get("timeout_seconds"),
               load_timeout_seconds=entry.get("load_timeout_seconds", LOAD_DEFAULT))
    return out


def load_config(path=None, root=ROOT):
    """{name: normalized entry} of the configuration file; LocalModelError for a missing file, a file that is not in its
    form and any entry that is refused (the first reason)."""
    path = path or config_path()
    if not os.path.isfile(path):
        raise LocalModelError(f"there is no local models file at {path}: create it (see evals/README.md, \"Testing a local model\")")
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as e:
        raise LocalModelError(f"{path} is not valid JSON: {e}") from None
    if not (isinstance(doc, dict) and set(doc) == {"models"} and isinstance(doc["models"], dict)):
        raise LocalModelError(f"{path} must be {{\"models\": {{\"<name>\": {{...}}}}}}")
    return {name: check_entry(name, entry, root) for name, entry in doc["models"].items()}


def is_local(model):
    """True for an id of a local model, typed (local/<name>) or resolved (local/<name>@<12 hex>)."""
    return isinstance(model, str) and ID_RE.fullmatch(model) is not None


def parse_id(model):
    """(name, 12 hex or None) of a local model id; LocalModelError for anything else."""
    m = ID_RE.fullmatch(model or "")
    if not m:
        raise LocalModelError(f"{model!r} is not a local model id: local/<name>, or local/<name>@<12 hex> once resolved")
    return m.group(1), m.group(2)


def stat_of(path):
    st = os.stat(path)
    return [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns]


def hash_weights(path, block=BLOCK):
    """{"sha256", "stat", "seconds"}: the whole file streamed in 1 MiB blocks, and its (device, inode, size, mtime_ns)
    taken before it is read and checked after (a file that changed while it was read is refused)."""
    before = stat_of(path)
    started = time.monotonic()
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(block), b""):
            h.update(chunk)
    if stat_of(path) != before:
        raise LocalModelError(f"{path} changed while it was hashed")
    return {"sha256": h.hexdigest(), "stat": before, "seconds": time.monotonic() - started}


def assert_unchanged(path, stat):
    """LocalModelError unless the file still has the (device, inode, size, mtime_ns) taken with its hash."""
    try:
        now = stat_of(path)
    except OSError:
        raise LocalModelError(f"the weights {path} cannot be read any more") from None
    if now != list(stat):
        raise LocalModelError("the weights changed during the event")


def _read(f, n):
    data = f.read(n)
    if len(data) != n:
        raise LocalModelError("the file ends inside its header: it is not a whole GGUF file")
    return data


def _string(f):
    (n,) = struct.unpack("<Q", _read(f, 8))
    if n > STRING_LIMIT:
        raise LocalModelError("a string of the header is longer than any real one: the file is corrupt")
    return _read(f, n).decode("utf-8", errors="replace")


def _skip(f, kind, size_left):
    """Pass one value of the given type without keeping it."""
    if kind in FIXED:
        f.seek(FIXED[kind], os.SEEK_CUR)
    elif kind == STRING:
        (n,) = struct.unpack("<Q", _read(f, 8))
        if n > size_left:
            raise LocalModelError("a string of the header runs past the end of the file: it is corrupt")
        f.seek(n, os.SEEK_CUR)
    elif kind == ARRAY:
        (inner,) = struct.unpack("<I", _read(f, 4))
        (count,) = struct.unpack("<Q", _read(f, 8))
        if count > size_left:
            raise LocalModelError("an array of the header runs past the end of the file: it is corrupt")
        if inner in FIXED:
            f.seek(FIXED[inner] * count, os.SEEK_CUR)
        else:
            for _ in range(count):
                _skip(f, inner, size_left)
    else:
        raise LocalModelError(f"the header holds a value of an unknown type ({kind}): not a GGUF file this reader knows")


def read_header(path):
    """{"version", "architecture", "file_type" (the name from the closed table, or "unknown"), "file_type_id" (the number
    or None), "context_length" (the trained context, or None), "split" (True when the file says it is one part of
    several)}. LocalModelError for a file that is not GGUF, a version other than 2 and 3, or a header that is not whole."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            raise LocalModelError(f"{os.path.basename(path)} is not a GGUF file (its first four bytes are not GGUF)")
        (version,) = struct.unpack("<I", _read(f, 4))
        if version not in GGUF_VERSIONS:
            raise LocalModelError(f"GGUF version {version} is not read here (versions {', '.join(map(str, GGUF_VERSIONS))} are)")
        _, kv_count = struct.unpack("<QQ", _read(f, 16))
        if kv_count > KV_LIMIT:
            raise LocalModelError("the header claims more keys than any real file has: it is corrupt")
        found = {}
        for _ in range(kv_count):
            key = _string(f)
            (kind,) = struct.unpack("<I", _read(f, 4))
            wanted = key in ("general.architecture", "general.file_type", "split.count") or key.endswith(".context_length")
            if wanted and kind in INTEGERS:
                (found[key],) = struct.unpack(INTEGERS[kind], _read(f, struct.calcsize(INTEGERS[kind])))
            elif wanted and kind == STRING:
                found[key] = _string(f)
            else:
                _skip(f, kind, size)
            if f.tell() > min(size, HEADER_LIMIT):
                raise LocalModelError("the header runs past the end of the file: it is corrupt")
    arch = found.get("general.architecture")
    if not isinstance(arch, str) or not arch:
        raise LocalModelError("the header has no general.architecture")
    context = found.get(f"{arch}.context_length")
    file_type = found.get("general.file_type")
    split = isinstance(found.get("split.count"), int) and found["split.count"] > 1
    return {"version": version, "architecture": arch, "file_type_id": file_type if isinstance(file_type, int) else None,
            "file_type": FILE_TYPES.get(file_type, UNKNOWN_TYPE) if isinstance(file_type, int) else UNKNOWN_TYPE,
            "context_length": context if isinstance(context, int) else None, "split": split}


def check_weights(path, context):
    """The header of the weights, after the checks of the model's configuration: not a part of a split file, and a declared
    context that does not exceed the trained one. LocalModelError otherwise."""
    if re.search(r"-\d{5}-of-\d{5}\.gguf$", os.path.basename(path)):
        raise LocalModelError("the file is one part of a split model (-00001-of-N): give a single GGUF file")
    header = read_header(path)
    if header["split"]:
        raise LocalModelError("the file says it is one part of a split model: give a single GGUF file")
    trained = header["context_length"]
    if trained is not None and context > trained:
        raise LocalModelError(f"the declared context {context} is above the {trained} the model was trained on")
    return header


def resolve(name, typed_hex=None, config=None, hashed=None):
    """The whole description of one local model: its configuration, the id, the hash and stat of the weights, the header.
    typed_hex is the 12 characters of a typed id or of a resumed event's: a hash that does not start with them is refused.
    hashed is a hash_weights() result when the caller has it. LocalModelError for any refusal."""
    config = load_config() if config is None else config
    if name not in config:
        raise LocalModelError(f"{name!r} is not in the local models file {config_path()}: it lists {', '.join(sorted(config)) or 'none'}")
    entry = config[name]
    header = check_weights(entry["weights"], entry["context"])
    size = os.path.getsize(entry["weights"])
    if entry["memory_gb"] * (1 << 30) <= size:
        raise LocalModelError(f"memory_gb {entry['memory_gb']} is not above the {size} bytes of the weights; give the machine's memory the model may use")
    hashed = hashed or hash_weights(entry["weights"])
    short = hashed["sha256"][:12]
    if typed_hex and typed_hex != short:
        raise LocalModelError(f"the weights of {name!r} hash to @{short}, not @{typed_hex}: the file changed, or the id is another model's")
    return {**entry, "name": name, "id": f"local/{name}@{short}", "alias": f"{name}@{short}", "weights_sha256": hashed["sha256"],
            "stat": hashed["stat"], "hash_seconds": hashed["seconds"], "size": size, "file_type": header["file_type"],
            "architecture": header["architecture"], "trained_context": header["context_length"]}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("--help", "-h") or not argv:
        print(__doc__.strip())
        return 0 if argv else 2
    if len(argv) == 2 and argv[0] == "check":
        name, typed = parse_id(argv[1] if argv[1].startswith("local/") else "local/" + argv[1])
        spec = resolve(name, typed)
        rate = spec["size"] / (1 << 20) / spec["hash_seconds"] if spec["hash_seconds"] > 0 else 0.0
        print(json.dumps({"id": spec["id"], "file_type": spec["file_type"], "architecture": spec["architecture"],
                          "trained_context": spec["trained_context"], "declared_context": spec["context"],
                          "size_bytes": spec["size"], "accelerator": spec["accelerator"]}, indent=2))
        print(f"hashed {spec['size']} bytes in {spec['hash_seconds']:.1f} s ({rate:.0f} MiB/s)", file=sys.stderr)
        return 0
    print("Error: unknown arguments. See --help.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except LocalModelError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
