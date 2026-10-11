// The autopilot: the story the demo plays, as data, and the small engine that plays it. The story is the website's tour storyboard
// (nine steps, about 57 seconds): the City, the Lobby, the plan, the Building, a Floor at work, a review, an effect with its hash, the
// request accepted and the Control room. Each step names the route to show, how long it lasts, the changes it makes to the world (what the
// runtime would have done by then) and, in `at`, what happens inside it at a time (in milliseconds from its start): a change of the world
// (`op`), or the autopilot doing what a person does on the page (`ui`), with the change that stands in for it if the page could not
// (`op`, applied a moment later; it does nothing when the page's own write already made the change).
// A caption is a key only: the page that embeds the demo shows the words.
//
// The engine takes everything it touches (the world, the route, the page, the timers, the messages out) so that it runs headless.

import { STORY_PROJECT } from "./world-story.js";

const P = STORY_PROJECT;
const REQUEST = 4;        // the number the story's request gets when the visitor has made none: the plan step looks it up by its title, and falls back to this
const lobby = `#/p/${P}/lobby/conversation`;
const CONFIRM_MS = 900;   // how long the page gets to make a change itself before the autopilot makes it

export const STEPS = Object.freeze([
  { id: "city", seconds: 6, caption: "tour.city", route: "#/city", at: [] },
  {
    id: "lobby", seconds: 6, caption: "tour.lobby", route: lobby,
    at: [
      { t: 1000, ui: [{ do: "type", selector: "#wb-say", text: "/" }] },
      { t: 3400, ui: [{ do: "type", selector: "#wb-say", text: "Spring sale page" }, { do: "submit", selector: "form.wb-composer" }], op: "type-request" },
    ],
  },
  {
    id: "plan", seconds: 7, caption: "tour.plan", route: `${lobby}/request/{request}`,
    at: [
      { t: 0, op: "open-plan" },
      { t: 4800, ui: [{ do: "click", selector: "button.wb-card-button", label: "Approve this plan" }], op: "approve-plan" },
    ],
  },
  { id: "building", seconds: 6, caption: "tour.building", route: `#/p/${P}`, at: [] },
  { id: "floor", seconds: 6, caption: "tour.floor", route: `#/p/${P}/floor/engineering/agent`, at: [] },
  { id: "review", seconds: 6, caption: "tour.review", route: `#/p/${P}/floor/engineering/inbox`, at: [{ t: 0, op: "finish-build" }] },
  {
    id: "effect", seconds: 8, caption: "tour.effect", route: `#/p/${P}/floor/marketing/inbox`,
    at: [
      { t: 0, op: "release-build" },
      { t: 600, op: "open-effect" },
      { t: 6200, ui: [{ do: "click", selector: "button.wb-card-button", label: "Approve this exact content" }], op: "approve-effect" },
    ],
  },
  {
    id: "request-done", seconds: 6, caption: "tour.request-done", route: `#/p/${P}/lobby/inbox`,
    at: [{ t: 3200, ui: [{ do: "click", selector: "button.wb-card-button", label: "Accept" }], op: "approve-acceptance" }],
  },
  { id: "control-room", seconds: 6, caption: "tour.control-room", route: `#/p/${P}/control/skills`, at: [] },
]);

export const TOTAL_SECONDS = STEPS.reduce((sum, s) => sum + s.seconds, 0);

/**
 * The autopilot. deps: {world (apply, reset), setRoute(hash), perform(action) -> boolean|Promise (the page: null headless), schedule(fn, ms) -> id,
 * cancel(id), post(message), reduced (prefers-reduced-motion: the story does not advance by itself: `play` shows the next step at once, `goto` the
 * step named), steps}. Returns {play, pause, replay, goto, status, index}. A message out is {type: "step" | "ended", step, id, caption}.
 */
export function createAutopilot({ world, setRoute, perform = null, schedule, cancel, post = () => {}, reduced = false, steps = STEPS }) {
  let index = -1;
  let status = "idle";          // idle | playing | paused | ended
  let timers = [];
  let epoch = 0;                // a timer of an earlier step or a paused story finds the epoch moved and does nothing

  const clear = () => {
    for (const id of timers) cancel(id);
    timers = [];
    epoch += 1;
  };
  const later = (fn, ms, at = epoch) => {
    timers.push(schedule(() => { if (at === epoch) fn(); }, ms));
  };
  /** The route of a step: `{request}` is the number of the story's request in the world as it stands (a visitor's own request may hold #4). */
  const routeOf = async (route) => {
    if (!route.includes("{request}")) return route;
    const id = typeof world.storyRequest === "function" ? await world.storyRequest() : null;
    return route.replace("{request}", String(id === null || id === undefined ? REQUEST : id));
  };
  const apply = (entry) => world.apply({ op: entry.op, project: entry.project });

  async function runEntry(entry) {
    const mine = epoch;
    const acted = entry.ui && perform ? await Promise.all(entry.ui.map((action) => perform(action))) : [];
    if (mine !== epoch) return;
    if (entry.op) {
      if (acted.length) later(() => apply(entry), CONFIRM_MS);
      else await apply(entry);
    }
  }

  /** Every change of the steps before `upTo`, and of `upTo` itself when `through`, at once and in order. */
  async function catchUp(upTo, through) {
    for (let i = 0; i < upTo + (through ? 1 : 0); i += 1) {
      for (const entry of steps[i].at) if (entry.op) await apply(entry);
    }
  }

  async function enter(i) {
    clear();
    index = i;
    status = "playing";
    const step = steps[i];
    const mine = epoch;
    post({ type: "step", step: i, id: step.id, caption: step.caption });
    for (const entry of step.at) {
      if (mine !== epoch) return;      // paused, taken over or moved while a change was made: nothing of this step is scheduled
      if (entry.t === 0) await runEntry(entry);
      else later(() => { runEntry(entry); }, entry.t, mine);
    }
    if (mine !== epoch) return;
    const route = await routeOf(step.route);
    if (mine !== epoch) return;
    setRoute(route);
    later(() => next(), step.seconds * 1000, mine);
  }

  async function next() {
    if (index + 1 >= steps.length) {
      clear();
      status = "ended";
      post({ type: "ended", step: index, id: steps[index].id, caption: steps[index].caption });
      return;
    }
    await enter(index + 1);
  }

  /** The step shown at once, with nothing timed: reduced motion, and `goto` under it. */
  async function show(i) {
    clear();
    index = i;
    status = i + 1 >= steps.length ? "ended" : "paused";
    await catchUp(i, true);
    setRoute(await routeOf(steps[i].route));
    post({ type: "step", step: i, id: steps[i].id, caption: steps[i].caption });
    if (i + 1 >= steps.length) post({ type: "ended", step: i, id: steps[i].id, caption: steps[i].caption });
  }

  return {
    get index() { return index; },
    get status() { return status; },
    /** Start, or go on: from the first step; from the step it paused in (its timeline again); under reduced motion, the next step at once. */
    async play() {
      if (reduced) {
        if (status === "ended") return replayNow();
        return show(Math.min(index + 1, steps.length - 1));
      }
      if (status === "ended") return replayNow();
      return enter(Math.max(index, 0));
    },
    pause() {
      if (status !== "playing") return;
      clear();
      status = "paused";
    },
    /** Take over: the autopilot stops where it is. Returns whether it was playing. */
    takeOver() {
      const was = status === "playing";
      clear();
      if (was) status = "paused";
      return was;
    },
    async replay() {
      return replayNow();
    },
    /** The world as it is after step `i`'s start, then the step plays on (under reduced motion it stops there). */
    async goto(i) {
      const target = Math.max(0, Math.min(Number(i) || 0, steps.length - 1));
      clear();
      await world.reset();
      setRoute("#/city");
      if (reduced) return show(target);
      await catchUp(target, false);
      return enter(target);
    },
  };

  async function replayNow() {
    clear();
    await world.reset();
    index = -1;
    setRoute("#/city");
    if (reduced) {
      status = "idle";
      return show(0);
    }
    return enter(0);
  }
}
