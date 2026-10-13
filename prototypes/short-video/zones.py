"""Zones of the picture: where the face is, where cards and captions may go. Pure functions.

The face box is given per recording, in OUTPUT pixels (`--face x,y,w,h`). Framing changes the picture at each cut
(a punch-in about a fixed point, optionally a slow push), so the zones are computed from the box as it is at the most
zoomed moment, not as it is at 100%:

  expanded face   the face box scaled by the largest zoom (punch-in times push) about the anchor point
  top band        from `top_margin` down to `gap` above the expanded face: cards and lists live here
  caption zone    from `gap` below the expanded face down to `bottom_margin` above the frame's bottom edge

A rectangle an overlay draws is refused when it intersects the expanded face box. With no face box the zones are the
fixed bands of the earlier prototype (`NO_FACE`), and nothing is refused.
"""

NO_FACE = {"top_band": (285, 700), "caption_zone": (1000, 1248)}


class ZoneError(ValueError):
    pass


def parse_box(text):
    """'x,y,w,h' -> (x, y, w, h) integers, positive size."""
    try:
        x, y, w, h = [int(round(float(p))) for p in text.split(",")]
    except (ValueError, AttributeError):
        raise ZoneError("a box is x,y,w,h in pixels")
    if w <= 0 or h <= 0 or x < 0 or y < 0:
        raise ZoneError("a box has a positive size and a position inside the frame")
    return x, y, w, h


def anchor_point(face, anchor_y):
    """The fixed point of a zoom: the face's horizontal centre and `anchor_y` of the box height from its top."""
    x, y, w, h = face
    return x + w / 2.0, y + anchor_y * h


def scale_box(box, factor, point):
    """The box scaled by `factor` about `point`."""
    x, y, w, h = box
    px, py = point
    return (px + (x - px) * factor, py + (y - py) * factor, w * factor, h * factor)


def expanded_face(face, zoom, push, anchor_y):
    """The face box at the most zoomed moment (zoom * (1 + push)), about the zoom's fixed point."""
    return scale_box(face, zoom * (1.0 + push), anchor_point(face, anchor_y))


def intersects(a, b, margin=0.0):
    """Do rectangles (x, y, w, h) intersect (with `margin` pixels added around b)?"""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx - margin or bx + bw + margin <= ax or ay + ah <= by - margin or by + bh + margin <= ay)


def compute(face, frame, zoom, push, anchor_y, top_margin=110, bottom_margin=300, gap=18):
    """Zones for a recording. `frame` is (width, height). Returns a dict (all numbers in output pixels)."""
    w, h = frame
    if face is None:
        return {"face": None, "face_expanded": None, "top_band": list(NO_FACE["top_band"]),
                "caption_zone": list(NO_FACE["caption_zone"])}
    ex = expanded_face(face, zoom, push, anchor_y)
    top = [top_margin, int(ex[1] - gap)]
    cap = [int(ex[1] + ex[3] + gap), h - bottom_margin]
    if top[1] - top[0] < 80:
        raise ZoneError("the band above the face is only %d px tall (needs 80): lower --zoom, anchor the zoom higher, "
                        "or give a smaller face box" % (top[1] - top[0]))
    if cap[1] - cap[0] < 120:
        raise ZoneError("the zone below the face is only %d px tall (needs 120)" % (cap[1] - cap[0]))
    return {"face": list(face), "face_expanded": [round(v, 1) for v in ex], "top_band": top, "caption_zone": cap}


def check_rect(rect, zones, what="overlay"):
    """Raise ZoneError when an overlay rectangle (x, y, w, h) intersects the expanded face box."""
    ex = zones.get("face_expanded")
    if ex is not None and intersects(rect, ex):
        raise ZoneError("%s rectangle %s intersects the face box %s" % (what, [round(v) for v in rect], [round(v) for v in ex]))
