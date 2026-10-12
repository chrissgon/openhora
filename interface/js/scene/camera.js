// The person's own camera: zoom and pan on top of the fitted view. Pure arithmetic on rectangles, with no three.js and no
// document, so a test can run it. The fitted frustum (fit.js) is the whole diorama inside the free rectangle the panels leave;
// a view {zoom, x, y} narrows it by `zoom` and moves its centre by (x, y), both in camera space. The limits:
//   - the zoom is at least 1 (the diorama fitted, as before) and at most MAX_ZOOM;
//   - the pan keeps the diorama's bounding box at least half visible on each axis (all of the visible part, when the view
//     is narrower than half the box), so it never leaves the view;
//   - a press that moves more than DRAG_PX pixels is a pan, not a click.

export const MIN_ZOOM = 1;
export const MAX_ZOOM = 3;
export const DRAG_PX = 5;
export const KEY_ZOOM = 1.25;       // one + or - key
export const KEY_PAN = 0.1;         // one arrow key: a tenth of the visible width or height
export const IDENTITY = Object.freeze({ zoom: 1, x: 0, y: 0 });

const centre = (f) => ({ x: (f.left + f.right) / 2, y: (f.top + f.bottom) / 2 });
const half = (f) => ({ w: (f.right - f.left) / 2, h: (f.top - f.bottom) / 2 });

/** The view that shows the whole fitted diorama. */
export function fitView() {
  return { ...IDENTITY };
}

/** True when a press moved far enough to be a drag. */
export function isDrag(dx, dy, threshold = DRAG_PX) {
  return dx * dx + dy * dy > threshold * threshold;
}

/** The frustum the camera shows for a fitted frustum and a view. */
export function frustumOf(fitted, view) {
  const c = centre(fitted);
  const hf = half(fitted);
  const z = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, view.zoom));
  const cx = c.x + view.x;
  const cy = c.y + view.y;
  return { left: cx - hf.w / z, right: cx + hf.w / z, top: cy + hf.h / z, bottom: cy - hf.h / z };
}

function clampAxis(c, halfExtent, lo, hi) {
  const size = hi - lo;
  const need = Math.min(0.5 * size, 2 * halfExtent);   // the part of the box that must stay in view
  return Math.max(lo + need - halfExtent, Math.min(hi - need + halfExtent, c));
}

/** The view brought inside the limits for a fitted frustum and the diorama's bounds {x0, x1, y0, y1} in camera space. */
export function clampView(view, fitted, bounds) {
  const zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, Number.isFinite(view.zoom) ? view.zoom : 1));
  const c = centre(fitted);
  const hf = half(fitted);
  const cx = clampAxis(c.x + (view.x || 0), hf.w / zoom, bounds.x0, bounds.x1);
  const cy = clampAxis(c.y + (view.y || 0), hf.h / zoom, bounds.y0, bounds.y1);
  return { zoom, x: cx - c.x, y: cy - c.y };
}

/** The view after a zoom by `factor` around the point `ndc` {x, y} (each from -1 to 1) of the canvas, kept inside the limits. */
export function zoomAt(view, fitted, bounds, factor, ndc = { x: 0, y: 0 }) {
  const now = frustumOf(fitted, view);
  const c = centre(now);
  const h = half(now);
  const zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, view.zoom * factor));
  const hf = half(fitted);
  const nextHalf = { w: hf.w / zoom, h: hf.h / zoom };
  const px = c.x + ndc.x * h.w;   // the point under the pointer, in camera space
  const py = c.y + ndc.y * h.h;
  const fc = centre(fitted);
  return clampView({ zoom, x: px - ndc.x * nextHalf.w - fc.x, y: py - ndc.y * nextHalf.h - fc.y }, fitted, bounds);
}

/** The view after a pan by a fraction of the visible width and height (positive x moves the scene to the right on screen). */
export function panBy(view, fitted, bounds, fx, fy) {
  const now = frustumOf(fitted, view);
  const h = half(now);
  return clampView({ zoom: view.zoom, x: view.x - fx * 2 * h.w, y: view.y + fy * 2 * h.h }, fitted, bounds);
}

/** The view after a drag of (dx, dy) pixels in a canvas of `size` {w, h}: the scene follows the pointer. */
export function panPixels(view, fitted, bounds, dx, dy, size) {
  return panBy(view, fitted, bounds, dx / Math.max(1, size.w), dy / Math.max(1, size.h));
}

/** The zoom factor of one wheel event (`deltaMode` 1 is lines, 2 is pages), a smooth exponential of the distance. */
export function wheelFactor(deltaY, deltaMode = 0) {
  const pixels = deltaY * (deltaMode === 1 ? 16 : deltaMode === 2 ? 400 : 1);
  return Math.exp(-Math.max(-400, Math.min(400, pixels)) * 0.002);
}

/** What a key does to the view when the canvas has the focus: {zoom: factor}, {pan: [fx, fy]}, {fit: true} or null. */
export function keyAction(key) {
  switch (key) {
    case "+": case "=": return { zoom: KEY_ZOOM };
    case "-": case "_": return { zoom: 1 / KEY_ZOOM };
    case "0": return { fit: true };
    case "ArrowLeft": return { pan: [KEY_PAN, 0] };    // the scene moves to the right, the view to the left
    case "ArrowRight": return { pan: [-KEY_PAN, 0] };
    case "ArrowUp": return { pan: [0, KEY_PAN] };
    case "ArrowDown": return { pan: [0, -KEY_PAN] };
    default: return null;
  }
}

/**
 * A pointer position in the canvas's normalised device coordinates (each from -1 to 1, y up). `rect` is the canvas's box on the
 * page in CSS pixels (getBoundingClientRect), so the mapping holds for a canvas scaled by CSS and for any pixel ratio: the
 * drawing buffer's own size never enters.
 */
export function pointerToNdc(clientX, clientY, rect) {
  const w = Math.max(1, rect.width);
  const h = Math.max(1, rect.height);
  return { x: ((clientX - rect.left) / w) * 2 - 1, y: -(((clientY - rect.top) / h) * 2 - 1) };
}
