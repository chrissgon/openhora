// The rendered video of a post, and the person's approval of it (decisions D19 to D22 of the short-video plan; runtime/video.py is the other half).
// The card shows what the service returned for one recording: the video itself, fetched with the bearer header (a `<video src>` cannot send
// one, so the bytes become a `blob:` URL the page built, which the page's policy allows as media and nothing else), the cover frame, the size,
// the length and the sha256 of the file, and the caption exactly as the post file has it with its own sha256. "Approve" sends the two hashes
// the card shows, read back from its own state at the moment of the click, and nothing else: the service checks that both still name the
// current render and the current caption and hashes the file again before it records anything. A new render or an edit of the caption makes
// the approval stale, and the card says so and asks again. "Send back with a comment" returns the post to the review step. "Download" gives
// the approved file, under a plain name, to post by hand; nothing in this card publishes, schedules or approves a configuration.
//
// The video is watched on the Mac that runs the service: the byte routes answer on the loopback socket only, so on a page opened from a phone
// or over --lan the card shows the caption and the hashes and says "watch and approve on the Mac". The service refuses an approval there as
// well; this is the sentence, not the guard. Every value is text (h() puts it in with textContent), the caption is a `pre` that wraps, and
// the blob URLs are revoked when the card closes or shows another render.
//
//   env = {project, recording, api: {videoCard, videoApprove, videoSendBack, videoRaw, videoCover, videoDownload, mediaList (optional: where the pipeline stands)},
//          can(op) (optional: whether the page may do an operation, js/permissions.js; without it everything is allowed),
//          loopback (optional: whether this page was opened on the Mac, default onLoopback()), now() (a Date), objects (optional, for a test:
//          {create(blob) -> url, revoke(url)}), save(blob, name) (optional, for a test: what "Download" does with the bytes),
//          pollEvery (ms between two reads while the video is being made, default 3000; at most MAX_POLLS reads, or `maxPolls` for a test), measure(body) (optional, for a test: whether the caption is taller than its preview)}
// Returns {el, load({quiet}), close()}.

import { sleep, untilVisible } from "../api.js";
import { fill, h, keepScroll } from "../dom.js";
import { formatSize } from "../floor-model.js";
import { reader } from "../permissions.js";
import { failureText, stepRows } from "./captions-model.js";
import { onLoopback } from "./media-upload.js";
import { replyView } from "./reply.js";
import { actionClass, busyLine, chip, errorText, field, notice, textArea, withheldLine } from "./widgets.js";

export const ON_THE_MAC = "Watch and approve on the Mac that runs the service: a video is not shown, and nothing is approved, over the network.";
export const APPROVE_WORDS = "Approving binds this exact file and this exact caption, by the two hashes above. A new render or any edit of the caption asks you again. Nothing is published or scheduled.";
export const SENT_BACK_WORDS = "This post was sent back for review. It takes no approval until it is rendered again or its caption is edited.";
export const COMMENT_LABEL = "Comment for the review (required)";
export const MAX_POLLS = 200;       // reads while the video is being made: about ten minutes at the default pause, then the card stops looking and says so
export const STALLED_WORDS = "The page stopped checking for progress after a while: press Check again.";
export const IDLE_WORDS = "The video is not being made: the pipeline stopped before it finished (the service was restarted, or the request was cancelled). Nothing is running.";
export const MAKING_WORDS = "Making the video takes a few minutes. This page reads the pipeline again by itself; there is nothing to approve until the video is made.";
export const CAPTION_LINES = 4;
export const NO_RENDER = "There is no render yet.";
export const NO_RENDER_REVIEW = "There is no render yet: the video is made after you check the captions.";

/** The first characters of a sha256, the form a person compares by eye. */
export function shortHash(sha) {
  return typeof sha === "string" ? sha.slice(0, 12) : "";
}

/** "41.5 s, 1080 x 1920, 14.2 MiB": the facts of a render the service knew, joined; a missing one is left out. */
export function factsLine(render) {
  if (!render) return "";
  const parts = [];
  if (Number.isFinite(render.duration) && render.duration > 0) parts.push(`${Number(render.duration).toFixed(1)} s`);
  if (Number.isFinite(render.width) && Number.isFinite(render.height) && render.width > 0) parts.push(`${render.width} × ${render.height}`);
  if (Number.isFinite(render.bytes)) parts.push(formatSize(render.bytes));
  return parts.join(", ");
}

/**
 * Where the card stands, from the pipeline and the render: "stopped" (a step failed, or the render is not done and no process runs it), "making" (the captions are checked, the render or the cover is not done and a process runs it),
 * "none" (no render, and nothing is making one) or "ready" (a render exists and nothing is being made). The pipeline is null when it has not started or was not read.
 */
export function phaseOf(card, pipeline) {
  const steps = pipeline && pipeline.steps;
  if (pipeline && pipeline.failure) return "stopped";
  if (steps && Object.values(steps).includes("failed")) return "stopped";      // agrees with captions-model isRunning: a failed step means stopped
  if (steps && steps.review === "done" && ["render", "cover"].some((step) => steps[step] && steps[step] !== "done")) {
    return pipeline.active === false ? "stopped" : "making";       // a step left pending with nobody running it (a cancelled request, a killed service) is not "making"
  }
  return card && card.render ? "ready" : "none";
}

/** The state of the card as its chip: [word, tone]. The pipeline decides while the video is made or a step stopped; the approval, once there is a render. */
export function stateOf(card, pipeline = null) {
  const phase = phaseOf(card, pipeline);
  if (phase === "stopped") return ["Stopped", "pui-warn pui-soft"];
  if (phase === "making") return ["Making the video", "pui-muted pui-soft"];
  const approval = card && card.approval;
  if (approval && approval.state === "approved") return ["Approved", "pui-theme pui-soft"];
  if (approval && approval.state === "stale") return ["Approval no longer holds", "pui-warn pui-soft"];
  if (card && card.sent_back) return ["Sent back", "pui-muted pui-soft"];
  if (phase === "none") return ["No video yet", "pui-muted pui-soft"];
  return ["Waiting for your approval", "pui-muted pui-soft"];
}

/** The sentence that says why a stale approval stopped holding. */
export function staleLine(approval) {
  const reasons = (approval && approval.reasons) || [];
  const what = [];
  if (reasons.includes("render_changed")) what.push("the video was rendered again");
  if (reasons.includes("caption_changed")) what.push("the caption was edited");
  return `You approved this post on ${approval.approved_at}, but ${what.join(" and ") || "it changed"} since. Watch and read it again, then approve again.`;
}

export function createVideoCard(env) {
  const el = h("section", { class: "pui-card wb-card wb-video", "aria-label": "Rendered video", "data-key": "video-card" });
  const can = reader(env);
  const loopback = typeof env.loopback === "boolean" ? env.loopback : onLoopback();
  const urls = env.objects || { create: (blob) => URL.createObjectURL(blob), revoke: (url) => URL.revokeObjectURL(url) };
  const save = env.save || ((blob, name) => {
    const url = urls.create(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", name);
    link.click();
    setTimeout(() => urls.revoke(url), 120000);     // a large file in Safari keeps reading the URL for a while after the click
  });
  const state = {
    card: null, pipeline: null, stalled: false, restarting: false, error: null, loading: true, platform: env.platform || null,
    media: { sha: null, state: "idle", url: null, cover: null, blob: null, received: 0, total: 0, error: null },   // the video, its bytes and the cover of one render
    busy: null, comment: "", message: null, captionOpen: false,
  };
  let controller = null;
  let closed = false;
  const closing = new AbortController();      // aborted when the card closes: what waits (the next read, a restart) stops
  let watching = false;        // one chain of reads at a time, however many loads overlap
  let polls = 0;

  function releaseMedia() {
    if (controller) controller.abort();
    controller = null;
    if (state.media.url) urls.revoke(state.media.url);
    if (state.media.cover) urls.revoke(state.media.cover);
    state.media = { sha: null, state: "idle", url: null, cover: null, blob: null, received: 0, total: 0, error: null };
  }

  /** Fetch the cover (small) and then the video of the render the card names, once for each render; both become blob URLs. */
  async function fetchMedia(card) {
    const sha = card.render && card.render.sha256;
    if (!sha || !loopback || state.media.sha === sha) return;
    releaseMedia();
    controller = new AbortController();
    const mine = controller;
    state.media = { ...state.media, sha, state: "loading" };
    draw();
    try {
      if (card.cover) {
        try {
          const cover = await env.api.videoCover(env.project, env.recording, sha, { signal: mine.signal });
          if (mine.signal.aborted) return;
          state.media.cover = urls.create(cover);
        } catch (e) {
          if (mine.signal.aborted || (e && e.name === "AbortError")) return;     // no cover is not a failure of the video
        }
      }
      const blob = await env.api.videoRaw(env.project, env.recording, sha, {
        signal: mine.signal,
        onBytes: (received, total) => {
          state.media.received = received;
          state.media.total = total;
          paintProgress();
        },
      });
      if (mine.signal.aborted) return;
      state.media.url = urls.create(blob);
      state.media.blob = blob;
      state.media.state = "ready";
    } catch (e) {
      if (mine.signal.aborted || (e && e.name === "AbortError")) return;
      state.media.state = "failed";
      state.media.error = errorText(e);
    }
    if (!closed) draw();
  }

  function paintProgress() {
    const bar = el.querySelector ? el.querySelector("progress.wb-video-progress") : null;
    const text = el.querySelector ? el.querySelector(".wb-video-loading") : null;
    const { received, total } = state.media;
    if (bar) {
      bar.value = total > 0 ? Math.min(100, Math.floor((received / total) * 100)) : 0;
    }
    if (text) text.textContent = loadingText();
  }

  function loadingText() {
    const { received, total } = state.media;
    return total > 0 ? `Loading the video: ${formatSize(received)} of ${formatSize(total)}` : `Loading the video: ${formatSize(received)}`;
  }

  // --- reading and the two writes ---------------------------------------------------------------------------------------------

  /** Where the pipeline of the recording stands, as `media-list` gives it, or null (not started, not readable, or the page has no such call). Never a refusal that stops the card. */
  async function readPipeline() {
    if (typeof env.api.mediaList !== "function") return null;
    try {
      const found = await env.api.mediaList(env.project, { recording: env.recording });
      const record = ((found && found.recordings) || [])[0];
      return record && record.pipeline ? record.pipeline : null;
    } catch (e) {
      return null;
    }
  }

  /** One read: the card and the pipeline, drawn. Resolves the card read, or null when the read failed or the card closed. */
  async function readOnce() {
    const [card, pipeline] = await Promise.all([env.api.videoCard(env.project, env.recording, { platform: state.platform || undefined }), readPipeline()]);
    if (closed) return null;
    state.card = card;
    state.pipeline = pipeline;
    state.error = null;
    state.loading = false;
    if (card.platform) state.platform = card.platform;
    draw();
    return card;
  }

  /**
   * While the video is being made the card reads again by itself, so that a reload of the page, or a pipeline that ran elsewhere, is not left looking stuck. One chain
   * of reads: none while the tab is hidden (it reads at once when the tab shows again), and at most MAX_POLLS of them, after which the card says it stopped looking.
   */
  async function watch() {
    if (watching) return;
    watching = true;
    try {
      while (!closed && state.card && phaseOf(state.card, state.pipeline) === "making") {
        if (polls >= (env.maxPolls || MAX_POLLS)) {
          if (!state.stalled) {
            state.stalled = true;
            draw();
          }
          return;
        }
        await sleep(env.pollEvery || 3000, closing.signal);
        await untilVisible(closing.signal);
        if (closed) return;
        polls += 1;
        try {
          await readOnce();
        } catch (e) {
          if (closed || (e && e.name === "AbortError")) return;
          return;      // a read that failed ends the chain: "Check again" reads again
        }
      }
    } catch (e) {
      if (!(e && e.name === "AbortError")) throw e;
    } finally {
      watching = false;
    }
  }

  async function load({ quiet = false } = {}) {
    if (closed) return;
    if (!quiet && !state.card) {
      state.loading = true;
      draw();
    }
    polls = 0;
    state.stalled = false;
    try {
      const card = await readOnce();
      if (!card) return;
      watch();
      if (phaseOf(card, state.pipeline) === "ready") await fetchMedia(card);      // the video of a render is fetched only when there is nothing being made
    } catch (e) {
      if (closed) return;
      state.loading = false;
      state.error = errorText(e);
      draw();
    }
  }

  /** "Start again": the pipeline stopped with nobody running it; it runs again from the step it had reached (prepare-again), and the card reads as it goes. */
  async function startAgain() {
    const step = state.pipeline && state.pipeline.next;
    if (!step || state.restarting || !can("prepare-again") || !loopback || typeof env.api.prepareAgain !== "function") return;
    state.restarting = true;
    state.error = null;
    draw();
    try {
      const job = await env.api.prepareAgain(env.project, env.recording, step, { signal: closing.signal });
      const last = await env.api.pollJob(job.job, env.pollEvery || 3000, { signal: closing.signal });
      if (last.state === "failed") state.error = (last.error && last.error.message) || "The pipeline could not be started again.";
    } catch (e) {
      if (closed || (e && e.name === "AbortError")) return;
      state.error = errorText(e);
    }
    state.restarting = false;
    if (!closed) await load({ quiet: true });
  }

  async function write(word, call) {
    if (state.busy) return;
    state.busy = word;
    state.error = null;
    state.message = null;
    draw();
    try {
      state.card = await call();
      state.comment = word === "send-back" ? "" : state.comment;
      state.busy = null;
      state.loading = false;
      draw();
      if (phaseOf(state.card, state.pipeline) === "ready") await fetchMedia(state.card);
    } catch (e) {
      state.busy = null;
      state.error = errorText(e);
      draw();
    }
  }

  /** "Approve": the two hashes the card shows, and the platform it shows them for. Nothing else is sent. */
  function approve() {
    const card = state.card;
    if (!card || !card.render || !card.caption || !can("video-approve") || !loopback || state.media.state !== "ready") return;
    if (state.media.sha !== card.render.sha256) return;      // the video on screen is not the render the card names: watch the new one first
    if (card.sent_back && card.sent_back.blocks_approval) return;
    write("approve", () => env.api.videoApprove(env.project, env.recording, { videoSha256: card.render.sha256, captionSha256: card.caption.sha256, platform: card.platform }));
  }

  function sendBack() {
    const card = state.card;
    const comment = state.comment.trim();
    if (!card || !can("video-send-back") || !loopback) return;
    if (!comment) {
      state.error = "Say what to change: a comment is needed to send the video back.";
      draw();
      return;
    }
    write("send-back", () => env.api.videoSendBack(env.project, env.recording, comment, { platform: card.platform }));
  }

  async function download() {
    const card = state.card;
    if (!card || !card.can_download || state.busy || !loopback) return;
    state.busy = "download";
    state.error = null;
    draw();
    try {
      // the bytes already held are the approved file's when they are the render of the approved hash: save those, else fetch the file
      const held = state.media.state === "ready" && state.media.blob && card.approval && state.media.sha === card.approval.video_sha256 ? state.media.blob : null;
      const blob = held || await env.api.videoDownload(env.project, env.recording, card.platform, {});
      save(blob, card.download_name);
      state.message = `Saved ${card.download_name}. Post it by hand: nothing was published.`;
    } catch (e) {
      state.error = errorText(e);
    }
    state.busy = null;
    draw();
  }

  // --- drawing ----------------------------------------------------------------------------------------------------------------

  function button(label, key, onClick, { disabled = false, primary = false } = {}) {
    const node = h("button", { class: `${actionClass(primary)} wb-video-button`, type: "button", "data-key": key, disabled, text: label });
    node.addEventListener("click", onClick);
    return node;
  }

  function mediaNode(card, phase) {
    if (phase === "making" || phase === "stopped") return null;      // the pipeline part says what is going on; an older render is not shown beside it
    if (!card.render) return h("p", { class: "wb-empty-line", "data-key": "no-render", text: state.pipeline && state.pipeline.steps && state.pipeline.steps.review !== "done" ? NO_RENDER_REVIEW : NO_RENDER });
    if (!loopback) return notice(ON_THE_MAC, "warn");
    const media = state.media;
    if (media.state === "ready" && media.sha === card.render.sha256) {
      const video = h("video", { class: "wb-video-player", controls: true, playsinline: true, preload: "metadata", src: media.url, poster: media.cover || undefined, "aria-label": "The rendered video" });
      return h("div", { class: "wb-video-figure" }, video);
    }
    if (media.state === "failed") return notice(media.error || "The video could not be loaded.", "error");
    const bar = h("progress", { class: "wb-video-progress", max: "100", value: "0", "aria-label": "Video download progress" });
    return h("div", { class: "wb-video-loadbox" }, h("p", { class: "wb-video-loading wb-muted", role: "status", text: loadingText() }), bar);
  }

  /** The steps of the pipeline while the video is made or a step stopped, with what it takes and, on a failure, its sentence and the command. */
  function pipelineNode(phase) {
    const pipeline = state.pipeline;
    if (!pipeline || (phase !== "making" && phase !== "stopped")) return null;
    const failure = pipeline.failure;
    const idle = phase === "stopped" && !failure && !Object.values(pipeline.steps || {}).includes("failed");      // stopped with no failure word: nobody is running it
    return h("div", { class: "wb-video-pipeline", "data-key": "pipeline" },
      phase === "making" ? h("p", { class: "wb-card-note", role: "status", "data-key": "making", text: MAKING_WORDS }) : null,
      phase === "making" && state.stalled ? h("p", { class: "wb-card-note", role: "status", "data-key": "stalled", text: STALLED_WORDS }) : null,
      idle ? h("p", { class: "wb-card-note", role: "status", "data-key": "idle", text: IDLE_WORDS }) : null,
      h("ol", { class: "wb-video-steps", "data-key": "steps" }, stepRows(pipeline.steps).map((r) => h("li", { class: `wb-video-step is-${r.status}`, "data-step": r.step }, h("span", { text: r.label }), h("span", { class: "wb-card-hint", text: ` — ${r.word}` })))),
      failure ? notice(failureText(failure), "error", h("code", { class: "mono wb-video-code", text: ` ${failure.code}` })) : null,
      idle && loopback && can("prepare-again") && pipeline.next ? h("div", { class: "wb-card-actions" }, button(state.restarting ? "Starting..." : "Start again", "start-again", startAgain, { disabled: state.restarting, primary: true })) : null);
  }

  function hashLine(label, value) {
    return h("div", { class: "wb-video-hash" }, h("span", { class: "wb-card-hint", text: `${label} sha256` }), h("code", { class: "wb-hash", "data-key": `hash-${label.toLowerCase()}`, text: value }));
  }

  function approvalNode(card, phase) {
    if (phase !== "ready") return null;      // nothing is approved or downloaded while a video is made, a step stopped, or there is no render
    const approval = card.approval;
    const ready = Boolean(card.render && card.caption && loopback && state.media.state === "ready" && state.media.sha === card.render.sha256);
    const rows = [];
    if (approval && approval.state === "approved") {
      rows.push(h("p", { class: "wb-video-approved", role: "status" },
        `Approved ${approval.approved_at}${approval.approved_via ? ` from the ${approval.approved_via}` : ""}: this exact file (sha256 ${shortHash(approval.video_sha256)}) and this exact caption (sha256 ${shortHash(approval.caption_sha256)}) for ${approval.platform}.`));
      if (card.can_download && loopback) rows.push(h("div", { class: "wb-card-actions" }, button(state.busy === "download" ? "Downloading..." : `Download ${card.download_name}`, "download", download, { disabled: Boolean(state.busy), primary: true })));
      rows.push(h("p", { class: "wb-card-note wb-muted", text: "The download is for you to post by hand. It is the approved file, byte for byte; nothing is published or scheduled." }));
    } else {
      if (approval && approval.state === "stale") rows.push(notice(staleLine(approval), "warn"));
      rows.push(h("p", { class: "wb-card-note wb-muted", text: APPROVE_WORDS }));
      if (card.sent_back && card.sent_back.blocks_approval) {
        rows.push(h("p", { class: "wb-card-note", "data-key": "held-back", role: "status", text: SENT_BACK_WORDS }));
      } else if (loopback && can("video-approve")) {
        rows.push(h("div", { class: "wb-card-actions" }, button(state.busy === "approve" ? "Approving..." : "Approve this video and caption", "approve", approve, { disabled: !ready || Boolean(state.busy), primary: true })));
        if (card.render && loopback && state.media.state !== "ready" && state.media.state !== "failed") rows.push(h("p", { class: "wb-card-note wb-muted", text: "You can approve once the video has loaded." }));
      }
    }
    return h("div", { class: "wb-video-approval" }, rows);
  }

  let sendButton = null;       // the Send back button of the form that is on screen, so that its busy state is set without drawing the form again

  function sendBackNode(card, phase) {
    if (!loopback || !can("video-send-back") || !card.render || phase !== "ready") {
      sendButton = null;
      return null;
    }
    const area = textArea({ rows: "3", "aria-label": COMMENT_LABEL, "data-key": "comment", placeholder: "What should change?" });
    area.value = state.comment;
    area.addEventListener("input", () => { state.comment = area.value; });
    sendButton = button("Send back with a comment", "send-back", sendBack);
    return h("div", { class: "wb-video-back" },
      field(COMMENT_LABEL, area),
      h("div", { class: "wb-card-actions" }, sendButton));
  }

  // The card is drawn in parts. Each part has a signature of everything it shows; a part is drawn again only when its signature changed, so that a
  // read that changed nothing (a store change somewhere else) keeps the same `video` node (the position of the playback) and the same comment
  // box (what is typed in it and where the focus is).
  const PART_NAMES = ["picker", "notes", "pipeline", "media", "facts", "caption", "sentBack", "approval", "sendBack", "actions", "withheld"];
  const parts = {};
  let shape = null;       // "card" once the skeleton of the parts is on screen

  function skeleton() {
    parts.head = { node: h("div", { class: "wb-card-head wb-video-head" }), sig: null };
    for (const name of PART_NAMES) parts[name] = { node: h("div", { class: "wb-video-slot", "data-part": name }), sig: null };
    fill(el, parts.head.node, h("div", { class: "wb-card-content wb-video-content" }, PART_NAMES.map((name) => parts[name].node)));
    shape = "card";
  }

  function paint(name, signature, build) {
    const part = parts[name];
    const key = JSON.stringify(signature);
    if (part.sig === key) return;
    part.sig = key;
    fill(part.node, [build()].flat(Infinity));
  }

  /** Draw, and leave the scroll position of the panel where it was (dom.js keepScroll). */
  function draw() {
    keepScroll(el, drawNow);
  }

  function drawNow() {
    if (closed) return;
    const card = state.card;
    if (!card) {
      shape = null;
      sendButton = null;
      fill(el, h("div", { class: "wb-card-content" }, state.loading
        ? busyLine("Loading the video...")
        : [notice(state.error || "The video could not be read.", "error"), h("div", { class: "wb-card-actions" }, button("Try again", "reload", () => load()))]));
      return;
    }
    if (shape !== "card") skeleton();
    const phase = phaseOf(card, state.pipeline);
    const [word, tone] = stateOf(card, state.pipeline);
    const withheld = [];
    if (!can("video-approve")) withheld.push("video-approve");
    if (!can("video-send-back")) withheld.push("video-send-back");
    const media = state.media;
    const ready = Boolean(card.render && card.caption && loopback && media.state === "ready" && media.sha === card.render.sha256);
    const blocked = Boolean(card.sent_back && card.sent_back.blocks_approval);
    paint("head", [card.platform, word], () => [h("strong", { class: "wb-card-title", text: `Video for ${card.platform || "the post"}` }), chip(word, tone)]);
    paint("picker", [card.platforms, card.platform], () => (card.platforms.length > 1 ? h("div", { class: "wb-video-platforms", role: "group", "aria-label": "Platform" },
      card.platforms.map((name) => {
        const node = button(name, `platform-${name}`, () => { state.platform = name; state.card = null; releaseMedia(); load(); }, { primary: name === card.platform });
        node.setAttribute("aria-pressed", name === card.platform ? "true" : "false");
        return node;
      })) : null));
    paint("notes", [state.error, state.message, card.problems], () => [
      state.error ? notice(state.error, "error") : null,
      state.message ? h("p", { class: "wb-card-note", role: "status", text: state.message }) : null,
      card.problems.filter((line) => line !== "there is no render yet").map((line) => notice(line, "warn"))]);      // the card says "no render yet" once, in its own part
    paint("pipeline", [phase, state.pipeline && state.pipeline.steps, state.pipeline && state.pipeline.failure, state.stalled, state.restarting, can("prepare-again")], () => pipelineNode(phase));
    paint("media", [phase, card.render ? card.render.sha256 : null, loopback, media.sha, media.state, media.url, media.cover, media.error, state.pipeline && state.pipeline.steps && state.pipeline.steps.review], () => mediaNode(card, phase));
    paint("facts", [card.render], () => (card.render ? h("div", { class: "wb-video-facts" },
      h("p", { class: "wb-card-hint wb-video-line", text: factsLine(card.render) }), hashLine("Video", card.render.sha256)) : null));
    paint("caption", [card.caption], () => (card.caption ? h("div", { class: "wb-video-caption-box" },
      h("p", { class: "wb-video-heading", text: "Caption" }),
      // the caption is cut to a few lines with "Show the whole caption" (floor/reply.js): the panel is the only scroll, the card has no box that scrolls by itself
      replyView(h("pre", { class: "wb-pre wb-video-caption", "data-key": "caption", "aria-label": "The caption of the post", text: card.caption.text }),
        { whole: "Show the whole caption", lines: CAPTION_LINES, open: state.captionOpen, onToggle: (open) => { state.captionOpen = open; }, ...(env.measure ? { measure: env.measure } : {}) }).el,
      h("p", { class: "wb-card-hint wb-video-line", text: `${card.caption.chars} characters, from ${card.caption.post_file}` }),
      hashLine("Caption", card.caption.sha256)) : null));
    paint("sentBack", [card.sent_back], () => (card.sent_back ? h("p", { class: "wb-card-note", "data-key": "sent-back", text: `Sent back on ${card.sent_back.at}: ${card.sent_back.comment}` }) : null));
    paint("approval", [card.approval, card.can_download, card.download_name, Boolean(card.render), Boolean(card.caption), loopback, can("video-approve"), media.state, ready,
      state.busy === "approve" || state.busy === "download" ? state.busy : null, blocked, phase], () => approvalNode(card, phase));
    paint("sendBack", [Boolean(card.render), loopback, can("video-send-back"), phase], () => sendBackNode(card, phase));
    if (sendButton) {
      sendButton.textContent = state.busy === "send-back" ? "Sending..." : "Send back with a comment";
      if (state.busy) sendButton.setAttribute("disabled", "");
      else sendButton.removeAttribute("disabled");
    }
    paint("actions", 1, () => h("div", { class: "wb-card-actions" }, button("Check again", "reload", () => load({ quiet: true }))));
    paint("withheld", [withheld], () => withheldLine(withheld));
  }

  return {
    el,
    load,
    /** The card was left or its task closed: stop the downloads and revoke the URLs. */
    close() {
      closed = true;
      closing.abort();
      releaseMedia();
    },
    /** For a test: the state the last draw was made from. */
    snapshot() {
      return { card: state.card, media: { ...state.media }, busy: state.busy };
    },
  };
}
