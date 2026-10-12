// Small helpers the demo world shares: copies, rows filled from a fixture's template, the hash of an exact content, the refusal shape.

export const clone = (value) => JSON.parse(JSON.stringify(value));

/** A refusal the service would give: its status, its word, its sentence and, for the 412, the command that gets past it. */
export class Refusal extends Error {
  constructor(status, word, message, next = null) {
    super(message);
    this.status = status;
    this.word = word;
    this.next = next;
  }
}

export const usage = (message) => new Refusal(400, "usage", message);
export const refused = (message) => new Refusal(409, "refused", message);
export const notFound = (message) => new Refusal(404, "not_found", message);
/** What the demo does not do: the service's own 409 "refused" with a sentence that says so. */
export const notInDemo = (what) => refused(`${what} is not part of the demo: nothing runs here, and nothing leaves this page.`);

/**
 * A copy of a fixture's row with some fields replaced. A field the fixture's row does not have is an error: the world gives the page
 * the keys the operations give, no more, so a typo or an invented field fails in the tests instead of in the page.
 */
export function fill(template, fields = {}) {
  const row = clone(template);
  for (const [key, value] of Object.entries(fields)) {
    if (!(key in row)) throw new Error(`the fixture has no field ${key}`);
    row[key] = value;
  }
  return row;
}

/** JSON with sorted keys and no spaces: what a plan's hash is taken over (runtime/plan.py plan_hash). */
export function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.keys(value).sort().map((k) => `${JSON.stringify(k)}:${canonical(value[k])}`).join(",")}}`;
  return JSON.stringify(value);
}

/** The sha256 of a text, in hexadecimal, computed with the browser's own crypto (Node has the same). */
export async function sha256Hex(text) {
  const subtle = globalThis.crypto && globalThis.crypto.subtle;
  if (!subtle) throw new Refusal(500, "internal", "This page needs a secure context (https or localhost) to compute a hash.");
  const bytes = await subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(bytes), (b) => b.toString(16).padStart(2, "0")).join("");
}

/** The five modes of an agent, narrowest first (runtime/autonomy.py MODES). */
export const MODES = ["stopped", "supervised", "milestones", "autonomous", "autonomous-with-policy"];
