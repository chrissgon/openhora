"""The data each drawing page is given for one frame: the caption chunk's words and bands, a beat's parameters, looks and bands, a pip's
geometry. Plain data from the checked documents and the layout arithmetic, no browser and no frames, so both engines (and the HyperFrames
page stage, which runs in the common image) build the same payload. Moved from `_frames.py` byte for byte (decision V3b-1); `_frames`
imports the three names back. Standard library only.
"""
from __future__ import annotations

import _layout


def pip_geometry(data: dict, entry: dict) -> dict:
    """The pip's card box {x, y, w, h}, settled by `_layout.pip_cards` and stored on the entry."""
    return dict(entry["card"])


def look_of(data: dict, edl: dict, preset: str) -> dict:
    """The look a beat of `preset` is drawn with (V9g): `presets.<preset>.looks`, with the variant the edit list's optional `looks` names for the
    preset laid over it (`presets.<preset>.variants.<name>`, plus `variant`: the name). With no such entry it is `presets.<preset>.looks` itself."""
    base = data["presets"][preset]["looks"]
    name = (edl.get("looks") or {}).get(preset)
    if not name:
        return base
    return dict(base, **data["presets"][preset]["variants"][name], variant=name)


def caption_data(data: dict, edl: dict, chunk: dict, by_index: dict, fps: int) -> dict:
    f = data["frame"]
    origin = chunk["start_frame"] / fps
    words = [by_index[i] for i in sorted(by_index) if chunk["word_from"] <= i <= chunk["word_to"]]
    out = {"duration": (chunk["end_frame"] - chunk["start_frame"]) / fps, "anchor": edl["captions"]["position"],
           "words": [{"text": w["text"], "start": round(w["start"] - origin, 4), "end": round(w["end"] - origin, 4)} for w in words],
           "zones": _layout.entry_zones(data, chunk), "margin": data["zones"]["caption_margin"]}
    if chunk.get("seam"):
        out["seam"] = True          # a piece inside a top or bottom split: the page draws it as a chip on the seam (V9g)
    return out


def beat_data(data: dict, entry: dict, fps: int, edl: dict) -> dict:
    out = {"params": entry["params"], "look": look_of(data, edl, entry["preset"]), "zones": _layout.zones(data, entry["face"]),
           "duration": (entry["end_frame"] - entry["start_frame"]) / fps}
    if entry["preset"] == "pip":
        out["geom"] = pip_geometry(data, entry)
    return out


def split_geometry_of(entry: dict) -> dict:
    """The split page's geometry (`data.geom`): the asset half, the caption bar, the label and the seam's feather (rows past the seam, 0 for left
    and right), settled by `_layout.split_layouts` and stored
    on the entry. The speaker's half is not the page's: ffmpeg lays the crop there."""
    g = entry["split"]
    return {"side": g["side"], "asset": dict(g["asset"]), "bar": list(g["bar"]) if g["bar"] else None, "label": dict(g["label"]),
            "feather": g["feather"]}
