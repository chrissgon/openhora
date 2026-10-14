// What "Edit this recording" needs and decides, with no DOM and no network (floor/media-start.js draws it): which stored recordings have not been started, which of the
// project's files are post files with a script, which network a post names, and the sentences of the refusals of `media-pipeline`. Nothing is guessed: with several
// post files the page asks, and a post that names no network leaves the network to the person.

export const POST_PATH = /^docs\/[A-Za-z0-9][A-Za-z0-9._/-]{0,200}\.md$/;       // runtime/media.py POST_PATH: what the service takes as a post file
export const NETWORK_LINE = /^- Network:\s*([a-z0-9][a-z0-9-]{0,31})\s*$/im;      // runtime/pipeline.py NETWORK_LINE
export const NETWORK_WORD = /^[a-z0-9][a-z0-9-]{0,31}$/;
export const POST_OWNER = "mkt-social-copy";                                       // the skill whose output a post file is (docs/marketing/content/<date>-<slug>.md)
export const POST_FOLDER = /^docs\/marketing\/content\/[^/]+\.md$/;                  // where that skill writes a post file
export const MAX_POST_READS = 20;                                                  // the post files read to see which carry a script, the newest first

/** Whether the text of a document has a script block, the block of a short video's beats. */
export function hasScript(text) {
  return typeof text === "string" && /^```script\s*$/m.test(text);
}

/** The network a post file's `- Network:` line names, or null. */
export function networkOf(text) {
  const found = typeof text === "string" ? NETWORK_LINE.exec(text) : null;
  return found ? found[1].toLowerCase() : null;
}

/** The post-path form of a path the person typed, or null when the service would not take it as a post file. */
export function postPath(text) {
  const path = String(text || "").trim();
  return POST_PATH.test(path) && !path.split("/").includes("..") && !path.includes("//") ? path : null;
}

/**
 * The files to read to find the post files: the Markdown documents the post-writing skill owns, newest first, at most MAX_POST_READS. The listing names an owner only for a file a
 * task produced, so a post file is also recognised by where that skill writes it (docs/marketing/content/<date>-<slug>.md, contracts/project-layout.md).
 */
export function postCandidates(artifacts) {
  return (Array.isArray(artifacts) ? artifacts : [])
    .filter((a) => a && typeof a.path === "string" && postPath(a.path) && (a.owner === POST_OWNER || POST_FOLDER.test(a.path)) && (a.kind === undefined || a.kind === "markdown" || a.kind === "text"))
    .sort((a, b) => String(b.modified_at || "").localeCompare(String(a.modified_at || "")) || b.path.localeCompare(a.path))
    .slice(0, MAX_POST_READS);
}

/** The recordings of a `media-list` answer that are stored and not started: a raw file, still open, no pipeline. [{id, bytes, duration, name, at}] */
export function waitingRecordings(list) {
  return (Array.isArray(list) ? list : [])
    .filter((r) => r && typeof r.id === "string" && r.raw && r.status === "open" && !r.pipeline && !r.purged_raw)
    .map((r) => ({ id: r.id, bytes: Number(r.raw.bytes) || 0, duration: Number.isFinite(Number(r.raw.duration)) ? Number(r.raw.duration) : null, name: typeof r.raw.name === "string" ? r.raw.name : "", at: r.created_at || "" }))
    .sort((a, b) => String(b.at).localeCompare(String(a.at)));
}

/** The recording as a line: "Recording 4a16f80a, 32.0 s, 3.4 MB". */
export function recordingLine(r) {
  const size = r.bytes ? `${(r.bytes / (1024 * 1024)).toFixed(1)} MiB` : "";
  return ["Recording " + r.id.slice(0, 8), r.duration !== null ? `${r.duration.toFixed(1)} s` : "", size].filter(Boolean).join(", ");
}

/**
 * The closed sentences of the refusals `media-pipeline` gives as plain text (runtime/ops_pipeline.py), matched by their own words, else the service's sentence as it came. The
 * codes a step stops with are told by captions-model.failureText.
 */
export const REFUSALS = Object.freeze([
  [/has no file yet/, "This recording has no file yet: upload it first."],
  [/the post file has no `- Network:` line/, "The post file names no network: type the network (for example instagram)."],
  [/has no post file for/, "That network has no post file for this recording: choose the post file."],
  [/several post files|the recording has no post file/, "Choose the post file this recording is for."],
  [/a post file is a Markdown file/, "A post file is a Markdown file under docs/ of the project."],
  [/was cancelled/, "The request this recording belonged to was cancelled: its pipeline stopped with it."],
  [/already being run/, "The pipeline of this recording is being run by another process: wait for it to end."],
  [/was started for/, "This recording's pipeline was started for another post file: change that post file's text and open the captions again, or start another recording."],
]);

/** The sentence a refused start is shown with. */
export function refusalText(error) {
  const message = error && typeof error.message === "string" ? error.message : "";
  const known = REFUSALS.find(([pattern]) => pattern.test(message));
  if (known) return known[1];
  if (error && error.name === "ApiError" && error.status === 0) return "The service could not be reached. Is it still running?";
  if (error && error.name === "ApiError" && error.status === 404) return "This page cannot start the pipeline from here: it runs on the Mac that runs the service.";
  return message || "The pipeline could not be started.";
}
