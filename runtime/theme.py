#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The project's theme for the renderer (package P4g of the short-video plan, amendment A6.3, decision D32 option (i)).

`theme_args(project)` reads the closed `brand-tokens` block of the project's visual identity (docs/brand/identity.md, owned by the
skill brand-identity, checked by check_brand_tokens.py, of which runtime/ carries a generated copy) and returns the `--color` and
`--font` arguments of the renderer's `base` verb, with a record `{source, reason, colors, fonts, notes, hash}` that the pipeline keeps
in its result and in render.json. The catalogue and the storyboard of later packages call it too, so that every picture of the
theme comes from one place.

The mapping, one table (the renderer's roles are in providers/renderer/renderer-presets.json, `theme`; its fonts in
providers/renderer/assets/fonts/allowlist.json). It reads the dark column, because the renderer's cards are dark panels over a
picture; a role that has one value uses it:

  identity role      renderer token (--color)
  bg                 bg
  fg                 text
  muted              muted
  accent             accent, and chip_border (the defaults hold the two equal)
  surface (optional) chip_fill; without it the renderer's own default stays
  (derived)          chip_text: the accent when it reaches 4.5:1 on chip_fill, else fg

  identity font role   renderer font role (--font ROLE=ID:WEIGHT)
  display              display
  body                 text
  mono (optional)      mono

A family is passed only when an allow-listed font has exactly that family name and exactly that weight: the weight comes from the
block. Otherwise the renderer keeps its default for the role, and the record carries a note. A brand typeface joins the allow-list by
the decision D6 (licence file, hash, glyph test), never by the identity's word.

What is refused, each with a closed code and one fixed sentence (`ThemeError`), never a word of the file:

  identity_unreadable    the file is a link, is not a regular file, is over the limit, leaves the project or is not UTF-8
  theme_draft            the identity is a draft (the `- Status:` line, or the block's `status`)
  theme_status_unknown   the `- Status:` line starts with a word that is not draft or approved in a language the checker lists
  theme_block_invalid    a block that is repeated, over the limit, not JSON, not an object, or whose shape is wrong
  theme_bad_color        a colour that is not `#RRGGBB`
  theme_unknown_role     a colour role or a font role the block does not have (a fourth font role, for one)
  theme_bad_font         a font that is not {family, weight} with a plain family name and a weight of 100 to 900
  theme_low_contrast     a text pair under 4.5:1 (text, muted and chip_text on chip_fill; text on bg), named in the sentence: nothing is
                         darkened or picked for the person

and what is never a refusal but the default theme, said in the record's `reason`: no identity file (`no_identity`), no block in it
(`no_tokens_block`), an open block written before the closed one existed (`open_block`), and the person's choice of the default
theme for this render (`chosen`; the review's `theme` edit, runtime/captions.py). `describe(record)` is the one sentence that says it. Nothing here runs a model, reads a network or writes a file.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check_brand_tokens as tokens  # noqa: E402  (the generated copy of shared/scripts/check_brand_tokens.py)

IDENTITY = "docs/brand/identity.md"
IDENTITY_LIMIT = 1024 * 1024
PRESETS = ("providers", "renderer", "renderer-presets.json")
ALLOWLIST = ("providers", "renderer", "assets", "fonts", "allowlist.json")
MIN_TEXT_RATIO = 4.5               # WCAG 2 AA for text, applied to a card over a moving picture by choice (A6.9, question 9)
COLOR_MAP = (("bg", "bg"), ("fg", "text"), ("muted", "muted"), ("accent", "accent"))   # (identity role, renderer token)
FONT_MAP = (("display", "display"), ("body", "text"), ("mono", "mono"))               # (identity role, renderer role)
PAIRS = (("text", "chip_fill"), ("muted", "chip_fill"), ("chip_text", "chip_fill"), ("text", "bg"))   # (text token, the token it sits on)
# The way to the default theme until the page has a control for it: the review is opened again, the choice is a `theme` edit of
# captions-edit, and the captions are done again (the pipeline then runs `base` again with the choice).
CHOICE = ("in a terminal: prepare-again --step review, then captions-edit with --text '[{\"op\": \"theme\", \"choice\": \"default\"}]', "
          "then captions-done")
DRAFT_SENTENCE = "the identity is a draft: approve it, or choose the default theme (%s)" % CHOICE
SENTENCES = {
    "identity_unreadable": "the identity file cannot be read: it must be a regular file of the project, not a link, at most 1 MiB, in UTF-8; "
                           "fix it, or choose the default theme (%s)" % CHOICE,
    "theme_draft": DRAFT_SENTENCE,
    "theme_status_unknown": "the Status line of the identity does not start with draft or approved (or a translation check_brand_tokens.py lists): "
                            "fix it, or choose the default theme (%s)" % CHOICE,
    "theme_block_invalid": "the brand-tokens block of the identity is not valid: run brand-identity again, or fix the block and check it with "
                           "check_brand_tokens.py, or choose the default theme (%s)" % CHOICE,
    "theme_bad_color": "a colour of the brand-tokens block is not #RRGGBB: fix it in the identity, or choose the default theme (%s)" % CHOICE,
    "theme_unknown_role": "the brand-tokens block has a role the theme does not have: fix it in the identity, or choose the default theme (%s)" % CHOICE,
    "theme_bad_font": "a font of the brand-tokens block is not a family name and a weight from 100 to 900: fix it in the identity, "
                      "or choose the default theme (%s)" % CHOICE,
}
LOW_CONTRAST_SENTENCE = ("the %s contrast is %s:1, under 4.5:1: change the colours in the identity, or choose the default theme for this render "
                         "(" + CHOICE + ")")
REFUSAL_OF = {"bad_color": "theme_bad_color", "unknown_role": "theme_unknown_role", "bad_font": "theme_bad_font"}
REASONS = {   # what the person is told when the default theme is used (the approval's text and the page): one fixed sentence per reason
    "no_identity": "default theme: the project has no identity file (docs/brand/identity.md)",
    "no_tokens_block": "default theme: the identity has no brand-tokens block",
    "open_block": "default theme: the identity's block is in the old format; run brand-identity again to write the closed one",
    "chosen": "default theme: chosen for this render",
}
FIELD = re.compile(r"[A-Za-z0-9_.\[\]-]{0,40}")


class ThemeError(Exception):
    """A theme that is refused: a closed `code`, the `field` it names (a path of closed key names, never a value) and `sentence`, the
    fixed instruction for the person."""

    def __init__(self, code: str, field: str = "", sentence: str = ""):
        super().__init__(f"{code} {field}".strip())
        self.code, self.field, self.sentence = code, field if FIELD.fullmatch(field or "") else "", sentence or SENTENCES.get(code, "")


# --- the renderer's own data -----------------------------------------------------------------------------------------------------


def _load(root: str, parts: tuple) -> dict:
    with open(os.path.join(root, *parts), encoding="utf-8") as f:
        return json.load(f)


def default_root() -> str:
    """The checkout this file is in (runtime/ sits directly under it)."""
    return os.path.dirname(HERE)


def renderer_theme(root: str) -> dict:
    """The renderer's `theme` section: {"colors": {token: "#RRGGBB"}, "font_roles": [...], ...}."""
    return _load(root, PRESETS)["theme"]


def font_ids(root: str) -> dict:
    """{(family, weight): id} of the renderer's font allow-list."""
    return {(row["family"], row["weight"]): row["id"] for row in _load(root, ALLOWLIST)["fonts"]}


# --- contrast --------------------------------------------------------------------------------------------------------------------


def _luminance(colour: str) -> float:
    lin = []
    for i in (1, 3, 5):
        c = int(colour[i:i + 2], 16) / 255
        lin.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(fg: str, bg: str) -> float:
    """The WCAG 2 contrast ratio of two #RRGGBB colours (the formula of skills/brand-identity/scripts/contrast.py, held equal by a test)."""
    hi, lo = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# --- the identity file -----------------------------------------------------------------------------------------------------------


def read_identity(project: str):
    """The text of the project's identity, or None when there is no such file. ThemeError (identity_unreadable) for a link, a file that
    is not a regular one, one over IDENTITY_LIMIT, one whose folders lead out of the project, or text that is not UTF-8 (the rules of
    pipeline.post_file)."""
    path = os.path.join(project, *IDENTITY.split("/"))
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError:
        raise ThemeError("identity_unreadable", "identity") from None
    inside = os.path.realpath(os.path.dirname(path)).startswith(os.path.realpath(project) + os.sep)
    if not stat.S_ISREG(info.st_mode) or info.st_size > IDENTITY_LIMIT or not inside:
        raise ThemeError("identity_unreadable", "identity")
    try:
        with open(path, "rb") as f:
            return f.read(IDENTITY_LIMIT + 1).decode("utf-8")
    except (OSError, UnicodeDecodeError):
        raise ThemeError("identity_unreadable", "identity") from None


# --- the theme -------------------------------------------------------------------------------------------------------------------


def _record(source: str, reason, colors: dict, fonts: dict, notes: list) -> dict:
    body = {"source": source, "reason": reason, "colors": colors, "fonts": fonts, "notes": notes}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return dict(body, hash=digest)


def _default(reason: str):
    return [], _record("default", reason, {}, {}, [])


def _column(role: dict) -> str:
    return (role.get("dark") or role.get("light")).upper()


def theme_args(project: str, root: str = None, use_default: bool = False):
    """(args, record): the arguments `--color TOKEN=#RRGGBB` and `--font ROLE=ID:WEIGHT` for the renderer's `base`, and the record of
    where they came from: {"source": "identity" | "default", "reason": None | "no_identity" | "no_tokens_block" | "open_block" | "chosen",
    "colors": {token: #RRGGBB, as passed}, "fonts": {role: "ID:WEIGHT", as passed}, "notes": [{"role", "asked", "used", "reason"}],
    "hash"} (the hash of the other fields, so that it differs when the effective theme does). No identity, no block or an open block
    gives no arguments (the renderer's default theme) and says why; `use_default` is the person's choice of that for this render.
    ThemeError for everything in the module's docstring that is refused."""
    root = root or default_root()
    if use_default:
        return _default("chosen")
    text = read_identity(project)
    if text is None:
        return _default("no_identity")
    state = tokens.document_status(text)
    if state == "draft":
        raise ThemeError("theme_draft", "status")
    if state == "unknown":
        raise ThemeError("theme_status_unknown", "status")
    obj, found = tokens.parse(text)
    if found and found[0]["code"] == "block_missing":
        return _default("no_tokens_block")
    if found and found[0]["code"] == "block_open":
        return _default("open_block")
    if found:
        first = found[0]
        raise ThemeError(REFUSAL_OF.get(first["code"], "theme_block_invalid"), first["field"])
    if obj["status"] != "approved":
        raise ThemeError("theme_draft", "status")
    return _from_block(obj, renderer_theme(root), font_ids(root))


def _from_block(block: dict, renderer: dict, ids: dict):
    palette = renderer["colors"]
    chosen = {role: _column(spec) for role, spec in block["color"].items()}
    colors = {token: chosen[role] for role, token in COLOR_MAP}
    colors["chip_border"] = chosen["accent"]
    fill = chosen.get("surface")
    if fill:
        colors["chip_fill"] = fill
    effective_fill = colors.get("chip_fill", palette["chip_fill"])
    colors["chip_text"] = chosen["accent"] if ratio(chosen["accent"], effective_fill) >= MIN_TEXT_RATIO else chosen["fg"]
    shown = dict(colors, chip_fill=effective_fill)
    for token, base in PAIRS:
        value = ratio(shown[token], shown[base])
        if value < MIN_TEXT_RATIO:
            name = "%s on %s" % (token.replace("_", " "), base.replace("_", " "))
            raise ThemeError("theme_low_contrast", "%s_on_%s" % (token, base), LOW_CONTRAST_SENTENCE % (name, "%.2f" % value))
    fonts, notes = {}, []
    for role, target in FONT_MAP:
        spec = block["font"].get(role)
        if spec is None:
            continue
        found = ids.get((spec["family"], spec["weight"]))
        if found and target in renderer["font_roles"]:
            fonts[target] = "%s:%d" % (found, spec["weight"])
        else:
            notes.append({"role": target, "asked": "%s %d" % (spec["family"], spec["weight"]), "used": "default", "reason": "not_on_allow_list"})
    args = []
    for token in sorted(colors):
        args += ["--color", "%s=%s" % (token, colors[token])]
    for role in sorted(fonts):
        args += ["--font", "%s=%s" % (role, fonts[role])]
    return args, _record("identity", None, {t: colors[t] for t in sorted(colors)}, {r: fonts[r] for r in sorted(fonts)}, notes)


def describe(record: dict) -> str:
    """The one sentence for a record that used the default theme (REASONS), else the empty string."""
    return REASONS.get(record.get("reason"), "") if record.get("source") == "default" else ""
