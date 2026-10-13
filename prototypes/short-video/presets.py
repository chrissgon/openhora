"""Preset contract: loading, typed parameter validation and text hardening.

Prototype of amendment A2 (typed parameters) and of the text rules of the plan's hard limits:
text is NFC, has no character of the Unicode categories Cc, Cf, Zl or Zp, and is bounded in length.
Errors carry a closed code and the parameter name, never the text that was refused.
"""
import json
import os
import re
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONTRACT = os.path.join(HERE, "presets.json")

HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}\Z")
SLOT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}\Z")
REFUSED_CATEGORIES = {"Cc", "Cf", "Zl", "Zp"}


class ParamError(ValueError):
    """A parameter or a text was refused. `code` is closed; `param` names the field."""

    def __init__(self, code, param=""):
        super().__init__("%s:%s" % (code, param) if param else code)
        self.code = code
        self.param = param


def load_contract(path=None):
    with open(path or DEFAULT_CONTRACT, "r", encoding="utf-8") as fh:
        contract = json.load(fh)
    if contract.get("version") != 1:
        raise ParamError("contract_version")
    return contract


def clean_text(value, max_len, param="text", allow_empty=False):
    """Return `value` normalised to NFC, or raise. Newlines are Cc, so they are refused too."""
    if not isinstance(value, str):
        raise ParamError("not_text", param)
    value = unicodedata.normalize("NFC", value)
    for ch in value:
        if unicodedata.category(ch) in REFUSED_CATEGORIES:
            raise ParamError("forbidden_character", param)
    value = value.strip()
    if not value and not allow_empty:
        raise ParamError("empty_text", param)
    if len(value) > max_len:
        raise ParamError("text_too_long", param)
    return value


def validate_color(value, palette, param="color"):
    """A palette token name or #RRGGBB. Anything else (rgba(), names, var(), url()) is refused."""
    if not isinstance(value, str):
        raise ParamError("bad_color", param)
    if value in palette:
        return value
    if HEX_COLOR.match(value):
        return value.upper()
    raise ParamError("bad_color", param)


def validate_param(contract, spec, name, value):
    kind = spec["type"]
    if kind == "text":
        return clean_text(value, spec["max"], name)
    if kind == "choice":
        if value not in spec["values"]:
            raise ParamError("bad_choice", name)
        return value
    if kind == "icon":
        if value not in contract["icons"]:
            raise ParamError("bad_icon", name)
        return value
    if kind == "color":
        return validate_color(value, contract["palette"], name)
    if kind == "image":
        if not isinstance(value, str) or not SLOT_ID.match(value):
            raise ParamError("bad_slot", name)
        return value
    if kind == "number":
        # bool is an int in Python; refuse it explicitly
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ParamError("bad_number", name)
        if value != value or value in (float("inf"), float("-inf")):
            raise ParamError("bad_number", name)
        if value < spec["min"] or value > spec["max"]:
            raise ParamError("number_out_of_range", name)
        return round(float(value), spec.get("decimals", 0))
    raise ParamError("unknown_type", name)


def validate_params(contract, preset, params):
    """Validate `params` against the preset's declared contract.

    Refuses undeclared parameters and missing required ones; fills defaults.
    Returns a new dict with only declared parameters.
    """
    presets = contract["presets"]
    if preset not in presets:
        raise ParamError("unknown_preset", preset)
    if not isinstance(params, dict):
        raise ParamError("params_not_object", preset)
    declared = presets[preset]["params"]
    for name in params:
        if name not in declared:
            raise ParamError("undeclared_param", name)
    out = {}
    for name, spec in declared.items():
        if name in params and params[name] is not None:
            out[name] = validate_param(contract, spec, name, params[name])
        elif spec.get("required"):
            raise ParamError("missing_param", name)
        elif "default" in spec:
            out[name] = spec["default"]
    return out


def validate_theme_colors(contract, colors):
    """Theme colour tokens must be #RRGGBB (the brand-tokens block is model-written, never trusted)."""
    out = {}
    for name, value in colors.items():
        if name not in contract["palette"]:
            raise ParamError("unknown_token", name)
        if not isinstance(value, str) or not HEX_COLOR.match(value):
            raise ParamError("bad_color", name)
        out[name] = value.upper()
    return out


def asset_slots(contract, preset, params):
    """Slot ids of the image parameters of a validated preset."""
    declared = contract["presets"][preset]["params"]
    return [params[n] for n, s in declared.items() if s["type"] == "image" and n in params]
