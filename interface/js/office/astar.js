// Ported from Habblaud (the repository marmottajr/habblaud on GitHub), files client/src/world/path/grid.ts and
// client/src/world/path/astar.ts at commit faa1a012b5fbf632c66dc6801c5383e53a542406: TypeScript types removed,
// comments translated to English, logic unchanged. Its licence, kept as its terms require:
//
// MIT License
//
// Copyright (c) 2026 Márcio Junior
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in all
// copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.

// Walkability grid of the building (1 cell per tile).
//   0 = blocked, 1 = free, 2 = free but avoided (seats: A* goes through one only when it must).

export const BLOCKED = 0;
export const FREE = 1;
export const SEAT = 2;

export class WalkGrid {
  constructor(w, h, version = 0) {
    this.w = w;
    this.h = h;
    this.version = version;
    this.cells = new Uint8Array(w * h);
  }

  inside(x, y) {
    return x >= 0 && y >= 0 && x < this.w && y < this.h;
  }

  get(x, y) {
    return this.inside(x, y) ? this.cells[y * this.w + x] : BLOCKED;
  }

  set(x, y, v) {
    if (this.inside(x, y)) this.cells[y * this.w + x] = v;
  }

  walkable(x, y) {
    return this.get(x, y) !== BLOCKED;
  }

  fill(x, y, w, h, v) {
    for (let yy = y; yy < y + h; yy++) for (let xx = x; xx < x + w; xx++) this.set(xx, yy, v);
  }

  /** Nearest walkable tile (ring search), or null. */
  nearestWalkable(x, y, maxR = 12) {
    if (this.walkable(x, y)) return { x, y };
    for (let r = 1; r <= maxR; r++) {
      let best = null;
      let bestD = Infinity;
      for (let dy = -r; dy <= r; dy++) {
        for (let dx = -r; dx <= r; dx++) {
          if (Math.max(Math.abs(dx), Math.abs(dy)) !== r) continue;
          if (!this.walkable(x + dx, y + dy)) continue;
          const d = dx * dx + dy * dy;
          if (d < bestD) {
            bestD = d;
            best = { x: x + dx, y: y + dy };
          }
        }
      }
      if (best) return best;
    }
    return null;
  }

  /** BFS: set of indices reachable from (x, y). */
  reachableFrom(x, y) {
    const seen = new Uint8Array(this.w * this.h);
    if (!this.walkable(x, y)) return seen;
    const queue = new Int32Array(this.w * this.h);
    let head = 0;
    let tail = 0;
    queue[tail++] = y * this.w + x;
    seen[y * this.w + x] = 1;
    while (head < tail) {
      const i = queue[head++];
      const cx = i % this.w;
      const cy = (i - cx) / this.w;
      for (let k = 0; k < 4; k++) {
        const nx = cx + (k === 0 ? 1 : k === 1 ? -1 : 0);
        const ny = cy + (k === 2 ? 1 : k === 3 ? -1 : 0);
        if (!this.walkable(nx, ny)) continue;
        const j = ny * this.w + nx;
        if (seen[j]) continue;
        seen[j] = 1;
        queue[tail++] = j;
      }
    }
    return seen;
  }
}

// 4-direction A* over the WalkGrid. Buffers are reused between searches (no allocation per call,
// except the output array the caller gives). Turns cost extra, to give natural L-shaped paths
// instead of staircases.

const SEAT_COST = 6;
const TURN_COST = 0.35;
const DX = [1, -1, 0, 0];
const DY = [0, 0, 1, -1];

export class PathFinder {
  heapSize = 0;
  gen = 0;

  constructor(grid) {
    this.setGrid(grid);
  }

  setGrid(grid) {
    const n = grid.w * grid.h;
    if (!this.g || this.g.length !== n) {
      this.g = new Float32Array(n);
      this.f = new Float32Array(n);
      this.from = new Int32Array(n);
      this.dirIn = new Int8Array(n);
      this.stamp = new Uint32Array(n);
      this.closed = new Uint32Array(n);
      this.heap = new Int32Array(n * 4 + 8);
      this.heapKey = new Float32Array(n * 4 + 8);
      this.gen = 0;
    }
    this.grid = grid;
  }

  /**
   * Path from (sx, sy) to (gx, gy). Fills `out` with pairs [x0, y0, x1, y1, ...] WITHOUT the start
   * and WITH the goal. The start may be blocked (e.g. a character on a seat).
   * Returns false when there is no path.
   */
  find(sx, sy, gx, gy, out) {
    out.length = 0;
    const grid = this.grid;
    if (!grid.inside(sx, sy) || !grid.walkable(gx, gy)) return false;
    if (sx === gx && sy === gy) return true;
    const w = grid.w;
    const cells = grid.cells;
    if (++this.gen >= 0xffffffff) {
      this.stamp.fill(0);
      this.closed.fill(0);
      this.gen = 1;
    }
    const gen = this.gen;
    const start = sy * w + sx;
    const goal = gy * w + gx;
    this.heapSize = 0;
    this.stamp[start] = gen;
    this.g[start] = 0;
    this.f[start] = Math.abs(sx - gx) + Math.abs(sy - gy);
    this.from[start] = -1;
    this.dirIn[start] = -1;
    this.push(start);

    while (this.heapSize > 0) {
      const cur = this.pop();
      if (cur === goal) {
        this.reconstruct(goal, start, w, out);
        return true;
      }
      if (this.closed[cur] === gen) continue;
      this.closed[cur] = gen;
      const cx = cur % w;
      const cy = (cur - cx) / w;
      const gCur = this.g[cur];
      const dIn = this.dirIn[cur];
      for (let k = 0; k < 4; k++) {
        const nx = cx + DX[k];
        const ny = cy + DY[k];
        if (nx < 0 || ny < 0 || nx >= w || ny >= grid.h) continue;
        const ni = ny * w + nx;
        const cell = cells[ni];
        if (cell === BLOCKED) continue;
        if (this.closed[ni] === gen) continue;
        let cost = cell === SEAT && ni !== goal ? SEAT_COST : 1;
        if (dIn >= 0 && dIn !== k) cost += TURN_COST;
        const ng = gCur + cost;
        if (this.stamp[ni] === gen && ng >= this.g[ni]) continue;
        this.stamp[ni] = gen;
        this.g[ni] = ng;
        // slight tie-break in favour of nodes closer to the goal
        const h = Math.abs(nx - gx) + Math.abs(ny - gy);
        this.f[ni] = ng + h * 1.001;
        this.from[ni] = cur;
        this.dirIn[ni] = k;
        this.push(ni);
      }
    }
    return false;
  }

  reconstruct(goal, start, w, out) {
    let n = 0;
    for (let i = goal; i !== start && i >= 0; i = this.from[i]) n++;
    out.length = n * 2;
    let k = n - 1;
    for (let i = goal; i !== start && i >= 0; i = this.from[i]) {
      const x = i % w;
      out[k * 2] = x;
      out[k * 2 + 1] = (i - x) / w;
      k--;
    }
  }

  push(i) {
    if (this.heapSize >= this.heap.length) {
      // should not happen (each node enters a few times); grows for safety
      const bi = new Int32Array(this.heap.length * 2);
      bi.set(this.heap);
      this.heap = bi;
      const bk = new Float32Array(this.heapKey.length * 2);
      bk.set(this.heapKey);
      this.heapKey = bk;
    }
    const heap = this.heap;
    const key = this.heapKey;
    const k = this.f[i];
    let pos = this.heapSize++;
    while (pos > 0) {
      const parent = (pos - 1) >> 1;
      if (key[parent] <= k) break;
      heap[pos] = heap[parent];
      key[pos] = key[parent];
      pos = parent;
    }
    heap[pos] = i;
    key[pos] = k;
  }

  pop() {
    const heap = this.heap;
    const key = this.heapKey;
    const top = heap[0];
    const size = --this.heapSize;
    const last = heap[size];
    const lastK = key[size];
    let pos = 0;
    while (true) {
      const l = pos * 2 + 1;
      if (l >= size) break;
      const r = l + 1;
      const c = r < size && key[r] < key[l] ? r : l;
      if (key[c] >= lastK) break;
      heap[pos] = heap[c];
      key[pos] = key[c];
      pos = c;
    }
    heap[pos] = last;
    key[pos] = lastK;
    return top;
  }
}
