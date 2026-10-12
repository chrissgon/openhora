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
