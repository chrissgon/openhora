// The Floor's Agent tab (handoff floor.md): the agent's state row, the mode plate with "Stop agent" and "Supervise" (A-17: a narrowing
// the runtime accepts at once; a wider mode is the terminal's), the result notice with the exact command the service gave (A-18, the
// terminal-command component), three meters that say what they count (A-20), the current task with its runs and, when the dispatcher
// held it, why (A-10), the other tasks, and "Hand a file over". The current task and the other tasks carry the actions of a Tasks-tab row
// (task-actions.js, A-32: Retry on a failed or blocked task with the sentence the runtime stored beside it, "Open in the Inbox" on a waiting
// one, "Go ahead" and "Drop the after" on a task that waits for another). Each control sends exactly one request: `setMode` with the
// word of the button, `retry` with no body, `goAhead`, `handOver` with the file as the person chose it. The page decides nothing: the mode's words
// and its line are constants of one table, every other value is what an operation returned. The tab is built once and its
// parts are drawn again only when their data changed, so a poll never takes the keyboard focus or the typed choice away.

import { fill, h } from "../dom.js";
import * as router from "../router.js";
import { MODES, MODE_LINES, currentSub, meters, stateRow, stateTone, taskWord } from "../floor-model.js";
import { commandBlock, copyCommand, isCommand, selectNode } from "../frame/command.js";
import { icon } from "../frame/icons.js";
import { trackNode } from "../scene/plates.js";
import { runsSection } from "./run-block.js";
import { fileRefusal, handChooser, handOverStep, toBase64 } from "./hand-file.js";
import { MEDIA_LABEL, isMediaFile, mediaHintText, pickRefusal, progressBar, storedLine, uploadRecording } from "./media-upload.js";
import { createTaskActions } from "./task-actions.js";
import { busyLine, chip, errorText, notice, ring, withheldLine } from "./widgets.js";
import { reader } from "../permissions.js";
import { waitLines } from "../waits.js";

export { MAX_FILE_BYTES, fileRefusal, toBase64 } from "./hand-file.js";
export const STANDING = "Stop agent and Supervise take effect at once and need no acceptance.";
export const WIDER = "A wider mode is set in the terminal, not on this page.";
export const WIDER_BELOW_NOTE = "Run this command in the terminal: it sets the mode and accepts it.";     // A-62, M-21: one step; the command the service sends sets the mode and accepts it
export const WAITING_NOTE = "The new mode takes effect once the configuration is accepted. Run this command in the terminal.";
export const WAITING_NOTE_NO_COMMAND = "The new mode takes effect once the configuration is accepted in the terminal.";     // the refusal gave no command: nothing for "this command" to point at
export const NOT_ACCEPTED_RESULT = "Accept the configuration in the terminal (the step below).";
// What the command of a held reason does, in the page's words (the command itself is the service's, verbatim): the service that dispatches nothing gives `run-next`
const HELD_COMMAND_LABEL = Object.freeze({ "dispatch off": "Run the next task from the terminal" });
export const BRING_BACK = "To bring it back, choose supervised below and run its command in the terminal.";

/** Keep the keyboard focus on the control with the same `data-key` after a part is drawn again. */
function redraw(container, render) {
  const active = document.activeElement;
  const key = active && container.contains(active) && active.getAttribute ? active.getAttribute("data-key") : null;
  render();
  if (!key || !container.querySelectorAll) return;
  const next = [...container.querySelectorAll("[data-key]")].find((n) => n.getAttribute("data-key") === key);
  if (next && next.focus) next.focus({ preventScroll: true });
}

/**
 * Create the Agent tab. env: {project, agent, api: {setMode, retry, goAhead, handOver}, refresh(), now(), links: {inbox(pendingId)} (optional), task(id) (optional: the task's body, for the file-drop line),
 * can(op, kind) (optional: whether the page may do an operation, js/permissions.js, read at every draw; all allowed when left out)}. Returns {el, update(view),
 * focusSelect()}; view is floor-model.floor(...) (found, notAccepted or loading). "Stop agent" and "Supervise" only narrow the mode, a brake that the policy never withholds
 * (setMode is exempt, js/permissions.js); "Hand a file over" is `hand-over` and Retry, "Go ahead" and "Drop the after" are drawn by task-actions.js under their own operations.
 */
export function createAgentTab(env) {
  const can = reader(env);
  const el = h("div", { class: "wb-agent-tab" });
  const stateBox = h("div", { class: "wb-state-box", role: "status" });
  const plateBox = h("div", { class: "wb-mode-row" });
  const formBox = h("div", { class: "wb-mode-form" });
  const standing = h("p", { class: "wb-notice-card", text: STANDING });
  const resultBox = h("div", { class: "wb-result-box" });
  const runsTotalLine = h("p", { class: "wb-runs-total wb-muted", hidden: true, text: "" });
  const waitingLine = h("p", { class: "wb-empty-line", text: "Waiting for the configuration to be accepted." });
  const metersBox = h("div", { class: "wb-meters" });
  const currentBox = h("div", { class: "wb-section" });
  const othersBox = h("div", { class: "wb-section" });
  const handBox = h("div", { class: "wb-hand" });
  const handLine = h("div");      // the line under the hand-over when the policy withholds it
  const body = h("div", { class: "wb-agent-body" }, waitingLine, metersBox, runsTotalLine, currentBox, othersBox, handBox);
  const widerBox = h("div", { class: "wb-wider-modes" });
  fill(el, stateBox, plateBox, formBox, standing, resultBox, widerBox, body);

  const shown = {};
  const earlierOpen = new Set();     // the current task's "Earlier attempts" disclosure, open by the person's choice (A-72)
  const swap = (name, value, draw) => {
    const key = JSON.stringify(value);
    if (shown[name] === key) return;
    shown[name] = key;
    draw();
  };

  // --- Stop agent and Supervise -------------------------------------------------------------------------------------------------
  const stopButton = h("button", { class: "pui-btn pui-theme pui-outline wb-set-mode", type: "button", "data-key": "stop-agent", text: "Stop agent" });
  const superviseButton = h("button", { class: "pui-btn pui-theme pui-outline wb-set-mode", type: "button", "data-key": "supervise", text: "Supervise" });
  const formError = h("div", { class: "wb-form-error" });
  let setting = null;          // the word being sent, or null
  let modeResult = null;       // {mode, accepted, next}
  let sawUnaccepted = false;
  let locked = false;          // the configuration is not accepted: the buttons do nothing
  let currentMode = null;
  fill(formBox, h("div", { class: "wb-mode-controls" }, stopButton, superviseButton), formError);
  const LABELS = new Map([[stopButton, "Stop agent"], [superviseButton, "Supervise"]]);

  /** A button is off when the agent is already in that mode or a narrower one (the runtime accepts only a narrowing), while one is being sent, and while the configuration is not accepted. */
  function drawButtons() {
    const at = MODES.indexOf(currentMode);
    const off = (word) => setting !== null || locked || at < 0 || at <= MODES.indexOf(word);
    stopButton.disabled = off("stopped");
    superviseButton.disabled = off("supervised");
  }

  async function send(word, button) {
    if (setting !== null) return;
    setting = word;
    drawButtons();
    fill(button, ring(true), "Setting...");
    button.setAttribute("aria-busy", "true");
    fill(formError);
    try {
      const result = await env.api.setMode(env.project, env.agent, word);
      modeResult = { mode: result.mode, accepted: result.accepted !== false, next: result.next || null };
      drawResult();
      env.refresh();
    } catch (e) {
      fill(formError, notice(errorText(e), "error"));
    }
    setting = null;
    button.removeAttribute("aria-busy");
    fill(button, LABELS.get(button));
    drawButtons();
  }
  stopButton.addEventListener("click", () => send("stopped", stopButton));
  superviseButton.addEventListener("click", () => send("supervised", superviseButton));

  function drawResult() {
    if (!modeResult) {
      fill(resultBox);
      return;
    }
    if (modeResult.accepted) {
      fill(resultBox, h("div", { class: "notice pui-soft pui-success wb-notice-card", role: "status" }, h("strong", { text: `Mode set to ${modeResult.mode}.` })));
      return;
    }
    // A-62: the accept command is shown once, in the step the tab draws while the configuration waits (the refusal's own command); the result only points at it
    fill(resultBox, h("div", { class: "notice pui-soft pui-warn wb-notice-card is-warn", role: "status" },
      h("strong", { text: `Mode set to ${modeResult.mode}. Nothing works on this page until you accept the new configuration. ${NOT_ACCEPTED_RESULT}` })));
  }

  function drawPlate(agent, waiting = false) {
    if (!agent || !agent.mode) {
      fill(plateBox);
      return;
    }
    const plate = h("span", { class: "pui-chip pui-muted pui-outline pui-rounded-full wb-mode-plate", text: agent.mode });
    const acting = agent.acting_mode && agent.acting_mode !== agent.mode
      ? h("span", { class: "pui-chip pui-muted pui-outline pui-rounded-full wb-mode-plate wb-acting-plate", text: `acting as ${agent.acting_mode}` }) : null;
    // A-62: a stopped agent's line says how to bring it back (not while the configuration waits for acceptance: that step comes first)
    const back = agent.mode === "stopped" && !waiting ? ` ${BRING_BACK}` : "";
    fill(plateBox, plate, acting, h("span", { class: "wb-muted wb-mode-line", text: `${MODE_LINES[agent.mode] || ""}.${back}` }));
  }

  // --- the other parts -----------------------------------------------------------------------------------------------------------
  function drawState(row, view) {
    if (!row) {
      fill(stateBox, busyLine("Loading the floor..."));
      return;
    }
    const content = [chip(row.chip, row.tone), h("span", { class: "wb-muted wb-state-line", text: row.line })];
    fill(stateBox, h("div", { class: "wb-state-row" }, content));
  }

  function meterCell(label, text, share, full, note, tip, reserved = 0) {
    return h("div", { class: "wb-meter-cell", role: "group", "aria-label": `${label} ${text}`, title: tip || null },
      h("span", { class: "wb-muted wb-meter-label", text: label }), h("strong", { class: "wb-meter-value", text }),
      share !== null ? trackNode(share, full, reserved, "wb-meter-track") : null,
      note ? h("span", { class: "wb-note wb-muted", text: note }) : null);
  }

  function drawMeters(m) {
    fill(metersBox, m.runs ? meterCell(m.runs.label, m.runs.text, m.runs.share, m.runs.full, "", m.runs.tip) : null,
      m.spend ? meterCell(m.spend.label, m.spend.text, m.spend.recordedShare, m.spend.full, m.spend.notes, m.spend.tip, m.spend.reservedShare) : null,
      meterCell("Queued", m.queued.text, null, false));
    runsTotalLine.hidden = !m.runsTotal;      // the plain total of runs today, whatever their billing (the runs meter counts only subscription and free runs)
    runsTotalLine.textContent = m.runsTotal || "";
  }

  /**
   * The held reason: its sentence and what the service gave to get past it. The credential's commands are the fields `commands` ([{name, command}],
   * `command` null when no username is registered), each with its Copy; `next` is the sentence (text) or, for the reasons that give one, a command.
   */
  function heldBlock(held) {
    const commands = Array.isArray(held.commands) ? held.commands : [];
    const sentence = held.next && !isCommand(held.next) ? h("p", { class: "wb-held-detail wb-muted", text: held.next }) : null;
    const single = !commands.length && held.next && isCommand(held.next) ? commandBlock({ command: held.next, sentence: HELD_COMMAND_LABEL[held.reason] }) : null;     // F2-D7: floor.html labels the held command
    return h("div", { class: "wb-held" }, h("p", { class: "wb-held-line", text: `Held: ${held.sentence}` }), sentence,
      commands.map((c) => (c.command ? commandBlock({ command: c.command, sentence: c.name }) : h("p", { class: "wb-held-detail wb-muted", text: `${c.name}: no username registered` }))),
      single);
  }

  /** The warn notice that says a wider mode is the terminal's (R-35): the soft style in the warn colour, with an icon. */
  const widerNote = (text) => h("p", { class: "notice pui-soft pui-warn wb-wider-note", role: "note" }, icon("triangle-alert", 16), h("span", { text }));

  /**
   * R-35: `Mode` over a select of the wider modes, `Copy` beside it, the chosen mode's command under them, and under the command the soft warn notice. The select
   * chooses, the command follows it, Copy copies what the select holds (the service's own command, verbatim). The person's choice survives a draw that changes nothing.
   */
  let widerEmpty = false;
  function drawWider(wider, waiting = null) {
    const list = Array.isArray(wider) ? wider : null;
    if (waiting) {      // A-62: the configuration waits for acceptance: that step, with its command and Copy, in place of the mode select; no other set-mode is offered
      widerEmpty = false;
      fill(widerBox, h("div", { class: "wb-wider-box wb-accept-step" }, h("p", { class: "wb-card-line", text: waiting.command ? WAITING_NOTE : WAITING_NOTE_NO_COMMAND }), waiting.command ? commandBlock({ command: waiting.command }) : null));
      return;
    }
    widerEmpty = Boolean(list) && list.length === 0;     // nothing is wider than the widest mode
    if (widerEmpty) {
      fill(widerBox);
      return;
    }
    if (!list) {      // an older service gave no list: only the sentence
      fill(widerBox, widerNote(WIDER));
      return;
    }
    const id = `mode-wider-${env.agent}`;
    const select = h("select", { class: "pui-input wb-select", id, "data-key": "wider" }, list.map((w) => h("option", { value: w.command, title: MODE_LINES[w.mode] || null, text: w.mode })));
    select.value = list[0].command;
    const code = h("code", { class: "wb-command-code wb-wider-code", text: list[0].command });
    const word = h("span", { class: "wb-copy-label", text: "Copy" });
    const copy = h("button", { class: "pui-btn pui-surface pui-outline wb-copy", type: "button", "aria-label": "Copy the command of the chosen mode", "data-key": "wider-copy" }, word);
    const status = h("span", { class: "wb-copy-status wb-muted", role: "status", text: "" });
    select.addEventListener("change", () => {
      code.textContent = select.value;
      status.textContent = "";
    });
    copy.addEventListener("click", async () => {
      const result = await copyCommand(select.value, { clipboard: typeof navigator !== "undefined" && navigator.clipboard ? navigator.clipboard : null, select: () => selectNode(code) });
      word.textContent = result === "copied" ? "Copied" : "Selected";
      status.textContent = result === "copied" ? "Copied to the clipboard." : "Select the command and copy it with the keyboard.";
      setTimeout(() => { word.textContent = "Copy"; status.textContent = ""; }, 2000);
    });
    fill(widerBox, h("div", { class: "wb-wider-box" },
      h("div", { class: "wb-wider-row" }, h("label", { class: "wb-wider-label", for: id, text: "Mode" }), select, copy),
      code, widerNote(WIDER_BELOW_NOTE), status));
  }

  /** One card of "Current task(s)": the task, its skill and time, what it waits for, its actions, why it is held and its runs. */
  function currentCard(view, card) {
    const task = card.task;
    const sub = currentSub(task, card.body, view.decisions, env.now());
    return h("div", { class: "pui-card wb-current" },
      h("div", { class: "wb-cur-head wb-current-head" }, h("strong", { text: `#${task.id} ${task.title || task.key || ""}`.trim() }), chip(taskWord(task.state), stateTone(task.state))),
      h("span", { class: "wb-muted wb-cur-sub wb-current-sub" }, h("span", { class: "mono", text: sub.skill }), sub.when ? ` · ${sub.when}` : ""),
      waitLines(task).map((line) => h("p", { class: "wb-task-waits wb-muted", text: line })),
      taskActions(task, view),
      card.held ? heldBlock(card.held) : null,
      runsSection(card.runs, { key: `current-${task.id}`, isOpen: earlierOpen.has(task.id), onToggle: () => {
        if (earlierOpen.has(task.id)) earlierOpen.delete(task.id);
        else earlierOpen.add(task.id);
        if (lastView) drawCurrent(lastView);
      } }));
  }

  function drawCurrent(view) {
    const cards = view.currents || [];
    if (!cards.length) {
      fill(currentBox, view.tasks.length ? null : h("p", { class: "wb-empty-line", text: "This agent has no task yet." }));
      return;
    }
    // several running tasks (a floor with several slots): one card for each, the oldest first, under "Current tasks"
    redraw(currentBox, () => fill(currentBox, h("span", { class: "wb-sec-head", text: cards.length > 1 ? "Current tasks" : "Current task" }), cards.map((card) => currentCard(view, card))));
  }

  // The actions of a task (task-actions.js): the same nodes as a Tasks-tab row, for the current task and for each of the others.
  const taskActionsUse = createTaskActions({
    project: env.project, api: env.api, refresh: () => env.refresh(), can: env.can,
    redraw: () => { shown.current = null; shown.others = null; if (lastView) { drawCurrent(lastView); drawOthers(lastView); } },
  });
  const links = env.links || { inbox: () => router.cityHash() };

  function taskActions(task, view) {
    const nodes = taskActionsUse.nodes(task, { pending: view.decisions, links, locked });
    return nodes.length || taskActionsUse.failure(task.id)
      ? h("div", { class: "wb-current-actions" }, nodes.length ? h("div", { class: "wb-task-actions" }, nodes) : null, taskActionsUse.failure(task.id)) : null;
  }

  function drawOthers(view) {
    if (!view.others.length) {
      fill(othersBox);
      return;
    }
    redraw(othersBox, () => fill(othersBox, h("span", { class: "wb-sec-head", text: "Other tasks of this agent" }),
      view.others.map((t) => {
        const nodes = taskActionsUse.nodes(t, { pending: view.decisions, links, locked });
        return h("div", { class: "wb-other" },
          h("div", { class: "wb-cur-head" }, h("strong", { class: "wb-other-title", text: `#${t.id} ${t.title || t.key || ""}`.trim() }), chip(taskWord(t.state), stateTone(t.state))),
          nodes.length ? h("div", { class: "wb-task-actions" }, nodes) : null,
          waitLines(t).map((line) => h("p", { class: "wb-task-waits wb-muted", text: line })),
          view.heldOthers && view.heldOthers[t.id] ? heldBlock(view.heldOthers[t.id]) : null,
          taskActionsUse.failure(t.id));
      })));
  }

  // --- hand a file over ------------------------------------------------------------------------------------------------------------
  const fileInput = h("input", { class: "pui-input wb-file", type: "file", "data-key": "file" });
  const hint = h("span", { class: "wb-hint wb-muted wb-cur-sub", text: "At most 25 MiB." });
  const mediaHint = h("span", { class: "wb-media-hint wb-muted wb-cur-sub", text: mediaHintText() });      // a video is attached on the Mac, through the media route
  const handResult = h("div", { class: "wb-hand-result" });
  const dropLine = h("p", { class: "wb-drop-line", role: "note", hidden: true, text: "" });     // the line of a web task, above the chooser: seen before a file is chosen
  const chooser = handChooser({ input: fileInput, line: dropLine, hint });
  const handStep = h("div", { class: "wb-hand-steps" });     // the second step: the chosen file's name and the button (C-17)
  fill(handBox, chooser.nodes.slice(0, 4), handStep, hint, mediaHint, handResult, handLine);
  const drops = new Map();       // task id -> the `drop` of its body ({web, takes, line}), or null: read once, as the review card does
  let target = null;
  let picked = null;       // the file chosen, held until the button sends it (C-17); choosing sends nothing
  let pickedFor = null;    // the id of the task the hint named when the file was chosen: the button names it and sends to it, whatever a poll draws since
  let sending = false;

  function drawStep() {
    fill(handStep, picked ? handOverStep(picked, pickedFor, sendFile, { disabled: sending || locked, label: isMediaFile(picked) ? MEDIA_LABEL : undefined }) : null);
  }

  fileInput.addEventListener("change", () => {
    const file = fileInput.files && fileInput.files[0];
    if (!file || !target || sending) return;
    const refusal = pickRefusal(file, fileRefusal, { may: can("media-in") });
    if (refusal) {
      picked = null;
      pickedFor = null;
      fill(handResult, notice(refusal, "error"));
      fileInput.value = "";
    } else {
      picked = file;
      pickedFor = target.id;
      fill(handResult);
    }
    drawStep();
  });

  /** The button: send the file held to the task it names, the one the hint named when the file was chosen (a poll that moves the target does not change it). */
  async function sendFile() {
    const file = picked;
    const to = pickedFor;
    const media = isMediaFile(file);
    if (!file || to === null || sending || !can(media ? "media-in" : "hand-over")) return;
    sending = true;
    fileInput.disabled = true;
    drawStep();
    const bar = media ? progressBar() : null;
    fill(handResult, busyLine(media ? "Uploading..." : "Sending..."), bar ? bar.node : null);
    try {
      let line;
      if (media) {      // a video, or a file over 25 MiB: its own bytes to the media route with a progress bar, never base64 (the Mac only)
        line = storedLine(await uploadRecording(env.api, env.project, file, { bar }));
      } else {
        const bytes = new Uint8Array(await file.arrayBuffer());
        const result = await env.api.handOver(env.project, to, file.name, toBase64(bytes));
        line = `Handed over: ${result.path} (${result.bytes} bytes)`;
      }
      fill(handResult, h("p", { class: "wb-card-line", role: "status", text: line }));
      picked = null;
      pickedFor = null;
      fileInput.value = "";
      env.refresh();
    } catch (e) {
      fill(handResult, notice(errorText(e), "error"));      // the file stays held: the button can be pressed again
    }
    sending = false;
    drawHandLine();
    drawStep();
  }

  /**
   * The file-drop line of the target task (`task.drop`). The current task's body is already read by the view: it is used as it is, no read of its own; any other
   * target is read once through `env.task`. A read that fails leaves no line, and the runtime still refuses what it must.
   */
  async function loadDrop(view) {
    const id = target.id;
    if (view.current && view.current.id === id) {
      if (view.currentBody) drops.set(id, view.currentBody.drop && typeof view.currentBody.drop === "object" ? view.currentBody.drop : null);
      return;
    }
    if (!env.task || drops.has(id)) return;
    drops.set(id, null);
    try {
      const body = await env.task(id);
      drops.set(id, body && body.drop && typeof body.drop === "object" ? body.drop : null);
    } catch (e) {
      drops.set(id, null);
    }
    if (target && target.id === id) drawHandLine();
  }

  function drawHandLine() {
    const drop = target ? drops.get(target.id) : null;
    const line = drop && drop.web && drop.takes !== false && typeof drop.line === "string" ? drop.line : "";
    dropLine.textContent = line;
    const mayHand = can("hand-over");
    dropLine.hidden = !line || !mayHand;
    fileInput.disabled = !target || locked || !mayHand || Boolean(drop && drop.takes === false);      // a task that takes no file: nothing to choose
    chooser.button.disabled = fileInput.disabled;
  }

  function drawHand(view) {
    target = view.target;
    hint.textContent = target ? `To task #${target.id}. At most 25 MiB.` : "This agent has no task to hand a file to.";
    // the policy withholds `hand-over`: the chooser is left out and the line says so (the other parts of the box stay as they are)
    const mayHand = can("hand-over");
    for (const node of [...chooser.nodes.slice(0, 4).filter((n) => n !== dropLine), handStep, hint, mediaHint, handResult]) node.hidden = !mayHand;
    fill(handLine, mayHand || !target ? null : withheldLine(["hand-over"]));      // only when there is a task to hand a file to
    if (target) loadDrop(view);
    drawHandLine();
    drawStep();
  }

  let lastView = null;
  return {
    el,
    focusSelect() {
      stopButton.focus();
    },
    /** view: floor-model.floor(...) with found true; {notAccepted: true, ...} draws the waiting line only; null while loading. */
    update(view) {
      lastView = view;
      if (view && (view.notAccepted || view.unaccepted)) sawUnaccepted = true;
      else if (view && sawUnaccepted && modeResult) {
        modeResult = null;
        sawUnaccepted = false;
      }
      drawResult();
      const unaccepted = !view || view.notAccepted;
      waitingLine.hidden = !(view && view.notAccepted);
      for (const node of [metersBox, currentBox, othersBox, handBox]) node.hidden = unaccepted;
      if (unaccepted) widerBox.hidden = true;
      if (unaccepted) runsTotalLine.hidden = true;
      stateBox.hidden = false;
      plateBox.hidden = unaccepted;
      formBox.hidden = unaccepted;
      if (!view) {
        swap("state", "loading", () => drawState(null));
        return;
      }
      if (view.notAccepted) {
        swap("state", "unaccepted", () => fill(stateBox));
        return;
      }
      const row = stateRow(view.row.state, view.decisions.length, view.runningBody, env.now(), view.row.slots);
      swap("state", row, () => drawState(row, view));
      const waiting = view.unaccepted ? { command: view.acceptNext } : null;     // A-62
      swap("plate", [view.agent.mode, view.agent.acting_mode, Boolean(waiting)], () => drawPlate(view.agent, Boolean(waiting)));
      locked = Boolean(view.unaccepted);
      currentMode = view.agent.mode || null;
      drawButtons();
      swap("meters", meters(view.agent), () => drawMeters(meters(view.agent)));
      runsTotalLine.hidden = !meters(view.agent).runsTotal;     // every update: a draw skipped as identical must not leave it hidden after a not-accepted spell
      swap("wider", [view.agent.wider || null, waiting], () => drawWider(view.agent.wider, waiting));
      widerBox.hidden = widerEmpty;
      const pendingIds = view.decisions.map((d) => [d.id, d.task_id]);
      const cards = (view.currents || []).map((c) => [c.task, c.runs, earlierOpen.has(c.task.id), c.held, currentSub(c.task, c.body, view.decisions, env.now())]);     // "for 12 min" moves with the clock: it is part of what is drawn
      swap("current", [cards, view.tasks.length, pendingIds, taskActionsUse.signature(), locked], () => drawCurrent(view));
      swap("others", [view.others.map((t) => [t.id, t.title, t.state, t.note, t.waiting_for]), view.heldOthers || {}, pendingIds, taskActionsUse.signature(), locked], () => drawOthers(view));
      swap("hand", [view.target ? view.target.id : null, locked, Boolean(view.currentBody), can("hand-over")], () => drawHand(view));
    },
  };
}
