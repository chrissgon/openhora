"""Framing at the cuts: a jump cut reads as an edit when the framing changes with it.

The kept ranges alternate between the full frame (zoom 1.0) and a punch-in (`zoom`, about 1.10) about a fixed point
(zones.anchor_point: the face's horizontal centre, `anchor_y` of the box height from its top). A long range also gets a
slow push-in, at most `push` (3 percent at the most) over its length. Pure data: the renderer turns it into a filter.
"""

MAX_PUSH = 0.03


def plan(kept, zoom=1.10, push=0.02, push_min=5.0, alternate=True):
    """[{z0, z1}] parallel to `kept` (source ranges): the zoom at the first and at the last frame of each range."""
    if push > MAX_PUSH + 1e-9 or push < 0:
        raise ValueError("push is a fraction between 0 and %.2f" % MAX_PUSH)
    if zoom < 1.0 or zoom > 1.25:
        raise ValueError("zoom is between 1.0 and 1.25")
    out = []
    for k, (a, b) in enumerate(kept):
        z0 = zoom if (alternate and k % 2 == 1) else 1.0
        z1 = z0 * (1.0 + push) if (b - a) >= push_min else z0
        out.append({"z0": round(z0, 4), "z1": round(z1, 4)})
    return out


def max_zoom(frames):
    return max((f["z1"] for f in frames), default=1.0)
