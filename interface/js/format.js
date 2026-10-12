// Display words and numbers: pure functions with no document, so they run under a test.

export const KIND_WORDS = Object.freeze({
  plan: "Plan", question: "Question", review: "Review", effect: "Effect", acceptance: "Acceptance", your_document: "Your document",
});

/** The word a decision kind is shown with; an unknown kind is shown as it came. */
export function kindWord(kind) {
  return KIND_WORDS[kind] || (typeof kind === "string" && kind ? kind : "Decision");
}

/** "marketing" -> "Marketing": the display form of an agent's name (the planning agent is the Lobby). */
export function agentWord(name) {
  if (!name || name === "planning") return "Lobby";
  return name.charAt(0).toUpperCase() + name.slice(1);
}

/** "$3.82": a dollar amount with two decimals; a value that is not a number is "$0.00". */
export function dollars(value) {
  const n = typeof value === "number" && Number.isFinite(value) ? value : 0;
  return "$" + n.toFixed(2);
}

/** A number for a count; a value that is not a finite number is 0. */
export function count(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

/** The share of `used` in `cap` between 0 and 1 for a meter; 0 when the cap is not a positive number. */
export function share(used, cap) {
  const c = count(cap);
  return c > 0 ? Math.max(0, Math.min(1, count(used) / c)) : 0;
}

/** The age of a stamp as "now", "12 min", "5 h" or "2 d"; the stamp is ISO text, `now` a Date. Unknown is "". */
export function age(stamp, now) {
  const then = Date.parse(typeof stamp === "string" ? stamp : "");
  if (!Number.isFinite(then)) return "";
  const seconds = Math.max(0, Math.floor((now.getTime() - then) / 1000));
  if (seconds < 60) return "now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h`;
  return `${Math.floor(seconds / 86400)} d`;
}

/** An age (from `age`) as a phrase: "just now" for "now", else "12 min ago"; an unknown age is "". The one place that words an age with "ago". */
export function agoPhrase(short) {
  if (!short) return "";
  return short === "now" ? "just now" : `${short} ago`;
}

/** How long a task has run, from the start of its last run: "for 12 min", "for 5 h", "for 2 d", "for under a minute"; "" when the stamp is unknown (R-8: how long, not since when). */
export function runningFor(stamp, now) {
  const short = age(stamp, now);
  if (!short) return "";
  return short === "now" ? "for under a minute" : `for ${short}`;
}

/** The age spelled for a screen reader: "2 days", "5 hours", "12 minutes". */
export function ageWords(stamp, now) {
  const short = age(stamp, now);
  if (!short) return "";
  if (short === "now") return "just now";
  const [n, unit] = short.split(" ");
  const word = { min: "minute", h: "hour", d: "day" }[unit];
  return `${n} ${word}${n === "1" ? "" : "s"}`;
}

/** "14:02" in the browser's time zone for an ISO stamp, or "". */
export function clock(stamp) {
  const when = new Date(typeof stamp === "string" ? stamp : "");
  if (!Number.isFinite(when.getTime())) return "";
  return `${String(when.getHours()).padStart(2, "0")}:${String(when.getMinutes()).padStart(2, "0")}`;
}

/** "1 decision" / "5 decisions". */
export function decisions(n) {
  return `${n} decision${n === 1 ? "" : "s"}`;
}

/**
 * The day's metered spend in words, both numbers labelled: "$0.14 recorded · up to $1.50 reserved" (the reserved part only when
 * something is reserved for a run whose cost is not recorded yet), "$0.14 recorded", or "" when both are zero.
 */
export function spendNote(recorded, reserved) {
  const r = count(recorded);
  const q = count(reserved);
  if (q > 0) return `${dollars(r)} recorded · up to ${dollars(q)} reserved`;
  return r > 0 ? `${dollars(r)} recorded` : "";
}

/**
 * The note under a spend meter: the labelled numbers, and "(+n of unknown cost)" when runs of unknown cost exist that nothing is reserved
 * for (when something is reserved the reservation already says so).
 */
export function costNote(spendWords, reserved, unknown) {
  const missing = count(unknown) > 0 && !(count(reserved) > 0) ? `(+${count(unknown)} of unknown cost)` : "";
  return [spendWords, missing].filter(Boolean).join(" ");
}

// The words of the two caps (A-20, A-38), and the sentence that says what each one counts: a cap follows the billing of the credential a run
// used, not the model's tier. The runs cap counts runs on a subscription or free credential, the dollar cap the spend of runs on a metered
// one (an API key), so the two never read as one.
export const METER_WORDS = Object.freeze({ runs: "Runs today", spend: "Spend today" });
export const METER_TIPS = Object.freeze({
  runs: "Counted against the cap of runs per day: runs on a subscription or free credential.",
  spend: "Counted against the cap of dollars per day: runs on a metered credential (an API key); a run whose cost is not recorded yet counts at the per-run limit.",
});
/**
 * Which of the two meters mean something for a project: {runs, spend}. The service says it per agent (`caps_in_use` of the `agents` read: whether
 * the project's credentials, or a run of today, have that billing). Only an explicit false hides a meter; an entry without it (an older service)
 * shows both.
 */
export function metersInUse(source) {
  const use = source && typeof source === "object" && source.caps_in_use && typeof source.caps_in_use === "object" ? source.caps_in_use : {};
  return { runs: use.runs !== false, spend: use.spend !== false };
}
