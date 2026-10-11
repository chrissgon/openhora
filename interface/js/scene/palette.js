// The scene's colours: none of its own. Every colour is read from the page's CSS custom properties when the scene is
// built and again when the colour scheme changes, so dark mode (and a new primary colour) flows into the scene. The
// recipes (a mix of two tokens) are the handoff's scene.md section 3.

import * as THREE from "../three.js";

// The names read through a probe element. `--wb-raised` and `--wb-ground` are the page's two derived properties
// (DEVIATION-1): the scene reads them where the design tool read the library's background tokens.
export const TOKEN_NAMES = Object.freeze({
  bg: "--wb-raised", muted: "--wb-ground", emphasis: "--pui-bg-emphasis", text: "--pui-text", textMuted: "--pui-text-muted",
  border: "--pui-border", theme: "--pui-theme", warn: "--pui-warn", success: "--pui-success", error: "--pui-error",
  mutedRole: "--pui-muted", bgToken: "--pui-bg",
});

// A light's colour is not a painted colour (DEVIATION-8): named once here.
export const LIGHT_WHITE = 0xffffff;
export const SHADOW_BLACK = 0x000000;

/**
 * Ask for a new palette when the colours change: the system's scheme (the media query) or the person's choice of light or dark (the
 * library's `data-pui-mode` attribute on the root element, set by `mode.js`). Returns a function that stops listening. The query, the root
 * and the observer class are arguments so a test runs it with stand-ins; where `MutationObserver` is missing the query alone is watched.
 */
export function watchScheme(onChange, { query = window.matchMedia("(prefers-color-scheme: dark)"), root = document.documentElement,
  Observer = typeof MutationObserver === "function" ? MutationObserver : null } = {}) {
  query.addEventListener("change", onChange);
  const observer = Observer ? new Observer(() => onChange()) : null;
  if (observer) observer.observe(root, { attributes: true, attributeFilter: ["data-pui-mode"] });
  return () => {
    query.removeEventListener("change", onChange);
    if (observer) observer.disconnect();
  };
}

/** Read one token's resolved colour through a probe element placed in `host`. */
function read(probe, name) {
  probe.style.setProperty("color", `var(${name})`);
  return new THREE.Color().setStyle(getComputedStyle(probe).color, THREE.SRGBColorSpace);
}

/**
 * A mix of two colours as the page's stylesheet mixes them: `color-mix(in srgb, a, b t)`, a straight blend of the encoded channels (round 4,
 * `scene.css`). Three.js keeps colours in a linear working space, where a blend of the same two colours comes out lighter, so the blend is made
 * in the encoded space and brought back.
 */
export function mixSrgb(a, b, t) {
  const x = a.clone().convertLinearToSRGB();
  const y = b.clone().convertLinearToSRGB();
  x.r += (y.r - x.r) * t;
  x.g += (y.g - x.g) * t;
  x.b += (y.b - x.b) * t;
  return x.convertSRGBToLinear();
}

/** The palette: the token colours, the recipes derived from them and whether the scheme is dark. */
export function readPalette(host) {
  const probe = document.createElement("span");
  probe.className = "wb-probe";
  host.appendChild(probe);
  const T = {};
  for (const [key, name] of Object.entries(TOKEN_NAMES)) T[key] = read(probe, name);
  // The decision mark is the same amber in light and in dark (R-20): its three tones are mixed from the tokens as the dark scheme gives them.
  probe.style.setProperty("color-scheme", "dark");
  const inDark = { warn: read(probe, TOKEN_NAMES.warn), text: read(probe, TOKEN_NAMES.text), bgToken: read(probe, TOKEN_NAMES.bgToken) };
  probe.remove();
  const mix = mixSrgb;
  const dark = T.bgToken.r + T.bgToken.g + T.bgToken.b < 1.5;
  const bg = T.bg;
  const palette = {
    dark, T, mix, bg, inDark,
    ground: T.muted,
    pale: mix(bg, T.theme, 0.25),
    // R-18: a lit window is a warm white, not amber (`scene.css` `.m-g-lit`): the raised surface with a little of the warn colour in light, the
    // text colour with a little of the brand's light brown in dark. The full amber is left to the decision marks.
    warm: dark ? mix(T.text, T.theme, 0.36) : mix(bg, T.warn, 0.34),
    glass: mix(bg, T.theme, dark ? 0.18 : 0.12),
    shell: dark ? T.emphasis.clone() : bg.clone(),
    leafA: mix(bg, T.success, dark ? 0.55 : 0.66),
    leafB: mix(bg, T.success, dark ? 0.42 : 0.52),
    trunk: mix(T.textMuted, T.warn, 0.25),
    wood: mix(bg, T.warn, dark ? 0.28 : 0.2),
    metal: T.textMuted.clone(),
    ink: dark ? mix(T.emphasis, T.text, 0.15) : mix(T.text, T.textMuted, 0.25),
    screenOff: dark ? mix(bg, T.theme, 0.12) : mix(T.text, T.theme, 0.28),
    drawer: mix(bg, T.theme, 0.55),
    lot: dark ? mix(T.muted, bg, 0.6) : bg.clone(),
    deskTop: dark ? mix(T.emphasis, T.text, 0.12) : mix(bg, T.emphasis, 0.6),
    skin: dark ? mix(T.emphasis, T.text, 0.35) : mix(bg, T.emphasis, 0.35),
    shadowColor: dark ? new THREE.Color(SHADOW_BLACK) : T.text.clone(),
    shadowOpacity: dark ? 0.35 : 0.1,
    hemiIntensity: dark ? 1.15 : 1.85,
    sunIntensity: dark ? 0.9 : 1.45,
  };
  // A window is warm when its floor's agent works and the border tone otherwise, in light and in dark (WP-9.8); `pale` stays
  // the front door's colour only.
  palette.windows = { lit: palette.warm, grey: T.border };
  return palette;
}

/**
 * The City's drawing in the colours of `scene.css` (round 4): every one a token or a mix of two tokens, in light and in dark, as that file writes
 * them. A face of a solid is top, left (the front, +z) or right (+x), each its own tone, so the drawing is flat faces and needs no light.
 * Pure: it reads `palette.T`, `palette.mix`, `palette.bg` and `palette.dark` only (a stand-in without the two tokens `bgToken` and `muted`
 * takes the surface for them). Returns Colours (and {top, left, right} for a solid).
 */
export function cityTones(palette) {
  const { T, mix, bg, dark } = palette;
  const bgt = T.bgToken || bg;                       // --pui-bg
  const emph = T.emphasis;                           // --pui-bg-emphasis
  const tm = T.textMuted;
  const tx = T.text;
  const th = T.theme;
  const ink = dark ? bgt : tx;                       // --wb-shadow-ink: light-dark(--pui-text, --pui-bg)
  const pick = (light, deep) => (dark ? deep : light);
  const warnD = (palette.inDark && palette.inDark.warn) || T.warn;
  const textD = (palette.inDark && palette.inDark.text) || tx;
  const bgD = (palette.inDark && palette.inDark.bgToken) || bgt;
  const solid = (top, left, right) => ({ top, left, right });
  return {
    road: pick(mix(emph, tm, 0.24), mix(bg, emph, 0.6)),
    lane: pick(bg.clone(), tm.clone()),
    kerb: pick(mix(emph, tm, 0.45), mix(bgt, emph, 0.55)),
    walk: pick(mix(bg, emph, 0.55), mix(emph, T.border, 0.35)),
    plaza: pick(bg.clone(), mix(bgt, bg, 0.78)),
    grass: pick(mix(bg, T.success, 0.26), mix(bgt, T.success, 0.3)),
    trunk: mix(tm, T.warn, 0.25),
    // the four tones of a crown, lightest first: facets are given the tone of the light they face
    crown: [
      pick(mix(bg, T.success, 0.48), mix(bgt, T.success, 0.62)),
      pick(mix(bg, T.success, 0.62), mix(bgt, T.success, 0.5)),
      pick(mix(bg, T.success, 0.76), mix(bgt, T.success, 0.4)),
      pick(mix(T.success, ink, 0.14), mix(bgt, T.success, 0.31)),
    ],
    shell: solid(pick(mix(bg, emph, 0.75), mix(bgt, emph, 0.72)), pick(mix(bg, emph, 0.75), mix(bgt, emph, 0.72)), pick(mix(bg, emph, 0.25), mix(bgt, emph, 0.92))),
    ledge: solid(pick(bg.clone(), mix(emph, tm, 0.42)), pick(mix(emph, tm, 0.38), mix(emph, tm, 0.2)), pick(mix(emph, tm, 0.2), mix(emph, tm, 0.3))),
    glass: pick(mix(emph, tm, 0.78), mix(bgt, bg, 0.55)),
    glassOff: pick(mix(bg, emph, 0.9), mix(bgt, emph, 0.6)),
    glassLit: pick(mix(bg, T.warn, 0.34), mix(tx, th, 0.36)),
    store: pick(mix(bg, th, 0.34), mix(bgt, th, 0.46)),
    door: pick(mix(bg, th, 0.62), mix(bgt, th, 0.66)),
    sill: pick(bg.clone(), mix(emph, tm, 0.34)),
    jamb: pick(mix(emph, tm, 0.7), bgt.clone()),
    roof: solid(mix(th, ink, 0.1), mix(th, ink, 0.36), mix(th, ink, 0.22)),
    roofFloor: th.clone(),
    roofIn: solid(mix(th, ink, 0.18), mix(th, ink, 0.3), mix(th, ink, 0.18)),
    unit: solid(pick(mix(emph, tm, 0.3), mix(emph, tm, 0.55)), pick(mix(emph, tm, 0.7), mix(emph, tm, 0.28)), pick(mix(emph, tm, 0.5), mix(emph, tm, 0.4))),
    post: tm.clone(),
    // R-20: the same amber in light and in dark (`.m-ex` sets `color-scheme: dark`)
    mark: solid(mix(warnD, textD, 0.3), mix(warnD, bgD, 0.26), warnD.clone()),
    beacon: bgt.clone(),
    bracket: th.clone(),
    agent: ink.clone(),
    shadow: ink.clone(),
  };
}

/**
 * The rooms' drawing in the colours of `scene.css` (round 4: R-21, R-23, R-23b, R-49), each a token or a mix of two, in light and in dark, as that file
 * writes them (the later rule of a class wins, as in the cascade). A face of a solid is {top, left (+z), right (+x)}. Pure, as `cityTones`: it reads
 * `palette.T`, `palette.mix`, `palette.bg` and `palette.dark`, and a stand-in without `bgToken` takes the surface for it.
 */
export function roomTones(palette) {
  const { T, mix, bg, dark } = palette;
  const city = cityTones(palette);
  const bgt = T.bgToken || bg;
  const emph = T.emphasis;
  const tm = T.textMuted;
  const tx = T.text;
  const th = T.theme;
  const ink = city.shadow;
  const pick = (light, deep) => (dark ? deep : light);
  const solid = (top, left, right) => ({ top, left, right });
  const all = (colour) => solid(colour, colour, colour);
  const eh = (t) => mix(emph, tm, t);                         // a step between the emphasis ground and the muted text
  const cover = (n) => [th, pick(mix(bg, th, 0.45), mix(tx, th, 0.45)), pick(mix(bg, T.warn, 0.55), mix(emph, T.warn, 0.6)), pick(mix(tm, emph, 0.3), eh(0.7))][n - 1];
  const tb = pick(mix(bg, emph, 0.7), mix(bgt, emph, 0.7));
  const note = { done: pick(mix(bg, T.success, 0.45), mix(emph, T.success, 0.62)), run: th, left: pick(bg, mix(emph, tx, 0.55)), fail: pick(mix(bg, T.error, 0.45), mix(emph, T.error, 0.62)) };
  const noteEdge = pick(eh(0.6), bgt);
  const shelfIn = pick(eh(0.42), eh(0.05));
  return {
    ink,
    // the floor, by what the agent does: a lit room is a soft warm tone (R-21, R-23)
    floor: pick(eh(0.3), mix(bgt, bg, 0.7)),
    floorOff: pick(eh(0.55), bgt),
    floorLit: pick(mix(bg, th, 0.3), mix(emph, th, 0.28)),
    ledge: city.ledge,
    wall: solid(pick(bg, eh(0.42)), pick(mix(bg, emph, 0.7), mix(bgt, emph, 0.78)), pick(mix(bg, emph, 0.28), mix(bgt, emph, 0.94))),
    // a window seen from inside (an opening as deep as the wall, the glass set back with one upright and one rail, a trim, a board under it)
    glass: city.glass, glassOff: city.glassOff, glassLit: city.glassLit,
    mull: pick(bg, mix(bgt, emph, 0.6)),
    jamb: city.jamb,
    under: pick(bg, eh(0.3)),
    trim: pick(eh(0.45), eh(0.4)),
    board: solid(pick(bg, eh(0.48)), pick(eh(0.4), eh(0.22)), pick(eh(0.24), eh(0.32))),
    // the task board: a frame, the panel, a shade, a note by state with its shadow, fold, three lines and pin, two markers and an eraser on the ledge
    tbFrame: pick(eh(0.46), eh(0.44)),
    tb,
    tbShade: mix(tb, ink, 0.12),
    note,
    noteEdge,
    noteShadow: mix(tb, ink, 0.18),
    noteFold: { done: mix(note.done, ink, 0.22), run: mix(note.run, ink, 0.22), left: mix(note.left, ink, 0.22), fail: mix(note.fail, ink, 0.22) },
    noteLine: { done: mix(note.done, ink, 0.38), run: mix(note.run, ink, 0.38), left: mix(note.left, ink, 0.38), fail: mix(note.fail, ink, 0.38) },
    notePin: pick(mix(tm, tx, 0.4), tx),
    marker: all(th),
    markerB: all(pick(mix(tm, tx, 0.4), mix(emph, tx, 0.5))),
    eraser: all(pick(eh(0.3), eh(0.7))),
    // the bookcase: a plinth, a body, a top, a dark inside, boards with a lip, and a binder in one of four cover tones
    cabBase: all(pick(mix(tm, tx, 0.25), eh(0.14))),
    cab: solid(pick(bg, eh(0.6)), pick(eh(0.6), eh(0.3)), pick(eh(0.4), eh(0.42))),
    cabTop: solid(pick(bg, eh(0.72)), pick(eh(0.7), eh(0.36)), pick(eh(0.5), eh(0.48))),
    shelfIn,
    shelfSide: pick(mix(tm, tx, 0.2), mix(bgt, emph, 0.3)),
    shelfBoard: pick(bg, eh(0.6)),
    shelfLip: pick(eh(0.3), eh(0.82)),
    cover,
    binder: (n) => {
      const c = cover(n);
      const light = pick(bg, tx);
      return {
        face: solid(c, c, mix(c, ink, 0.3)), outline: mix(c, ink, 0.22), round: mix(c, light, 0.28), edge: mix(c, ink, 0.25), band: mix(c, ink, 0.28), hole: mix(c, ink, 0.55),
        pages: pick(bg, mix(tx, emph, 0.3)), label: pick(bg, mix(tx, emph, 0.25)), writing: pick(tm, emph),
      };
    },
    // the desk in greys five steps apart: a light top, a darker drawer unit with lighter fronts, dark legs, the darkest keyboard
    work: solid(pick(bg, eh(0.82)), pick(eh(0.48), eh(0.42)), pick(eh(0.26), eh(0.58))),
    workLeg: all(pick(mix(tm, tx, 0.35), eh(0.34))),
    ped: solid(pick(mix(tm, emph, 0.22), eh(0.14)), pick(mix(tm, emph, 0.22), eh(0.14)), pick(mix(tm, emph, 0.45), eh(0.26))),
    pedDrawer: pick(eh(0.22), eh(0.5)),
    handle: pick(bg, mix(emph, tx, 0.45)),
    keyb: solid(pick(mix(tx, tm, 0.45), mix(bgt, emph, 0.4)), pick(mix(tx, tm, 0.15), bgt), pick(mix(tx, tm, 0.15), bgt)),
    keyLine: pick(mix(tm, bg, 0.4), eh(0.6)),
    mouse: solid(pick(mix(tx, tm, 0.55), eh(0.3)), pick(mix(tx, tm, 0.15), bgt), pick(mix(tx, tm, 0.15), bgt)),
    paper: pick(bg, mix(tx, emph, 0.2)),
    paperEdge: pick(eh(0.4), emph),
    paperLine: pick(mix(tm, bg, 0.3), tm),
    mug: solid(pick(mix(bg, th, 0.55), mix(emph, th, 0.7)), pick(mix(bg, th, 0.55), mix(emph, th, 0.7)), pick(mix(bg, th, 0.75), mix(emph, th, 0.5))),
    mugIn: mix(th, ink, 0.45),
    stand: solid(pick(mix(tm, emph, 0.2), eh(0.5)), pick(mix(tm, tx, 0.3), eh(0.24)), pick(mix(tm, tx, 0.3), eh(0.24))),
    screen: all(pick(mix(tx, bg, 0.25), eh(0.22))),
    screenBack: pick(mix(tx, tm, 0.45), eh(0.2)),
    screenLogo: pick(mix(tm, bg, 0.2), eh(0.6)),
    // the office chair: a star base, a column, a padded seat, a back with a pad, two armrests
    chair: solid(pick(mix(tm, emph, 0.3), eh(0.66)), pick(mix(tm, tx, 0.3), eh(0.3)), pick(mix(tm, tx, 0.1), eh(0.46))),
    chairBase: all(pick(mix(tm, tx, 0.45), eh(0.18))),
    chairPad: pick(mix(tm, emph, 0.48), eh(0.78)),
    // the Lobby's door: a casing a step lighter than the wall, the leaf in the brand's pale tone with two sunk panels, a light handle
    doorFrame: pick(eh(0.4), eh(0.4)),
    door: city.door,
    doorShade: mix(th, ink, 0.38),
    doorPanel: pick(mix(bg, th, 0.78), mix(bgt, th, 0.5)),
    knob: pick(bg, tx),
    // the two potted plants (A-45): a dark pot in three tones, and the trees' four crown tones
    pot: solid(pick(mix(tx, tm, 0.5), eh(0.3)), pick(mix(tx, tm, 0.25), eh(0.16)), pick(mix(tx, tm, 0.1), eh(0.1))),
    crown: city.crown,
    bracket: city.bracket,
  };
}

/**
 * The server room's drawing in the colours of `scene.css` (round 4: R-51), each a token or a mix of two, in light and in dark, as that file writes them (the later rule of a class
 * wins, as in the cascade). The room's desk, chair, keyboards and screens on their stands are `roomTones`'s; these are what the racks, the wall screen and the screens' faces add.
 * A face of a solid is {top, left (+z), right (+x)}. A stroke drawn at a share of opacity over a face (a vent, a grid line) is the blend, one flat tone. Pure, as `roomTones`: it reads
 * `palette.T`, `palette.mix`, `palette.bg` and `palette.dark`, and a stand-in without `bgToken` takes the surface for it.
 */
export function serverTones(palette) {
  const { T, mix, bg, dark } = palette;
  const bgt = T.bgToken || bg;
  const emph = T.emphasis;
  const tm = T.textMuted;
  const tx = T.text;
  const th = T.theme;
  const pick = (light, deep) => (dark ? deep : light);
  const solid = (top, left, right) => ({ top, left, right });
  const eh = (t) => mix(emph, tm, t);                         // a step between the emphasis ground and the muted text
  const rack = solid(pick(mix(tm, emph, 0.35), eh(0.5)), pick(mix(tm, tx, 0.35), eh(0.22)), pick(mix(tm, tx, 0.12), eh(0.36)));
  const ink = pick(mix(tx, tm, 0.3), bgt);                    // a vent's stroke
  const wsScreen = pick(mix(tx, tm, 0.25), bgt);
  const line = pick(bg, tx);                                  // the grid's, the head's and the base line's stroke
  const mount = pick(mix(tm, tx, 0.35), eh(0.22));
  return {
    // the rack: a plinth, a body in three tones, a framed front with a grille over it, vents on the top and the side, and a cable tray over the racks
    rack,
    rackBase: pick(mix(tx, tm, 0.4), bgt),
    rackDoor: pick(mix(tx, tm, 0.55), mix(bgt, emph, 0.55)),
    grille: pick(mix(tm, tx, 0.1), eh(0.4)),
    ventTop: mix(rack.top, ink, 0.55),
    ventSide: mix(rack.left, ink, 0.55),
    tray: solid(pick(mix(emph, tm, 0.5), eh(0.46)), pick(mix(tm, emph, 0.2), eh(0.26)), pick(mix(tm, emph, 0.2), eh(0.26))),
    // a unit: a dark slot with two ears, three drive bays, an activity dot (dim) and the fact's light: found, missing, or dim when the unit carries none
    unit: pick(mix(tx, tm, 0.18), bgt),
    ear: pick(mix(tm, emph, 0.3), eh(0.55)),
    bay: pick(mix(tx, tm, 0.6), eh(0.16)),
    ledDim: pick(mix(tm, emph, 0.4), eh(0.6)),
    ledOk: T.success.clone(),
    ledBad: T.error.clone(),
    ledOff: pick(mix(tm, tx, 0.3), eh(0.3)),
    // the wall screen: two mounts, a body with depth, a bezel, the screen, its grid (16 percent), head and base lines and ticks (45 percent), the bars and their caps, its light
    mount,
    body: solid(pick(mix(tm, emph, 0.25), eh(0.56)), mount, mount),
    bezel: pick(mix(tx, tm, 0.5), eh(0.34)),
    wsScreen,
    wsGrid: mix(wsScreen, line, 0.16),
    wsLine: mix(wsScreen, line, 0.45),
    bar: th.clone(),
    barCap: pick(mix(th, bg, 0.45), mix(th, tx, 0.4)),
    wsLed: T.success.clone(),
    // a console screen that is off: its dark face, and the glint on it (10 percent of the surface or the text); the desk's back panel
    screenFace: pick(mix(tx, tm, 0.12), bgt),
    glint: mix(pick(mix(tx, tm, 0.12), bgt), pick(bg, tx), 0.1),
    workBack: pick(mix(emph, tm, 0.62), eh(0.28)),
  };
}
