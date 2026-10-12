// What the City's "Add a project" and "Leave this project" show (A-24), worked out with no document and no network. The page never opens a folder
// and never starts the service: a project enters the service, or leaves it, by the person's hand in the terminal, so the page shows the restart
// line with the folders it holds and the one that changes (`--project` repeated), and, for a folder with no configuration, the line that makes one.
//
// Where each piece comes from: the head of the restart line (everything before the first `--project`: the runner and the service's script) is the
// service's own start line, read from `connections.service.start` of an accepted project, which carries the absolute path of this checkout; the
// folders of the projects it holds are the `folder` of each entry of `GET /projects` (A-34: the service knows it for every project, accepted or
// not), else, for an answer without the key, the configuration file's place (`status.config.path`, minus the configuration's own place); the
// folder to add is what the person typed. A folder the page cannot know at all is written `<folder of NAME>`, to be replaced; the service's
// answer always carries it, so that form is a fallback and not a case the person meets.
// When the service's start line cannot be read, the head is the known form with the checkout left for the person to fill in.

const CONFIG_TAIL = "/docs/workbench/runtime.json";
const SAFE = /^[A-Za-z0-9@%+=:,./_-]+$/;
const PLACEHOLDER = /^<[^<>]+>$/;
const SERVICE_SCRIPT = "/runtime/service.py";

export const AUTONOMY_MODES = Object.freeze([["milestones", "milestones (recommended)"], ["every-phase", "every phase"], ["end", "at the end"]]);
export const FALLBACK_HEAD = "python3 <the workbench folder>/runtime/service.py";
export const ABSOLUTE = /^(\/|[A-Za-z]:[\\/])/;      // a `~/` path is not absolute: quoted it would name a folder called "~"

/** A word of a shell command: as it is when it is safe, else in single quotes; a value written as <placeholder> is kept. */
export function shellWord(text) {
  const value = String(text);
  if (PLACEHOLDER.test(value) || SAFE.test(value)) return value;
  return `'${value.replace(/'/g, "'\"'\"'")}'`;
}

/** The words of a command line, quotes taken off (single and double quotes, backslash escapes inside double quotes). */
export function splitWords(line) {
  const words = [];
  let current = "";
  let started = false;
  let quote = null;
  for (let i = 0; i < line.length; i += 1) {
    const c = line[i];
    if (quote === "'") {
      if (c === "'") quote = null;
      else current += c;
    } else if (quote === '"') {
      if (c === '"') quote = null;
      else if (c === "\\" && i + 1 < line.length) current += line[++i];
      else current += c;
    } else if (c === "'" || c === '"') {
      quote = c;
      started = true;
    } else if (/\s/.test(c)) {
      if (started || current) words.push(current);
      current = "";
      started = false;
    } else {
      current += c;
      started = true;
    }
  }
  if (started || current) words.push(current);
  return words;
}

/**
 * The head of the restart line from the service's own start line: everything before the first `--project`, as written. "" when the line is not a
 * text or holds no script of the service.
 */
export function startHead(start) {
  if (typeof start !== "string") return "";
  const at = start.indexOf(" --project ");
  const head = (at < 0 ? start : start.slice(0, at)).trim();
  return head.includes(SERVICE_SCRIPT.slice(1)) ? head : "";
}

/** The checkout of the workbench the head names (the folder that holds runtime/service.py), or "". */
export function checkoutOf(head) {
  const script = splitWords(head).find((w) => w.endsWith(SERVICE_SCRIPT));
  return script ? script.slice(0, -SERVICE_SCRIPT.length) : "";
}

/** The folder of a project from the path of its configuration file (`status.config.path`), or null when it is not the configuration's own place. */
export function folderOf(configPath) {
  return typeof configPath === "string" && configPath.endsWith(CONFIG_TAIL) && configPath.length > CONFIG_TAIL.length ? configPath.slice(0, -CONFIG_TAIL.length) : null;
}

/** The projects the service holds, from the page's snapshot: [{id, name, folder|null}], in the service's order. The folder is the service's own (`folder` of the entry). */
export function projectsOf(snapshot) {
  const listed = snapshot && Array.isArray(snapshot.projects) ? snapshot.projects : [];
  return listed.map((p) => {
    const detail = snapshot.details && snapshot.details[p.id];
    const status = detail && detail.status;
    const given = typeof p.folder === "string" && p.folder ? p.folder : null;
    return { id: p.id, name: p.name, folder: given || folderOf(status && status.config && status.config.path) };
  });
}

/** The first project the page can read the service's start line through: an accepted one. */
export function readableProject(snapshot) {
  const listed = snapshot && Array.isArray(snapshot.projects) ? snapshot.projects : [];
  const found = listed.find((p) => p.config && p.config.accepted);
  return found ? found.id : null;
}

/** The path a person typed, trimmed and without a trailing slash; "" when empty. */
export function cleanFolder(text) {
  const value = String(text || "").trim();
  return value.length > 1 ? value.replace(/[\\/]+$/, "") : value;
}

/** The refusal of a folder before a line is shown, or "": empty, not absolute, or already one of the projects. */
export function folderRefusal(text, projects) {
  const folder = cleanFolder(text);
  if (!folder) return "";
  if (!ABSOLUTE.test(folder)) return "Type the absolute path of the folder, such as /home/me/shop.";
  if (projects.some((p) => p.folder === folder)) return "That folder is already one of the service's projects.";
  return "";
}

/** A project's name as it may stand in a placeholder: every character outside letters, digits, space, ".", "_" and "-" is replaced, so a name never carries shell text. */
export function safeName(name) {
  return String(name === undefined || name === null ? "" : name).replace(/[^A-Za-z0-9 ._-]/g, "_");
}

/** The word a restart line writes for one project: its folder, or `<folder of NAME>` when the page does not know it. */
function folderWord(project) {
  return project.folder ? shellWord(project.folder) : `<folder of ${safeName(project.name)}>`;
}

/**
 * The line that starts the service again: the head, then `--project <folder>` for each project it will hold. `add` is the folder to add
 * (appended), `leave` the id of the project to drop. Returns {command, unknown: [names of projects whose folder is a placeholder], empty}; `empty` is
 * true when no project would be left (the service needs at least one), and then the command is "".
 */
export function restartLine({ head, projects, add = null, leave = null }) {
  const kept = projects.filter((p) => p.id !== leave);
  const words = kept.map(folderWord);
  if (add) words.push(shellWord(add));
  if (!words.length) return { command: "", unknown: [], empty: true };
  return {
    command: [head || FALLBACK_HEAD, ...words.map((w) => `--project ${w}`)].join(" "),
    unknown: kept.filter((p) => !p.folder).map((p) => safeName(p.name)), empty: false,
  };
}

/** The line that makes the configuration of a folder that has none (the project-init script of the checkout), with the autonomy the person chose. */
export function initLine({ head, folder, autonomy }) {
  const checkout = checkoutOf(head);
  const script = checkout ? shellWord(`${checkout}/skills/core-project-init/scripts/init_project.py`) : "<the workbench folder>/skills/core-project-init/scripts/init_project.py";
  return `python3 ${script} --root ${shellWord(folder)} --apply --autonomy ${shellWord(autonomy)}`;
}
