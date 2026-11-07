"""Check C8 (layout fit), host side, from the boxes measure.mjs took: does every caption chunk (1 to 3 words) fit the caption band and the frame, and where is
the lowest pixel drawn? Numbers only (no word of the recording).
  python3 -I c8.py --renderer-src .../providers/renderer --edl edl.json --beats beats.json --boxes boxes.json --vocabulary V --out c8.json
"""
import argparse, json, sys

p = argparse.ArgumentParser()
p.add_argument("--renderer-src", required=True); p.add_argument("--edl", required=True); p.add_argument("--beats", required=True)
p.add_argument("--boxes", required=True); p.add_argument("--vocabulary", required=True); p.add_argument("--out", required=True)
a = p.parse_args()
sys.path.insert(0, a.renderer_src)
import _edl, _vocab  # noqa: E402

data = _vocab.load_data(); vocab = _vocab.load_vocabulary(a.vocabulary)
edl = _vocab.read_json(a.edl); beats = _vocab.read_json(a.beats)
tl = _edl.resolve_timeline(edl, beats, vocab, data)
m = json.load(open(a.boxes))
W, H = edl["size"]
out = {"caption": {"frames": 0, "max_right": 0, "min_left": 1e9, "max_bottom": 0, "min_top": 1e9, "outside_frame": 0, "below_1620": 0, "below_1560": 0, "above_band": 0},
       "card": {"frames": 0, "outside_frame": 0, "outside_band": 0, "max_bottom": 0}}
for f, boxes in enumerate(m["per_frame"]):
    for zone in ("caption", "card"):
        zb = [b for b in boxes if b["zone"] == zone]
        if not zb:
            continue
        if zone == "caption":      # the glyphs, not the element box (a block-level word spans the whole width): the text range of each box
            zb = [dict(b, x=b["tx"], y=b["ty"], w=b["tw"], h=b["th"]) for b in zb if b.get("tw", 0) > 0]
            settled = [b for b in zb if b.get("op", 1) >= 0.95]
            if settled and any(b["x"] < -0.5 or b["x"] + b["w"] > W + 0.5 for b in settled):
                out["caption"]["outside_frame_settled"] = out["caption"].get("outside_frame_settled", 0) + 1
            if not zb:
                continue
        o = out[zone]; o["frames"] += 1
        left, right = min(b["x"] for b in zb), max(b["x"] + b["w"] for b in zb)
        top, bottom = min(b["y"] for b in zb), max(b["y"] + b["h"] for b in zb)
        o["max_bottom"] = max(o["max_bottom"], round(bottom, 1))
        if any(b["x"] < -0.5 or b["x"] + b["w"] > W + 0.5 or b["y"] < -0.5 or b["y"] + b["h"] > H + 0.5 for b in zb):
            o["outside_frame"] += 1
        if zone == "caption":
            o["max_right"] = max(o["max_right"], round(right, 1)); o["min_left"] = min(o["min_left"], round(left, 1)); o["min_top"] = min(o["min_top"], round(top, 1))
            o["box_width_max"] = max(o.get("box_width_max", 0), round(max(b["w"] for b in zb), 1))
            o["frame_margin_min"] = min(o.get("frame_margin_min", 1e9), round(min(min(b["x"] for b in zb), W - max(b["x"] + b["w"] for b in zb)), 1))
            if bottom > 1620.5: o["below_1620"] += 1
            if bottom > 1560.5: o["below_1560"] += 1
            ent = [e for e in tl["captions"] if e["start_frame"] <= f < e["end_frame"]]
            if ent:
                band = _edl.zones(data, ent[0]["face"])["caption"]
                if top < band[0] - 0.5: o["above_band"] += 1
        else:
            ent = [e for e in tl["beats"] if e["start_frame"] <= f < e["end_frame"]]
            if ent:
                band = _edl.zones(data, ent[0]["face"])["card"]
                if top < band[0] - 0.5 or bottom > band[1] + 0.5: o["outside_band"] += 1
sizes = [e["word_to"] - e["word_from"] + 1 for e in tl["captions"]]
out["chunks"] = {"count": len(sizes), "words_min": min(sizes), "words_max": max(sizes)}
json.dump(out, open(a.out, "w"), indent=1); print(json.dumps(out))
