"""The preset vocabulary and the renderer's own data, and the typed-parameter checks.

The vocabulary (shared/references/video-presets.json) is read from the path a flag gives; the renderer holds no second
list of presets. renderer-presets.json beside this file holds what the renderer decides (frame, timing, limits).
Parameter values are checked against the vocabulary's types: text (max, max_items, pattern), icon, color (a palette
token or #RRGGBB), choice, and an asset slot (image or clip), which in an edit list holds a slot id, never a description.
Standard library only.
"""
from __future__ import annotations

import json
import os
import re

from _text import Refusal, clean_text

HERE = os.path.dirname(os.path.abspath(__file__))
HEX_COLOR = re.compile(r"#[0-9A-Fa-f]{6}")
SLOT_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")


def read_json(path: str, max_bytes: int = 5 * 1024 * 1024):
    """A JSON file of at most max_bytes, or a Refusal. The text of a parse error is not echoed."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read(max_bytes + 1)
    except OSError:
        raise Refusal("unreadable_file", os.path.basename(path)) from None
    if len(raw) > max_bytes:
        raise Refusal("file_too_large", os.path.basename(path))
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise Refusal("not_json", os.path.basename(path)) from None


def load_data(name: str = "renderer-presets.json") -> dict:
    return read_json(os.path.join(HERE, name))


def load_vocabulary(path: str) -> dict:
    """The vocabulary file, with the same structural checks as the script checker's own loader."""
    vocab = read_json(path)
    try:
        assert vocab["version"] == 1 and isinstance(vocab["presets"], dict)
        for key in ("icons", "palette", "limits"):
            assert key in vocab
        for name, preset in vocab["presets"].items():
            assert preset["main"] in preset["params"] and preset["kind"] in ("overlay", "layout"), name
            for spec in preset["params"].values():
                assert "type" in spec
    except (AssertionError, KeyError, TypeError):
        raise Refusal("not_a_vocabulary", os.path.basename(path)) from None
    return vocab


def slot_types(spec: dict) -> list:
    kinds = spec["type"] if isinstance(spec["type"], list) else [spec["type"]]
    return [k for k in kinds if k in ("image", "clip")]


def slot_params(vocab: dict, preset: str) -> list:
    return [n for n, s in vocab["presets"][preset]["params"].items() if slot_types(s)]


def check_color(value, palette, field) -> str:
    if not isinstance(value, str):
        raise Refusal("bad_color", field)
    if value in palette:
        return value
    if HEX_COLOR.fullmatch(value):
        return value.upper()
    raise Refusal("bad_color", field)


def check_param(vocab: dict, spec: dict, field: str, value):
    kind = spec["type"]
    if slot_types(spec):
        if not isinstance(value, str) or not SLOT_ID.fullmatch(value):
            raise Refusal("bad_slot", field)
        return value
    if kind == "text":
        items_max = spec.get("max_items", 1)
        if items_max > 1:
            if not isinstance(value, str):
                raise Refusal("not_text", field)
            parts = value.split(" | ")
            if len(parts) > items_max:
                raise Refusal("too_many_items", field)
            out = " | ".join(clean_text(p, spec["max"], field) for p in parts)
        else:
            out = clean_text(value, spec["max"], field)
        pattern = spec.get("pattern")
        if pattern and not re.fullmatch(pattern, out):
            raise Refusal("bad_pattern", field)
        return out
    if kind == "icon":
        if value not in vocab["icons"]:
            raise Refusal("bad_icon", field)
        return value
    if kind == "color":
        return check_color(value, vocab["palette"], field)
    if kind == "choice":
        if value not in spec["values"]:
            raise Refusal("bad_choice", field)
        return value
    raise Refusal("unknown_type", field)


def check_params(vocab: dict, preset: str, params, field: str = "params") -> dict:
    """The params of one beat against the preset's declaration: no undeclared name, every required one present,
    every value of its type and bounds. Defaults are not filled in (the template and the data file own them)."""
    if preset not in vocab["presets"]:
        raise Refusal("unknown_preset", field)
    if not isinstance(params, dict):
        raise Refusal("params_not_object", field)
    declared = vocab["presets"][preset]["params"]
    out = {}
    for name, value in params.items():
        if name not in declared:
            raise Refusal("undeclared_param", f"{field}.{name}")
        out[name] = check_param(vocab, declared[name], f"{field}.{name}", value)
    for name, spec in declared.items():
        if spec.get("required") and name not in out:
            raise Refusal("missing_param", f"{field}.{name}")
    return out
