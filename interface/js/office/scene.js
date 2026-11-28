// The office's canvas: floor, walls, desks, the board and one figure for each agent, drawn in whole device pixels (the zoom is an integer number of
// device pixels for each art pixel, so the art never blurs). It draws only when something asked for a frame, through the render scheduler of the
// other scenes (../scene/loop.js), and nothing here reads the service: the view gives it the room, the agents and the figures.

import { createLoop } from "../scene/loop.js";
import { paintPlaceholder } from "./placeholder.js";
import { createSprites, SPRITE_H, SPRITE_W } from "./sprites.js";
import { TILE } from "./room.js";

const BOARD_ROWS = 8;          // art pixels the board is tall, on the wall

/**
 * The zoom that fits the room in the host: `device` device pixels for each art pixel (a whole number when the room fits at 1 or more, else the fraction
 * that makes the whole room fit), `css` the same in CSS pixels,
 * and the room's top left corner in CSS pixels (the room is centred). A little room is left under the room for the figures' feet.
 */
export function fitScale({ cssW, cssH, dpr, roomW, roomH }) {
  const fit = Math.min((cssW * dpr) / (roomW * TILE), (cssH * dpr) / (roomH * TILE + 8));
  const k = fit >= 1 ? Math.floor(fit) : fit;     // below one device pixel for each art pixel the whole room still shows, at the fractional fit (smoothing stays off)
  const css = k / dpr;
  return { device: k, css, left: (cssW - roomW * TILE * css) / 2, top: (cssH - roomH * TILE * css) / 2 };
}

/**
 * Make the scene in `host`, or null when the browser gives no 2D context (the view then says so and lists every agent).
 * options: {context(canvas), raf, caf, hidden(), reduced(), onPick(name|null), onFrame(timestamp), dpr()}.
 */
export function createOfficeScene(host, { context, raf, caf, hidden, reduced, onPick, onFrame, dpr = () => (typeof window !== "undefined" && window.devicePixelRatio) || 1 }) {
  const canvas = document.createElement("canvas");
  canvas.setAttribute("class", "wb-office-canvas");
  canvas.setAttribute("aria-hidden", "true");
  const ctx = context(canvas);
  if (!ctx) return null;
  host.append(canvas);

  let room = null;
  let agents = [];
  let walkers = null;
  let signature = "";
  let tones = { floor: "", wall: "", board: "", warn: "" };
  let tonesKey = "";
  let drawn = { scale: null, list: [] };
  const sprites = createSprites({
    paint: paintPlaceholder,
    surface: (width, height) => {
      const surface = document.createElement("canvas");
      surface.width = width;
      surface.height = height;
      return { canvas: surface, ctx: context(surface) };
    },
  });

  const loop = createLoop({ raf, caf, render, hidden, reduced });

  function readTones() {
    const probe = document.createElement("span");
    probe.setAttribute("class", "wb-probe");
    host.append(probe);
    const read = (token) => {
      probe.style.setProperty("color", `var(${token})`);
      return typeof getComputedStyle === "function" ? getComputedStyle(probe).color : "";
    };
    const next = { floor: read("--wb-ground"), wall: read("--wb-sunken"), board: read("--pui-theme"), warn: read("--pui-warn") };
    probe.remove();
    const key = Object.values(next).join("|");
    const changed = key !== tonesKey;
    tonesKey = key;
    tones = next;
    return changed;
  }

  function size() {
    return { cssW: canvas.clientWidth || host.clientWidth || 640, cssH: canvas.clientHeight || host.clientHeight || 480 };
  }

  function layout() {
    const { cssW, cssH } = size();
    return { cssW, cssH, dpr: dpr(), ...fitScale({ cssW, cssH, dpr: dpr(), roomW: room.w, roomH: room.h }) };
  }

  /** The CSS point of the top centre of the figure standing at `tile` (fractional tiles allowed), relative to the host. */
  function screenOf(tile) {
    const view = layout();
    const px = TILE * view.css;
    return { x: view.left + (tile.x + 0.5) * px, y: view.top + (tile.y + 1) * px - SPRITE_H * view.css };
  }

  function rectOf(tile, view) {
    const px = TILE * view.css;
    const width = SPRITE_W * view.css;
    const left = view.left + (tile.x + 0.5) * px - width / 2;
    const top = view.top + (tile.y + 1) * px - SPRITE_H * view.css;
    return { left, top, right: left + width, bottom: top + SPRITE_H * view.css };
  }

  function render(timestamp) {
    if (onFrame) onFrame(timestamp);
    if (!room || !walkers) return;
    const view = layout();
    const width = Math.round(view.cssW * view.dpr);
    const height = Math.round(view.cssH * view.dpr);
    if (canvas.width !== width) canvas.width = width;
    if (canvas.height !== height) canvas.height = height;
    ctx.imageSmoothingEnabled = false;
    ctx.clearRect(0, 0, width, height);
    const k = view.device;
    const ox = Math.round(view.left * view.dpr);
    const oy = Math.round(view.top * view.dpr);
    const t = TILE * k;
    // floor, then the walls (the border), the board on the top wall and the desks with their chairs
    ctx.fillStyle = tones.floor;
    ctx.fillRect(ox, oy, room.w * t, room.h * t);
    ctx.fillStyle = tones.wall;
    ctx.fillRect(ox, oy, room.w * t, t);
    ctx.fillRect(ox, oy + (room.h - 1) * t, room.w * t, t);
    ctx.fillRect(ox, oy, t, room.h * t);
    ctx.fillRect(ox + (room.w - 1) * t, oy, t, room.h * t);
    ctx.fillStyle = tones.board;
    ctx.fillRect(ox + 2 * t, oy + 4 * k, (room.w - 4) * t, BOARD_ROWS * k);
    ctx.fillStyle = tones.wall;
    for (const seat of room.seats) {
      ctx.fillRect(ox + seat.desk.x * t, oy + seat.desk.y * t, 2 * t, t);
      ctx.fillRect(ox + seat.seat.x * t + 4 * k, oy + seat.seat.y * t + 6 * k, 8 * k, 8 * k);
    }
    // the figures, back to front
    const byName = new Map(agents.map((a) => [a.name, a]));
    const figures = walkers.positions().filter((f) => byName.has(f.name)).sort((a, b) => a.y - b.y);
    drawn = { scale: view, list: [] };
    for (const figure of figures) {
      const agent = byName.get(figure.name);
      const { image, mirror } = spriteOf(agent, figure);
      const sx = ox + Math.round(figure.x * t) + (t - SPRITE_W * k) / 2;
      const sy = oy + Math.round((figure.y + 1) * t) - SPRITE_H * k;
      if (mirror) {
        ctx.save();
        ctx.translate(sx + SPRITE_W * k, sy);
        ctx.scale(-1, 1);
        ctx.drawImage(image, 0, 0, SPRITE_W * k, SPRITE_H * k);
        ctx.restore();
      } else {
        ctx.drawImage(image, sx, sy, SPRITE_W * k, SPRITE_H * k);
      }
      if (agent.decisions > 0) {
        ctx.fillStyle = tones.warn;
        ctx.fillRect(sx + 12 * k, sy, 3 * k, 3 * k);
      }
      drawn.list.push({ name: figure.name, rect: rectOf(figure, view) });
    }
  }

  function spriteOf(agent, figure) {
    return sprites.get(agent.look, figure.pose, figure.frame, figure.dir);
  }

  // The colours come from the page's tokens, so they are read again when the system's scheme or the person's choice of light or dark changes.
  const query = typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  const onScheme = () => {
    if (readTones()) loop.requestRender();
  };
  if (query && query.addEventListener) query.addEventListener("change", onScheme);
  const observer = typeof MutationObserver === "function" && typeof document !== "undefined" && document.documentElement ? new MutationObserver(onScheme) : null;
  if (observer) observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-pui-mode"] });
  const sizer = typeof ResizeObserver === "function" ? new ResizeObserver(() => loop.requestRender()) : null;
  if (sizer) sizer.observe(canvas);
  readTones();

  function onClick(event) {
    const box = canvas.getBoundingClientRect ? canvas.getBoundingClientRect() : { left: 0, top: 0 };
    if (onPick) onPick(scene.pick(event.clientX - box.left, event.clientY - box.top));
  }
  canvas.addEventListener("click", onClick);
  // the pointer cursor is for a figure: a class on the canvas while the pointer is over one
  function onMove(event) {
    const box = canvas.getBoundingClientRect ? canvas.getBoundingClientRect() : { left: 0, top: 0 };
    canvas.classList.toggle("is-pointer", scene.pick(event.clientX - box.left, event.clientY - box.top) !== null);
  }
  function onLeave() {
    canvas.classList.remove("is-pointer");
  }
  canvas.addEventListener("pointermove", onMove);
  canvas.addEventListener("pointerleave", onLeave);

  const scene = {
    /** Give the scene what to draw: the room, the drawn agents ([{name, look, decisions, ...}]), and the figures. A frame is asked for only when something changed. */
    setModel(nextRoom, nextAgents, nextWalkers) {
      const key = nextAgents.map((a) => `${a.name}|${a.state}|${a.decisions}|${a.look.hue}`).join(";");
      const changed = nextRoom !== room || nextWalkers !== walkers || key !== signature;
      room = nextRoom;
      agents = nextAgents;
      walkers = nextWalkers;
      signature = key;
      if (readTones() || changed) loop.requestRender();
    },
    requestRender() {
      loop.requestRender();
    },
    /** Start the walk animation (ambient: held to the scheduler's rate); false under reduced motion, where one frame is drawn instead. */
    startWalk() {
      return loop.start("walk", { ambient: true });
    },
    stopWalk() {
      loop.stop("walk");
    },
    /** The CSS point (relative to the host) of the top centre of a figure standing at `tile`. */
    screenOf(tile) {
      return room ? screenOf(tile) : { x: 0, y: 0 };
    },
    /** The name of the figure under a CSS point of the canvas (the one in front when two overlap), or null. */
    pick(x, y) {
      for (let i = drawn.list.length - 1; i >= 0; i--) {
        const r = drawn.list[i].rect;
        if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) return drawn.list[i].name;
      }
      return null;
    },
    setHidden(value) {
      loop.setHidden(value);
    },
    resize() {
      loop.requestRender();
    },
    stats() {
      return loop.stats();
    },
    dispose() {
      loop.dispose();
      canvas.removeEventListener("click", onClick);
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerleave", onLeave);
      if (query && query.removeEventListener) query.removeEventListener("change", onScheme);
      if (observer) observer.disconnect();
      if (sizer) sizer.disconnect();
      canvas.remove();
    },
  };
  return scene;
}
