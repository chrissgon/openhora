// The City's "Add a project" and "Leave this project" (A-24). The service holds the projects it was started with (`--project`, repeated); nothing
// on the page opens a folder or starts the service, because a project enters the service by the person's hand in the terminal. This panel takes the
// folder the person types, and shows the line that starts the service again with it, with Copy; when the person says the folder has no
// configuration, it shows the line that makes one first (with the autonomy they choose: a decision that is theirs, the recommended one marked).
// "Leave this project" shows the line without that project. Every line comes from city-projects-model.js; the head of it is the service's own
// start line, read once when the panel opens. Text only.

import { h } from "../dom.js";
import { commandBlock } from "../frame/command.js";
import { AUTONOMY_MODES, cleanFolder, folderRefusal, initLine, restartLine, startHead } from "./city-projects-model.js";

let counter = 0;

/**
 * Create the panel. env: {readStart() -> Promise<string> (the service's start line, or "" when it cannot be read), copy (optional, for a test: the
 * command component's environment)}. Returns {el, setProjects(list), openAdd(), openLeave(id?), close(), isOpen()}; the list is
 * city-projects-model.projectsOf(snapshot).
 */
export function createProjectsPanel(env) {
  counter += 1;
  const uid = `wb-add-${counter}`;
  const el = h("div", { class: "wb-add-project", hidden: true });
  let projects = [];
  let mode = null;                // "add", "leave" or null
  let leaving = null;             // the id of the project to leave
  let head = null;                // the head of the restart line: null until read, "" when it could not be read
  let folder = "";
  let noConfig = false;
  let autonomy = AUTONOMY_MODES[0][0];

  // F1-D14: the service takes a second or two to answer (it checks the machine), and until it has the panel said it could not read the start line, with a placeholder in the
  // command: while the read lasts the panel says it is reading and shows no command. A head that was read stays; one that could not be read (the page had no accepted project to
  // ask yet, or the read failed) is asked again the next time the panel opens. One read at a time.
  let reading = false;
  const pending = () => head === null || reading;
  const readingNote = () => h("p", { class: "wb-card-note wb-muted wb-reading", text: "Reading the start line of the service..." });
  // A read that never answers must not leave the panel on "Reading..." for the session: after START_WAIT_MS (env.startWaitMs in a test) the panel gives up waiting, shows the placeholder with
  // its note, and asks again the next time it opens. An answer that comes late is still taken, and the panel is drawn again with it.
  const START_WAIT_MS = Number.isFinite(env.startWaitMs) ? env.startWaitMs : 5000;
  async function readHead() {
    if (head || reading) return;
    reading = true;
    head = "";
    const answer = Promise.resolve().then(() => env.readStart()).then((start) => startHead(start), () => "");
    let timer = null;
    const gaveUp = new Promise((resolve) => { timer = setTimeout(() => resolve(null), START_WAIT_MS); });
    const got = await Promise.race([answer, gaveUp]);
    clearTimeout(timer);
    reading = false;
    if (got === null) {
      answer.then((late) => {
        if (late && !head) {
          head = late;
          draw(true);
        }
      });
    } else {
      head = got;
    }
    draw(true);      // the person may be typing the folder: the field keeps its focus and caret when the read lands
  }

  function close() {
    mode = null;
    leaving = null;
    el.hidden = true;
    el.replaceChildren();
  }

  function copy(command, sentence, label) {
    return commandBlock({ command, sentence, label }, env.copy || null);
  }

  function addForm() {
    const input = h("input", { class: "pui-input wb-field-input", id: `${uid}-folder`, type: "text", autocomplete: "off", placeholder: "/path/to/the/project", "data-key": "project-folder", "aria-describedby": `${uid}-hint` });
    input.value = folder;
    const refusal = folderRefusal(folder, projects);
    if (refusal) input.setAttribute("aria-invalid", "true");
    input.addEventListener("input", () => {
      folder = input.value;
      draw(true);
    });
    const box = h("input", { class: "wb-checkbox", id: `${uid}-none`, type: "checkbox", "data-key": "no-configuration" });
    box.checked = noConfig;
    box.addEventListener("change", () => {
      noConfig = box.checked;
      draw(true);
    });
    const select = h("select", { class: "pui-input wb-field-input", id: `${uid}-autonomy`, "data-key": "autonomy" }, AUTONOMY_MODES.map(([value, label]) => h("option", { value, text: label })));
    select.value = autonomy;
    select.addEventListener("change", () => {
      autonomy = select.value;
      draw(true);
    });
    const clean = cleanFolder(folder);
    const ready = clean && !refusal;
    const out = [];
    if (ready && pending()) {
      out.push(readingNote());
    } else if (ready) {
      if (noConfig) {
        out.push(copy(initLine({ head, folder: clean, autonomy }), "1. Make the folder a project (this makes docs/workbench/state.md and nothing else):", "Copy the command"));
        out.push(h("p", { class: "wb-card-note", text: "2. Write the project's configuration, docs/workbench/runtime.json, by hand (contracts/runtime.md describes it). The service does not start without that file; once it is running, the page shows the command that accepts it." }));
      }
      const line = restartLine({ head, projects, add: clean });
      out.push(copy(line.command, `${noConfig ? "3. " : ""}Stop the service and start it again with this line (add --port if you started it with one):`, "Copy the command"));
      if (line.unknown.length) out.push(h("p", { class: "wb-card-note wb-muted", text: `Replace ${line.unknown.map((n) => `<folder of ${n}>`).join(", ")} with the folder of that project: the page knows a folder only for a project it could read.` }));
      if (!head) out.push(h("p", { class: "wb-card-note wb-muted", text: "The page could not read the start line of the service: replace <the workbench folder> with the folder of this checkout, or use the line you started it with." }));
    }
    return h("form", { class: "wb-add-form" },
      h("label", { class: "pui-field-group", for: `${uid}-folder` }, h("span", { text: "Project folder" }), input,
        h("small", { class: refusal ? "wb-hint is-error" : "wb-hint", id: `${uid}-hint`, text: refusal || "The folder's absolute path. This page does not open it: you restart the service." })),
      h("label", { class: "wb-waits-label", for: `${uid}-none` }, box, h("span", { text: "This folder has no configuration yet (docs/workbench/runtime.json)" })),
      noConfig ? h("label", { class: "pui-field-group", for: `${uid}-autonomy` }, h("span", { text: "Autonomy of the new project (yours to choose)" }), select) : null,
      out);
  }

  /** Which project to leave: one button for each, when none was chosen (the control is not on a project's row). */
  function leaveChooser() {
    return h("div", { class: "wb-add-form" }, h("p", { class: "wb-card-note", text: "Which project does the service stop holding?" }),
      projects.map((p) => {
        const choose = h("button", { class: "pui-btn pui-surface pui-outline wb-touch", type: "button", "data-key": `leave-choose-${p.id}`, "aria-label": `Leave project ${p.name}`, text: `Leave ${p.name}` });
        choose.addEventListener("click", () => {
          leaving = p.id;
          draw();
        });
        return choose;
      }));
  }

  function leaveBody() {
    if (leaving === null) return leaveChooser();
    const gone = projects.find((p) => p.id === leaving);
    if (!gone) return h("p", { class: "wb-card-note", text: "That project is not in the list any more." });
    const line = restartLine({ head, projects, leave: leaving });
    if (line.empty) return h("p", { class: "wb-card-note", text: `${gone.name} is the service's only project, and the service needs at least one. Start it on another folder instead.` });
    return h("div", { class: "wb-add-form" },
      h("p", { class: "wb-card-note", text: `Leaving ${gone.name} stops showing it here; its folder and its data stay where they are.` }),
      pending() ? readingNote() : copy(line.command, "Stop the service and start it again with this line (add --port if you started it with one):", "Copy the command"),
      !pending() && line.unknown.length ? h("p", { class: "wb-card-note wb-muted", text: `Replace ${line.unknown.map((n) => `<folder of ${n}>`).join(", ")} with the folder of that project.` }) : null,
      head || pending() ? null : h("p", { class: "wb-card-note wb-muted", text: "The page could not read the start line of the service: replace <the workbench folder> with the folder of this checkout, or use the line you started it with." }));
  }

  /** `typing`: the draw follows a keystroke, so the field keeps the focus and the caret. */
  function draw(typing = false) {
    if (mode === null) return;
    const active = document.activeElement;
    const key = typing && active && el.contains(active) && active.getAttribute ? active.getAttribute("data-key") : null;
    const closeButton = h("button", { class: "pui-btn pui-surface pui-outline wb-touch", type: "button", "data-key": "close-add", text: "Close" });
    closeButton.addEventListener("click", close);
    el.replaceChildren(
      h("div", { class: "wb-add-head" }, h("strong", { text: mode === "add" ? "Add a project" : "Leave this project" }), closeButton),
      mode === "add" ? addForm() : leaveBody());
    el.hidden = false;
    if (key) {
      const next = [...el.querySelectorAll("[data-key]")].find((n) => n.getAttribute("data-key") === key);
      if (next && next.focus) {
        next.focus({ preventScroll: true });
        if (typeof next.setSelectionRange === "function" && next.type === "text") next.setSelectionRange(next.value.length, next.value.length);
      }
    }
  }

  function open(next, id = null) {
    mode = next;
    leaving = id;
    readHead();       // before the first draw: it marks the read as started, so the panel says "reading" and never the placeholder
    draw();
    const field = el.querySelector("[data-key=project-folder]");
    if (field && field.focus) field.focus();
  }

  return {
    el,
    setProjects(list) {
      const before = JSON.stringify(projects);
      projects = list;
      if (mode !== null && JSON.stringify(list) !== before) draw(true);
    },
    openAdd() {
      open("add");
    },
    /** id: the project to leave; none: the panel asks which. */
    openLeave(id = null) {
      open("leave", id);
    },
    close,
    isOpen: () => mode !== null,
  };
}
