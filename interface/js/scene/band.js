// Where a drawing stands beside a notice band (F2-D15): pure arithmetic on rectangles, no three.js and no document.
//
// The Control room's server room is fitted in what the KPI column, the header and the panel leave. A band over the scene (a configuration not accepted: a column as narrow as the room between the
// KPI column and the panel, as tall as its command is long) stands exactly where that rectangle is, so the room, fitted as if the band were not there, was drawn under it and hidden, and fitted
// round it, was a slot of 50 px. The room goes into the strip left of the band instead, under the KPI cards (which end above it), at the size that strip lets it have.

/** The room a strip of the scene has to leave for a drawing, at least (pixels): narrower than this the band is let to cover the drawing, as the Building's tower is. */
export const MIN_STRIP = 160;

/**
 * The insets to fit a drawing with a notice band over the scene. `counted` are the page's insets with the band counted, `free` the same with it ignored (both {left, right, top, bottom, pad});
 * `band`, `scene` and `kpis` are rectangles {left, top, right, bottom, width, height} in the page's pixels (`band` null or empty when there is none). A band that is wide (a strip along the top: the
 * page's own insets already put the drawing under it) and a band with no room beside it give `counted` when the strip is too narrow to be worth it, `free` (the band floats over the drawing) otherwise;
 * a tall band gives the strip left of it, from the KPI cards' foot down: left edge 8, right edge 12 px before the band.
 */
export function insetsBesideBand({ counted, free, band, scene, kpis }) {
  if (!band || !(band.width > 0 && band.height > 0)) return free;
  const wide = band.width / scene.width > band.height / scene.height;
  if (wide) return counted;
  const strip = band.left - scene.left - 12 - 8;
  if (strip < MIN_STRIP) return free;   // no room beside it: the band floats over the drawing at its size
  const cards = kpis && kpis.height > 0 && kpis.right <= band.left ? Math.max(0, kpis.bottom - scene.top + 12) : 0;
  return { ...free, left: 8, right: Math.max(8, scene.right - band.left + 12), top: Math.max(free.top || 0, cards) };
}
