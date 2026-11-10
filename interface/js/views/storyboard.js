// The storyboard of a short-video post (package V5-1, VD14), a part of the Videos section: the button that draws a still per beat of the chosen post's script
// over a neutral placeholder, the contact sheet, and one line for each beat whose video block differs from the block that drew it. The page decides nothing:
// the service draws (or replays) it, and the sentence for a refusal is shown as it came. It is advisory, and the view says so in the one sentence the service
// returns. The pictures are Blobs read with the token, so each lives at a blob URL that is given back when the drawing is replaced. Text from the service
// goes in as text.

import { h } from "../dom.js";
import { failureText } from "../cards/plan-rows.js";
import { can as pageMay } from "../permissions.js";

export const HEAD = "Storyboard";
export const BUTTON = "Draw the storyboard";
export const ADVISORY = "A still per beat over a placeholder. The video may look different.";      // = runtime/phrases_parts/v5-1.en.json VID_STORYBOARD_ADVISORY; the service's own sentence is shown when it comes
export const NO_POST = "Choose a post to draw its storyboard.";
const POLL_MS = 1000;
const SHEET_WIDTH = 300;      // CSS pixels, written as an attribute of the picture (the height follows the picture)
const BEAT_WIDTH = 96;

/** The line for one beat whose video block is not the block that drew it, or "" when they are the same. `beat` is a row of the service's answer. */
export function blockLine(beat) {
  const row = beat || {};
  if (row.video_block === null || row.video_block === undefined) return `This engine draws no ${row.preset}.`;
  if (row.video_block !== row.drawn_block) return `Drawn with ${row.drawn_block}; the video uses ${row.video_block}.`;
  return "";
}

/**
 * env: {api (the client), project (getter), entry() (the GET /projects entry, for the policy)}. Returns {el, update(post, shown), stop()}: `post` is the path of the
 * chosen post or "", `shown` whether the section is wanted at all.
 */
export function createStoryboard(env) {
  const head = h("h4", { class: "wb-steps-head", text: HEAD });
  const button = h("button", { class: "pui-btn pui-surface pui-outline wb-vd-button", type: "button", text: BUTTON });
  const note = h("p", { class: "wb-steps-note wb-sb-note", role: "status", text: NO_POST });
  const error = h("p", { class: "wb-steps-note wb-sb-error", role: "alert", hidden: true });
  const result = h("div", { class: "wb-sb-result", hidden: true });
  const el = h("div", { class: "wb-sb", hidden: true }, head, button, note, error, result);
  let post = "";
  let shown = false;
  let busy = false;
  let drawn = null;         // {post, urls: [blob urls], ...} the drawing on show
  let controller = null;
  const may = () => pageMay(env.entry ? env.entry() : null, "video-storyboard");

  function give() {
    if (drawn) for (const url of drawn.urls) URL.revokeObjectURL(url);
    drawn = null;
    result.replaceChildren();
    result.hidden = true;
  }

  function say(text) {
    note.textContent = text || "";
    note.hidden = !text;
  }

  function fail(e) {
    error.textContent = failureText(e);
    error.hidden = false;
  }

  function clear() {
    error.textContent = "";
    error.hidden = true;
  }

  function draw() {
    el.hidden = !shown || !may();
    if (el.hidden) return;
    button.disabled = busy || !post;
    button.textContent = busy ? "Drawing..." : BUTTON;
    if (busy) button.setAttribute("aria-busy", "true"); else button.removeAttribute("aria-busy");
    if (!busy && !drawn) say(post ? "" : NO_POST);
  }

  function show(found, blobs) {
    const urls = blobs.map((blob) => URL.createObjectURL(blob));
    drawn = { post, urls };
    const [sheetUrl, ...beatUrls] = urls;
    const items = found.beats.map((beat, i) => {
      const line = blockLine(beat);
      return h("li", { class: "wb-vd-item wb-sb-beat", "data-beat": String(beat.beat) },
        h("img", { class: "wb-sb-still", src: beatUrls[i], width: String(BEAT_WIDTH), alt: `Beat ${beat.beat}, ${beat.preset}` }),
        h("p", { class: "wb-steps-note wb-sb-line", text: `Beat ${beat.beat}: ${beat.preset}${line ? `. ${line}` : ""}` }));
    });
    result.replaceChildren(
      h("p", { class: "wb-steps-line wb-sb-advisory", text: typeof found.advisory === "string" && found.advisory ? found.advisory : ADVISORY }),
      h("img", { class: "wb-sb-sheet", src: sheetUrl, width: String(SHEET_WIDTH), alt: "The contact sheet of the storyboard" }),
      h("ul", { class: "wb-vd-list wb-sb-list", "aria-label": "The beats of the storyboard" }, ...items));
    result.hidden = false;
  }

  async function run() {
    if (busy || !post || !may()) return;      // a click asks the policy again
    const asked = post;
    busy = true;
    clear();
    say("");
    give();
    draw();
    try {
      const signal = controller ? controller.signal : undefined;
      const started = await env.api.videoStoryboard(env.project, asked, { signal });
      const final = await env.api.pollJob(started.job, POLL_MS, { signal });
      if (final && final.state === "failed") {
        fail({ message: (final.error && final.error.message) || "The storyboard could not be drawn." });
      } else if (asked === post) {
        const found = final && final.result;
        if (!found || !Array.isArray(found.beats) || typeof found.key !== "string") throw new Error("The storyboard came back in a shape the page does not know.");
        const files = ["sheet.png", ...found.beats.map((beat) => beat.file)];
        const blobs = await Promise.all(files.map((file) => env.api.videoStoryboardFile(env.project, found.key, file, { signal })));
        if (asked === post) show(found, blobs);
      }
    } catch (e) {
      if (!(e && e.name === "AbortError")) fail(e);
    }
    busy = false;
    draw();
  }

  button.addEventListener("click", run);

  return {
    el,
    /** post: the chosen post's path or ""; shown: whether the Videos section is drawn at all. A different post drops the drawing on show. */
    update(next, isShown) {
      const wanted = typeof next === "string" ? next : "";
      if (wanted !== post) {
        post = wanted;
        give();
        clear();
        say("");
      }
      shown = Boolean(isShown);
      if (shown) {
        if (!controller) controller = new AbortController();
      } else {
        this.stop();
      }
      draw();
    },
    /** Gives the pictures back and cancels what is in flight. */
    stop() {
      if (controller) controller.abort();
      controller = null;
      busy = false;
      give();
      clear();
    },
  };
}
