// Taking a recording in through the page: what the page knows before it sends a video, and the one call that sends it with a progress report.
// The control is the existing "Hand a file over" of the Agent tab (hand-file.js, agent-tab.js): a file that is a video (its type, or .mov, .mp4,
// .m4v) does not go as base64 in a JSON body; it goes to the media route (runtime/service.py, POST /projects/<id>/media) as its own bytes with
// a progress bar. Any other file, large or not, keeps the hand-over and its 25 MiB limit; when the project turns `media-in` off, a small video
// is handed over as a file and the page says why. That route answers on the loopback socket only, so on a page opened from a phone or over
// --lan the control says the video must be attached on the Mac. The service checks everything again (the type by the file's bytes, the size,
// the length). The review card routes no video here: a recording is not the output of a task, and no card binds one to its task yet.

import { h } from "../dom.js";
import { MAX_FILE_BYTES } from "./hand-file.js";

export const MEDIA_MAX_BYTES = 1024 * 1024 * 1024;       // runtime/media.py MEDIA_MAX_BYTES
export const MEDIA_MAX_SECONDS = 300;                    // runtime/media.py MAX_SECONDS: told to the person, checked by the service from the file
const VIDEO_NAME = /\.(mov|mp4|m4v)$/i;
const LOOPBACK = ["127.0.0.1", "localhost", "[::1]", "::1"];
export const MEDIA_HINT = "A video (a .mov or .mp4 up to 1 GiB and 5 minutes) is attached on the Mac that runs the service; any other file is at most 25 MiB.";
export const MEDIA_OFF = "Attaching a video is turned off for the page (media-in). Use the terminal: media-in.";
export const MEDIA_LABEL = "Upload the recording";
export const NOT_ON_THE_MAC = "A video is attached on the Mac that runs the service: open this page there, not from a phone or over the network.";

/** Whether the file is a video, by its type or its extension: the only kind that may go to the media route. */
export function isMediaFile(file) {
  if (!file) return false;
  const type = typeof file.type === "string" ? file.type : "";
  return type.startsWith("video/") || VIDEO_NAME.test(String(file.name || ""));
}

/** Whether the file goes to the media route now: a video, when the project allows `media-in` (`may`). With it off a small video is handed over as a file. */
export function usesMedia(file, may = true) {
  return isMediaFile(file) && Boolean(may);
}

/** The sentence added to a hand-over that carried a video because the media route is turned off for the page, or "". */
export function asFileNote(file, may = true) {
  return isMediaFile(file) && !may ? "It went as an ordinary file because attaching a video is turned off for the page (media-in)." : "";
}

/** Whether this page was opened on the machine that runs the service (the media route answers on the loopback socket only). */
export function onLoopback(hostname = globalThis.location && globalThis.location.hostname) {
  return LOOPBACK.includes(String(hostname || "").toLowerCase());
}

/** The refusal of a file for the media route that the page can know, or "" when it may be sent. */
export function mediaRefusal(file, { loopback = onLoopback() } = {}) {
  if (!loopback) return NOT_ON_THE_MAC;
  if (!Number.isFinite(Number(file.size)) || Number(file.size) <= 0) return "This file is empty.";
  if (Number(file.size) > MEDIA_MAX_BYTES) return "A recording is at most 1 GiB.";
  return "";      // the service shortens a long or odd file name: a label is never a reason to refuse
}

/** The words under the chooser: what a video needs, or that this page cannot take one. */
export function mediaHintText(loopback = onLoopback()) {
  return loopback ? MEDIA_HINT : NOT_ON_THE_MAC;
}

/**
 * The first thing the control checks when a file is chosen: a video by the media route's rules, any other file by the hand-over's (so a large
 * file that is not a video says "at most 25 MiB"). With `media-in` off (`may` false) a small video keeps the hand-over's rules and a large one
 * is refused with the reason.
 */
export function pickRefusal(file, refusalOfHandOver, { may = true, ...options } = {}) {
  if (!isMediaFile(file)) return refusalOfHandOver(file.name, file.size);
  if (may) return mediaRefusal(file, options);
  return Number(file.size) > MAX_FILE_BYTES ? MEDIA_OFF : refusalOfHandOver(file.name, file.size);
}

/** The progress bar: a native `progress` element (0 to 100), drawn once and moved between redraws; `set(sent, total)` moves it. */
export function progressBar() {
  const node = h("progress", { class: "wb-media-progress", max: "100", value: "0", "aria-label": "Upload progress" });
  return { node, set(sent, total) { node.value = total > 0 ? Math.min(100, Math.floor((sent / total) * 100)) : 0; } };
}

/** The line that tells what an upload stored. */
export function storedLine(result) {
  const mib = (Number(result.bytes) / (1024 * 1024)).toFixed(1);
  const seconds = result.facts && Number.isFinite(Number(result.facts.duration)) ? `, ${Number(result.facts.duration).toFixed(1)} s` : "";
  return `Recording stored: ${result.recording} (${mib} MiB${seconds}). It stays on this Mac until its post is done.`;
}

/**
 * Send a file to the media store through `api.uploadMedia` with a progress bar: `bar.set` is called as the bytes go. `recording` and `slot` (both
 * issued by code, never typed) bind it to a recording or to one of its asset slots. Resolves with the service's answer; rejects with the ApiError.
 */
export async function uploadRecording(api, project, file, { recording, slot, bar, signal } = {}) {
  if (typeof api.uploadMedia !== "function") throw new Error("the client has no media upload");
  return api.uploadMedia(project, file, { recording, slot, signal, onProgress: (sent, total) => { if (bar) bar.set(sent, total); } });
}
