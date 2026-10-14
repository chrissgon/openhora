// The document viewer (handoff floor.md, "Document viewer"): a file under docs/ read with `artifact`. A Markdown document is
// drawn by the page's own renderer (markdown.js: nodes, never markup) with a "Plain text" toggle one click away, the choice kept
// for the page session; any other file, and the plain view, is the text in a wrapped `pre`. An image (A-33) is fetched with
// `artifactRaw` (the bearer header, so not a plain address), shown as an `<img>` from a `blob:` URL built from the bytes, fit to the panel's
// width, with the path as its alt text, the size and the dimensions under it, and "Open in a new tab"; the URL is revoked when the viewer
// closes or shows another file. A type the page cannot show gets one sentence and the path to copy. Never markup, never inline SVG, never
// a data URL. Its header names the path, the size and the modification time, and has "Close". It has the
// states loading, loaded and refused (the operation's own message, shown whole). It owns no layout: the Floor puts it where the
// panel was, a phone puts it in a dialog, and the Building's "Project state" link opens it in a dialog.

import * as api from "../api.js";
import { fill, h } from "../dom.js";
import { formatSize, formatWhen } from "../floor-model.js";
import { commandBlock } from "../frame/command.js";
import { markdownView } from "../markdown-view.js";
import { busyLine } from "./widgets.js";

const MARKDOWN_FILE = /\.(md|markdown)$/i;

/** The body of a loaded document: a Markdown file gets the rendered view, the plain `pre` and the toggle; any other file, the `pre`. */
function documentBody(doc, path) {
  const name = doc.path || path;
  if (MARKDOWN_FILE.test(name)) return markdownView(doc.text, { name, renderedLabel: `Document ${name}`, plainClass: "wb-viewer-text" });
  return [h("pre", { class: "wb-viewer-text", tabindex: "0", "aria-label": `Text of ${name}` }, String(doc.text))];
}

// What the page shows as an image: the types the service serves (png, jpeg, webp, and an svg it checked). Any other type of bytes is "cannot show", whatever the list said.
const SHOWN_TYPES = ["image/png", "image/jpeg", "image/webp", "image/svg+xml"];
// "Open in a new tab" is offered for these only. A svg opened as a document of the service's origin is a sandbox question nobody verified (the in-page `<img>` shows it
// inertly already), so the stricter rule stays: no new-tab link for a svg.
const NEW_TAB_TYPES = ["image/png", "image/jpeg", "image/webp"];

export const SHOWN_KINDS = "the Desk shows text, Markdown and images";

/** The sentence for a file the page cannot show: the runtime's own when it gave one, else built from the Desk's kind word and the size. */
export function unshownSentence(given, kindWord, size) {
  if (typeof given === "string" && given) return given;
  return `This file is ${kindWord || "of a type the page cannot show"}, ${size || "of unknown size"}; ${SHOWN_KINDS}`;
}

/**
 * Create a viewer. options: {onClose, listed(path) (optional: the Desk's row of a file, {kind: "text" | "markdown" | "image" | "other", size}, when the list is read),
 * object (optional, for a test: {create(blob) -> url, revoke(url)}, default URL.createObjectURL and URL.revokeObjectURL), open (optional: opens a url in a new tab)}.
 * Returns {el, load(project, path, {quiet}), close(), focus()}; onClose is called by "Close". `quiet`: read the file again without the loading line (the page reloaded: the text stays until the new one arrives).
 */
export function createViewer({ onClose, listed = () => undefined, object = null, open = null }) {
  const titleId = "wb-viewer-title";
  const el = h("div", { class: "pui-card wb-viewer", role: "region", "aria-labelledby": titleId });
  let controller = null;
  let blobUrl = null;
  const urls = object || { create: (blob) => URL.createObjectURL(blob), revoke: (url) => URL.revokeObjectURL(url) };
  const openTab = open || ((url) => window.open(url, "_blank", "noopener,noreferrer"));

  function release() {
    if (blobUrl !== null) urls.revoke(blobUrl);
    blobUrl = null;
  }

  /** The image: bytes fetched with the bearer header, shown from a blob URL, never markup. Returns the nodes of the body. */
  function imageBody(blob, path, listedSize) {
    release();
    blobUrl = urls.create(blob);
    const img = h("img", { class: "wb-viewer-image", src: blobUrl, alt: path });
    const dims = h("span", { class: "wb-viewer-dims", text: "" });
    img.addEventListener("load", () => {
      if (img.naturalWidth > 0 && img.naturalHeight > 0) dims.textContent = ` · ${img.naturalWidth} × ${img.naturalHeight} px`;
    });
    const url = blobUrl;
    let newTab = null;
    if (NEW_TAB_TYPES.includes(blob.type)) {
      newTab = h("button", { class: "pui-btn pui-surface pui-outline wb-touch", type: "button", "data-key": "open-tab", text: "Open in a new tab" });
      newTab.addEventListener("click", () => openTab(url));
    }
    const size = formatSize(typeof blob.size === "number" ? blob.size : listedSize);
    return [h("div", { class: "wb-viewer-figure" }, img), h("p", { class: "wb-viewer-caption wb-muted" }, h("span", { text: size }), dims), newTab];
  }

  /** A file the page cannot show: the sentence, and the path to copy. */
  function unshownBody(path, sentence) {
    return [h("div", { class: "wb-refusal is-info", role: "status" }, h("strong", { class: "wb-refusal-title", text: "The Desk cannot show this file" }), h("span", { text: sentence })),
      commandBlock({ command: path, sentence: "Path", label: "Copy the path" })];
  }

  /**
   * The head (floor.html): the path and, under it, the size and the time at the left; at the right the tools: `Plain text` for a Markdown document (the toggle of `markdownView`,
   * which the body no longer carries) and `Close`.
   */
  function head(path, line, tools = null) {
    const close = h("button", { class: "pui-btn pui-surface pui-outline wb-touch", type: "button", "data-key": "close", text: "Close" });
    close.addEventListener("click", () => onClose());
    return h("div", { class: "wb-viewer-head" },
      h("div", { class: "wb-viewer-titles wb-panel-titles" }, h("strong", { class: "wb-viewer-path mono", id: titleId, tabindex: "-1", text: path }), line ? h("span", { class: "wb-muted wb-viewer-line wb-panel-sub", text: line }) : null),
      h("span", { class: "wb-viewer-tools" }, tools, close));
  }

  return {
    el,
    async load(project, path, { quiet = false } = {}) {
      if (controller) controller.abort();
      controller = new AbortController();
      const mine = controller;
      if (!quiet) fill(el, head(path, ""), h("div", { class: "wb-viewer-body" }, busyLine("Loading the floor...")));
      const row = listed(path) || {};
      /** Read the bytes of an image; a refusal of the type (400) is the sentence of a file the page cannot show. `first`: the refusal of the text read, shown when the bytes fail too. */
      async function raw(first) {
        let blob;
        try {
          blob = await api.artifactRaw(project, path, { signal: mine.signal });
        } catch (e) {
          if (mine.signal.aborted || (e && e.name === "AbortError")) return;
          if (!first && e && e.name === "ApiError" && e.status === 400) {      // the list says the file is of a type the Desk does not show
            release();
            fill(el, head(path, row.size !== undefined ? formatSize(row.size) : ""),
              h("div", { class: "wb-viewer-body" }, unshownBody(path, unshownSentence(e.message, row.kind, formatSize(row.size)))));
            return;
          }
          throw first || e;
        }
        if (mine.signal.aborted) return;
        if (!SHOWN_TYPES.includes(blob.type)) {      // bytes of a type the page does not show are never given to an <img>
          release();
          fill(el, head(path, formatSize(blob.size)), h("div", { class: "wb-viewer-body" }, unshownBody(path, unshownSentence(null, row.kind, formatSize(blob.size)))));
          return;
        }
        fill(el, head(path, formatSize(blob.size)), h("div", { class: "wb-viewer-body" }, imageBody(blob, path, row.size)));
      }
      try {
        if (row.kind === "image" || row.kind === "other") {
          await raw(null);
          return;
        }
        let doc;
        try {
          doc = await api.artifact(project, path, { signal: mine.signal });
        } catch (e) {
          // the list does not say what the file is (not read yet, or an older service): a file the text read refuses may be an image
          if (row.kind === undefined && e && e.name === "ApiError" && (e.status === 409 || e.status === 400)) {
            await raw(e);
            return;
          }
          throw e;
        }
        if (mine.signal.aborted) return;
        release();
        const line = `${formatSize(doc.size)}, modified ${formatWhen(doc.modified_at)}`;
        const [tools, ...body] = documentBody(doc, path);
        fill(el, head(doc.path || path, line, MARKDOWN_FILE.test(doc.path || path) ? tools : null), h("div", { class: "wb-viewer-body" }, MARKDOWN_FILE.test(doc.path || path) ? body : [tools, ...body]));
      } catch (e) {
        if (mine.signal.aborted || (e && e.name === "AbortError")) return;
        release();
        const message = e && e.name === "ApiError" && e.status === 0 ? "The service could not be reached. Is it still running?" : (e && e.message) || "The file could not be opened.";
        fill(el, head(path, ""), h("div", { class: "wb-viewer-body" },
          h("div", { class: "wb-refusal", role: "alert" }, h("strong", { class: "wb-refusal-title", text: "The file could not be opened" }), h("span", { class: "mono", text: message }))));
      }
    },
    close() {
      if (controller) controller.abort();
      controller = null;
      release();       // the blob URL of an image is revoked when the viewer closes
    },
    focus() {
      const node = el.querySelector ? el.querySelector(`#${titleId}`) : null;
      if (node && node.focus) node.focus();
    },
  };
}
