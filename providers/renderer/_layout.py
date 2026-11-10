"""Where things may be drawn: the two bands the face box leaves, the test of a drawn box against the face and the test of a caption
against the bottom line. Pure arithmetic on the numbers of renderer-presets.json: no browser, no frames. Both engines import this
file (the ffmpeg engine's drawing loop and, in V3b, the HyperFrames gate). Standard library only.
"""
from __future__ import annotations


def zones(data: dict, face: dict) -> dict:
    """The two bands the face box leaves: cards above it, captions below it. [top, bottom] in frame pixels."""
    z = data["zones"]
    return {"card": [z["card_top"], face["y"] - z["gap"]], "caption": [face["y"] + face["h"] + z["gap"], z["caption_bottom"]]}


def face_hit(boxes: list, face: dict):
    """The zone (`card` or `caption`) of the first drawn box that touches the face box, else None. Layout presets
    (cutaway, pip) are not in a zone: they replace the picture, they do not sit over the face."""
    for b in boxes:
        if b["zone"] in ("card", "caption") and b["w"] > 0 and b["h"] > 0 \
                and b["x"] < face["x"] + face["w"] - 0.5 and b["x"] + b["w"] > face["x"] + 0.5 \
                and b["y"] < face["y"] + face["h"] - 0.5 and b["y"] + b["h"] > face["y"] + 0.5:
            return b["zone"]
    return None


def caption_hit(box: dict, zones: dict) -> bool:
    """True when the drawn caption box's bottom (`y + h`) is below the line the caption band ends at (`zones["caption"][1]`, the
    presets' `zones.caption_bottom`: 1560 clears the apps' interface, decision VD12)."""
    return box["y"] + box["h"] > zones["caption"][1]
