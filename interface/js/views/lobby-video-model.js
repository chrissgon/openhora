// The Videos section of the Building (package V1c-1), the pure part: which posts the form offers, the state of a recording in plain words, the size of a
// recording and its limit, and the order of the list. The page decides nothing here: the operations (media-list, video-new, video-run) decide what a state
// allows and refuse the rest; this only chooses what to draw. No document, no network, no storage.

export const POST_PATH = /^docs\/marketing\/content\/[a-z0-9][a-z0-9.-]*\.md$/;      // the page's filter only: the operation decides (step_media._is_post)
export const MAX_BYTES = 1073741824;                                                  // = runtime/media.py MEDIA_MAX_BYTES
export const LIST_MAX = 10;

/** The `path` of every row of an `artifacts` answer that is a post, sorted; [] for anything else. */
export function postChoices(artifacts) {
  const rows = artifacts && Array.isArray(artifacts.artifacts) ? artifacts.artifacts : [];
  return rows.map((row) => (row && typeof row.path === "string" ? row.path : "")).filter((path) => POST_PATH.test(path)).sort();
}

export const STATE_TEXT = Object.freeze({
  none: "Not started.",
  ready: "Ready to run.",
  running: "Working: transcribing, cutting or rendering.",
  review: "Waiting for you: check the captions.",
  deliver: "Waiting for you: approve the delivery.",
  waiting: "Waiting for you.",
  done: "Delivered.",
  finished: "Ended without a delivery.",
  failed: "Failed.",
  cancelled: "Cancelled.",
  removed: "The recording was removed by the retention.",
  unknown: "Its state is unknown.",
});

/**
 * The state of one recording of the media list, the first rule that holds: delivered, removed, no task, ready, running, waiting (on the decision the task holds:
 * a delivery, a review or another), then the end of the task. `pendingRows` are the open decisions of the project (`status.pending`).
 */
export function stateOf(record, pendingRows) {
  const row = record || {};
  if (typeof row.delivered_at === "string") return "done";
  if (row.raw_kept === false) return "removed";
  if (row.task === null || row.task === undefined) return "none";
  if (row.task_state === "ready") return "ready";
  if (row.task_state === "running") return "running";
  if (row.task_state === "waiting") {
    const held = (Array.isArray(pendingRows) ? pendingRows : []).find((p) => p && p.task_id === row.task);
    if (held && held.kind === "effect") return "deliver";
    if (held && held.kind === "question") return "review";
    return "waiting";
  }
  if (row.task_state === "done") return "finished";
  if (row.task_state === "failed") return "failed";
  if (row.task_state === "cancelled") return "cancelled";
  return "unknown";
}

/** A size for a person: `812 bytes`, `3.5 KiB`, `12.0 MiB`, `1.2 GiB`. */
export function sizeWords(count) {
  const n = Number(count);
  if (!Number.isFinite(n) || n < 0) return "";
  if (n >= 1024 * 1024 * 1024) return `${(n / (1024 * 1024 * 1024)).toFixed(1)} GiB`;
  if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MiB`;
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KiB`;
  return `${n} bytes`;
}

/** The sentence for a file the page will not send, or null when its size is fine (more than nothing, at most MAX_BYTES). */
export function fileProblem(file) {
  const size = file ? Number(file.size) : NaN;
  if (!Number.isFinite(size) || size <= 0) return "The file is empty.";
  if (size > MAX_BYTES) return "A recording is at most 1 GiB.";
  return null;
}

/** The recordings newest first: a copy, reversed (the operation lists the oldest first). */
export function newestFirst(recordings) {
  return Array.isArray(recordings) ? [...recordings].reverse() : [];
}
