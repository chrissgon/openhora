"""Where things may be drawn: the two bands the face box leaves, the pip's card, the split's halves, the test of a drawn box against the
face and the test of a caption against the bottom line. Pure arithmetic on the numbers of renderer-presets.json: no browser, no frames. Both engines import this
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

    The asset goes whole into the box (contain): at most the safe width wide and as high as the room allows, at most `pip.card_max_height`.
    The room runs from the face box's bottom plus `gap` down to `caption_bottom`; no caption band is kept under the card, the captions are
    drawn over its lower part (`pip_cards`). With `position` top the card's top is the face box's bottom plus `gap`; with bottom the card's
    bottom is `caption_bottom`. It is centred. Under `pip.card_min_height` of room there is no card (unless `strict` is false, the storyboard's
    way: the card is then as high as the room allows, at least 1 px)."""
    z, f, p = data["zones"], data["frame"], data["pip"]
    below = face["y"] + face["h"] + z["gap"]
    room = z["caption_bottom"] - below
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
    frames with a pip gets `chunk["band"]`, the card's lower `caption_min_height` pixels: its words are drawn over the bottom of the card and
    never above its top; the band is inside the card, which is below the face. `drop` false (the storyboard, which draws no captions) keeps
    every pip, with the card the room allows. Returns the rows of `dropped_reasons`."""
    least = data["zones"]["caption_min_height"]
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
        top, bottom = None, None
        for e in kept:
            if e["preset"] == "pip" and e["start_frame"] < c["end_frame"] and c["start_frame"] < e["end_frame"]:
                card = e["card"]
                lo, hi = max(card["y"], card["y"] + card["h"] - least), card["y"] + card["h"]
                top, bottom = (lo, hi) if top is None else (max(top, lo), min(bottom, hi))
        if top is not None:
            c["band"] = [top, bottom]
    return rows


def _union(boxes: list) -> dict:
    """The smallest box holding every box (the same arithmetic as `_edl.union`, which imports this module)."""
    left, top = min(b["x"] for b in boxes), min(b["y"] for b in boxes)
    right, bottom = max(b["x"] + b["w"] for b in boxes), max(b["y"] + b["h"] for b in boxes)
    return {"x": left, "y": top, "w": right - left, "h": bottom - top}


SPLIT_SIDES = ("top", "bottom", "left", "right")


def split_geometry(data: dict, face: dict, side: str) -> dict:
    """Where a split beat draws, for its `side` (the half the picture takes) and its face box (the entry's `face`, in output pixels).

    asset, speaker: the two halves {x, y, w, h}; top and bottom split the frame at y = height // 2, left and right at x = width // 2.
    crop: the part of the picture ffmpeg lays into the speaker half, the size of that half, not scaled, centred on the face and kept
    inside the frame. moved_face: the face box as the crop puts it, clipped to the speaker half. band: the caption band [top, bottom],
    the lowest stretch of rows inside [frame.safe.top, zones.caption_bottom] at least zones.caption_min_height tall that keeps `gap`
    from the face as it was, from the moved face and, for top and bottom, from the whole speaker half (so never across the seam);
    None when there is none. bar: for left and right, the band cut to split.bar_height rows, which the page covers with an opaque bar
    across the frame so that no seam runs under a caption; None otherwise. label: where the page puts the label chip, in the asset
    half's corner nearest the seam: {x, max_w, top, bottom} (one of top and bottom is None)."""
    f, z, sp = data["frame"], data["zones"], data["split"]
    W, H = f["width"], f["height"]
    hw, hh = W // 2, H // 2
    halves = {"top": ((0, 0, W, hh), (0, hh, W, H - hh)), "bottom": ((0, hh, W, H - hh), (0, 0, W, hh)),
              "left": ((0, 0, hw, H), (hw, 0, W - hw, H)), "right": ((hw, 0, W - hw, H), (0, 0, hw, H))}
    (ax, ay, aw, ah), (sx, sy, sw, sh) = halves[side]
    cx, cy = face["x"] + face["w"] // 2, face["y"] + face["h"] // 2
    crop = {"x": min(max(cx - sw // 2, 0), W - sw), "y": min(max(cy - sh // 2, 0), H - sh), "w": sw, "h": sh}
    dx, dy = sx - crop["x"], sy - crop["y"]
    x0, y0 = max(sx, face["x"] + dx), max(sy, face["y"] + dy)
    x1, y1 = min(sx + sw, face["x"] + face["w"] + dx), min(sy + sh, face["y"] + face["h"] + dy)
    moved = {"x": x0, "y": y0, "w": max(0, x1 - x0), "h": max(0, y1 - y0)}
    gap = z["gap"]
    blocked = [(face["y"] - gap, face["y"] + face["h"] + gap)]
    if moved["w"] and moved["h"]:
        blocked.append((moved["y"] - gap, moved["y"] + moved["h"] + gap))
    if side in ("top", "bottom"):
        blocked.append((sy - gap, sy + sh + gap))
    free, top = [], f["safe"]["top"]
    for lo, hi in sorted(blocked):
        if lo > top:
            free.append((top, min(lo, z["caption_bottom"])))
        top = max(top, hi)
    if top < z["caption_bottom"]:
        free.append((top, z["caption_bottom"]))
    room = [iv for iv in free if iv[1] - iv[0] >= z["caption_min_height"]]
    band = list(max(room, key=lambda iv: iv[1])) if room else None
    bar = None
    if band and side in ("left", "right"):
        band = [band[0], min(band[1], band[0] + sp["bar_height"])]
        bar = list(band)
    inset = sp["label_inset"]
    lx0, lx1 = max(ax + inset, f["safe"]["left"]), min(ax + aw - inset, W - f["safe"]["right"])
    label = {"x": lx0, "max_w": lx1 - lx0, "top": None, "bottom": None}
    if side == "bottom":
        label["top"] = ay + inset
    elif side == "top":
        label["bottom"] = H - (ay + ah - inset)
    else:
        label["top"] = f["safe"]["top"]
    return {"side": side, "asset": {"x": ax, "y": ay, "w": aw, "h": ah}, "speaker": {"x": sx, "y": sy, "w": sw, "h": sh},
            "crop": crop, "moved_face": moved, "band": band, "bar": bar, "label": label}


def split_layouts(data: dict, timeline: dict, drop: bool = True) -> list:
    """Settle every split of the timeline, in place: each gets `entry["split"]` (`split_geometry`, its side from the params, `bottom` by
    default), or, when it leaves no caption band and `drop` is true, is taken out of `timeline["beats"]` (its id to `timeline["dropped"]`, a
    {id, reason: split_no_room} row to `timeline["dropped_reasons"]`). Each caption chunk that shares frames with a kept split gets that split's
    band as `chunk["band"]` (a later split wins) and, as its `face`, the union of its face and the moved face. Call it after `pip_cards`, which
    resets every caption's band. `drop` false (the storyboard, which draws no captions) keeps every split. Returns the rows it added."""
    kept, added = [], []
    rows = timeline.setdefault("dropped_reasons", [])
    for e in timeline["beats"]:
        if e["preset"] == "split":
            geom = split_geometry(data, e["face"], e["params"].get("side", "bottom"))
            if geom["band"] is None and drop:
                timeline["dropped"].append(e["id"])
                row = {"id": e["id"], "reason": "split_no_room"}
                rows.append(row)
                added.append(row)
                continue
            e["split"] = geom
        kept.append(e)
    timeline["beats"][:] = kept
    for c in timeline["captions"]:
        for e in kept:
            if e["preset"] == "split" and e["split"]["band"] and e["start_frame"] < c["end_frame"] and c["start_frame"] < e["end_frame"]:
                c["band"] = list(e["split"]["band"])
                moved = e["split"]["moved_face"]
                if moved["w"] and moved["h"]:
                    c["face"] = _union([c["face"], moved])
    return added


def split_rows(timeline: dict) -> list:
    """The compose plan's rows of the settled splits (`_media.compose_argv`): {start_frame, end_frame, crop {x, y, w, h}, at {x, y}}."""
    return [{"start_frame": e["start_frame"], "end_frame": e["end_frame"], "crop": dict(e["split"]["crop"]),
             "at": {"x": e["split"]["speaker"]["x"], "y": e["split"]["speaker"]["y"]}} for e in timeline["beats"] if e["preset"] == "split"]


def face_hit(boxes: list, face: dict):
    """The zone (`card` or `caption`) of the first drawn box that touches the face box, else None. Layout presets
    (cutaway, split) are not in a zone: they replace the picture. A pip's card box is marked `card`, so the check covers it."""
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
