// The delivery of a new video on the page (package V1c-1), the pure part: whether this page is the computer's own (a loopback host) and the rows of a deliver
// decision. The loopback test fails closed (an empty, missing or unknown host is not loopback) and is a courtesy, never the rule: the service refuses the upload,
// the still, the download and the approval of a delivery on the local network (limits L67 and L68), so a page that drew them anyway would only be refused. The
// rows are the lines of the delivery document as the decision's body holds them, one English line each; the page keeps no copy of the phrase table. No document,
// no network, no storage.

export const LOOPBACK_HOSTS = Object.freeze(["127.0.0.1", "localhost", "[::1]", "::1"]);
export const LAN_MEDIA = "A recording, its still and the video are sent only through this computer's own page (127.0.0.1).";
export const LAN_APPROVE = "Approve the delivery on this computer's own page (127.0.0.1): a video is never approved over the local network.";

/** True only when `host` is exactly one of the loopback names; "", null, undefined and anything else are false. */
export function onLoopback(host) {
  return typeof host === "string" && LOOPBACK_HOSTS.includes(host);
}

/** The host of the page now, as a string, or "" when there is no location or reading it throws. */
export function hostNow() {
  try {
    const found = globalThis.location && globalThis.location.hostname;
    return typeof found === "string" ? found : "";
  } catch (e) {
    return "";
  }
}

/** The host a part asks about: `env.host()` when its environment has one (a test), else the page's own. */
export function hostOf(env) {
  return env && typeof env.host === "function" ? String(env.host() || "") : hostNow();
}

/** Whether a decision is the approval of a delivery: an effect whose word is `deliver`. */
export function isDeliver(item) {
  return Boolean(item) && item.kind === "effect" && item.effect_word === "deliver";
}

/** The lines of the delivery document as the body holds them, without the empty ones. */
export function deliverRows(body) {
  return String(body || "").split("\n").filter((line) => line !== "");
}
