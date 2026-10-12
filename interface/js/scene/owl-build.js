// The owl as meshes (R-41, R4D-2): the mark's own drawing, flat, on a plane that faces the camera, so that it is drawn as the page draws it and stands in the room
// with a depth of its own (a corner of a bracket behind it is hidden by it, a desk in front of it covers it). No texture, no HTML. A pose is built from its list
// of parts (owl.js): each part's fill and its ink outline become triangles of one colour a vertex, the layers a little apart along the plane's normal (a layer
// is nearer the camera than the one under it by `LAYER`, which the camera's orthographic view never shows), the still parts in one mesh and each moving part
// (the raised wing, the two typing wings, the three z) in a mesh of its own that turns on a pivot. `owl-motion.js` says how they move.

import { OWL_ORIGIN, OWL_PALETTE, OWL_POSES, OWL_ZEES, partOutlines, zeePolygon } from "./owl.js";
import { REST, blinkPose, snorePose, tapPose, wavePose, zzPose } from "./owl-motion.js";
import { strokeTriangles } from "./svgpath.js";
import { AZIMUTH, ELEVATION } from "./rig.js";

export const LAYER = 0.0016;     // the distance between two layers, in world units along the plane's normal
const DIVISIONS = 16;            // segments of a curve
const DEG = Math.PI / 180;
const INK_WIDTH_OF_Z = 5;        // the ink outline round a z, as the page draws it

/** The turn of a plane that faces the camera (its up is the screen's up): the camera's own. */
export function billboardEuler(THREE) {
  return new THREE.Euler(-ELEVATION, AZIMUTH, 0, "YXZ");
}

/** The direction from the scene toward the camera, as a unit vector: moving a plane along it changes its depth and not where it is drawn. */
export function towardCamera(THREE) {
  return new THREE.Vector3(Math.sin(AZIMUTH) * Math.cos(ELEVATION), Math.sin(ELEVATION), Math.cos(AZIMUTH) * Math.cos(ELEVATION));
}

/** The tone of the owl's shadow on a floor of tone `floor`: the mark's ink at 14 percent over it (`m-owl-shadow`). */
export function shadowTone(THREE, mix, floor) {
  return mix(floor, new THREE.Color(OWL_PALETTE.ink), 0.14);
}

const bounds = (polygons) => {
  const box = { x0: Infinity, x1: -Infinity, y0: Infinity, y1: -Infinity };
  for (const poly of polygons) for (const [x, y] of poly) {
    box.x0 = Math.min(box.x0, x);
    box.x1 = Math.max(box.x1, x);
    box.y0 = Math.min(box.y0, y);
    box.y1 = Math.max(box.y1, y);
  }
  return box;
};

/**
 * Build the owl in pose `pose` ("waiting", "working", "ready" or "idle") for a floor of tone `floorTone`. o: {scale (world units a unit of the drawing: `owlScale`), mix (the
 * palette's), handLift (how much nearer the camera than the owl the working wings are drawn, so that they cover the keyboard)}. Returns
 * {group (stand it on the owl's feet; it faces the camera), motion {tick(seconds), rest()}, size {w, h} in world units, parts (the meshes by name), dispose()}.
 */
export function buildOwl(kit, pose, { scale, mix, floorTone, handLift = 0 }) {
  const { THREE } = kit;
  const spec = OWL_POSES[pose];
  if (!spec) throw new Error(`buildOwl: no pose ${pose}`);
  const s = scale;
  const colour = (hex) => new THREE.Color(hex);
  const materials = [];
  const geometries = [];
  const material = (o = {}) => {
    const m = kit.adopt(new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.DoubleSide, ...o }));
    materials.push(m);
    return m;
  };
  const triangles = (poly, ox, oy) => {
    const points = poly.map(([x, y]) => new THREE.Vector2(x, y));
    if (points.length > 1 && points[0].equals(points[points.length - 1])) points.pop();
    return THREE.ShapeUtils.triangulateShape(points, []).map((face) => face.flatMap((i) => [points[i].x - ox, points[i].y - oy]));
  };
  const group = new THREE.Group();
  group.rotation.copy(billboardEuler(THREE));
  const inner = new THREE.Group();
  group.add(inner);

  // the outlines of every layer, and where each moving group turns (a share of its own box)
  const drawn = spec.layers.map((layer) => ({ layer, outline: partOutlines(THREE, layer.part, { scale: s, originX: OWL_ORIGIN.x, originY: OWL_ORIGIN.y }, DIVISIONS) }));
  const pivots = {};
  for (const name of new Set(spec.layers.map((l) => l.group).filter(Boolean))) {
    const box = bounds(drawn.filter((d) => d.layer.group === name).flatMap((d) => d.outline.polygons));
    const [fx, fy] = spec.pivots[name];
    pivots[name] = [box.x0 + fx * (box.x1 - box.x0), box.y1 - fy * (box.y1 - box.y0)];
  }

  const buckets = new Map();
  const bucket = (name) => {
    if (!buckets.has(name)) buckets.set(name, { position: [], colour: [] });
    return buckets.get(name);
  };
  const push = (b, tri, rgb, z) => {
    for (let i = 0; i < tri.length; i += 2) {
      b.position.push(tri[i], tri[i + 1], z);
      b.colour.push(rgb.r, rgb.g, rgb.b);
    }
  };
  drawn.forEach(({ layer, outline }, k) => {
    const part = layer.part;
    const name = layer.group || "still";
    const b = bucket(name);
    const [ox, oy] = pivots[name] || [0, 0];
    const fill = part.id === "shadow" ? shadowTone(THREE, mix, floorTone) : part.fill ? colour(part.fill) : null;
    for (const poly of outline.polygons) {
      if (fill) for (const tri of triangles(poly, ox, oy)) push(b, tri, fill, k * LAYER);
      if (part.stroke) {
        const line = strokeTriangles(poly.map(([x, y]) => [x - ox, y - oy]), part.stroke.width * s, outline.kind === "closed");
        const rgb = colour(part.stroke.colour);
        for (let i = 0; i < line.length; i += 3) b.position.push(line[i], line[i + 1], k * LAYER + LAYER / 2), b.colour.push(rgb.r, rgb.g, rgb.b);
      }
    }
  });

  const parts = {};
  const whole = bounds(drawn.flatMap((d) => d.outline.polygons));
  const meshOf = (b) => {
    const geometry = kit.track(new THREE.BufferGeometry());
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(b.position, 3));
    geometry.setAttribute("color", new THREE.Float32BufferAttribute(b.colour, 3));
    geometry.computeBoundingSphere();
    geometries.push(geometry);
    const mesh = new THREE.Mesh(geometry, material());
    mesh.castShadow = false;
    return mesh;
  };
  for (const [name, b] of buckets) {
    const mesh = meshOf(b);
    if (name === "still") {
      inner.add(mesh);
      parts.still = mesh;
    } else {
      const turn = new THREE.Group();
      turn.position.set(pivots[name][0], pivots[name][1], name.startsWith("hand") ? handLift : 0);
      turn.add(mesh);
      inner.add(turn);
      parts[name] = turn;
    }
  }

  // the z of a sleeping owl: white, an ink outline behind the fill (the fill is nearer, drawn first, so the whole is faded as one when it takes an alpha)
  const zees = [];
  if (pose === "idle") {
    const top = (spec.layers.length + 2) * LAYER;
    OWL_ZEES.forEach((z) => {
      const poly = zeePolygon(z).map(([x, y]) => [(x - OWL_ORIGIN.x) * s, -(y - OWL_ORIGIN.y) * s]);
      const box = bounds([poly]);
      const centre = [(box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2];
      const b = { position: [], colour: [] };
      for (const tri of triangles(poly, centre[0], centre[1])) push(b, tri, colour(OWL_PALETTE.white), top + LAYER);
      const line = strokeTriangles(poly.map(([x, y]) => [x - centre[0], y - centre[1]]), INK_WIDTH_OF_Z * s, true);
      const rgb = colour(OWL_PALETTE.ink);
      for (let i = 0; i < line.length; i += 3) b.position.push(line[i], line[i + 1], top), b.colour.push(rgb.r, rgb.g, rgb.b);
      const mesh = meshOf(b);
      mesh.material = material({ transparent: true, opacity: 1 });
      const turn = new THREE.Group();
      turn.position.set(centre[0], centre[1], 0);
      turn.add(mesh);
      group.add(turn);
      zees.push({ turn, material: mesh.material, home: centre });
      parts[z.id] = turn;
    });
  }

  // what the pointer meets: a plane over the owl, not drawn (the wing raised over the head and the gaps between the parts are the owl too)
  const pad = 6 * s;
  const hitGeometry = kit.track(new THREE.PlaneGeometry(whole.x1 - whole.x0 + 2 * pad, whole.y1 - whole.y0 + 2 * pad));
  geometries.push(hitGeometry);
  const hit = new THREE.Mesh(hitGeometry, kit.adopt(new THREE.MeshBasicMaterial({ visible: false })));
  materials.push(hit.material);
  hit.position.set((whole.x0 + whole.x1) / 2, (whole.y0 + whole.y1) / 2, -LAYER);
  group.add(hit);
  parts.hit = hit;

  const turnOf = (name, degrees) => { if (parts[name]) parts[name].rotation.z = -degrees * DEG; };   // a CSS angle runs clockwise, the plane's runs the other way
  const lids = (shut) => { if (parts.blink) parts.blink.scale.y = Math.max(shut, 0.001); };   // the lids come down from the top of the eyes; open is no lid at all
  const place = (seconds) => {
    if (pose === "waiting") turnOf("wave", wavePose(seconds));
    if (pose === "working") {
      turnOf("hand-far", tapPose(seconds, true));
      turnOf("hand-near", tapPose(seconds, false));
    }
    if (pose === "ready") lids(blinkPose(seconds));
    if (pose === "idle") {
      const breath = snorePose(seconds);
      inner.scale.set(breath.x, breath.y, 1);
      zees.forEach((z, k) => {
        const p = zzPose(seconds, k);
        z.material.opacity = p.opacity;
        z.turn.position.set(z.home[0] + p.dx * s, z.home[1] - p.dy * s, 0);
        z.turn.scale.setScalar(p.scale);
      });
    }
  };
  const rest = () => {
    turnOf("wave", REST.wave);
    turnOf("hand-far", REST.tap);
    turnOf("hand-near", REST.tap);
    lids(REST.blink);
    inner.scale.set(REST.snore.x, REST.snore.y, 1);
    zees.forEach((z) => {
      z.material.opacity = REST.zz.opacity;
      z.turn.position.set(z.home[0], z.home[1], 0);
      z.turn.scale.setScalar(REST.zz.scale);
    });
  };
  rest();

  return {
    group, parts, size: { w: whole.x1 - whole.x0, h: whole.y1 - whole.y0 },
    motion: { tick: place, rest },
    dispose() {
      for (const g of geometries) kit.release(g);
      for (const m of materials) kit.free(m);
      geometries.length = 0;
      materials.length = 0;
    },
  };
}
