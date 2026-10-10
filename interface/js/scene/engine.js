// The scene engine: one WebGL renderer for the page, an isometric orthographic camera, the palette read from the page's
// tokens, picking, HTML labels and the render scheduler. It draws a scene only when something changed (loop.js), at most
// 30 frames a second while an ambient animation runs, never while the tab is hidden, at a pixel ratio of at most 2, and
// with no ambient animation under reduced motion. Without WebGL it throws NoWebGL and the screen shows its HTML alone.
//
// What it draws is built by a scene builder (city.js now; the building, floor, lobby and control room scenes come with
// their packages through the same `show(kind, model)`).

import * as THREE from "../three.js";
import { h } from "../dom.js";
import { icon } from "../frame/icons.js";
import { clampView, fitView, frustumOf, panBy, panPixels, pointerToNdc, zoomAt } from "./camera.js";
import { pulseBeacon, restBeacon } from "./city.js";
import { ease, fitFrustum } from "./fit.js";
import { createKit } from "./kit.js";
import { cornerPosition, fitInsets, mountLabels, placeLabels } from "./labels.js";
import { applyOutlineVisibility, showPlan } from "./look.js";
import { createLoop } from "./loop.js";
import { outlineGeometry } from "./outline.js";
import { pickHit, pickList, visibleSamples } from "./pick.js";
import { createPointer } from "./pointer.js";
import { LIGHT_WHITE, readPalette, watchScheme } from "./palette.js";
import { buildWorld } from "./world.js";
import { boundsOfBox, contentBounds, createCamera } from "./rig.js";
import { createTween } from "./tween.js";
import { frameSeconds } from "./prototype-motion.js";
import { tooltipPlace } from "./room-words.js";

export const BUILDERS = { world: buildWorld };   // the Control room registers its own kind here (views/control-scene.js)
// The motions of the prototype (WP-9.10: its own functions, prototype-motion.js, stepped frame by frame): the camera approaches its
// goal by `1 - exp(-dt * 4.5)` a frame and the building opens by `1 - exp(-dt * 3.2)` read through a smoothstep. A move ends when it is
// within one percent of its goal, which takes ln(100) over the rate: the two durations below are what that comes to, for the page's
// checks, not times the engine counts.
export const CAMERA_MS = 1023;    // A5: the camera moves in (ln 100 / 4.5 seconds)
export const OPEN_MS = 1439;      // A5: the building opens, the floors separate once (ln 100 / 3.2 seconds)
export const FLY_SETTLE_AT = 0.9; // the promise of a move resolves when it is nine tenths done (about 0.5 s); the route does not wait for it
export const DROP_MS = 300;       // A3: a waiting marker drops in once
export const TAG_MS = 600;        // A6: the work-order tag moves to the next floor once
export const OUTLINE_PAD = 0.04;  // the hover outline stands this far off the object (the prototype's, for a piece of furniture)
export const SHADE_Y = 0.22;      // the shadows land on a plane just over the City's blocks (their paving is at 0.21), so they show on the walk and the paving


export class NoWebGL extends Error {
  constructor() {
    super("WebGL is not available");
    this.name = "NoWebGL";
  }
}

/**
 * Create the engine in `host`: it makes the canvas and the label overlay itself.
 * options: {label, getInsets({dim}) -> {left, right, top, bottom, pad}, onOpen(id), onHover(id|null), onUnavailable()}.
 */
export function createEngine(host, options) {
  const canvas = h("canvas", { class: "wb-canvas", role: "img", tabindex: "0", "aria-label": options.label || "Scene" });
  canvas.setAttribute("aria-describedby", "wb-camera-help");
  let renderer;
  try {
    // the room's layers (the owl's drawing, a note, a binder) stand 0.0016 of a unit apart in depth, which asks for a 24-bit depth buffer over the camera's 1 to 500: the plain
    // (linear) one the browser gives by default, asked for here by name; a 16-bit one would fight (README, "The rooms")
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, depth: true, logarithmicDepthBuffer: false });
  } catch (e) {
    throw new NoWebGL();
  }
  if (!renderer.getContext()) throw new NoWebGL();
  const overlay = h("div", { class: "wb-overlay", "aria-hidden": "true" });
  const tooltip = h("div", { class: "pui-tooltip wb-tooltip", role: "tooltip", hidden: true });
  overlay.append(tooltip);
  // The HTML equivalent of the camera: zoom in, zoom out and fit, in reach of the keyboard. With the focus on the scene, + and -
  // zoom, the arrows pan and 0 fits; the wheel and a pinch zoom, a drag pans, a double click on the ground fits.
  const cameraButton = (label, name) => h("button", { class: "pui-btn pui-surface pui-outline wb-camera-btn", type: "button", "aria-label": label, title: label }, icon(name, 16));
  const zoomInButton = cameraButton("Zoom in", "plus");
  const zoomOutButton = cameraButton("Zoom out", "minus");
  const fitButton = cameraButton("Fit the scene", "maximize");
  const tools = h("div", { class: "wb-camera-tools", role: "group", "aria-label": "Scene view" }, zoomInButton, zoomOutButton, fitButton,
    h("span", { class: "wb-sr", id: "wb-camera-help", text: "Scene view: plus and minus zoom, the arrow keys move, zero fits the whole scene." }));
  host.append(canvas, overlay, tools);

  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;   // the library's soft filter: the PCFSoft name was folded into it, and `shadow.radius` softens it
  renderer.shadowMap.autoUpdate = false;   // the sun does not move: shadows are drawn again only when the geometry changes
  const scene = new THREE.Scene();
  const camera = createCamera(THREE);

  const reducedQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  const clock = () => performance.now();
  const loop = createLoop({
    raf: (fn) => requestAnimationFrame(fn), caf: (id) => cancelAnimationFrame(id),
    render: (ts) => draw(ts), hidden: () => document.hidden, reduced: () => reducedQuery.matches,
  });

  let palette = null;
  let worldKit = null;
  let contentKit = null;
  let content = null;             // what the builder returned
  let labelEntries = [];
  let model = null;
  let kind = null;
  let signature = "";
  let size = { w: 0, h: 0 };
  let frustum = null;             // the fitted frustum: the whole diorama in the free rectangle
  let bounds = null;              // the diorama's bounds in camera space
  let view = fitView();           // the person's zoom and pan on top of it (camera.js)
  const tween = createTween();    // the camera move in flight, if any
  let drops = [];                 // {marker, start}
  let worldLast = 0;              // the time of the last frame of the world's opening or closing
  let cameraSet = false;          // the camera has been fitted once: later moves of the focus fly instead of cutting
  let lotCount = 0;               // the lots the world had at the last show
  let tagRun = null;              // {group, from, to, start}: the work-order tag moving (A6)
  let previousTag = null;         // {y}: where the tag was on the build before
  let lastInsets = null;
  let previousMarkers = new Set();
  let previousReady = false;      // the build before this one held real data: a marker not in it has arrived
  let previousDecisions = new Map();
  let outline = null;
  let markedOutline = null;      // the thin outline the building of the chosen project keeps in the City (WP-9.11)
  let hoverId = null;
  let hoverSource = null;        // who outlined it: "pointer" (over the scene or a list row) or "keyboard" (the focus on a list row): Escape clears only the second
  let lostText = false;
  let disposed = false;
  const epoch = clock();          // the ambient animations' clock: it is never restarted, so a rebuild cannot restart a motion
  let structureSignature = "";
  let builds = 0;                 // how many times the scene was built and how many times only its words changed: the page's check that a poll does not rebuild
  let relabels = 0;
  let frameMs = 0;                // the browser-side cost of the last frame (submitting the draw calls)
  // The hover outline is the prototype's: a one-pixel line of the theme colour, full opacity, tested against the depth so the
  // edges behind the object stay hidden, standing OUTLINE_PAD off the object.
  const outlineMaterial = new THREE.LineBasicMaterial({ color: 0xffffff });

  // --- the world: lights and ground, rebuilt when the palette changes -----------------------------------------------------
  function buildSky() {
    if (worldKit) {
      const old = scene.children.filter((c) => c.userData.world);
      scene.remove(...old);
      for (const light of old) if (light.shadow) light.shadow.dispose();   // the 2048 px shadow map of the sun being replaced
      worldKit.dispose();
    }
    palette = readPalette(host);
    worldKit = createKit(palette);
    const world = [];
    const hemi = new THREE.HemisphereLight(LIGHT_WHITE, palette.T.emphasis, palette.hemiIntensity);
    const sun = new THREE.DirectionalLight(LIGHT_WHITE, palette.sunIntensity);
    sun.position.set(-14, 34, 22);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, { left: -45, right: 45, top: 45, bottom: -45, near: 1, far: 140 });
    sun.shadow.radius = 5;
    sun.shadow.bias = -0.0006;
    const ground = new THREE.Mesh(worldKit.track(new THREE.PlaneGeometry(600, 600)), worldKit.unlit(palette.ground));
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.06;   // under the City's streets (city.js), which lie at 0
    const shade = new THREE.Mesh(worldKit.track(new THREE.PlaneGeometry(600, 600)),
      worldKit.adopt(new THREE.ShadowMaterial({ color: palette.shadowColor, opacity: palette.shadowOpacity })));
    shade.rotation.x = -Math.PI / 2;
    shade.position.y = SHADE_Y;
    shade.receiveShadow = true;
    world.push(hemi, sun, ground, shade);
    for (const object of world) object.userData.world = true;
    scene.add(...world);
    renderer.setClearColor(palette.ground, 1);
    outlineMaterial.color.copy(palette.T.theme);
  }

  // --- the content: a scene builder's group, rebuilt when the model changes ------------------------------------------------
  function clearContent() {
    stopAnimations();
    if (outline) {
      scene.remove(outline);
      outline.geometry.dispose();
      outline = null;
    }
    if (markedOutline) {
      scene.remove(markedOutline);
      markedOutline.geometry.dispose();
      markedOutline = null;
    }
    hoverId = null;
    hoverSource = null;
    if (content) scene.remove(content.group);
    if (contentKit) contentKit.dispose();
    for (const entry of labelEntries) entry.node.remove();
    labelEntries = [];
    content = null;
    contentKit = null;
  }

  function stopAnimations() {
    for (const name of ["camera", "drops", "beacon", "tag", "world"]) loop.stop(name);
    tween.cancel();   // settles a waiting fly-in with false: nobody is left waiting for a move that will not finish
    drops = [];
    tagRun = null;
  }

  /** Build the scene again from the model. `keep`: the same scene again (a new palette): the open building stays open, no motion plays again. */
  function build(keep = false) {
    builds += 1;
    const playOpen = !keep && (!content || lotCount === 0);   // the first scene with buildings in it plays the opening; a rebuild of the same one does not
    clearContent();
    if (!model || !BUILDERS[kind]) return;
    contentKit = createKit(palette);
    content = BUILDERS[kind](contentKit, model);
    content.beacons = content.beacons || [];
    content.motions = content.motions || [];
    content.markers = content.markers || [];
    content.outlines = content.outlines || [];
    scene.add(content.group);
    // The world opens the building the route names: the first time it plays (the floors separate while the camera is fitted on it), and
    // never again for a rebuild of the same scene.
    if (content.live) {
      // a page opened on a floor shows the room at once; one opened on a building plays the opening
      const instant = !playOpen || reducedQuery.matches || Boolean(model.floor);
      content.setFocus(model.focus, instant);
      content.setFloors(model.floor, model.frame, instant);
      lotCount = model.lots.length;
    }
    applyOutlines();
    drawMarked();
    const words = content.live ? content.text(model) : { labels: content.labels };
    content.labels = words.labels;
    labelEntries = mountLabels(overlay, content.labels.map((l) => ({ ...l, anchor: l.anchor })), { popped: poppedOf(content.labels) });
    markLabels();
    const fresh = trackMarkers();
    renderer.shadowMap.needsUpdate = true;
    fit();
    cameraSet = Boolean(content.live ? lotCount > 0 : true);
    dropMarkers(fresh);
    startWorld();
    syncSurroundings();
    startTag();
    syncBeacons();
  }

  // The markers that arrived since the last build or update: they drop in once (A3).
  function trackMarkers() {
    const markerKeys = new Set(content.markers.map((m) => m.key));
    const fresh = previousReady ? content.markers.filter((m) => !previousMarkers.has(m.key)) : [];
    previousReady = Boolean(model.ready);
    previousMarkers = markerKeys;
    return fresh;
  }

  function dropMarkers(fresh) {
    if (!fresh.length || reducedQuery.matches) return;
    drops = fresh.map((marker) => ({ marker, start: clock() }));
    for (const d of drops) d.marker.group.position.y = d.marker.restY + 1.5;
    loop.start("drops", { ambient: false });
  }

  // The Floor and the Lobby show the room alone once the camera and the floors have settled; any motion shows the city round it again.
  function syncSurroundings() {
    if (!content || !content.live) return;
    const settled = !tween.active() && !content.moving();
    content.hideSurroundings(settled && Boolean(model.floor));
    pickCache = null;
    loop.requestRender();
  }

  // The world's towers move toward their targets frame by frame (the prototype's `explode`): the loop runs while any is moving.
  function startWorld() {
    if (!content || !content.live || !content.moving()) return;
    worldLast = clock();
    loop.start("world", { ambient: false });
  }

  // The labels whose decisions went up since the last build pop once (the badge's A3).
  function poppedOf(labels) {
    const popped = new Set();
    for (const label of labels) {
      if (previousDecisions.has(label.id) && label.decisions > previousDecisions.get(label.id)) popped.add(label.id);
    }
    previousDecisions = new Map(labels.map((l) => [l.id, l.decisions]));
    return reducedQuery.matches ? new Set() : popped;
  }

  // The same scene, other words (a meter moved, a title changed on a poll): the labels and tooltips are made again and nothing
  // else is touched, so no motion restarts, no shadow is drawn again and the camera stays where it is.
  function relabel() {
    relabels += 1;
    const words = content.text(model);
    for (const hit of content.hits) if (words.tips.has(hit.id)) hit.tip = words.tips.get(hit.id);
    content.labels = words.labels;
    if (words.open) {   // the object of the open tab changed (the Control room): its brackets move, nothing is built again
      content.open = words.open;
      content.noMarks = Boolean(words.noMarks);
      applyBrackets();
    }
    const popped = poppedOf(words.labels);
    for (const entry of labelEntries) entry.node.remove();
    labelEntries = mountLabels(overlay, words.labels.map((l) => ({ ...l, anchor: l.anchor })), { popped });
    markLabels();
    positionLabels();
    const hit = hoverId ? content.hits.find((x) => x.id === hoverId) : null;
    if (hit && !tooltip.hidden) tooltip.textContent = hit.tip;
    loop.requestRender();
  }

  // The outline lines of the lot, the floor or the room are drawn only for the object that is hovered or selected by the route.
  // A building's card is drawn with the theme border while the person has that project: hovered (on the scene or in the list) or
  // chosen by the route. The tracking bar's default project does not count.
  function markLabels() {
    for (const entry of labelEntries) {
      if (entry.spec.kind !== "card") continue;
      const open = Boolean(entry.spec.selected) || entry.spec.id === hoverId || (Boolean(content) && entry.spec.id === content.marked);
      if (open === entry.node.classList.contains("is-selected")) continue;
      entry.node.classList.toggle("is-selected", open);
      // C-7: a quiet project's dot opens into its card for the pointer and for the focus of its row in the list alike; the card is another size than the dot, and the
      // culling reads the size
      entry.width = entry.node.offsetWidth;
      entry.height = entry.node.offsetHeight;
      if (size.w) positionLabels();
    }
  }

  function applyOutlines() {
    if (content) applyOutlineVisibility(content.outlines, content.selected);
    canvas.classList.toggle("is-dim", Boolean(content && content.dim));   // a project that is not accepted: the whole drawing at 55 percent (`scene.css`)
    applyBrackets();
  }

  // R-17: a building of the City, followed (the project the person has chosen) or pointed at (on the scene or in the list), wears its eight corner
  // brackets in the brand colour, never an outline. They are drawn only while the building is closed: an opening building has its floors marked instead.
  function applyBrackets() {
    if (!content) return;
    for (const b of content.brackets || []) b.group.visible = b.tower.brackets.closed && (b.id === hoverId || b.id === content.marked);
    // R-28, R-31: an object of a room under the pointer or the focus (a floor of the Building, the owl, the board, the bookcase, the door) wears its corner brackets; R-51: so does the
    // object of the open tab in the Control room (`content.open`, the ids of its hits), and hits that share one set of brackets (the three racks) show it together
    // The page draws none on a phone, while the room has nothing to say (loading, not accepted): `content.noMarks`, and `content.marksMinWidth`, the canvas's width under which there are none
    const quiet = Boolean(content.noMarks) || Boolean(content.marksMinWidth && size.w && size.w < content.marksMinWidth);
    const open = quiet ? [] : content.open || [];
    const shown = new Map();
    for (const hit of content.hits) if (hit.marks) shown.set(hit.marks, shown.get(hit.marks) === true || (!quiet && hit.id === hoverId) || open.includes(hit.id));
    for (const [marks, on] of shown) marks.visible = on;
  }

  // The world changes in place: a model of the same lots (another poll, another route: the focus) never builds the scene again. A tower
  // whose floors changed is made again (tower by tower); the focus moves the camera; only another set of lots builds the world again.
  function updateWorld(next) {
    const sig = JSON.stringify(next);
    if (sig === signature) return false;
    const before = content.focusId();
    const floorBefore = `${model.floor || ""}|${model.frame || ""}`;
    const result = content.update(next);
    model = next;
    signature = sig;
    if (result.rebuild) {
      build();
      return true;
    }
    pickCache = null;
    drawMarked();
    const hadLots = lotCount > 0;
    lotCount = next.lots.length;
    relabel();
    const fresh = trackMarkers();
    dropMarkers(fresh);
    applyOutlines();
    if (hoverId && !content.hits.some((hit) => hit.id === hoverId)) {
      hoverId = null;
      setOutline(null);
    }
    renderer.shadowMap.needsUpdate = true;
    if (result.focus || result.floors || (hadLots === false && lotCount > 0)) {
      if (reducedQuery.matches) content.finish();
      refocus(hadLots && (content.focusId() !== before || `${next.floor || ""}|${next.frame || ""}` !== floorBefore));
    } else {
      fit();
    }
    startWorld();
    syncSurroundings();
    startTag();
    syncBeacons();
    loop.requestRender();
    return true;
  }

  // A6: the work-order tag moves from its old floor to its new one, once.
  function startTag() {
    const tag = content.tag;
    const before = previousTag;
    previousTag = tag ? { y: tag.y } : null;
    if (!tag || !before || before.y === tag.y || reducedQuery.matches || !model.ready || (content.live && content.moving())) return;
    tag.group.position.y = before.y;
    tagRun = { group: tag.group, from: before.y, to: tag.y, start: clock() };
    loop.start("tag", { ambient: false });
  }

  function syncBeacons() {
    if (!content || (!content.beacons.length && !content.motions.length)) {
      loop.stop("beacon");
      return;
    }
    if (reducedQuery.matches) {
      loop.stop("beacon");
      content.beacons.forEach(restBeacon);
      content.motions.forEach((m) => m.rest());
      loop.requestRender();
    } else {
      loop.start("beacon", { ambient: true });
    }
  }

  // --- layout and camera --------------------------------------------------------------------------------------------------
  function applyFrustum(f) {
    camera.left = f.left;
    camera.right = f.right;
    camera.top = f.top;
    camera.bottom = f.bottom;
    camera.updateProjectionMatrix();
  }

  // The part of the scene the camera frames: the open building of a world (or one floor of it), else all of it.
  function subjectBounds() {
    return content.subject ? boundsOfBox(THREE, camera, content.subject()) : contentBounds(THREE, camera, content.group);
  }

  // What the drawing says about itself to the page that measures the room round it: `dim` is true for a project that is not accepted, whose last data stays as it
  // was (building.html draws the notice band over it, not the drawing fitted under the band).
  const about = () => ({ dim: Boolean(content && content.dim) });

  // The frustum the camera should show now: the subject fitted in the free rectangle the page's panels leave, the person's view on top.
  function computeFit() {
    const insets = options.getInsets ? options.getInsets(about()) : {};
    lastInsets = insets;
    tools.style.setProperty("--wb-y", `${Math.max(16, insets.bottom || 0)}px`);   // above the tracking bar, whatever its height
    bounds = subjectBounds();
    const cap = content.zoomCap ? content.zoomCap(size) : null;   // the City is not closer than the page draws it
    frustum = fitFrustum(bounds, size, fitInsets(insets, corner ? corner.offsetHeight : 0), insets.pad || 1.04, cap);   // below the corner card, when there is one
    view = clampView(view, frustum, bounds);   // the person's zoom and pan stay while they are inside the limits
    return frustumOf(frustum, view);
  }

  function fit() {
    if (!content || !size.w || !size.h) return;
    const goal = computeFit();
    if (tween.active()) tween.retarget(goal);   // a move in flight goes on from where the camera is, to where the panels now leave room
    else applyView();
    positionLabels();
    applyBrackets();   // the Control room's marks depend on the canvas's width (none on a phone)
    loop.requestRender();
  }

  const cameraNow = () => ({ left: camera.left, right: camera.right, top: camera.top, bottom: camera.bottom });

  // The subject changed (a building opens, Back, a floor framed): the camera goes to its new frame, flying when it was already framed on
  // something (and the person allows motion), cutting otherwise. Returns the promise of the move (true when it is `settleAt` done).
  function refocus(animate, settleAt = 1) {
    if (!content || !size.w || !size.h) return Promise.resolve(false);
    view = fitView();
    const from = cameraNow();
    const goal = computeFit();
    positionLabels();
    loop.requestRender();
    if (animate && cameraSet && !reducedQuery.matches) {
      const move = tween.start(from, goal, clock(), settleAt);
      loop.start("camera", { ambient: false });
      return move;
    }
    tween.cancel();
    applyView();
    return Promise.resolve(false);
  }

  function applyView() {
    if (frustum) applyFrustum(frustumOf(frustum, view));
  }

  // The camera on the person's command (wheel, pinch, drag, keys, buttons): one frame on demand per change, never a loop.
  function setView(next) {
    view = next;
    applyView();
    positionLabels();
    loop.requestRender();
    pointerControl.again();   // the scene moved under a still mouse
  }
  const canMove = () => Boolean(content && frustum && bounds && !tween.active());
  const ndcOf = (clientX, clientY) => pointerToNdc(clientX, clientY, canvas.getBoundingClientRect());
  function zoomBy(factor, ndc = { x: 0, y: 0 }) {
    if (canMove()) setView(zoomAt(view, frustum, bounds, factor, ndc));
  }
  function moveBy(fx, fy) {
    if (canMove()) setView(panBy(view, frustum, bounds, fx, fy));
  }
  function resetView() {
    if (!frustum) return;
    setView(fitView());
  }

  function project(anchor) {
    const v = anchor.clone().project(camera);
    return { x: ((v.x + 1) / 2) * size.w, y: ((1 - v.y) / 2) * size.h };
  }

  function positionLabels() {
    placeCorner();
    if (!labelEntries.length) return;
    placeLabels(labelEntries, project, { hidden: false, insets: lastInsets, size });
  }

  // The corner slot: one card the page puts at the top right of the free rectangle (the Building's floor card).
  let corner = null;
  function placeCorner() {
    if (!corner || !lastInsets) return;
    const at = cornerPosition(size, lastInsets);
    corner.classList.toggle("is-bottom", Boolean(at.bottom));   // a phone's card hangs from its position (it is anchored at the bottom)
    corner.style.setProperty("--wb-x", `${at.x.toFixed(1)}px`);
    corner.style.setProperty("--wb-y", `${at.y.toFixed(1)}px`);
  }

  // A bottom sheet that covers the whole scene pauses it (setPaused below). While it does, the fit is left as it was: the cards are away and the sheet
  // is as tall as the page, so a fit made now would re-clamp the person's zoom and pan to a room they will not have when the sheet goes down again.
  let paused = false;
  let fitWaits = false;

  function measure() {
    const w = host.clientWidth;
    const hh = host.clientHeight;
    if (!w || !hh) return false;
    size = { w, h: hh };
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(w, hh, false);
    return true;
  }

  const observer = new ResizeObserver(() => {
    if (disposed || !measure()) return;
    if (paused) fitWaits = true;
    else fit();
  });
  observer.observe(host);

  // --- drawing ------------------------------------------------------------------------------------------------------------
  function draw(ts) {
    if (disposed || lostText) return;
    const now = clock();
    const moved = tween.step(now, size.w);
    if (moved) {
      applyFrustum(moved);
      positionLabels();   // the labels ride along with the camera (the prototype projected them every frame)
      if (!tween.active()) {
        loop.stop("camera");
        syncSurroundings();
      }
    }
    if (tagRun) {
      const t = Math.min(1, (now - tagRun.start) / TAG_MS);
      tagRun.group.position.y = tagRun.from + (tagRun.to - tagRun.from) * ease(t);
      renderer.shadowMap.needsUpdate = true;
      if (t >= 1) {
        tagRun = null;
        loop.stop("tag");
      }
    }
    if (content && content.live && loop.isActive("world")) {
      const moving = content.step(frameSeconds(now, worldLast));
      worldLast = now;
      pickCache = null;
      renderer.shadowMap.needsUpdate = true;
      positionLabels();   // the plates, the cards and the tag ride along with the floors
      applyBrackets();    // a building that begins to open has no brackets
      refreshOutline();
      if (!moving) {
        loop.stop("world");
        syncSurroundings();
      }
    }
    if (drops.length) {
      renderer.shadowMap.needsUpdate = true;
      for (const d of drops) {
        const t = Math.min(1, (now - d.start) / DROP_MS);
        d.marker.group.position.y = d.marker.restY + 1.5 * Math.pow(1 - t, 3);
      }
      if (now - drops[0].start >= DROP_MS) {
        drops = [];
        loop.stop("drops");
      }
    }
    if (content && (content.beacons.length || content.motions.length) && !reducedQuery.matches) {
      const seconds = (now - epoch) / 1000;
      content.beacons.forEach((b) => pulseBeacon(b, seconds));
      content.motions.forEach((m) => m.tick(seconds));
    }
    const started = clock();
    renderer.render(scene, camera);
    frameMs = clock() - started;
  }

  // --- picking, hover, tooltip ---------------------------------------------------------------------------------------------
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();

  // The pick (pick.js): the mesh under the pointer among the meshes of the pickable objects, never a line. The list is made again
  // when the content is built or an object moved, not on every pointer move.
  let pickCache = null;
  function pick(event) {
    if (!content) return { x: 0, y: 0, hit: null };
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const ndc = pointerToNdc(event.clientX, event.clientY, rect);
    pointer.set(ndc.x, ndc.y);
    if (!pickCache || pickCache.content !== content || tagRun || drops.length || (content.live && content.moving())) pickCache = { content, list: pickList(content.hits) };
    return { x, y, hit: pickHit(raycaster, camera, content.hits, pointer, pickCache.list) };
  }

  // The outline of the hovered object (outline.js): the edges of its own meshes, OUTLINE_PAD off the surface; its pad is the hit's own
  // when it has one. It is made in world space, so it is made again while the object moves (the building opening).
  function setOutline(id) {
    if (outline) {
      scene.remove(outline);
      outline.geometry.dispose();
      outline = null;
    }
    const hit = id && content ? content.hits.find((x) => x.id === id) : null;
    applyOutlines();
    markLabels();
    if (hit && !hit.brackets && !hit.marks) {
      outline = new THREE.LineSegments(outlineGeometry(THREE, hit.outline || hit.object, hit.pad !== undefined ? hit.pad : OUTLINE_PAD), outlineMaterial);
      scene.add(outline);
    }
    loop.requestRender();
  }

  // The building the person has chosen keeps a thin outline in the City, as the route-selected object; a hover outlines the hovered one in addition.
  function drawMarked() {
    const hit = content && content.marked ? content.hits.find((x) => x.id === content.marked) : null;
    applyBrackets();
    if (!hit || hit.brackets || hit.marks) {
      if (markedOutline) {
        scene.remove(markedOutline);
        markedOutline.geometry.dispose();
        markedOutline = null;
      }
      return;
    }
    const geometry = outlineGeometry(THREE, hit.outline || hit.object, hit.pad !== undefined ? hit.pad : OUTLINE_PAD);
    if (markedOutline) {
      markedOutline.geometry.dispose();
      markedOutline.geometry = geometry;
    } else {
      markedOutline = new THREE.LineSegments(geometry, outlineMaterial);
      scene.add(markedOutline);
    }
  }

  const hoveredHit = () => (hoverId && content ? content.hits.find((x) => x.id === hoverId) || null : null);

  // The same outline made again from where the object is now (the opening moves a floor, typing moves a figure's arms): one geometry
  // swapped in place, nothing else touched.
  function refreshOutline() {
    drawMarked();
    const hit = hoveredHit();
    if (!hit || !outline) return;
    outline.geometry.dispose();
    outline.geometry = outlineGeometry(THREE, hit.outline || hit.object, hit.pad !== undefined ? hit.pad : OUTLINE_PAD);
  }

  // What the page's checks read: the object the outline is drawn for and where its box is on the screen (CSS pixels of the canvas),
  // so a test can put the pointer at an object's drawn centre and compare the tooltip, the pick and the outline.
  function outlineProbe() {
    if (!outline || !outline.geometry) return null;
    outline.geometry.computeBoundingBox();
    const box = outline.geometry.boundingBox.clone().applyMatrix4(outline.matrixWorld);
    const at = project(box.getCenter(new THREE.Vector3()));
    return { id: hoverId, x: Math.round(at.x * 10) / 10, y: Math.round(at.y * 10) / 10 };
  }

  function showHover(result) {
    const id = result.hit ? result.hit.id : null;
    if (id !== hoverId) {
      hoverId = id;
      hoverSource = id ? "pointer" : null;
      setOutline(id);
      if (options.onHover) options.onHover(id);
    }
    canvas.classList.toggle("is-pointer", Boolean(id));
    if (result.hit) {
      tooltip.textContent = result.hit.tip;
      tooltip.hidden = false;
      // an object of a room has its tooltip over it (R-31); a building follows the pointer
      const above = result.hit.anchor ? project(result.hit.anchor) : null;
      tooltip.classList.toggle("is-above", Boolean(above));
      // the tooltip stays inside the canvas: a word over an object at the edge is moved in by half its width, and one over an object at the top is let down under the top edge
      const { x, y } = tooltipPlace({ above, at: result, size, wide: tooltip.offsetWidth || 0, tall: tooltip.offsetHeight || 0 });
      tooltip.style.setProperty("--wb-x", `${x.toFixed(1)}px`);
      tooltip.style.setProperty("--wb-y", `${y.toFixed(1)}px`);
    } else {
      tooltip.hidden = true;
    }
  }

  // The pointer and the keys (pointer.js): a pan, a click, a pinch, the wheel, the keys; the hover pick is never stale.
  const pointerControl = createPointer({
    clock, setTimer: (fn, ms) => setTimeout(fn, ms), clearTimer: (id) => clearTimeout(id),
    pick, showHover, open: (id) => { if (options.onOpen) options.onOpen(id); }, canMove,
    pan: (dx, dy) => setView(panPixels(view, frustum, bounds, dx, dy, size)),
    zoomBy: (factor, x, y) => zoomBy(factor, x === null || x === undefined ? { x: 0, y: 0 } : ndcOf(x, y)),
    moveBy, resetView,
    dragging: (on) => {
      if (on) tooltip.hidden = true;
      canvas.classList.toggle("is-dragging", on);
    },
    capture: (id, on) => {
      const call = on ? canvas.setPointerCapture : canvas.releasePointerCapture;
      if (!call) return;
      try { call.call(canvas, id); } catch (e) { /* a pointer that is already gone */ }
    },
    hovering: () => hoverId !== null, disposed: () => disposed,
  });
  const onDown = (event) => pointerControl.down(event);
  const onMove = (event) => pointerControl.move(event);
  const onUp = (event) => pointerControl.up(event);
  const onLeave = () => pointerControl.leave();
  const onClick = (event) => pointerControl.click(event);
  const onDoubleClick = (event) => pointerControl.doubleClick(event);
  const onWheel = (event) => pointerControl.wheel(event);
  const onKeyDown = (event) => pointerControl.key(event);
  canvas.addEventListener("pointerdown", onDown);
  canvas.addEventListener("pointermove", onMove);
  canvas.addEventListener("pointerup", onUp);
  canvas.addEventListener("pointercancel", onUp);
  canvas.addEventListener("pointerleave", onLeave);
  canvas.addEventListener("click", onClick);
  canvas.addEventListener("dblclick", onDoubleClick);
  canvas.addEventListener("wheel", onWheel, { passive: false });
  canvas.addEventListener("keydown", onKeyDown);
  const onZoomIn = () => zoomBy(1.25);
  const onZoomOut = () => zoomBy(1 / 1.25);
  zoomInButton.addEventListener("click", onZoomIn);
  zoomOutButton.addEventListener("click", onZoomOut);
  fitButton.addEventListener("click", resetView);

  // --- the page's own signals: visibility, reduced motion, colour scheme, context loss ---------------------------------------
  // A page's bottom sheet that covers the whole scene (a phone) pauses it exactly as a hidden tab does: nothing is scheduled, nothing is drawn.
  const onVisibility = () => {
    loop.setHidden(document.hidden || paused);
    if (!document.hidden && options.onVisible) options.onVisible();
  };
  const onReduced = () => {
    if (reducedQuery.matches) {
      if (tween.cancel()) {
        applyView();
        loop.stop("camera");
      }
      if (content && content.live) {
        content.finish();
        loop.stop("world");
        syncSurroundings();
        pickCache = null;
        renderer.shadowMap.needsUpdate = true;
        positionLabels();
      }
      drops.forEach((d) => { d.marker.group.position.y = d.marker.restY; });
      drops = [];
      loop.stop("drops");
      if (tagRun) {
        tagRun.group.position.y = tagRun.to;
        tagRun = null;
        loop.stop("tag");
      }
    }
    syncBeacons();
  };
  const onScheme = () => {
    buildSky();
    build(true);
  };
  const onLost = (event) => {
    event.preventDefault();
    lostText = true;
    loop.stop("beacon");
    if (options.onUnavailable) options.onUnavailable();
  };
  const onRestored = () => {
    lostText = false;
    buildSky();
    build(true);
    if (options.onRestored) options.onRestored();
  };
  document.addEventListener("visibilitychange", onVisibility);
  reducedQuery.addEventListener("change", onReduced);
  const stopScheme = watchScheme(onScheme);     // the system's scheme and the person's light/dark choice (mode.js)
  canvas.addEventListener("webglcontextlost", onLost);
  canvas.addEventListener("webglcontextrestored", onRestored);

  buildSky();
  measure();
  // The test hook of the acceptance (scene.md section 10): the frames drawn so far, read from the canvas element.
  const stats = () => ({ ...loop.stats(), hover: hoverId, outline: outlineProbe(), towers: content && content.towers ? Object.fromEntries([...content.towers].map(([id, t]) => [id, +t.open.toFixed(3)])) : null, view: { left: camera.left, right: camera.right, top: camera.top, bottom: camera.bottom }, builds, relabels, zoom: view.zoom, panX: view.x, panY: view.y, frameMs, pixelRatio: renderer.getPixelRatio(), drawCalls: renderer.info.render.calls, geometries: renderer.info.memory.geometries });
  canvas.wbStats = stats;
  canvas.wbSamples = () => (content ? visibleSamples(THREE, camera, scene, content.hits, size) : []);
  canvas.wbMarks = () => (content ? content.hits.filter((hit) => hit.marks).map((hit) => [hit.id, hit.marks.visible]) : []);   // which object wears its brackets (R-28, R-31)

  return {
    canvas,
    /**
     * Show a scene: `kind` names a builder, `model` is its plain data. The same model is not built twice, and a model that
     * differs only in its words (the builder's `structure` is the same) changes the labels and tooltips alone: nothing that moves
     * is built again, so no motion restarts on a poll that found the same state.
     */
    show(nextKind, nextModel, label) {
      if (label) canvas.setAttribute("aria-label", label);
      if (nextKind === "world" && content && content.live && kind === "world") return updateWorld(nextModel);
      const builder = BUILDERS[nextKind];
      const plan = showPlan({ signature, structure: structureSignature, built: Boolean(content && content.text) }, nextKind, nextModel, builder && builder.structure);
      if (plan.action === "none") return false;
      kind = nextKind;
      model = nextModel;
      signature = plan.signature;
      if (plan.action === "relabel") {
        relabel();
        return true;
      }
      structureSignature = plan.structure;
      build();
      return true;
    },
    /** Pause the scene while a sheet covers it, or draw again (one frame) when it no longer does. The tab-hidden rule, driven by the page. */
    setPaused(on) {
      const next = Boolean(on);
      if (next === paused) return;
      paused = next;
      loop.setHidden(document.hidden || paused);
      if (!paused && fitWaits) {      // the fit that was left while the sheet covered the scene: once, in the room it has now
        fitWaits = false;
        if (measure()) fit();
      }
    },
    /** Measure the insets again and refit (a panel changed size). */
    refit() {
      if (disposed || !measure()) return;
      if (paused) fitWaits = true;
      else fit();
    },
    /** Outline a building from the HTML list (hover or focus there), with no tooltip. `source` is "pointer" or "keyboard" (the list's focus). */
    highlight(id, source = "pointer") {
      hoverSource = id ? source : null;
      if (id !== hoverId) {
        hoverId = id;
        setOutline(id);
      }
    },
    /** Move the camera in on a building (A5, the prototype's curve); resolves true when it is nine tenths done, false when it was a cut (the route does not wait for it). */
    flyTo(id) {
      // A building of the world: it opens where it stands while the camera flies in (the prototype's one scene); the screen changes the route in
      // the same moment and the scene goes on from where it is. A floor of the open building: the other floors shrink to nothing while the
      // camera closes on it.
      const floorName = content && content.live && String(id).startsWith("floor:") ? String(id).slice(6) : null;
      if (content && content.live && (content.towers.has(id) || floorName !== null)) {
        tooltip.hidden = true;
        if (floorName !== null) content.setFloors(floorName, null, reducedQuery.matches);
        else content.setFocus(id, reducedQuery.matches);
        pickCache = null;
        if (reducedQuery.matches) {
          refocus(false);
          return Promise.resolve(false);
        }
        const move = refocus(true, FLY_SETTLE_AT);
        startWorld();
        loop.requestRender();
        return move;
      }
      const hit = content && content.hits.find((x) => x.id === id);
      if (!hit || reducedQuery.matches || !frustum) return Promise.resolve(false);
      const insets = options.getInsets ? options.getInsets(about()) : {};
      const target = fitFrustum(contentBounds(THREE, camera, hit.object), size, insets, 1.6);
      const move = tween.start(frustumOf(frustum, view), target, clock(), FLY_SETTLE_AT);
      tooltip.hidden = true;
      positionLabels();
      loop.start("camera", { ambient: false });
      return move;
    },
    /** True while an object of the scene is outlined (hovered, or lit from the keyboard through the list). */
    hasHover: () => hoverId !== null,
    /** True while an object is outlined because the keyboard's focus is on it (a list row): the Escape key's "selection". The pointer's hover is never one. */
    hasSelection: () => hoverId !== null && hoverSource === "keyboard",
    /** Clear the outline the keyboard's focus put on an object; the pointer's hover stays. */
    clearSelection() {
      if (hoverId === null || hoverSource !== "keyboard") return false;
      hoverId = null;
      hoverSource = null;
      setOutline(null);
      tooltip.hidden = true;
      if (options.onHover) options.onHover(null, "clear");   // the page's other two places of the mark (a plate, a row) clear with it (R-28)
      return true;
    },
    clearHover() {
      if (hoverId === null) return false;
      hoverId = null;
      hoverSource = null;
      setOutline(null);
      tooltip.hidden = true;
      if (options.onHover) options.onHover(null, "clear");
      return true;
    },
    /** The page's next screen takes the scene over: its insets, its handlers; the hover of the screen before is gone. */
    setOptions(next) {
      options = next;
      if (next.label) canvas.setAttribute("aria-label", next.label);
      if (hoverId !== null) {
        hoverId = null;
        setOutline(null);
      }
      tooltip.hidden = true;
    },
    /** Put `node` (or nothing) in the corner slot: the top right of the free rectangle, over the scene, never over a panel. */
    setCorner(node) {
      if (corner) corner.remove();
      corner = node || null;
      if (corner) {
        corner.classList.add("wb-corner-card");
        overlay.append(corner);
        placeCorner();
      }
      fit();   // the scene is fitted below the card: its height is measured now
    },
    /** The person's camera, for the page's checks and the keyboard-free callers: zoom in, zoom out, fit, move. */
    zoomBy: (factor) => zoomBy(factor),
    resetView,
    moveBy,
    /** What the page can read to check the rules: frames drawn so far, animations running, hidden or not, the zoom and pan. */
    stats,
    dispose() {
      if (disposed) return;
      disposed = true;
      pointerControl.dispose();
      observer.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      reducedQuery.removeEventListener("change", onReduced);
      stopScheme();
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerup", onUp);
      canvas.removeEventListener("pointercancel", onUp);
      canvas.removeEventListener("pointerleave", onLeave);
      canvas.removeEventListener("click", onClick);
      canvas.removeEventListener("dblclick", onDoubleClick);
      canvas.removeEventListener("wheel", onWheel);
      canvas.removeEventListener("keydown", onKeyDown);
      zoomInButton.removeEventListener("click", onZoomIn);
      zoomOutButton.removeEventListener("click", onZoomOut);
      fitButton.removeEventListener("click", resetView);
      canvas.removeEventListener("webglcontextlost", onLost);
      canvas.removeEventListener("webglcontextrestored", onRestored);
      loop.dispose();
      clearContent();
      if (worldKit) worldKit.dispose();
      outlineMaterial.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      canvas.remove();
      overlay.remove();
      tools.remove();
      corner = null;
    },
  };
}
