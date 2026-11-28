// The room: a grid of tiles with one desk and one seat for each agent, a board along the top wall and open floor to walk on. Pure, no document.
// The grid is the A* port's WalkGrid: the border and the desks are blocked, a seat is walkable and avoided, the rest is free.

import { BLOCKED, FREE, SEAT, WalkGrid } from "./astar.js";

export const TILE = 16;           // art pixels in a tile
export const MAX_SEATS = 24;      // agents drawn; the rest are listed beside the room

/** The room for `names` (agent names, in floor order): {w, h, grid, seats: [{name, desk, seat}], board, wander, overflow}. */
export function buildRoom(names) {
  const drawn = names.slice(0, MAX_SEATS);
  const n = Math.max(1, drawn.length);
  const cols = Math.min(4, n);
  const rows = Math.ceil(n / 4);
  const w = 3 + 4 * cols;
  const h = 4 + 3 * rows;
  const grid = new WalkGrid(w, h);
  grid.fill(0, 0, w, h, FREE);
  for (let x = 0; x < w; x++) {
    grid.set(x, 0, BLOCKED);
    grid.set(x, h - 1, BLOCKED);
  }
  for (let y = 0; y < h; y++) {
    grid.set(0, y, BLOCKED);
    grid.set(w - 1, y, BLOCKED);
  }
  const seats = drawn.map((name, i) => {
    const x0 = 2 + 4 * (i % 4);
    const y0 = 3 + 3 * Math.floor(i / 4);
    grid.set(x0, y0, BLOCKED);
    grid.set(x0 + 1, y0, BLOCKED);
    grid.set(x0, y0 + 1, SEAT);
    return { name, desk: { x: x0, y: y0 }, seat: { x: x0, y: y0 + 1 } };
  });
  const board = [];
  for (let x = 2; x <= w - 3; x++) board.push({ x, y: 1 });
  const wander = [];
  for (let y = 2; y < h; y++) for (let x = 0; x < w; x++) if (grid.get(x, y) === FREE) wander.push({ x, y });
  return { w, h, grid, seats, board, wander, overflow: names.slice(MAX_SEATS) };
}
