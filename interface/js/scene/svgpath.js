// A small parser of SVG path data, our own, for the owl (R4D-2): the shapes of the mark's drawing become flat meshes of the scene, so no texture
// is drawn and no HTML sits over the scene. It reads the commands the owl's drawing uses, in absolute and relative form: M, L, H, V, C, S, Q, T and
// Z (m, l, h, v, c, s, q, t, z). An arc (A, a) is refused with a clear error: nothing the scene draws uses one, and a silent approximation would
// be a wrong shape. No three.js is imported here: `pathToShapes` takes the library as an argument, so the parser runs under Node with or without it.

const COMMAND_ARITY = { M: 2, L: 2, H: 1, V: 1, C: 6, S: 4, Q: 4, T: 2, Z: 0 };
const NUMBER = /[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?/y;

/** Split path data into [{command, numbers}], one entry per command letter with all its numbers, or throw on a character the grammar has no place for. */
function tokenize(d) {
  const text = String(d);
  const tokens = [];
  let i = 0;
  let current = null;
  while (i < text.length) {
    const ch = text[i];
    if (/[\s,]/.test(ch)) {
      i += 1;
    } else if (/[a-zA-Z]/.test(ch)) {
      if (!(ch.toUpperCase() in COMMAND_ARITY)) {
        throw new Error(ch.toUpperCase() === "A" ? "svgpath: an arc (A) is not supported" : `svgpath: the command ${ch} is not supported`);
      }
      current = { command: ch, numbers: [] };
      tokens.push(current);
      i += 1;
    } else {
      NUMBER.lastIndex = i;
      const match = NUMBER.exec(text);
      if (!match || !current) throw new Error(`svgpath: unexpected "${ch}" at ${i}`);
      current.numbers.push(Number(match[0]));
      i = NUMBER.lastIndex;
    }
  }
  return tokens;
}

/**
 * The path as absolute segments: [{type: "M"|"L"|"C"|"Q"|"Z", points: [[x, y], ...]}]. H and V become L; S and T take the reflection of the
 * previous control point; a relative command is made absolute; extra pairs after M are L; a number group that does not fill a command throws.
 */
export function parsePath(d) {
  const segments = [];
  let x = 0;
  let y = 0;
  let startX = 0;
  let startY = 0;
  let lastControl = null;   // {x, y, kind: "C"|"Q"} of the previous curve, for S and T
  let closed = false;       // the last segment was a Z: a drawing command now starts a new subpath at the start point
  for (const { command, numbers } of tokenize(d)) {
    const upper = command.toUpperCase();
    const relative = command !== upper;
    const arity = COMMAND_ARITY[upper];
    if (upper === "Z") {
      segments.push({ type: "Z", points: [] });
      x = startX;
      y = startY;
      lastControl = null;
      closed = true;
      continue;
    }
    if (closed && upper !== "M") segments.push({ type: "M", points: [[startX, startY]] });
    closed = false;
    if (numbers.length === 0 || numbers.length % arity !== 0) throw new Error(`svgpath: ${command} needs groups of ${arity} numbers, got ${numbers.length}`);
    for (let k = 0; k < numbers.length; k += arity) {
      const n = numbers.slice(k, k + arity);
      const ox = relative ? x : 0;
      const oy = relative ? y : 0;
      let again = upper;
      if (upper === "M" && k > 0) again = "L";   // the pairs after the first of a moveto are linetos
      if (again === "M") {
        x = n[0] + ox;
        y = n[1] + oy;
        startX = x;
        startY = y;
        segments.push({ type: "M", points: [[x, y]] });
        lastControl = null;
      } else if (again === "L") {
        x = n[0] + ox;
        y = n[1] + oy;
        segments.push({ type: "L", points: [[x, y]] });
        lastControl = null;
      } else if (again === "H") {
        x = n[0] + ox;
        segments.push({ type: "L", points: [[x, y]] });
        lastControl = null;
      } else if (again === "V") {
        y = n[0] + oy;
        segments.push({ type: "L", points: [[x, y]] });
        lastControl = null;
      } else if (again === "C") {
        const p = [[n[0] + ox, n[1] + oy], [n[2] + ox, n[3] + oy], [n[4] + ox, n[5] + oy]];
        segments.push({ type: "C", points: p });
        lastControl = { x: p[1][0], y: p[1][1], kind: "C" };
        [x, y] = p[2];
      } else if (again === "S") {
        const first = lastControl && lastControl.kind === "C" ? [2 * x - lastControl.x, 2 * y - lastControl.y] : [x, y];
        const p = [first, [n[0] + ox, n[1] + oy], [n[2] + ox, n[3] + oy]];
        segments.push({ type: "C", points: p });
        lastControl = { x: p[1][0], y: p[1][1], kind: "C" };
        [x, y] = p[2];
      } else if (again === "Q") {
        const p = [[n[0] + ox, n[1] + oy], [n[2] + ox, n[3] + oy]];
        segments.push({ type: "Q", points: p });
        lastControl = { x: p[0][0], y: p[0][1], kind: "Q" };
        [x, y] = p[1];
      } else if (again === "T") {
        const control = lastControl && lastControl.kind === "Q" ? [2 * x - lastControl.x, 2 * y - lastControl.y] : [x, y];
        const p = [control, [n[0] + ox, n[1] + oy]];
        segments.push({ type: "Q", points: p });
        lastControl = { x: control[0], y: control[1], kind: "Q" };
        [x, y] = p[1];
      }
    }
  }
  return segments;
}

/** The segments split into subpaths: each starts at an M and ends at its Z (or the end of the data). */
export function subpaths(segments) {
  const out = [];
  let current = null;
  for (const segment of segments) {
    if (segment.type === "M") {
      current = { closed: false, segments: [segment] };
      out.push(current);
    } else if (current) {
      current.segments.push(segment);
      if (segment.type === "Z") current.closed = true;
    }
  }
  return out;
}

/**
 * One THREE.Shape for each subpath of `d`. `THREE` is the library. o: {scale (default 1), originX, originY (the point of the drawing that becomes
 * the origin), flipY (default true: an SVG's y runs down, the scene's up); `scaleX` and `scaleY` stretch one axis alone (they default to `scale`)}.
 * A shape that was not closed in the data is closed, as a fill does.
 */
export function pathToShapes(THREE, d, o = {}) {
  const { sx, sy } = scales(o);
  const ox = o.originX || 0;
  const oy = o.originY || 0;
  const sign = o.flipY === false ? 1 : -1;
  const px = (p) => (p[0] - ox) * sx;
  const py = (p) => (p[1] - oy) * sy * sign;
  return subpaths(parsePath(d)).map((sub) => {
    const shape = new THREE.Shape();
    for (const segment of sub.segments) {
      const p = segment.points;
      if (segment.type === "M") shape.moveTo(px(p[0]), py(p[0]));
      else if (segment.type === "L") shape.lineTo(px(p[0]), py(p[0]));
      else if (segment.type === "C") shape.bezierCurveTo(px(p[0]), py(p[0]), px(p[1]), py(p[1]), px(p[2]), py(p[2]));
      else if (segment.type === "Q") shape.quadraticCurveTo(px(p[0]), py(p[0]), px(p[1]), py(p[1]));
      else shape.closePath();
    }
    if (!sub.closed) shape.closePath();
    return shape;
  });
}

/**
 * One THREE.Path for each subpath of `d`, left open as a stroke draws it (a feather chain, a brow line): the same options as `pathToShapes`.
 * `path.getPoints(divisions)` is the polyline to stroke.
 */
export function pathToLines(THREE, d, o = {}) {
  const { sx, sy } = scales(o);
  const ox = o.originX || 0;
  const oy = o.originY || 0;
  const sign = o.flipY === false ? 1 : -1;
  const px = (p) => (p[0] - ox) * sx;
  const py = (p) => (p[1] - oy) * sy * sign;
  return subpaths(parsePath(d)).map((sub) => {
    const line = new THREE.Path();
    for (const segment of sub.segments) {
      const p = segment.points;
      if (segment.type === "M") line.moveTo(px(p[0]), py(p[0]));
      else if (segment.type === "L") line.lineTo(px(p[0]), py(p[0]));
      else if (segment.type === "C") line.bezierCurveTo(px(p[0]), py(p[0]), px(p[1]), py(p[1]), px(p[2]), py(p[2]));
      else if (segment.type === "Q") line.quadraticCurveTo(px(p[0]), py(p[0]), px(p[1]), py(p[1]));
    }
    return line;
  });
}

/** The scale of each axis of an options object: `scaleX` and `scaleY`, each defaulting to `scale`, which defaults to 1. */
function scales(o) {
  const base = o.scale === undefined ? 1 : o.scale;
  return { sx: o.scaleX === undefined ? base : o.scaleX, sy: o.scaleY === undefined ? base : o.scaleY };
}

/** A shape for an ellipse (a circle when rx = ry) in the same drawing coordinates as `pathToShapes` takes. */
export function ellipseToShape(THREE, cx, cy, rx, ry, o = {}) {
  const { sx, sy } = scales(o);
  const sign = o.flipY === false ? 1 : -1;
  const shape = new THREE.Shape();
  shape.absellipse((cx - (o.originX || 0)) * sx, (cy - (o.originY || 0)) * sy * sign, rx * sx, ry * sy, 0, Math.PI * 2, false, 0);
  return shape;
}

/**
 * The triangles of a stroke along a polyline of [x, y] points: a rectangle for each segment of `width` and, at every joint and cap, a fan that
 * rounds it (an SVG stroke with round joins and caps). Returns a flat array of x, y triples (z = 0) for a position attribute. The rectangles
 * overlap at the joints, so the stroke is drawn in one flat colour with no transparency.
 */
export function strokeTriangles(points, width, closed = false, steps = 8) {
  const out = [];
  const half = width / 2;
  const count = points.length;
  const last = closed ? count : count - 1;
  const push = (...v) => out.push(...v);
  for (let i = 0; i < last; i++) {
    const a = points[i];
    const b = points[(i + 1) % count];
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const len = Math.hypot(dx, dy);
    if (len < 1e-9) continue;
    const nx = (-dy / len) * half;
    const ny = (dx / len) * half;
    push(a[0] + nx, a[1] + ny, 0, a[0] - nx, a[1] - ny, 0, b[0] + nx, b[1] + ny, 0);
    push(a[0] - nx, a[1] - ny, 0, b[0] - nx, b[1] - ny, 0, b[0] + nx, b[1] + ny, 0);
  }
  for (const p of points) {
    for (let k = 0; k < steps; k++) {
      const t0 = (k / steps) * Math.PI * 2;
      const t1 = ((k + 1) / steps) * Math.PI * 2;
      push(p[0], p[1], 0, p[0] + Math.cos(t0) * half, p[1] + Math.sin(t0) * half, 0, p[0] + Math.cos(t1) * half, p[1] + Math.sin(t1) * half, 0);
    }
  }
  return out;
}
