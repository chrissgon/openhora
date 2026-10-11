// The token prompt (R-13 to R-15): a technical sheet, not a card. A frame 1040 px wide with a line at each side on a ground of faint dots and small
// crosses at the corners of its body; a bar with the mark, the wordmark, `local service · 127.0.0.1` and the colour-mode button; an eyebrow, the title,
// step 1 (the command that copies the token, from the service), step 2 (the field); the owl keeping watch at the right; the numbered steps along the foot.
// It asks the person to paste the service's token once per browser session. The field is a text field that the stylesheet masks (`.wb-token-field`)
// where the browser can, not a password field: the token changes at every start, so the browser must not offer to save it.

import { h, fill, svg } from "../dom.js";
import { markImage } from "../brand.js";
import { commandBlock } from "../frame/command.js";
import { createModeButton } from "../frame/mode-button.js";
import { looksLikeToken } from "../token.js";
import { createOwl } from "./token-owl.js";

// The sentence the prompt had before the service told it where the token file is, and keeps when it cannot say.
const FIRST_LINE = "The token is in the file whose path the service printed when it started (the \"token_file\" value of its first line); open that file and paste its one line here.";
const COPIES = "It copies the token to the clipboard. The token itself is never shown on this page.";
const PRINTS = "It prints the token in the terminal; the token itself is never shown on this page.";

// The systems the page tells apart. `key` is the entry of the service's `commands` for it: the page picks one of the strings the
// service built and joins nothing into it.
const SYSTEMS = {
  macos: { name: "macOS", key: "macos", sentence: COPIES },
  linux: { name: "Linux", key: "linux", sentence: PRINTS },
  windows: { name: "Windows", key: "powershell", sentence: COPIES },
};

/**
 * The system a browser's platform string names ("macos", "linux" or "windows"), or null for any other (then the prompt keeps its
 * sentence). The string is a hint, not a fact: `hints` ({userAgent, touchPoints}) takes back two false answers, an Android browser that
 * says "Linux" (Firefox on Android) and a touch device that says "MacIntel" (iPad Safari in its desktop mode); neither has a terminal
 * to run the command in, so both are unknown.
 */
export function systemOf(platform, hints = {}) {
  if (typeof platform !== "string") return null;
  if (/android/i.test(String((hints && hints.userAgent) || ""))) return null;
  if (/^win/i.test(platform)) return "windows";
  if (/^mac/i.test(platform)) return Number(hints && hints.touchPoints) > 1 ? null : "macos";
  if (/^linux|^x11/i.test(platform)) return "linux";
  return null;
}

function browserPlatform() {
  if (typeof navigator === "undefined" || !navigator) return "";
  return String((navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "");
}

/** The address the page was opened on (`host:port`), shown as text: 127.0.0.1:<port> here, the LAN address on a phone (service --lan). */
function browserHost() {
  const where = typeof location === "undefined" || !location ? "" : location.host;
  return typeof where === "string" && where.trim() ? where.trim() : "127.0.0.1";
}

function browserHints() {
  if (typeof navigator === "undefined" || !navigator) return {};
  return { userAgent: String(navigator.userAgent || ""), touchPoints: Number(navigator.maxTouchPoints) || 0 };
}

/**
 * True when the browser can mask a text field by CSS (WebKit and Blink can; Firefox cannot). Where it cannot, the field is a password field:
 * the browser may then offer to save the token, which is the lesser failure next to showing it in clear. That the masked text field stops the
 * browser's offer rests on how browsers behave, not on a test.
 */
function masksText() {
  return typeof CSS !== "undefined" && typeof CSS.supports === "function" && CSS.supports("-webkit-text-security", "disc");
}

// What the foot of the sheet says: the two steps when the service gave a command, the three the prompt had when it gave none.
const STEPS_WITH_COMMAND = ["copy the command, run it in a terminal", "paste the token here"];
const STEPS_WITHOUT = ["the service prints token_file", "open that file", "paste its one line"];

/** The ground of faint dots: a pattern whose colour the stylesheet gives (`.tk-grid`), so no colour is written here. */
function dotsGround() {
  return svg("svg", { class: "tk-grid", "aria-hidden": "true" },
    svg("defs", {}, svg("pattern", { id: "tk-dots", width: 32, height: 32, patternUnits: "userSpaceOnUse" }, svg("circle", { cx: 1, cy: 1, r: 0.9 }))),
    svg("rect", { width: "100%", height: "100%", fill: "url(#tk-dots)" }));
}

/**
 * Draw the prompt in `root`. onSubmit(token) is called with the pasted text when it has the shape of a token and
 * resolves when the page has tried it; `message` is shown above the field (why the prompt is here again).
 * `tokenFile` (optional) is an async function that reads the service's answer to GET /token-file ({token_file, commands}); when the
 * answer has a command for the browser's system (`platform` and `hints`, default the browser's own) the prompt shows two steps, "1 · Run this in a
 * terminal" with the command and Copy, then "2 · Paste the token"; in every other case (no reader, an older service, an error, a path
 * with no safe command, a system not told apart) it keeps its sentence about the first line. The command is the service's string, as it comes
 * (R4D-4): the page picks one and joins nothing into it. `host` (default the address the page was opened on) is the address the bar names. `copyEnv` is for a test. Returns {destroy()}.
 */
export function showTokenPrompt(root, { message, onSubmit, tokenFile, platform, hints, copyEnv, host }) {
  const field = h("input", {
    id: "token-field", class: "pui-input wb-token-field", type: masksText() ? "text" : "password", name: "service-token", autocomplete: "off",
    autocapitalize: "off", spellcheck: "false", required: true, "aria-describedby": "token-help",
  });
  const problem = h("p", { class: "notice pui-soft pui-error", role: "alert", hidden: true });
  const button = h("button", { class: "pui-btn pui-solid pui-theme", type: "submit", text: "Continue" });
  const fieldLabel = h("span", { text: "Access token" });
  const form = h("form", { class: "tk-form", autocomplete: "off" },
    h("label", { class: "tk-label", for: "token-field" }, fieldLabel),
    h("div", { class: "tk-field" }, field, button),
    h("small", { class: "tk-help", id: "token-help", text: "It is kept in this browser tab until you close it, and sent only to this service." }),
    problem);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const pasted = field.value.trim();
    problem.hidden = true;
    if (!looksLikeToken(pasted)) {
      problem.textContent = "That does not look like the token: it is one line of 32 or more characters, with no spaces.";
      problem.hidden = false;
      return;
    }
    button.disabled = true;
    field.value = "";
    try {
      await onSubmit(pasted);
    } finally {
      button.disabled = false;
    }
  });

  // Where the person is told how to get the token: the two steps, or the sentence. Empty while the service's answer is awaited.
  const how = h("div", { class: "wb-token-how" });
  const foot = h("footer", { class: "tk-steps", hidden: true });
  const stepsOf = (words) => {
    foot.classList.toggle("is-two", words.length === 2);
    foot.hidden = false;
    foot.replaceChildren(...words.map((word, i) => h("div", { class: "tk-step" }, h("span", { class: "tk-num", text: String(i + 1).padStart(2, "0") }), h("span", { class: "tk-cap", text: word }))));
  };
  const fallback = () => {
    fieldLabel.textContent = "Access token";
    fieldLabel.removeAttribute("class");
    how.classList.remove("tk-cmd");
    fill(how, h("p", { class: "tk-text", text: FIRST_LINE }));
    stepsOf(STEPS_WITHOUT);
  };
  const steps = (system, command) => {
    fieldLabel.textContent = "2 \u00b7 Paste the token";
    fieldLabel.setAttribute("class", "wb-token-label");
    how.classList.add("tk-cmd");
    fill(how,
      h("div", { class: "tk-cmd-head" },
        h("span", { class: "wb-token-label tk-label", text: "1 \u00b7 Run this in a terminal" }),
        h("span", { class: "wb-token-system tk-cap", text: system.name })),
      commandBlock({ command, label: "Copy the command", icon: "copy" }, copyEnv || null),
      h("small", { class: "wb-token-help tk-help", text: system.sentence }));
    stepsOf(STEPS_WITH_COMMAND);
  };
  if (typeof tokenFile !== "function") {
    fallback();
  } else {
    const system = SYSTEMS[systemOf(platform === undefined ? browserPlatform() : platform, hints === undefined ? browserHints() : hints)];
    Promise.resolve().then(() => tokenFile()).then((answer) => {
      const commands = answer && typeof answer === "object" && answer.commands && typeof answer.commands === "object" ? answer.commands : null;
      const command = system && commands ? commands[system.key] : null;
      if (typeof command === "string" && command.trim()) steps(system, command);
      else fallback();
    }).catch(fallback);
  }

  const modeButton = createModeButton();
  const corners = ["tl", "tr", "bl", "br"].map((where) => h("span", { class: `tk-cross tk-${where}`, "aria-hidden": "true" }));
  fill(root,
    dotsGround(),
    h("main", { class: "tk" },
      h("div", { class: "tk-frame" },
        h("header", { class: "tk-bar" },
          h("div", { class: "wb-brand" }, markImage(24, ""), h("span", { class: "wb-wordmark", text: "openhora" })),
          h("span", { class: "tk-meta", text: `local service \u00b7 ${host === undefined ? browserHost() : String(host)}` }),
          modeButton.el),
        h("div", { class: "tk-body" },
          corners,
          h("section", { class: "tk-main" },
            h("span", { class: "tk-eyebrow", text: "01 \u00b7 service token" }),
            h("h1", { class: "tk-title", text: "Paste the openhora service token" }),
            message ? h("p", { class: "notice pui-soft pui-error", role: "alert", text: message }) : null,
            how,
            form),
          h("aside", { class: "tk-side" }, createOwl(168))),
        foot)));
  field.focus();
  return { destroy: () => modeButton.destroy() };
}
