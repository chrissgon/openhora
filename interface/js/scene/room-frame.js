// The room's measures as the page draws them (round 4, `building.html`): a room is 7 by 5.6 page units, a page unit being 20 px at the page's
// isometric angle, with walls 2.66 high. Every object of a room is written here in those units, measured off the page, and put on the room's own
// constants (the closed City's building is the same room: its width, depth and floor height are building.js's), so that the room is the page's room
// seen on the building the scene has. x runs along the back wall to the right, z along the left wall toward the camera, y up from the floor's top.
// The page's units are mapped on the width (x and y alike, so a desk is as tall against its width as the page draws it) and z on the depth, so a room is
// the page's room with its width, 6 percent shallower. No three.js and no document: a test can run it.

/** The page's room: its width, depth and wall height in page units, and the thickness of its walls. */
export const PAGE = Object.freeze({ w: 7, d: 5.6, h: 2.66, wall: 0.2, margin: 0.17 });

/**
 * The mapping of page units on a room of width `W`, depth `D`, floor height `H` and slab `SLAB` (world units), the room standing on the slab with its
 * centre at the origin. Returns {sx, sy, sz, X(px), Y(py), Z(pz), wallTop (the walls' top in page y: the page's 2.66), slab (the slab's thickness in page y)}.
 * `H` is the closed building's floor height; a room's walls are the page's own height on the same scale, a little lower, and the floors open by what the page leaves between them.
 */
export function pageFrame({ W, D, H, SLAB }) {
  const sx = W / PAGE.w;
  const sy = sx;
  const sz = D / PAGE.d;
  return {
    sx, sy, sz,
    X: (px) => -W / 2 + px * sx,
    Y: (py) => SLAB + py * sy,
    Z: (pz) => -D / 2 + pz * sz,
    wallTop: PAGE.h,
    slab: SLAB / sy,
  };
}

/**
 * The world size of one unit of the owl's drawing. The owl is a flat figure on a plane facing the camera, where a world unit is a screen unit; the page
 * draws it 0.2085 px a unit against a room unit of 20 px, and a room unit is `sx` world units whose isometric length on the screen is 0.817 of one.
 */
export const owlScale = (f) => (0.2085 / 20) * f.sx * 0.817;

/**
 * A batch (kit.batch()) that takes page units: `box(tones, x, y, z, w, h, d)` from the corner nearest the origin, `front(tone, x0, y0, x1, y1, z)` a rectangle
 * facing the camera's left (+z), `side(tone, z0, y0, z1, y1, x)` one facing its right (+x), `flat(tone, x0, z0, x1, z1, y)` one facing up, `tri` and `quad`
 * in page points. Returns the wrapper; `raw` is the batch.
 */
export function pageBatch(batch, f) {
  const point = (p) => [f.X(p[0]), f.Y(p[1]), f.Z(p[2])];
  return {
    raw: batch,
    box: (tones, x, y, z, w, h, d) => batch.box(w * f.sx, h * f.sy, d * f.sz, f.X(x + w / 2), f.Y(y), f.Z(z + d / 2), tones),
    front: (tone, x0, y0, x1, y1, z) => batch.front(f.X(x0), f.Y(y0), f.X(x1), f.Y(y1), f.Z(z), tone),
    side: (tone, z0, y0, z1, y1, x) => batch.side(f.Z(z0), f.Y(y0), f.Z(z1), f.Y(y1), f.X(x), tone),
    flat: (tone, x0, z0, x1, z1, y) => batch.flat(f.X(x0), f.Z(z0), f.X(x1), f.Z(z1), f.Y(y), tone),
    quad: (tone, a, b, c, d) => batch.quad(point(a), point(b), point(c), point(d), tone),
    tri: (tone, a, b, c) => batch.tri(point(a), point(b), point(c), tone),
  };
}

/**
 * A page batch for one seat of the L: the same methods as `pageBatch`'s result (`box`, `front`, `side`, `flat`, `raw`), taking today's workstation's page
 * units and putting them at the seat. `seat` is {turn ("none" or "swap"), q: [x, z] (the seat's centre), s (the scale), c0: [x, z] (the point today's workstation is taken about)}, as
 * `seat(i)` of seats-layout.js gives it. A "none" seat is today's workstation scaled and moved. A "swap" seat exchanges the two floor axes: a mirror, not a rotation, so a box stays a
 * box with its width and depth exchanged, a rectangle facing +z becomes one facing +x and the reverse, and every face keeps its tone (a face facing +z is the left face whatever drew
 * it, so the light stays on one side). Every range stays increasing (the scale is positive). `quad` and `tri` throw: a swapped quad would reverse its winding on the kit's single-sided material.
 */
export function seatBatch(pb, seat) {
  const { q, s, c0 } = seat;
  const only = () => {
    throw new Error("seatBatch draws boxes and rectangles only");
  };
  if (seat.turn === "swap") {
    const X = (z) => q[0] + s * (z - c0[1]);      // today's z becomes x
    const Z = (x) => q[1] + s * (x - c0[0]);      // today's x becomes z
    return {
      raw: pb.raw,
      box: (tones, x, y, z, w, h, d) => pb.box(tones, X(z), s * y, Z(x), s * d, s * h, s * w),
      front: (tone, x0, y0, x1, y1, z) => pb.side(tone, Z(x0), s * y0, Z(x1), s * y1, X(z)),
      side: (tone, z0, y0, z1, y1, x) => pb.front(tone, X(z0), s * y0, X(z1), s * y1, Z(x)),
      flat: (tone, x0, z0, x1, z1, y) => pb.flat(tone, X(z0), Z(x0), X(z1), Z(x1), s * y),
      quad: only,
      tri: only,
    };
  }
  const X = (x) => q[0] + s * (x - c0[0]);
  const Z = (z) => q[1] + s * (z - c0[1]);
  return {
    raw: pb.raw,
    box: (tones, x, y, z, w, h, d) => pb.box(tones, X(x), s * y, Z(z), s * w, s * h, s * d),
    front: (tone, x0, y0, x1, y1, z) => pb.front(tone, X(x0), s * y0, X(x1), s * y1, Z(z)),
    side: (tone, z0, y0, z1, y1, x) => pb.side(tone, Z(z0), s * y0, Z(z1), s * y1, X(x)),
    flat: (tone, x0, z0, x1, z1, y) => pb.flat(tone, X(x0), Z(z0), X(x1), Z(z1), s * y),
    quad: only,
    tri: only,
  };
}
