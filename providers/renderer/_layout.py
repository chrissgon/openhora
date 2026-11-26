"""Where things may be drawn: the two bands the face box leaves, the pip's card, the split's halves, the test of a caption against the bottom line. Pure arithmetic on the numbers of renderer-presets.json: no browser, no frames. The ffmpeg engine's drawing loop imports this
file. Standard library only.
"""
from __future__ import annotations

import _advice


def rooms(data: dict, face: dict) -> dict:
    """The room the face box leaves, unclamped, in frame pixels: `card` above it (from `card_top` to the face minus `gap`) and `caption` below it (from the face plus
    `gap` to `caption_bottom`). It can be small or negative: that is advice (`card_room_small`, `caption_room_small`), never a refusal."""
    z = data["zones"]
    return {"card": face["y"] - z["gap"] - z["card_top"], "caption": z["caption_bottom"] - (face["y"] + face["h"] + z["gap"])}


def zones(data: dict, face: dict) -> dict:
    """The two bands the face box leaves: cards above it, captions below it. [top, bottom] in frame pixels. A band the face leaves under its minimum
    (`zones.card_min_height`, `zones.caption_min_height`) is clamped to that minimum, over the face: the edit renders and `check_face` reports the advice."""
    z = data["zones"]
    return {"card": [z["card_top"], max(face["y"] - z["gap"], z["card_top"] + z["card_min_height"])],
            "caption": [min(face["y"] + face["h"] + z["gap"], z["caption_bottom"] - z["caption_min_height"]), z["caption_bottom"]]}


def entry_zones(data: dict, entry: dict) -> dict:
    """The bands of one entry (a beat or a caption chunk): the two the face box leaves, with the caption band replaced by `entry["band"]`
    ([top, bottom]) when a pip's card takes part of it (`pip_cards`)."""
    z = zones(data, entry["face"])
    if entry.get("band"):
        z["caption"] = list(entry["band"])
    return z


def pip_card(data: dict, face: dict, position: str, asset_w: int, asset_h: int, strict: bool = True, fallback: bool = False):
    """The box {x, y, w, h} of a pip's card, or None when no card fits (only an asset with no size; under `pip.card_min_height` of room a `fallback` card is drawn).

    The asset goes whole into the box (contain): at most the safe width wide and as high as the room allows, at most `pip.card_max_height`.
    The room runs from the face box's bottom plus `gap` down to `caption_bottom`; no caption band is kept under the card, the captions are
    drawn over its lower part (`pip_cards`). With `position` top the card's top is the face box's bottom plus `gap`; with bottom the card's
    bottom is `caption_bottom`. It is centred. Under `pip.card_min_height` of room there is no card (unless `strict` is false, the storyboard's
    way: the card is then as high as the room allows, at least 1 px), or, with `fallback`, a card `card_min_height` rows tall whose bottom is at `caption_bottom`,
    drawn over the face's lower part (advice `pip_card_over_face`; the maintainer's decision of 2026-11-24 that "no room" refuses nothing)."""
    z, f, p = data["zones"], data["frame"], data["pip"]
    below = face["y"] + face["h"] + z["gap"]
    room = z["caption_bottom"] - below
    cap = min(p["card_max_height"], room)
    if asset_w < 1 or asset_h < 1:
        return None
    over = False
    if strict and cap < p["card_min_height"]:
        if not fallback:
            return None
        cap, over = p["card_min_height"], True
    cap = max(1, cap)
    max_w = f["width"] - f["safe"]["left"] - f["safe"]["right"]
    scale = min(max_w / asset_w, cap / asset_h)
    w, h = max(1, min(max_w, int(round(asset_w * scale)))), max(1, min(cap, int(round(asset_h * scale))))
    y = below if position != "bottom" and not over else z["caption_bottom"] - h
    return {"x": (f["width"] - w) // 2, "y": y, "w": w, "h": h}


def pip_cards(data: dict, timeline: dict, assets: dict, drop: bool = True, advice=None) -> list:
    """Settle every pip of the timeline, in place: each gets `entry["card"]`. Under `pip.card_min_height` of room below the face the card is the fallback of
    `pip_card` and a `pip_card_over_face` row goes to `advice` (a list of `_advice`, when given); no pip is dropped for room any more (`pip_no_room` stays in the
    closed lists so that a stored delivery document still checks). Each caption chunk that shares
    frames with a pip gets `chunk["band"]`, the card's lower `caption_min_height` pixels: its words are drawn over the bottom of the card and
    never above its top; the band is inside the card. `drop` false (the storyboard, which draws no captions) keeps
    every pip, with the card the room allows. Returns the rows of `dropped_reasons`, which this function no longer adds to."""
    least = data["zones"]["caption_min_height"]
    kept, rows = [], timeline.setdefault("dropped_reasons", [])
    for e in timeline["beats"]:
        if e["preset"] == "pip":
            a = assets[e["params"]["asset"]]
            card = pip_card(data, e["face"], e["params"].get("position", "top"), a["width"], a["height"], drop, fallback=drop)
            if card is not None and drop and advice is not None:
                room = data["zones"]["caption_bottom"] - (e["face"]["y"] + e["face"]["h"] + data["zones"]["gap"])
                if min(data["pip"]["card_max_height"], room) < data["pip"]["card_min_height"]:
                    _advice.add(advice, "pip_card_over_face", max(0, room), data["pip"]["card_min_height"], e["id"])
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


def split_geometry(data: dict, face: dict, side: str, fallback: bool = False) -> dict:
    """The geometry of `_split_geometry`, alone."""
    return _split_geometry(data, face, side, fallback)[0]


def _split_geometry(data: dict, face: dict, side: str, fallback: bool = False) -> tuple:
    """Where a split beat draws, for its `side` (the half the picture takes) and its face box (the entry's `face`, in output pixels).

    asset, speaker: the two halves {x, y, w, h}; top and bottom split the frame at y = height // 2, left and right at x = width // 2.
    crop: the part of the picture ffmpeg lays into the speaker half, the size of that half, not scaled, centred on the face and kept
    inside the frame. moved_face: the face box as the crop puts it, clipped to the speaker half. band: the caption band [top, bottom],
    the lowest stretch of rows inside [frame.safe.top, zones.caption_bottom] at least zones.caption_min_height tall that keeps `gap`
    from the face as it was, from the moved face and, for top and bottom, from the whole speaker half (so never across the seam);
    None when there is none, unless `fallback` is true: the band is then [caption_bottom - caption_min_height, caption_bottom], over the face (advice
    `split_band_over_face`). bar: for left and right, the band cut to split.bar_height rows, which the page covers with an opaque bar
    across the frame so that no seam runs under a caption; None otherwise. label: where the page puts the label chip, {x, max_w, top, bottom} (one of top and bottom is None). For top and bottom it is in the
    asset half's corner nearest the seam, at the left of the safe width. For left and right it is at the top-left of the asset half, inside the
    safe area: x is the half's left edge plus split.label_inset, at least frame.safe.left, and top is frame.safe.top. For right that corner is
    beside the seam; for left it is at the frame's outer edge, away from the seam."""
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
    largest = max((iv[1] - iv[0] for iv in free), default=0)
    if band is None and fallback:
        band = [z["caption_bottom"] - z["caption_min_height"], z["caption_bottom"]]
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
            "crop": crop, "moved_face": moved, "band": band, "bar": bar, "label": label}, max(0, largest)


def caption_pieces(chunk: dict, splits: list) -> list:
    """One caption chunk cut at every first or last frame of a split that falls strictly inside it, as caption entries in frame order. A piece
    is the chunk itself (its words, its `face`, its pip `band` if any) on fewer frames. A piece inside a split whose band is set takes that band
    as `band`, and as `face` the union of its face and the moved face. Pieces outside every split keep the chunk's band and face. Beats never
    overlap (one beat track; a text beat yields to a picture, V9b-3e), so a piece is inside at most one split."""
    cuts = sorted({f for e in splits for f in (e["start_frame"], e["end_frame"]) if chunk["start_frame"] < f < chunk["end_frame"]})
    edges = [chunk["start_frame"]] + cuts + [chunk["end_frame"]]
    out = []
    for a, b in zip(edges, edges[1:]):
        piece = dict(chunk, start_frame=a, end_frame=b, face=dict(chunk["face"]))
        if "band" in chunk:
            piece["band"] = list(chunk["band"])
        for e in splits:
            if e["split"]["band"] and e["start_frame"] < b and a < e["end_frame"]:
                piece["band"] = list(e["split"]["band"])
                moved = e["split"]["moved_face"]
                if moved["w"] and moved["h"]:
                    piece["face"] = _union([piece["face"], moved])
        out.append(piece)
    return out


def split_layouts(data: dict, timeline: dict, drop: bool = True, advice=None) -> list:
    """Settle every split of the timeline, in place: each gets `entry["split"]` (`split_geometry`, its side from the params, `bottom` by
    default). One that leaves no caption band clear of the face gets the fallback band when `drop` is true (a `split_band_over_face` row goes to `advice`, a
    list of `_advice`, when given); no split is dropped for room any more (`split_no_room` stays in the closed lists so that a stored delivery document still checks). When a split is kept, every caption chunk is replaced by its pieces
    (`caption_pieces`): a chunk is cut at each split edge inside it, so a piece inside a split has that split's band and the moved face, and
    a piece outside keeps what it had. With no split kept, `timeline["captions"]` is not touched. Call it after `pip_cards`, which resets every
    caption's band. `drop` false (the storyboard, which draws no captions) keeps every split. Returns the rows it added."""
    kept, added = [], []
    rows = timeline.setdefault("dropped_reasons", [])
    for e in timeline["beats"]:
        if e["preset"] == "split":
            geom, largest = _split_geometry(data, e["face"], e["params"].get("side", "bottom"), fallback=drop)
            if drop and advice is not None and largest < data["zones"]["caption_min_height"]:
                _advice.add(advice, "split_band_over_face", largest, data["zones"]["caption_min_height"], e["id"])
            e["split"] = geom
        kept.append(e)
    timeline["beats"][:] = kept
    splits = [e for e in kept if e["preset"] == "split"]
    if splits:
        timeline["captions"][:] = [p for c in timeline["captions"] for p in caption_pieces(c, splits)]
    return added


def split_rows(timeline: dict) -> list:
    """The compose plan's rows of the settled splits (`_media.compose_argv`): {start_frame, end_frame, crop {x, y, w, h}, at {x, y}}."""
    return [{"start_frame": e["start_frame"], "end_frame": e["end_frame"], "crop": dict(e["split"]["crop"]),
             "at": {"x": e["split"]["speaker"]["x"], "y": e["split"]["speaker"]["y"]}} for e in timeline["beats"] if e["preset"] == "split"]


def caption_hit(box: dict, zones: dict) -> bool:
    """True when the drawn caption box's bottom (`y + h`) is below the line the caption band ends at (`zones["caption"][1]`, the
    presets' `zones.caption_bottom`: 1560 clears the apps' interface, decision VD12)."""
    return box["y"] + box["h"] > zones["caption"][1]
