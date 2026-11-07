"""Check C6 (the face-box guard), host side: reads the boxes measure.mjs took after the seek of every frame and applies OUR rule (`_frames.face_hit`)
to each. The face box of a frame is the one the timeline gives for the caption chunk and the beat on screen at that frame (the zoomed box).

  python3 -I c6.py --renderer-src .work/branch-src/providers/renderer --edl edl.json --beats beats.json --boxes boxes.json --vocabulary V --out c6.json
"""
import argparse, json, sys

p = argparse.ArgumentParser()
p.add_argument("--renderer-src", required=True); p.add_argument("--edl", required=True); p.add_argument("--beats", required=True)
p.add_argument("--glyph", action="store_true", help="test the glyph extent (the text range) of each caption box instead of the element box")
p.add_argument("--boxes", required=True); p.add_argument("--vocabulary", required=True); p.add_argument("--out", required=True)
a = p.parse_args()
sys.path.insert(0, a.renderer_src)
import _edl, _frames, _vocab  # noqa: E402

data = _vocab.load_data()
vocab = _vocab.load_vocabulary(a.vocabulary)
edl = _vocab.read_json(a.edl); beats = _vocab.read_json(a.beats)
tl = _edl.resolve_timeline(edl, beats, vocab, data)
measured = json.load(open(a.boxes))
hits, checked, drawn_frames = [], 0, 0
for f, boxes in enumerate(measured["per_frame"]):
    if not boxes:
        continue
    drawn_frames += 1
    faces = {"caption": None, "card": None}
    for e in tl["captions"]:
        if e["start_frame"] <= f < e["end_frame"]:
            faces["caption"] = e["face"]
    for e in tl["beats"]:
        if e["start_frame"] <= f < e["end_frame"]:
            faces["card"] = e["face"]
    for b in boxes:
        face = faces[b["zone"]] or edl["face_box"]      # a box drawn while no entry is on (a fade tail) is held to the plain face box
        checked += 1
        if a.glyph and b["zone"] == "caption" and b.get("tw", 0) > 0:
            b = dict(b, x=b["tx"], y=b["ty"], w=b["tw"], h=b["th"])
        hit = _frames.face_hit([{"zone": b["zone"], "x": b["x"], "y": b["y"], "w": b["w"], "h": b["h"]}], face)
        if hit:
            hits.append({"frame": f, "zone": b["zone"], "cls": b["cls"], "box": [round(b[k], 1) for k in "xywh"], "face": [face[k] for k in "xywh"]})
res = {"frames": measured["frames"], "frames_with_drawn_boxes": drawn_frames, "boxes_checked": checked, "hits": len(hits), "first_hits": hits[:5],
       "hit_frames": sorted({h["frame"] for h in hits})[:40], "console_errors": measured.get("console_errors", [])[:5]}
json.dump(res, open(a.out, "w"), indent=1)
print(json.dumps({k: res[k] for k in ("frames", "frames_with_drawn_boxes", "boxes_checked", "hits")}))
