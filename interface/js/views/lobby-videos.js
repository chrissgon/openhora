// The new videos of a project (package V1c-1), a section of the Building's panel: the form that starts one from a recording and a post, the recordings newest
// first with the state of each video and what that state offers (start, run, open the decision it waits on, download a delivered one), and the room the recordings
// use. The page decides nothing: the service lists, uploads, starts and runs, and its sentence for a refusal is shown as it came. The controls are drawn only when
// the page may (js/permissions.js), and on a page reached over the local network the upload and the download are not drawn at all and the page says why (the
// service refuses them there, limits L67 and L68; js/cards/deliver.js). It lives with the Lobby's modules because a write may not be sent from the Building itself
// (test_interface_files.py); the Building only places it. Text from the service goes in as text; the video is a blob URL for the moment it is saved.

import { h } from "../dom.js";
import { failureText } from "../cards/plan-rows.js";
import { LAN_MEDIA, hostOf, onLoopback } from "../cards/deliver.js";
import { can as pageMay } from "../permissions.js";
import * as router from "../router.js";
import { LIST_MAX, STATE_TEXT, fileProblem, newestFirst, postChoices, sizeWords, stateOf } from "./lobby-video-model.js";

export const HEAD = "Videos";
export const LEAD = "A new video starts from a recording and a post. It stops for you twice: to check the captions, and to approve the delivery.";
const REREAD_MS = 15000;      // the list is read again when it is older than this, when the page reloads, and after every write of this section
const POLL_MS = 1000;
const REVOKE_MS = 60000;      // the address of a saved video is given back this long after the save started

/**
 * env: {api (the client), project (getter), entry() (the GET /projects entry, for the policy), refresh(), host() (optional: the page's host, for a test),
 * openReview(task, mode) (optional: opens the caption review; without it the review is not offered)}. Returns {el, update(detail, shown, stamp)}.
 */
export function createVideos(env) {
  const head = h("h3", { class: "wb-steps-head", text: HEAD });
  const lead = h("p", { class: "wb-steps-line", text: LEAD });
  const list = h("ul", { class: "wb-vd-list", "aria-label": "Videos, newest first" });
  const quota = h("p", { class: "wb-steps-note wb-vd-quota", hidden: true });
  const note = h("p", { class: "wb-steps-note wb-vd-note", role: "status", hidden: true });
  const error = h("p", { class: "wb-vd-error", role: "alert", hidden: true });
  const picked = { file: null, post: "" };
  const fileInput = h("input", { class: "pui-input wb-field-input wb-vd-file", type: "file", accept: "video/mp4,video/quicktime,.mp4,.mov", id: "wb-vd-file" });
  const fileLabel = h("label", { class: "wb-field-label", for: "wb-vd-file", text: "Recording (MP4 or MOV, at most 1 GiB)" });
  const fileBox = h("div", { class: "wb-vd-file-box" });          // the label and the input on this computer's own page; the line that says why not elsewhere
  const postSelect = h("select", { class: "pui-input wb-field-input wb-vd-post", id: "wb-vd-post" });
  const postLabel = h("label", { class: "wb-field-label", for: "wb-vd-post", text: "Post" });
  const noPost = h("p", { class: "wb-steps-note wb-vd-no-post", text: "No post file under docs/marketing/content/ yet.", hidden: true });
  const uploadButton = h("button", { class: "pui-btn pui-solid pui-theme wb-vd-upload", type: "button", text: "Upload and start" });
  const form = h("div", { class: "wb-vd-form" }, fileBox, postLabel, postSelect, noPost, uploadButton);
  const stage = h("div", { class: "wb-vd-stage", hidden: true });   // holds the playing video outside the list, so a redraw of the list never detaches (and so never pauses) it
  const el = h("section", { class: "wb-sec wb-vd-sec", hidden: true }, head, lead, form, list, stage, quota, note, error);
  let media = null;         // the last answer of the media list
  let artifacts = null;     // the last answer of the artifacts list (the posts)
  let readAt = 0;
  let reading = false;
  let shown = false;
  let busy = null;          // {key, label} of the control that is sending
  let seen;                 // the page's reload stamp last seen
  let rows = [];            // the project's open decisions (status.pending)
  let choicesShown = null;
  let boxShown = null;
  let readingPosts = false;
  let controller = null;
  let watching = null;      // {task, url, video}: the one video played before its approval, from a blob URL the page built
  const may = (op) => pageMay(env.entry ? env.entry() : null, op);
  const here = () => onLoopback(hostOf(env));

  function say(text) {
    note.textContent = text || "";
    note.hidden = !text;
  }

  function fail(e) {
    error.textContent = failureText(e);
    error.hidden = false;
  }

  function clearMessages() {
    say("");
    error.textContent = "";
    error.hidden = true;
  }

  async function load(force = false) {
    if (reading || !shown || !may("media-list") || !(force || Date.now() - readAt >= REREAD_MS)) return;
    reading = true;
    try {
      media = await env.api.mediaList(env.project);
      readAt = Date.now();
    } catch (e) {
      fail(e);
    }
    reading = false;
    draw();
  }

  /** The posts the form offers: read once per reload stamp, and only while the form is wanted. */
  async function loadPosts() {
    if (readingPosts || !shown || !may("video-new")) return;
    readingPosts = true;
    try {
      artifacts = await env.api.artifacts(env.project);
    } catch (e) {
      fail(e);
    }
    readingPosts = false;
    draw();
  }

  /** The sentence for what a started or run video reported: a failed job, a video that did not start, a step that failed, or the review that is ready. */
  function resultText(final) {
    if (final && final.state === "failed") return (final.error && final.error.message) || "The video job failed.";
    const result = (final && final.result) || {};
    if (result.started === false) return `The video is ready to run: ${result.reason}`;
    if (result.failed) return `The step failed: ${result.code}${result.field ? ` (${result.field})` : ""}`;
    return "The captions are ready to check.";
  }

  /** Hands a started job to the poll and returns the sentence of its end. */
  async function followed(queued) {
    return resultText(await env.api.pollJob(queued.job, POLL_MS, { signal: controller ? controller.signal : undefined }));
  }

  /** One write of this section: every control is off while it sends, a refusal shows as it came, and the list is read again after it. */
  async function perform(key, label, work, { reread = true } = {}) {
    if (busy) return;
    busy = { key, label };
    clearMessages();
    draw();
    let sentence = "";
    try {
      sentence = await work((next) => { busy = { key, label: next }; draw(); });
    } catch (e) {
      if (!(e && e.name === "AbortError")) fail(e);
    }
    busy = null;
    say(sentence);
    if (reread) {
      readAt = 0;
      await load(true);
      if (env.refresh) await env.refresh();
    }
    draw();
  }

  async function upload() {
    if (!may("media-in") || !may("video-new") || !here()) return;      // a click asks the policy again
    const file = picked.file;
    if (!file || !picked.post) return;
    const problem = fileProblem(file);
    if (problem) {
      clearMessages();
      say(problem);
      return;
    }
    const post = picked.post;
    await perform("upload", "Uploading...", async (relabel) => {
      const received = await env.api.mediaIn(env.project, file);
      picked.file = null;
      fileInput.value = "";      // a second click never uploads the same recording twice
      relabel("Starting...");
      return followed(await env.api.videoNew(env.project, received.media, post));
    });
  }

  function start(record, key) {
    if (!may("video-new")) return;
    if (!picked.post) {
      clearMessages();
      say("Choose a post in the form above first.");
      return;
    }
    const post = picked.post;
    perform(key, "Starting...", async () => followed(await env.api.videoNew(env.project, record.media, post)));
  }

  function run(record, key) {
    if (!may("video-run")) return;
    perform(key, "Running...", async () => followed(await env.api.videoRun(env.project, record.task)));
  }

  /** Saves a video: an anchor with the blob's address and the name, clicked once, and the address given back later. */
  function save(blob, name) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", name);
    link.hidden = true;
    el.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), REVOKE_MS);
  }

  function download(record, key) {
    if (!may("video-download") || !here()) return;
    perform(key, "Saving the video...", async () => {
      const got = await env.api.videoDownload(env.project, record.task);
      save(got.blob, got.name);
      return "";
    }, { reread: false });
  }

  /** Gives the playing video's address back and removes it. */
  function stopWatching() {
    if (!watching) return;
    if (typeof watching.video.pause === "function") watching.video.pause();
    stage.replaceChildren();
    stage.hidden = true;
    URL.revokeObjectURL(watching.url);
    watching = null;
  }

  /** Plays the render the open delivery decision names, in the stage under the list, one at a time. A refusal shows as it came. */
  function watch(record, key) {
    if (!may("video-watch") || !here()) return;
    perform(key, "Loading the video...", async () => {
      const blob = await env.api.videoWatch(env.project, record.task);
      stopWatching();      // one at a time: the earlier address is given back
      const url = URL.createObjectURL(blob);
      const video = h("video", { class: "wb-vd-video", controls: "", playsinline: "", src: url, "aria-label": "The video waiting for your approval" });
      watching = { task: record.task, url, video };
      stage.replaceChildren(h("p", { class: "wb-steps-note wb-vd-stage-name", text: `Recording ${String(record.media).slice(0, 8)}: the video waiting for your approval` }), video);
      stage.hidden = false;
      return "";
    }, { reread: false });
  }

  function button(key, label, onClick) {
    const mine = busy !== null && busy.key === key;
    const control = h("button", { class: "pui-btn pui-surface pui-outline wb-vd-button", type: "button", "aria-busy": mine ? "true" : null, text: mine ? busy.label : label });
    control.disabled = busy !== null;
    control.addEventListener("click", onClick);
    return control;
  }

  function link(text, hash) {
    return h("a", { class: "pui-link pui-theme wb-vd-link", href: hash, text });
  }

  function reviewButton(record, mode, key) {
    if (!may("captions-read") || typeof env.openReview !== "function") return null;
    return button(`${key}:review`, "Check the captions", () => env.openReview(record.task, mode));
  }

  function actionsOf(record, state) {
    const key = String(record.media);
    const held = rows.find((p) => p && p.task_id === record.task);
    const out = [];
    if (state === "none" || state === "failed" || state === "cancelled") {
      if (may("video-new")) out.push(button(`${key}:start`, "Start", () => start(record, `${key}:start`)));
    } else if (state === "ready") {
      if (may("video-run")) out.push(button(`${key}:run`, "Run", () => run(record, `${key}:run`)));
    } else if (state === "review") {
      out.push(reviewButton(record, "review", key));
      if (held) out.push(link("Open the decision", router.lobbyHash(env.project, "inbox", held.id)));
    } else if (state === "deliver") {
      out.push(reviewButton(record, "gate", key));
      if (may("video-watch") && here()) {
        out.push(watching && watching.task === record.task
          ? button(`${key}:unwatch`, "Close the video", () => { stopWatching(); draw(); })
          : button(`${key}:watch`, "Watch the video", () => watch(record, `${key}:watch`)));
      }
      if (held) out.push(link("Open the delivery card", router.lobbyHash(env.project, "inbox", held.id)));
    } else if (state === "waiting") {
      out.push(link("Open the Inbox", router.lobbyHash(env.project, "inbox")));
    } else if (state === "done") {
      if (may("video-download")) {
        out.push(here() ? button(`${key}:download`, "Download", () => download(record, `${key}:download`)) : h("p", { class: "wb-steps-note wb-vd-lan", text: LAN_MEDIA }));
      }
      out.push(reviewButton(record, null, key));
    }
    return out.filter(Boolean);
  }

  function item(record) {
    const state = stateOf(record, rows);
    const size = typeof record.size === "number" ? ` · ${sizeWords(record.size)}` : "";
    const title = h("p", { class: "wb-vd-name" }, h("strong", { text: `Recording ${String(record.media).slice(0, 8)} · ${String(record.created_at || "").slice(0, 10)}${size}` }));
    const words = h("p", { class: "wb-steps-note wb-vd-state", text: STATE_TEXT[state] });
    const actions = h("div", { class: "wb-vd-actions" }, ...actionsOf(record, state));
    return h("li", { class: "wb-vd-item", "data-media": String(record.media) }, title, words, actions);
  }

  function drawList() {
    const found = media && Array.isArray(media.recordings) ? newestFirst(media.recordings) : [];
    const shownRows = found.slice(0, LIST_MAX);
    const items = shownRows.map(item);
    // the video stays in the stage, which a redraw never touches; it goes when its recording leaves the delivery state
    if (watching && !found.some((r) => r.task === watching.task && stateOf(r, rows) === "deliver")) stopWatching();
    if (found.length > LIST_MAX) items.push(h("li", { class: "wb-vd-more", text: `and ${found.length - LIST_MAX} older` }));
    if (media && !found.length) items.push(h("li", { class: "wb-vd-more", text: "No recording yet." }));
    list.replaceChildren(...items);
    const have = media && Number.isFinite(Number(media.used_bytes)) && Number.isFinite(Number(media.quota_bytes));
    quota.textContent = have ? `Recordings use ${sizeWords(media.used_bytes)} of ${sizeWords(media.quota_bytes)}.` : "";
    quota.hidden = !have;
  }

  function drawForm() {
    const posts = postChoices(artifacts);
    const wantPost = may("video-new");
    const wantFile = may("media-in") && wantPost;
    form.hidden = !wantPost;
    // the label and the file input are in the document only on this computer's own page; elsewhere the line that says why not stands in their place
    const box = !wantFile ? "none" : here() ? "file" : "lan";
    if (box !== boxShown) {
      boxShown = box;
      if (box === "file") fileBox.replaceChildren(fileLabel, fileInput);
      else if (box === "lan") fileBox.replaceChildren(h("p", { class: "wb-steps-note wb-vd-lan", text: LAN_MEDIA }));
      else fileBox.replaceChildren();
    }
    const signature = posts.join("\n");
    if (signature !== choicesShown) {
      choicesShown = signature;
      postSelect.replaceChildren(h("option", { value: "", text: "Choose a post" }), ...posts.map((path) => h("option", { value: path, text: path })));
      if (!posts.includes(picked.post)) picked.post = "";
    }
    postSelect.value = picked.post;
    postSelect.disabled = busy !== null;
    noPost.hidden = !wantPost || posts.length > 0;
    const mine = busy !== null && busy.key === "upload";
    uploadButton.hidden = box !== "file";
    uploadButton.textContent = mine ? busy.label : "Upload and start";
    uploadButton.disabled = busy !== null || !picked.file || !picked.post;
    if (mine) uploadButton.setAttribute("aria-busy", "true"); else uploadButton.removeAttribute("aria-busy");
  }

  fileInput.addEventListener("change", () => {
    picked.file = fileInput.files && fileInput.files[0] ? fileInput.files[0] : null;
    drawForm();
  });
  postSelect.addEventListener("change", () => {
    picked.post = postSelect.value || "";
    drawForm();
  });
  uploadButton.addEventListener("click", upload);

  function draw() {
    el.hidden = !shown || !may("media-list");
    if (el.hidden) return;
    drawForm();
    drawList();
  }

  return {
    el,
    /** detail: the project's entry of the snapshot (its status holds the open decisions); shown: whether the panel draws the section at all (the project is accepted); stamp: the page's reload stamp. */
    update(detail, isShown, stamp) {
      const moved = stamp !== undefined && stamp !== seen;
      seen = stamp;
      shown = Boolean(isShown && detail);
      rows = detail && detail.status && Array.isArray(detail.status.pending) ? detail.status.pending : [];
      if (!shown) {
        media = null;
        stopWatching();
        artifacts = null;
        clearMessages();
        if (controller) controller.abort();
        controller = null;
      } else if (!controller) {
        controller = new AbortController();
      }
      draw();
      if (shown) {
        load(moved);
        if (moved || artifacts === null) loadPosts();
      }
    },
  };
}
