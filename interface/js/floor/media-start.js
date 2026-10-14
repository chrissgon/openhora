// "New short video" and "Edit this recording": how a recording gets from the person's disk to the caption review without a terminal and without an agent's task.
// A recording does not need a task: `media-in` issues its own id and the pipeline makes its own code task (key media:<id>). So this part stands on its own, in the Tasks tab
// (with the upload) and in the Agent tab (the offers, after the upload of "Hand a file over"):
//
//   1. Upload the recording: a video, to the media route with a progress bar (the same `uploadRecording` the Agent tab uses; the Mac only).
//   2. Every stored recording whose pipeline has not started is offered, from `media-list`, so a reload strands none: choose the post file, give the network, "Edit this
//      recording". The post files are the Markdown documents the post-writing skill owns (read from `artifacts` and `artifact`), the ones that carry a script block; with several
//      the page asks and never picks, and with none it asks for the path. The network is the post file's `- Network:` line, else the person's.
//   3. "Edit this recording" calls `media-pipeline` (a job) and shows its steps until it stops at "Check the captions" (the caption review in the Tasks tab row of the new
//      task) or at a failure, told in the sentence of its closed code with the command to run. No model is called and no request is needed.
//
// The control is withheld when `media-pipeline` (or `media-in`, for the upload) is turned off for the page, the routes answer on the loopback socket only (off the Mac the part says
// to start it there and does nothing else), and every value is put in with textContent.
//
//   env = {project, api: {mediaList, artifacts, artifact, mediaPipeline, uploadMedia, pollJob}, can(op) (optional), loopback (optional, default onLoopback()), upload (optional,
//          default true: draw the upload step), title (optional: the card's heading, default "New short video"; false draws none), refresh() (optional: told when a task was
//          made, so that the Tasks tab reads again), loaded(waiting) (optional: told how many recordings wait, after every read), pollEvery (ms, default 1500)}
// Returns {el, load({again}), close(), pick(file) (the same as choosing a file)}.

import { fill, h } from "../dom.js";
import { reader } from "../permissions.js";
import { failureText, stepRows } from "./captions-model.js";
import { handOverStep } from "./hand-file.js";
import { isMediaFile, mediaRefusal, onLoopback, progressBar, uploadRecording } from "./media-upload.js";
import { NETWORK_WORD, hasScript, networkOf, postCandidates, postPath, recordingLine, refusalText, waitingRecordings } from "./media-start-model.js";
import { notice, withheldLine } from "./widgets.js";

export const ON_THE_MAC = "A short video is started on the Mac that runs the service: the recording is uploaded and edited there, and is not sent over the network.";
export const UPLOAD_HINT = "A video (a .mov or .mp4 up to 1 GiB and 5 minutes). It needs no task: it gets its own.";
export const OTHER = "__other__";      // the choice of a file the page did not find: its path is typed
export const NO_POSTS = "No post file with a script was found. Type the path of the post file this recording is for (a Markdown file under docs/ of the project).";

export function createMediaStart(env) {
  const can = reader(env);
  const loopback = typeof env.loopback === "boolean" ? env.loopback : onLoopback();
  const api = env.api;
  const el = h("section", { class: "pui-card wb-card wb-sv", "aria-label": env.title || "New short video", "data-key": "media-start" });
  const state = {
    waiting: [], platforms: [], busyIds: new Set(), entries: new Map(), posts: null, postsError: null, postsRead: false,
    picked: null, uploading: null, message: null, error: null, per: new Map(), loaded: false,
  };
  let closed = false;
  const closing = new AbortController();

  const row = (id) => {
    if (!state.per.has(id)) state.per.set(id, { post: "", typedPost: "", network: "", busy: false, steps: null, error: null, result: null });
    return state.per.get(id);
  };

  // --- reading -------------------------------------------------------------------------------------------------------------------------

  async function readMedia() {
    const found = await api.mediaList(env.project, { signal: closing.signal });
    const recordings = found.recordings || [];
    state.platforms = Array.isArray(found.platforms) ? found.platforms.filter((n) => NETWORK_WORD.test(n)) : [];      // the networks the service has a data file for: asked, never written here
    state.waiting = waitingRecordings(recordings);
    for (const w of state.waiting) state.entries.set(w.id, w);
    for (const r of recordings) {       // a recording being started: its steps, from the pipeline the first step made
      const per = state.per.get(r.id);
      if (per && per.busy && r.pipeline) per.steps = r.pipeline.steps;
    }
  }

  /** The post files: the documents the post-writing skill owns, read once to see which carry a script block and which network they name. */
  async function readPosts() {
    state.postsRead = true;
    state.postsError = null;
    try {
      const list = await api.artifacts(env.project, { signal: closing.signal });
      const found = await Promise.all(postCandidates(list.artifacts).map(async (a) => {
        try {
          const doc = await api.artifact(env.project, a.path, { signal: closing.signal });
          return hasScript(doc.text) ? { path: a.path, network: networkOf(doc.text) } : null;
        } catch (e) {
          if (e && e.name === "AbortError") throw e;
          return null;
        }
      }));
      state.posts = found.filter(Boolean);
    } catch (e) {
      if (e && e.name === "AbortError") throw e;
      state.posts = [];
      state.postsError = e;
    }
  }

  async function load({ again = false } = {}) {
    if (closed) return;
    if (!loopback) {
      draw();
      return;
    }
    if (typeof api.mediaList !== "function") return;       // an environment with no media client (a page of the Floor that never started one): nothing to offer
    try {
      await readMedia();
      if (state.waiting.length && (!state.postsRead || again)) await readPosts();
    } catch (e) {
      if (closed || (e && e.name === "AbortError")) return;
      state.error = refusalText(e);
    }
    state.loaded = true;
    if (!closed) draw();
    if (!closed && env.loaded) env.loaded(state.waiting.length);
  }

  // --- the upload ------------------------------------------------------------------------------------------------------------------------

  const fileInput = h("input", { class: "wb-file", type: "file", accept: "video/mp4,video/quicktime,.mov,.mp4,.m4v", "aria-label": "Recording to upload", tabindex: "-1", "data-key": "sv-file" });
  fileInput.addEventListener("change", () => pick((fileInput.files && fileInput.files[0]) || null));

  function pick(file) {
    state.error = null;
    state.message = null;
    if (!file) {
      state.picked = null;
    } else if (!isMediaFile(file)) {
      state.picked = null;
      state.error = "This is not a video: choose a .mov or .mp4 recording.";
    } else {
      const refusal = mediaRefusal(file, { loopback });
      state.picked = refusal ? null : file;
      state.error = refusal || null;
    }
    draw();
  }

  async function sendRecording() {
    const file = state.picked;
    if (!file || state.uploading || !can("media-in")) return;
    const bar = progressBar();
    state.uploading = bar;
    state.error = null;
    draw();
    try {
      const stored = await uploadRecording(api, env.project, file, { bar, signal: closing.signal });
      state.picked = null;
      fileInput.value = "";
      state.message = `Recording stored (${String(stored.recording).slice(0, 8)}). Choose its post file below and start the edit.`;
      state.uploading = null;
      await load({ again: true });
      return;
    } catch (e) {
      if (closed) return;
      state.error = e && e.name === "ApiError" && e.message ? e.message : refusalText(e);
    }
    state.uploading = null;
    if (!closed) draw();
  }

  // --- starting the pipeline ---------------------------------------------------------------------------------------------------------

  /** The post file of a recording among the ones found: the one the person chose (never one picked for them: the choice is a click). */
  function postOf(per, posts) {
    return posts.find((p) => p.path === per.post) || null;
  }

  /** Whether the post file is typed: none was found, or the person chose "another file...". */
  const typedPost = (per, posts) => !posts.length || per.post === OTHER;

  /** The post file and the network chosen for a recording, or why there is none yet: {post, network} or {reason}. */
  function chosen(id) {
    const per = row(id);
    const posts = state.posts || [];
    const typed = typedPost(per, posts);
    const known = typed ? null : postOf(per, posts);
    const post = typed ? postPath(per.typedPost) : (known ? known.path : null);
    if (!post) return { reason: typed ? "Type the path of the post file." : "Choose the post file." };
    const fromPost = Boolean(known && known.network);
    const network = fromPost ? known.network : per.network.trim().toLowerCase();
    const listed = state.platforms;
    if (fromPost && listed.length && !listed.includes(network)) return { reason: `The post file names ${network}, which has no data file here (${listed.join(", ")}): choose another post file.` };
    if (!network) return { reason: listed.length ? "Choose the network this post is for." : "Give the network this post is for (for example instagram)." };
    if (listed.length ? !listed.includes(network) : !NETWORK_WORD.test(network)) return { reason: "Give the network this post is for (for example instagram)." };
    return { post, network };
  }

  async function start(id) {
    const per = row(id);
    const picked = chosen(id);
    if (!can("media-pipeline") || per.busy || picked.reason) return;
    per.busy = true;
    per.error = null;
    per.result = null;
    per.steps = null;
    state.busyIds.add(id);
    draw();
    try {
      const job = await api.mediaPipeline(env.project, id, { post: picked.post, network: picked.network, signal: closing.signal });
      const last = await api.pollJob(job.job, env.pollEvery || 1500, { signal: closing.signal, onUpdate: () => { readMedia().then(() => { if (!closed) draw(); }).catch(() => {}); } });
      if (last.state === "failed") per.error = last.error && last.error.message ? refusalText(last.error) : "The pipeline stopped.";      // a refusal of the operation reaches the page as a failed job: its words are told in the page's sentences
      else if (last.result && last.result.ok === false) per.error = failureText({ step: last.result.failed, code: last.result.code, field: last.result.field, next: last.result.next });
      else per.result = last.result || {};
    } catch (e) {
      if (closed) return;
      per.error = refusalText(e);
    }
    per.busy = false;
    state.busyIds.delete(id);
    try {
      await readMedia();
    } catch (e) {
      if (closed) return;
    }
    if (closed) return;
    draw();
    if (env.refresh) env.refresh();
  }

  // --- drawing -----------------------------------------------------------------------------------------------------------------------------

  function button(label, key, onClick, { disabled = false, primary = false } = {}) {
    const node = h("button", { class: `pui-btn ${primary ? "pui-solid pui-theme" : "pui-surface pui-outline"} wb-card-button wb-sv-button`, type: "button", "data-key": key, disabled, text: label });
    node.addEventListener("click", onClick);
    return node;
  }

  function labelled(label, control) {
    return h("label", { class: "pui-field-group wb-field" }, h("span", { class: "wb-field-label", text: label }), control);
  }

  function uploadNode() {
    if (env.upload === false) return null;
    if (!can("media-in")) return withheldLine(["media-in"]);
    const choose = h("button", { class: "pui-btn pui-surface pui-outline wb-hand-choose wb-sv-button", type: "button", "data-key": "sv-choose", disabled: Boolean(state.uploading), text: "Choose a recording" });
    choose.addEventListener("click", () => { if (!fileInput.disabled) fileInput.click(); });
    fileInput.disabled = Boolean(state.uploading);
    return h("div", { class: "wb-hand wb-sv-upload" },
      h("div", { class: "wb-hand-row" }, choose), fileInput,
      handOverStep(state.picked, null, sendRecording, { disabled: Boolean(state.uploading), label: "Upload the recording" }),
      state.uploading ? [h("p", { class: "wb-card-note", role: "status", text: "Uploading..." }), state.uploading.node] : null,
      h("p", { class: "wb-card-hint", text: UPLOAD_HINT }));
  }

  function pathInput(r, per) {
    const input = h("input", { class: "pui-input wb-sv-input", type: "text", "data-key": `sv-path-${r.id}`, "aria-label": "Path of the post file", autocomplete: "off", spellcheck: "false", placeholder: "docs/marketing/content/..." });
    input.value = per.typedPost;
    input.addEventListener("input", () => { per.typedPost = input.value; refreshStart(r.id); });
    return labelled("Post file path", input);
  }

  function postPicker(r, per, posts) {
    if (posts.length) {
      const now = postOf(per, posts);
      const select = h("select", { class: "pui-input wb-sv-select", "data-key": `sv-post-${r.id}`, "aria-label": "The post file of this recording" },
        [h("option", { value: "", selected: !now && per.post !== OTHER, text: "Choose the post file" }),
          ...posts.map((p) => h("option", { value: p.path, selected: Boolean(now) && p.path === now.path, text: `${p.path}${p.network ? ` (${p.network})` : ""}` })),
          h("option", { value: OTHER, selected: per.post === OTHER, text: "another file..." })]);
      select.value = per.post === OTHER ? OTHER : (now ? now.path : "");
      select.addEventListener("change", () => { per.post = select.value; draw(); });
      return [labelled("Post file", select), per.post === OTHER ? pathInput(r, per) : null];
    }
    const why = state.postsError ? `The post files could not be read (${refusalText(state.postsError)}). Type the path of the post file this recording is for.` : NO_POSTS;
    return [h("p", { class: "wb-card-hint", "data-key": `sv-noposts-${r.id}`, text: why }), pathInput(r, per)];
  }

  function networkField(r, per, known) {
    if (known && known.network) return h("p", { class: "wb-card-note", "data-key": `sv-network-${r.id}`, text: `Network: ${known.network} (from the post file)` });
    if (state.platforms.length) {
      const select = h("select", { class: "pui-input wb-sv-select", "data-key": `sv-net-${r.id}`, "aria-label": "The network of the post" },
        [h("option", { value: "", selected: !per.network, text: "Choose the network" }), ...state.platforms.map((n) => h("option", { value: n, selected: n === per.network, text: n }))]);
      select.value = per.network;
      select.addEventListener("change", () => { per.network = select.value; refreshStart(r.id); });
      return labelled("Network", select);
    }
    const input = h("input", { class: "pui-input wb-sv-input", type: "text", "data-key": `sv-net-${r.id}`, "aria-label": "The network of the post", autocomplete: "off", spellcheck: "false", placeholder: "for example instagram" });
    input.value = per.network;
    input.addEventListener("input", () => { per.network = input.value; refreshStart(r.id); });
    return labelled("Network", input);
  }

  function offerNode(r) {
    const per = row(r.id);
    const posts = state.posts || [];
    const known = typedPost(per, posts) ? null : postOf(per, posts);
    const picked = chosen(r.id);
    const may = can("media-pipeline");
    return h("li", { class: "wb-sv-row", "data-recording": r.id }, ...[
      h("p", { class: "wb-sv-head" }, h("strong", { text: recordingLine(r) }), r.name ? h("span", { class: "wb-card-hint", text: ` · ${r.name}` }) : null),
      per.busy || per.result || per.error ? progressNode(r.id) : null,
      !per.busy && !per.result && may ? [postPicker(r, per, posts), networkField(r, per, known),
        h("p", { class: "wb-card-hint", "data-key": `sv-why-${r.id}`, text: picked.reason || "" }),
        h("div", { class: "wb-card-actions" }, button("Edit this recording", `sv-start-${r.id}`, () => start(r.id), { primary: true, disabled: Boolean(picked.reason) }))] : null,
      may ? null : withheldLine(["media-pipeline"])].flat(Infinity));
  }

  /** The start button follows what is typed without drawing the row again (the typed text and the focus stay). */
  function refreshStart(id) {
    if (!el.querySelector) return;
    const node = el.querySelector(`[data-key="sv-start-${id}"]`);
    if (!node) return;
    const why = chosen(id).reason;
    if (why) node.setAttribute("disabled", "");
    else node.removeAttribute("disabled");
    const note = el.querySelector(`[data-key="sv-why-${id}"]`);
    if (note) note.textContent = why || "";
  }

  function progressNode(id) {
    const per = row(id);
    return h("div", { class: "wb-sv-progress", "data-key": `sv-progress-${id}` },
      per.busy ? h("p", { class: "wb-card-note", role: "status", text: "Starting the pipeline..." }) : null,
      per.steps ? h("ol", { class: "wb-sv-steps" }, stepRows(per.steps).map((s) => h("li", { class: `wb-sv-step is-${s.status}`, "data-step": s.step }, h("span", { text: s.label }), h("span", { class: "wb-card-hint", text: ` — ${s.word}` })))) : null,
      per.result ? h("p", { class: "wb-card-note", role: "status", "data-key": `sv-result-${id}`, text: `It stopped at "Check the captions"${per.result.task ? ` (task #${per.result.task})` : ""}: open that task in the Tasks tab to check the words.` }) : null,
      per.error ? notice(per.error, "error") : null);
  }

  const parts = { notes: null, upload: null, offers: null };
  let shown = {};
  let shape = false;

  function paint(name, signature, produce) {
    const key = JSON.stringify(signature);
    if (shown[name] === key) return;
    shown[name] = key;
    fill(parts[name], [produce()].flat(Infinity));
  }

  function skeleton() {
    for (const name of Object.keys(parts)) parts[name] = h("div", { class: "wb-sv-part", "data-part": name });
    const title = env.title === undefined ? "New short video" : env.title;
    fill(el, title ? h("div", { class: "wb-card-head wb-sv-title" }, h("strong", { class: "wb-card-title", text: title })) : null, h("div", { class: "wb-card-content wb-sv-content" }, Object.values(parts)));
    shape = true;
    shown = {};
  }

  function draw() {
    if (closed) return;
    if (!shape) skeleton();
    if (!loopback) {
      paint("notes", ["mac"], () => notice(ON_THE_MAC, "warn"));
      paint("upload", ["off"], () => null);
      paint("offers", ["off"], () => null);
      return;
    }
    // the recordings that wait, and the ones being started or just started (their steps and the sentence of where they stopped stay until the page is read again from nothing)
    const shownIds = [...state.per].filter(([, p]) => p.busy || p.result || p.error).map(([id]) => id);
    const active = state.waiting.concat(shownIds.filter((id) => !state.waiting.some((w) => w.id === id) && state.entries.has(id)).map((id) => state.entries.get(id)));
    paint("notes", [state.error, state.message], () => [state.message ? h("p", { class: "wb-card-note", role: "status", "data-key": "sv-message", text: state.message }) : null, state.error ? notice(state.error, "error") : null]);
    paint("upload", [env.upload !== false, can("media-in"), state.picked && state.picked.name, Boolean(state.uploading)], uploadNode);
    paint("offers", [active.map((r) => r.id), state.posts, state.postsError && state.postsError.message, state.platforms, [...state.per].map(([id, p]) => [id, p.post, p.network, p.busy, p.steps, p.error, p.result]), can("media-pipeline"), state.loaded],
      () => (active.length ? h("ul", { class: "wb-sv-list", "data-key": "sv-list" }, active.map(offerNode))
        : (state.loaded ? h("p", { class: "wb-empty-line", "data-key": "sv-none", text: "No recording is waiting to be edited." }) : null)));
  }

  return {
    el,
    load,
    pick,
    close() {
      closed = true;
      closing.abort();
    },
  };
}
