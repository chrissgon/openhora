// Fitting the camera: pure arithmetic on rectangles, no three.js and no document.

/**
 * The orthographic frustum that puts a subject (its bounds in camera space: {x0, x1, y0, y1}) inside the free rectangle
 * of a view of `size` {w, h} left by the panels (`insets` {left, right, top, bottom}, in pixels), padded by `pad`.
 * `maxScale` (pixels a unit of the camera's space may take, optional) stops the fit from zooming past it. Returns {left, right, top, bottom} in camera space.
 */
export function fitFrustum(bounds, size, insets, pad, maxScale) {
  const ins = { left: 0, right: 0, top: 0, bottom: 0, ...(insets || {}) };
  const w = Math.max(1, size.w);
  const h = Math.max(1, size.h);
  const fw = Math.max(50, w - ins.left - ins.right);
  const fh = Math.max(50, h - ins.top - ins.bottom);
  let s = Math.max((bounds.x1 - bounds.x0) / fw, (bounds.y1 - bounds.y0) / fh, 1e-6) * (pad || 1);
  if (maxScale > 0) s = Math.max(s, 1 / maxScale);   // not closer than `maxScale` pixels to a unit: a subject that is small in the free rectangle stays as large as it is drawn
  const cx = (bounds.x0 + bounds.x1) / 2 - (ins.left + fw / 2 - w / 2) * s;
  const cy = (bounds.y0 + bounds.y1) / 2 + (ins.top + fh / 2 - h / 2) * s;
  return { left: cx - (w / 2) * s, right: cx + (w / 2) * s, top: cy + (h / 2) * s, bottom: cy - (h / 2) * s };
}

/**
 * The fit with room for the labels that stand over the subject (R4-B8): the subject's bounds are of its geometry, and a label (a building's pill, a card) is as wide as its text in pixels
 * whatever the zoom, so on a narrow canvas a label wider than its building runs out of the free rectangle (a phone's City cut the first building's name at the left edge).
 * `labels` are {x, y (the anchor in camera space: the label stands centred over it), width, height (pixels)}. The plain fit is returned when every label is inside the free rectangle
 * it leaves, so a canvas with room is framed exactly as before; otherwise the bounds grow to hold the labels as they are at the scale the fit then has, until they hold (a few rounds:
 * a wider box is a smaller scale, which makes a label wider in camera units).
 */
export function fitFrustumWithLabels(bounds, size, insets, pad, maxScale, labels) {
  const ins = { left: 0, right: 0, top: 0, bottom: 0, ...(insets || {}) };
  const w = Math.max(1, size.w);
  const h = Math.max(1, size.h);
  let fitted = fitFrustum(bounds, size, ins, pad, maxScale);
  const list = Array.isArray(labels) ? labels : [];
  if (!list.length) return fitted;
  let box = bounds;
  for (let round = 0; round < 8; round++) {
    const s = (fitted.right - fitted.left) / w;
    const free = { x0: fitted.left + ins.left * s, x1: fitted.right - ins.right * s, y1: fitted.top - ins.top * s, y0: fitted.bottom + ins.bottom * s };
    const rects = list.map((l) => ({ x0: l.x - (l.width / 2) * s, x1: l.x + (l.width / 2) * s, y0: l.y, y1: l.y + l.height * s }));
    const out = rects.some((r) => r.x0 < free.x0 - 1e-9 || r.x1 > free.x1 + 1e-9 || r.y1 > free.y1 + 1e-9 || r.y0 < free.y0 - 1e-9);
    if (!out) return fitted;
    const grown = { x0: bounds.x0, x1: bounds.x1, y0: bounds.y0, y1: bounds.y1 };
    for (const r of rects) {
      grown.x0 = Math.min(grown.x0, r.x0);
      grown.x1 = Math.max(grown.x1, r.x1);
      grown.y0 = Math.min(grown.y0, r.y0);
      grown.y1 = Math.max(grown.y1, r.y1);
    }
    if (grown.x0 === box.x0 && grown.x1 === box.x1 && grown.y0 === box.y0 && grown.y1 === box.y1) return fitted;
    box = grown;
    fitted = fitFrustum(box, size, ins, pad, maxScale);
  }
  return fitted;
}

/**
 * The frustum of a camera move at progress `p` (0 to 1), the prototype's way: the centre is moved in a straight line and the ZOOM
 * (the reciprocal of the frustum's half width, the prototype's `cam.zoom`) is moved in a straight line, not the frustum's sides.
 * Moving the sides in a straight line made a fly-in start slowly and end fast; moving the zoom is what the prototype did.
 */
export function moveFrustum(a, b, p) {
  const read = (f) => ({ x: (f.left + f.right) / 2, y: (f.top + f.bottom) / 2, zoom: 2 / (f.right - f.left), aspect: (f.top - f.bottom) / (f.right - f.left) });
  const from = read(a);
  const to = read(b);
  const mix = (x, y) => x + (y - x) * p;
  const zoom = mix(from.zoom, to.zoom);
  const half = 1 / zoom;
  const x = mix(from.x, to.x);
  const y = mix(from.y, to.y);
  const hh = half * mix(from.aspect, to.aspect);
  return { left: x - half, right: x + half, top: y + hh, bottom: y - hh };
}

/** A frustum between two, at t from 0 to 1 (the sides moved in a straight line). */
export function lerpFrustum(a, b, t) {
  const mix = (x, y) => x + (y - x) * t;
  return { left: mix(a.left, b.left), right: mix(a.right, b.right), top: mix(a.top, b.top), bottom: mix(a.bottom, b.bottom) };
}

/**
 * The prototype's feel (its `scene.js`): the camera approached its goal exponentially, `1 - exp(-4.5 t)` a second (a fast start
 * that settles softly), and the building opened with `1 - exp(-3.2 t)` read through a smoothstep. A move here runs for the time
 * those take to settle to one percent (ln 100 over the rate) and the curve is normalised so it ends exactly on its goal.
 */
export const CAMERA_RATE = 4.5;
export const OPEN_RATE = 3.2;
const SETTLE = Math.log(100);

/** Milliseconds a move of the prototype's rate takes to settle to one percent. */
export function settleMs(rate) {
  return Math.round((SETTLE / rate) * 1000);
}

const clamp01 = (t) => Math.max(0, Math.min(1, t));

/** The prototype's exponential approach for t from 0 to 1: fast at first, soft at the end, exactly 1 at t = 1. */
export function ease(t) {
  return (1 - Math.exp(-SETTLE * clamp01(t))) / (1 - Math.exp(-SETTLE));
}

/** The prototype's opening curve: the approach read through a smoothstep, so it also starts softly. */
export function openEase(t) {
  const e = ease(t);
  return e * e * (3 - 2 * e);
}
