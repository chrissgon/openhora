// What the page may do, read from the project entry it already holds: `GET /projects` answers, per project, `permissions`
// ({"channel": "page", "allowed": [...]}, or null while the configuration is not accepted). `allowed` is a list of operation names
// (`release`, `answer`, `reject`, `retry`, `go-ahead`, `say`, `request`, `route`, `hand-over`, `verdict`, the reads...) and of pairs for the two
// operations that depend on a second word: `approve:plan|acceptance|effect|go-ahead` and `set-mode:down|up`. This module only looks a word
// up in that list; the policy is the service's (runtime/operations.py), and a write the page still sends against it is refused there (409, the
// sentence), so what this file does is stop the page drawing a control that would only be refused. It has no network call and no DOM.
//
// A project entry without the key (an older service, a world made without the key) allows everything, as the page always did; `null` (the configuration is
// not accepted) allows everything too: every write already answers with the accept-config command. A key that is not understood (no list)
// is treated the same way: the page never hides a control because of a shape it does not know.

/**
 * Each write function of js/api.js and the operation it sends. A function in this map has controls on the page that ask `can` first
 * (floor/cards.js, cards/plan.js, cards/plan-waits.js, floor/task-actions.js, floor/agent-tab.js, views/lobby-composer.js, views/lobby.js,
 * views/lobby-request.js). A test ties this map and EXEMPT to the write functions of api.js, so a new one cannot be added without a decision.
 */
export const OPS = Object.freeze({
  answer: "answer",
  release: "release",
  approve: "approve",
  reject: "reject",
  request: "request",
  route: "route",
  retry: "retry",
  goAhead: "go-ahead",
  handOver: "hand-over",
  stageFile: "stage-file",
  flowSave: "flow-save",
  routineCreate: "routine-create",
  routineChange: "routine-change",
  routineApprove: "routine-approve",
  routineResume: "routine-resume",
  verdict: "verdict",
  say: "say",
  giveConsent: "give-consent",
});

/** The write functions of api.js that are never withheld, or that the page has no control for, each with its reason. */
export const EXEMPT = Object.freeze({
  cancel: "a brake: cancelling a request is never withheld from the page",
  routinePause: "a brake: pausing a routine is never withheld from the page",
  routineCancel: "a brake: cancelling a routine is never withheld from the page",
  setMode: "narrowing only, a brake: the page offers Stop agent and Supervise, a wider mode is a terminal command to copy",
  setModel: "the service decides: fixing a model needs the project's group set-mode; the consent that an autonomous agent needs is not given by this call (it has its own, giveConsent, and its own group, consent)",
  sync: "no control on the page",
  dispatch: "no control on the page",
});

/** Every plain name and pair that the controls ask about (the redraw key of a part is built from these). */
export const ASKED = Object.freeze([
  ["answer"], ["release"], ["reject"], ["retry"], ["go-ahead"], ["hand-over"], ["verdict"], ["say"], ["request"], ["route"], ["give-consent"],
  ["stage-file"], ["flow-save"], ["routine-create"], ["routine-change"], ["routine-approve"], ["routine-resume"],
  ["approve", "plan"], ["approve", "acceptance"], ["approve", "effect"], ["approve", "go-ahead"],
]);

/** The list the project entry holds, or null when the page decides nothing (no key, null, or a shape that is not a list). */
function listOf(project) {
  if (!project || typeof project !== "object") return null;
  const found = project.permissions;
  if (!found || typeof found !== "object" || !Array.isArray(found.allowed)) return null;
  return found.allowed;
}

/**
 * Whether the page may do `op` (with `kind` for approve: plan, acceptance, effect or go-ahead; for set-mode: down or up). `project` is the
 * entry of GET /projects. Without a kind, `approve` is allowed when any approve pair is.
 */
export function can(project, op, kind) {
  const list = listOf(project);
  if (list === null) return true;
  if (kind !== undefined && kind !== null) return list.includes(`${op}:${kind}`);
  if (op === "approve" || op === "set-mode") return list.some((name) => typeof name === "string" && name.startsWith(`${op}:`));
  return list.includes(op);
}

/** The word the line says for one asked operation: the operation's own name; a plan's go-ahead boxes say `go-ahead`. */
export function wordOf(op, kind) {
  return op === "approve" && kind === "go-ahead" ? "go-ahead" : op;
}

/**
 * The words that `can` refuses among `asked`, in the order asked and each once. An entry is a name ("retry"), a pair ("approve:plan") or
 * [op, kind]. The words are operation names, never button labels.
 */
export function withheld(project, asked) {
  const out = [];
  for (const entry of Array.isArray(asked) ? asked : []) {
    const [op, kind] = Array.isArray(entry) ? entry : String(entry).split(":");
    if (can(project, op, kind)) continue;
    const word = wordOf(op, kind);
    if (!out.includes(word)) out.push(word);
  }
  return out;
}

// The order the line names the operations in, whatever order a card drew its controls in.
const LINE_ORDER = Object.freeze(["approve", "reject", "answer", "release", "verdict", "hand-over", "retry", "go-ahead", "say", "request", "route", "give-consent"]);

/** The line a card or panel shows under its remaining controls when `words` is not empty: the words in a fixed order, each once. */
export function lineText(words) {
  const rank = (word) => (LINE_ORDER.includes(word) ? LINE_ORDER.indexOf(word) : LINE_ORDER.length);
  const sorted = [...new Set(words)].sort((a, b) => rank(a) - rank(b));
  return `Turned off for the page: ${sorted.join(", ")}. Use the terminal.`;
}

/** The getter a part reads at every draw: `env.can` when its environment has one, else everything is allowed (a test). */
export function reader(env) {
  return env && typeof env.can === "function" ? (op, kind) => Boolean(env.can(op, kind)) : () => true;
}

/** A string that changes when any answer of `canFn` changes: parts include it in what makes them draw again. */
export function fingerprint(canFn) {
  return ASKED.map(([op, kind]) => (canFn(op, kind) ? "1" : "0")).join("");
}
