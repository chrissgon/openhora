"""Where things may be drawn: the two bands the face box leaves, the test of a drawn box against the face and the test of a caption
against the bottom line. Pure arithmetic on the numbers of renderer-presets.json: no browser, no frames. Both engines import this
file (the ffmpeg engine's drawing loop and, in V3b, the HyperFrames gate). Standard library only.
"""
from __future__ import annotations


def zones(data: dict, face: dict) -> dict:
    """The two bands the face box leaves: cards above it, captions below it. [top, bottom] in frame pixels."""
    z = data["zones"]
    return {"card": [z["card_top"], face["y"] - z["gap"]], "caption": [face["y"] + face["h"] + z["gap"], z["caption_bottom"]]}


def entry_zones(data: dict, entry: dict) -> dict:
    """The bands of one entry (a beat or a caption chunk): the two the face box leaves, with the caption band replaced by `entry["band"]`
    ([top, bottom]) when a pip's card takes part of it (`pip_cards`)."""
    z = zones(data, entry["face"])
    if entry.get("band"):
        z["caption"] = list(entry["band"])
    return z


def pip_card(data: dict, face: dict, position: str, asset_w: int, asset_h: int, strict: bool = True):
    """The box {x, y, w, h} of a pip's card, or None when no card fits (the beat is then dropped: `pip_no_room`).

    The asset goes whole into the box (contain): at most the safe width wide and `pip.card_max_height` high, and not higher than the room
    left between the face box and the caption line once the captions have their minimum band. With `position` top the card's top is the
    face box's bottom plus `gap`; with bottom the card's bottom is `caption_bottom`. It is centred. Under `pip.card_min_height` of room
    there is no card (unless `strict` is false, the storyboard's way: the card is then as high as the room allows, at least 1 px)."""
    z, f, p = data["zones"], data["frame"], data["pip"]
    below = face["y"] + face["h"] + z["gap"]
    room = z["caption_bottom"] - below - z["gap"] - z["caption_min_height"]
    cap = min(p["card_max_height"], room)
    if asset_w < 1 or asset_h < 1 or (strict and cap < p["card_min_height"]):
        return None
    cap = max(1, cap)
    max_w = f["width"] - f["safe"]["left"] - f["safe"]["right"]
    scale = min(max_w / asset_w, cap / asset_h)
    w, h = max(1, min(max_w, int(round(asset_w * scale)))), max(1, min(cap, int(round(asset_h * scale))))
    y = below if position != "bottom" else z["caption_bottom"] - h
    return {"x": (f["width"] - w) // 2, "y": y, "w": w, "h": h}


def pip_cards(data: dict, timeline: dict, assets: dict, drop: bool = True) -> list:
    """Settle every pip of the timeline, in place: each gets `entry["card"]`, or is taken out of `timeline["beats"]` when no card fits (its
    id goes to `timeline["dropped"]` and a {id, reason: pip_no_room} row to `timeline["dropped_reasons"]`). Each caption chunk that shares
    frames with a pip gets `chunk["band"]`, the band the card leaves: below it for a card at the top, between the face and it for a card
    at the bottom. `drop` false (the storyboard, which draws no captions) keeps every pip, with the card the room allows. Returns the rows of `dropped_reasons`."""
    gap = data["zones"]["gap"]
    kept, rows = [], timeline.setdefault("dropped_reasons", [])
    for e in timeline["beats"]:
        if e["preset"] == "pip":
            a = assets[e["params"]["asset"]]
            card = pip_card(data, e["face"], e["params"].get("position", "top"), a["width"], a["height"], drop)
            if card is None:
                timeline["dropped"].append(e["id"])
                rows.append({"id": e["id"], "reason": "pip_no_room"})
                continue
            e["card"] = card
        kept.append(e)
    timeline["beats"][:] = kept
    for c in timeline["captions"]:
        c.pop("band", None)
        top, bottom = c["face"]["y"] + c["face"]["h"] + gap, data["zones"]["caption_bottom"]
        hit = False
        for e in kept:
            if e["preset"] == "pip" and e["start_frame"] < c["end_frame"] and c["start_frame"] < e["end_frame"]:
                hit = True
                card = e["card"]
                if e["params"].get("position", "top") == "bottom":
                    bottom = min(bottom, card["y"] - gap)
                else:
                    top = max(top, card["y"] + card["h"] + gap)
        if hit:
            c["band"] = [top, bottom]
    return rows


def face_hit(boxes: list, face: dict):
    """The zone (`card` or `caption`) of the first drawn box that touches the face box, else None. Layout presets
    (cutaway) is not in a zone: it replaces the picture. A pip's card box is marked `card`, so the check covers it."""
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
