// The cache of figures: each look, pose, frame and direction is painted once onto its own small surface, and a figure facing left is the one
// facing right, mirrored when it is drawn. The painter and the surface are given, so a test counts the paints and no browser is needed.

export const SPRITE_W = 16;
export const SPRITE_H = 24;

/** `paint(ctx, {look, pose, frame, dir})` draws one figure; `surface(w, h)` returns {canvas, ctx}. */
export function createSprites({ paint, surface }) {
  const cache = new Map();
  return {
    /** {image, mirror}: the painted surface and whether the caller draws it mirrored. */
    get(look, pose, frame, dir) {
      const facing = dir === "left" ? "right" : dir;
      const key = `${look.hue}|${pose}|${frame}|${facing}`;
      let image = cache.get(key);
      if (!image) {
        const made = surface(SPRITE_W, SPRITE_H);
        paint(made.ctx, { look, pose, frame, dir: facing });
        image = made.canvas;
        cache.set(key, image);
      }
      return { image, mirror: dir === "left" };
    },
    size() {
      return { w: SPRITE_W, h: SPRITE_H };
    },
  };
}
