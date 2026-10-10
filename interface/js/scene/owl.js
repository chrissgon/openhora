// The owl of the scene (R-41, R4D-2): the brand mark's own drawing as flat meshes, in the mark's fixed palette. The palette
// below is the one place where this scene holds a colour literal: it is the brand's drawing, not the interface's (round 4, the brand's
// exception to "no colour literal"; the same rule keeps the brand pair in `css/base.css`). Everything else in the scene is a token or a mix.
//
// This module holds the owl's parts as data and builds them as flat shapes with `svgpath.js`; no texture, no HTML. The City's shadow (R-19) takes
// the owl's outline from it; the rooms (R-41) take the three poses, each a list of parts back to front: waiting (it faces the person, one wing raised),
// working (turned three-quarters to its desk, its wings apart on the keyboard) and idle (standing, eyes shut, three z). Coordinates are the mark's
// own: a viewBox of 200 by 200, y down; a built part is centred on the owl's feet (x 100, y 186) with y up, so an owl stands on the origin.
// `owl-build.js` makes the meshes and `owl-motion.js` moves them.

import { ellipseToShape, pathToLines, pathToShapes, strokeTriangles } from "./svgpath.js";

/** The mark's fixed palette. */
export const OWL_PALETTE = Object.freeze({
  ink: "#1E1B2E", brown: "#6B4429", tan: "#A47551", cream: "#E6D2BC", white: "#FFFFFF", yellow: "#FCD34D",
});

/** Where the owl stands in the mark's drawing: the point under its feet, and the extent of its body with the ear tufts. */
export const OWL_ORIGIN = Object.freeze({ x: 100, y: 186 });
export const OWL_BOUNDS = Object.freeze({ x0: 20, x1: 180, y0: 22, y1: 186 });

const P = OWL_PALETTE;

// A part is {id, kind: "path" | "ellipse", d | e: [cx, cy, rx, ry], fill, stroke: {colour, width} | null}. The order is the mark's back to front. These are the
// parts the City's shadow and the next package start from: the brows, the rings round the eyes and the chains of feathers are not here, and R4-B2 adds them
// with the poses.
export const OWL_PARTS = Object.freeze([
  { id: "ear-left", kind: "path", d: "M44 70 Q30 40 36 22 Q60 34 74 50Z", fill: P.brown, stroke: { colour: P.ink, width: 7 } },
  { id: "ear-right", kind: "path", d: "M156 70 Q170 40 164 22 Q140 34 126 50Z", fill: P.brown, stroke: { colour: P.ink, width: 7 } },
  { id: "foot-left", kind: "ellipse", e: [80, 186, 13, 7], fill: P.yellow, stroke: { colour: P.ink, width: 7 } },
  { id: "foot-right", kind: "ellipse", e: [120, 186, 13, 7], fill: P.yellow, stroke: { colour: P.ink, width: 7 } },
  { id: "body", kind: "path", d: "M100 36 C152 36 180 74 180 120 C180 164 146 186 100 186 C54 186 20 164 20 120 C20 74 48 36 100 36Z", fill: P.tan, stroke: { colour: P.ink, width: 7 } },
  { id: "wing-left", kind: "path", d: "M30 120 Q28 158 62 174 Q48 148 50 122Z", fill: P.brown, stroke: { colour: P.ink, width: 6 } },
  { id: "wing-right", kind: "path", d: "M170 120 Q172 158 138 174 Q152 148 150 122Z", fill: P.brown, stroke: { colour: P.ink, width: 6 } },
  { id: "face", kind: "path", d: "M100 72 C84 52 42 54 42 96 C42 128 72 142 100 132 C128 142 158 128 158 96 C158 54 116 52 100 72Z", fill: P.cream, stroke: { colour: P.ink, width: 6 } },
  { id: "eye-left", kind: "ellipse", e: [74, 98, 22, 22], fill: P.white, stroke: { colour: P.ink, width: 6 } },
  { id: "eye-right", kind: "ellipse", e: [126, 98, 22, 22], fill: P.white, stroke: { colour: P.ink, width: 6 } },
  { id: "pupil-left", kind: "ellipse", e: [80, 101, 11, 11], fill: P.ink, stroke: null },
  { id: "pupil-right", kind: "ellipse", e: [132, 101, 11, 11], fill: P.ink, stroke: null },
  { id: "glint-left", kind: "ellipse", e: [84, 98, 4, 4], fill: P.white, stroke: null },
  { id: "glint-right", kind: "ellipse", e: [136, 98, 4, 4], fill: P.white, stroke: null },
  { id: "beak", kind: "path", d: "M92 116 Q100 112 108 116 Q103 130 100 132 Q97 130 92 116Z", fill: P.yellow, stroke: { colour: P.ink, width: 5 } },
  // what the poses add (R-41): the heavy lids over the eyes (the eye's circle above y 90), the rings round the eyes and the brow lines over them, the two
  // chains of feathers on the belly, the raised wing of the waiting owl, the shut eyes of the idle one
  { id: "lid-left", kind: "lid", e: [74, 98, 22, 22], cut: 90, fill: P.brown, stroke: null },
  { id: "lid-right", kind: "lid", e: [126, 98, 22, 22], cut: 90, fill: P.brown, stroke: null },
  { id: "ring-left", kind: "ring", e: [74, 98, 22, 22], fill: null, stroke: { colour: P.ink, width: 6 } },
  { id: "ring-right", kind: "ring", e: [126, 98, 22, 22], fill: null, stroke: { colour: P.ink, width: 6 } },
  { id: "brow-left", kind: "line", d: "M53 90 H95", fill: null, stroke: { colour: P.ink, width: 6 } },
  { id: "brow-right", kind: "line", d: "M105 90 H147", fill: null, stroke: { colour: P.ink, width: 6 } },
  { id: "chain-top", kind: "line", d: "M76 156 q6 6 12 0 q6 6 12 0 q6 6 12 0 q6 6 12 0", fill: null, stroke: { colour: P.brown, width: 4 } },
  { id: "chain-low", kind: "line", d: "M82 168 q6 6 12 0 q6 6 12 0 q6 6 12 0", fill: null, stroke: { colour: P.brown, width: 4 } },
  { id: "wing-wave", kind: "path", d: "M168 128 Q196 112 206 66 Q208 52 198 54 Q192 40 184 52 Q174 44 172 60 Q168 90 150 112Z", fill: P.brown, stroke: { colour: P.ink, width: 7 } },
  { id: "shut-left", kind: "ellipse", e: [74, 98, 22, 22], fill: P.brown, stroke: null },
  { id: "shut-right", kind: "ellipse", e: [126, 98, 22, 22], fill: P.brown, stroke: null },
  { id: "closed-left", kind: "line", d: "M60 102 Q74 112 88 102", fill: null, stroke: { colour: P.ink, width: 5 } },
  { id: "closed-right", kind: "line", d: "M112 102 Q126 112 140 102", fill: null, stroke: { colour: P.ink, width: 5 } },
  { id: "shadow", kind: "ellipse", e: [100, 190, 70, 12], fill: null, stroke: null },
]);

// The working owl is turned three-quarters to its desk: its own face, eyes, ears and feet, and two wings that come apart from it, drawn in front of the desk.
const WORKING_PARTS = Object.freeze([
  { id: "w-ear-left", kind: "path", d: "M52 66 Q42 38 52 22 Q74 34 90 50Z", fill: P.brown, stroke: { colour: P.ink, width: 7 } },
  { id: "w-ear-right", kind: "path", d: "M164 80 Q176 56 172 36 Q156 42 146 54Z", fill: P.brown, stroke: { colour: P.ink, width: 7 } },
  { id: "w-foot-left", kind: "ellipse", e: [96, 186, 13, 7], fill: P.yellow, stroke: { colour: P.ink, width: 7 } },
  { id: "w-foot-right", kind: "ellipse", e: [132, 186, 13, 7], fill: P.yellow, stroke: { colour: P.ink, width: 7 } },
  { id: "w-face", kind: "path", d: "M134 72 C118 52 76 54 76 96 C76 128 106 142 136 132 C152 140 172 128 172 100 C172 62 146 54 134 72Z", fill: P.cream, stroke: { colour: P.ink, width: 6 } },
  { id: "w-eye-left", kind: "ellipse", e: [106, 98, 22, 22], fill: P.white, stroke: { colour: P.ink, width: 6 } },
  { id: "w-eye-right", kind: "ellipse", e: [155, 98, 11, 21], fill: P.white, stroke: { colour: P.ink, width: 6 } },
  { id: "w-pupil-left", kind: "ellipse", e: [116, 107, 11, 11], fill: P.ink, stroke: null },
  { id: "w-pupil-right", kind: "ellipse", e: [159, 107, 6, 10], fill: P.ink, stroke: null },
  { id: "w-glint-left", kind: "ellipse", e: [120, 104, 4, 4], fill: P.white, stroke: null },
  { id: "w-glint-right", kind: "ellipse", e: [161, 104, 2.6, 2.6], fill: P.white, stroke: null },
  { id: "w-lid-left", kind: "lid", e: [106, 98, 22, 22], cut: 90, fill: P.brown, stroke: null },
  { id: "w-lid-right", kind: "lid", e: [155, 98, 11, 21], cut: 90, fill: P.brown, stroke: null },
  { id: "w-ring-left", kind: "ring", e: [106, 98, 22, 22], fill: null, stroke: { colour: P.ink, width: 6 } },
  { id: "w-ring-right", kind: "ring", e: [155, 98, 11, 21], fill: null, stroke: { colour: P.ink, width: 6 } },
  { id: "w-brow-left", kind: "line", d: "M85 90 H127", fill: null, stroke: { colour: P.ink, width: 6 } },
  { id: "w-brow-right", kind: "line", d: "M146 90 H164", fill: null, stroke: { colour: P.ink, width: 6 } },
  { id: "w-beak", kind: "path", d: "M131 116 Q138 112 145 116 Q142 130 139 132 Q135 130 131 116Z", fill: P.yellow, stroke: { colour: P.ink, width: 5 } },
  // the wings on the keyboard, 8 units lower than the owl's own drawing (the page's group is translated)
  { id: "w-hand-far", kind: "path", d: "M164 132 Q180 136 190 152 Q188 164 176 158 Q166 150 156 142Z", fill: P.brown, stroke: { colour: P.ink, width: 6 } },
  { id: "w-hand-near", kind: "path", d: "M94 134 Q86 154 104 162 Q124 170 144 166 Q154 158 144 150 Q130 146 118 132Z", fill: P.brown, stroke: { colour: P.ink, width: 6 } },
]);

/** The z of a sleeping owl: `size` is the letter's em in the drawing's units; [x, y] its baseline's left end. */
export const OWL_ZEES = Object.freeze([
  { id: "zee-1", x: 160, y: 44, size: 28, capital: false },
  { id: "zee-2", x: 176, y: 24, size: 36, capital: false },
  { id: "zee-3", x: 196, y: 0, size: 46, capital: true },
]);

const part = (id) => OWL_PARTS.find((x) => x.id === id) || WORKING_PARTS.find((x) => x.id === id);
const front = (...ids) => ids.map((id) => ({ part: part(id) }));

/**
 * The poses, back to front. A layer is {part, group}: `group` names what moves as one (`wave`, `hand-far`, `hand-near`); a layer with none is still. `pivot` is where a
 * moving group turns, as a share of its own box from its left and its top (the stylesheet's `transform-origin` on a `fill-box`).
 */
export const OWL_POSES = Object.freeze({
  waiting: Object.freeze({
    layers: [...front("shadow", "ear-left", "ear-right", "foot-left", "foot-right"), { part: part("wing-wave"), group: "wave" },
      ...front("body", "wing-left", "face", "eye-left", "eye-right", "pupil-left", "pupil-right", "glint-left", "glint-right", "lid-left", "lid-right",
        "ring-left", "ring-right", "brow-left", "brow-right", "beak", "chain-top", "chain-low")],
    pivots: { wave: [0.2, 0.9] },
  }),
  working: Object.freeze({
    layers: [...front("shadow", "w-ear-left", "w-ear-right", "w-foot-left", "w-foot-right", "body", "w-face", "w-eye-left", "w-eye-right", "w-pupil-left", "w-pupil-right",
      "w-glint-left", "w-glint-right", "w-lid-left", "w-lid-right", "w-ring-left", "w-ring-right", "w-brow-left", "w-brow-right", "w-beak"),
      { part: part("w-hand-far"), group: "hand-far" }, { part: part("w-hand-near"), group: "hand-near" }],
    pivots: { "hand-far": [0.08, 0.1], "hand-near": [0.08, 0.1] },
  }),
  idle: Object.freeze({
    layers: front("shadow", "ear-left", "ear-right", "foot-left", "foot-right", "body", "wing-left", "wing-right", "face", "eye-left", "eye-right", "shut-left", "shut-right",
      "closed-left", "closed-right", "lid-left", "lid-right", "ring-left", "ring-right", "beak", "chain-top", "chain-low"),
    pivots: {},
  }),
});

/** The part with this id, or null. */
export function owlPartById(id) {
  return part(id) || null;
}

/**
 * The shapes of one z (white, an ink outline round it) as a polygon in the drawing's units, y down: a bar on top, a bar at the foot and a diagonal between
 * them. A glyph, not text: the scene draws no text (the page's rule), and a z is a shape like the mark's own ears.
 */
export function zeePolygon({ x, y, size, capital }) {
  const w = (capital ? 0.7 : 0.62) * size;
  const h = (capital ? 0.72 : 0.56) * size;
  const t = 0.25 * h;
  const top = y - h;
  return [[x, top], [x + w, top], [x + w, top + t], [x + 0.3 * w, y - t], [x + w, y - t], [x + w, y], [x, y], [x, y - t], [x + 0.7 * w, top + t], [x, top + t]];
}

/** The points of an ellipse (cx, cy, rx, ry) cut by the horizontal line y = `cut` (the drawing's y, down), keeping what is above it: a lid. */
export function lidPoints([cx, cy, rx, ry], cut, steps = 48) {
  const full = [];
  for (let i = 0; i < steps; i++) {
    const a = (i / steps) * Math.PI * 2;
    full.push([cx + Math.cos(a) * rx, cy + Math.sin(a) * ry]);
  }
  const out = [];
  for (let i = 0; i < full.length; i++) {
    const a = full[i];
    const b = full[(i + 1) % full.length];
    const aIn = a[1] <= cut;
    const bIn = b[1] <= cut;
    if (aIn) out.push(a);
    if (aIn !== bIn) {
      const t = (cut - a[1]) / (b[1] - a[1]);
      out.push([a[0] + (b[0] - a[0]) * t, cut]);
    }
  }
  return out;
}

/**
 * The polygons of a part, each a list of [x, y] points standing on the owl's feet with y up (the options of `partShapes`): a closed outline for a filled or ringed
 * part, an open polyline for a line. `kind` of the result tells which: "closed" or "open".
 */
export function partOutlines(THREE, partOrId, o = {}, divisions = 24) {
  const spec = typeof partOrId === "string" ? part(partOrId) : partOrId;
  const frame = owlFrame(o);
  const sx = o.scaleX === undefined ? (o.scale === undefined ? 1 : o.scale) : o.scaleX;
  const sy = o.scaleY === undefined ? (o.scale === undefined ? 1 : o.scale) : o.scaleY;
  const toPoint = (p) => [(p[0] - frame.originX) * sx, -(p[1] - frame.originY) * sy];
  if (spec.kind === "lid") return { kind: "closed", polygons: [lidPoints(spec.e, spec.cut).map(toPoint)] };
  if (spec.kind === "line") return { kind: "open", polygons: pathToLines(THREE, spec.d, frame).map((path) => path.getPoints(divisions).map((v) => [v.x, v.y])) };
  const shapes = spec.kind === "path" ? pathToShapes(THREE, spec.d, frame) : [ellipseToShape(THREE, spec.e[0], spec.e[1], spec.e[2], spec.e[3], frame)];
  return { kind: "closed", polygons: shapes.map((shape) => shape.getPoints(divisions).map((v) => [v.x, v.y])) };
}

/** The part with this id, or null. */
export function owlPart(id) {
  return OWL_PARTS.find((part) => part.id === id) || null;
}

/** The options that put a part's drawing coordinates on the owl's feet, at `scale` (or stretched by `scaleX` and `scaleY`), y up. */
export function owlFrame(o = {}) {
  return { originX: OWL_ORIGIN.x, originY: OWL_ORIGIN.y, ...o };
}

/** The shapes of one part (a path may hold several subpaths), standing on the feet. `o`: {scale, scaleX, scaleY}. */
export function partShapes(THREE, part, o = {}) {
  const frame = owlFrame(o);
  if (part.kind === "ellipse" || part.kind === "ring") return [ellipseToShape(THREE, part.e[0], part.e[1], part.e[2], part.e[3], frame)];
  if (part.kind === "lid") return [new THREE.Shape(partOutlines(THREE, part, o).polygons[0].map(([x, y]) => new THREE.Vector2(x, y)))];
  return pathToShapes(THREE, part.d, frame);
}

/**
 * The owl's outline, the silhouette of the City's shadow (R-19): the body and the two ear tufts, no wings, no feet, no face. Returns
 * {body: Shape, ears: [Shape, Shape]}, standing on the origin; `o` stretches it ({scaleX, scaleY}): the shadow is fitted to a window.
 */
export function owlOutline(THREE, o = {}) {
  return {
    body: partShapes(THREE, owlPart("body"), o)[0],
    ears: [partShapes(THREE, owlPart("ear-left"), o)[0], partShapes(THREE, owlPart("ear-right"), o)[0]],
  };
}

/** The triangles of a part's ink outline, from its shape sampled at `divisions` points a curve, as a flat position array (z = 0), or null with no stroke. */
export function partStroke(THREE, part, o = {}, divisions = 24) {
  if (!part.stroke) return null;
  const { sx, sy } = { sx: o.scaleX === undefined ? (o.scale === undefined ? 1 : o.scale) : o.scaleX, sy: o.scaleY === undefined ? (o.scale === undefined ? 1 : o.scale) : o.scaleY };
  const width = part.stroke.width * ((sx + sy) / 2);
  const triangles = [];
  for (const shape of partShapes(THREE, part, o)) {
    const points = shape.getPoints(divisions).map((p) => [p.x, p.y]);
    if (points.length > 1 && points[0][0] === points[points.length - 1][0] && points[0][1] === points[points.length - 1][1]) points.pop();
    triangles.push(...strokeTriangles(points, width, true));
  }
  return triangles;
}
