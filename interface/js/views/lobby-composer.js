// The composer at the bottom of the Lobby's conversation: the message field, "Send" (the region's one solid button), "New request" beside it (R-44), the
// hint, the busy line while a turn runs, the line that says a run is in progress (A-23: Send stays on; a plain line is stored and routed when the run ends, a
// question about the state is answered now) and the notice when a turn was not sent or failed (R-11: the soft error style). Typing "/" opens the list of the
// commands over the field (R-45): one row for each command the service gave, narrowing as the person types; the arrows move, Enter or Tab fills the field,
// Escape closes the list and only the list. It holds no rule: it reports the text the person typed (Enter sends, Shift+Enter makes a new line) and draws
// the state it is given. A line that starts with "/" is sent unchanged; the page builds no prompt.

import { h } from "../dom.js";
import { icon } from "../frame/icons.js";
import * as router from "../router.js";
import { HINT, RUN_LINE, SENDING_TEXT, commandFill, commandMatches } from "./lobby-model.js";

const LIST_ID = "wb-say-cmds";

/** Create the composer. options: {onSend(text), onNew()}. Returns {el, set(state), focus(), text(), clear(), setCommands(rows)}. */
export function createComposer({ onSend, onNew = () => {} }) {
  const busy = h("div", { class: "wb-lobby-busy wb-comp-line", role: "status", "aria-busy": "true", hidden: true }, h("span", { class: "wb-lobby-ring", "aria-hidden": "true" }), h("span", { text: SENDING_TEXT }));
  const noticeTitle = h("strong", { class: "wb-lobby-notice-title", text: "" });
  const noticeText = h("span", { text: "" });
  const notice = h("div", { class: "wb-lobby-notice-card notice pui-soft pui-error wb-comp-line", role: "alert", hidden: true }, noticeTitle, noticeText);
  const runLink = h("a", { class: "pui-link pui-theme wb-lobby-run-link", href: router.cityHash(), hidden: true, text: "" });
  const runLine = h("p", { class: "wb-lobby-run wb-comp-line", id: "wb-say-run", role: "status", hidden: true }, h("span", { text: RUN_LINE }), " ", runLink);
  const field = h("textarea", {
    class: "pui-input wb-lobby-field wb-field-input wb-comp-field", id: "wb-say", rows: "1", placeholder: "Describe what you want done", autocomplete: "off",
    role: "combobox", "aria-autocomplete": "list", "aria-controls": LIST_ID, "aria-expanded": "false",
  });
  const label = h("label", { class: "wb-comp-label wb-composer-field", for: "wb-say" }, h("span", { text: "Message to the planning agent" }));
  const sendIcon = icon("send", 16);
  const word = document.createTextNode("Send");
  // the keyboard order is the field, "Send", then "New request" (lobby.md); the stylesheet draws "New request" at the left
  const button = h("button", { class: "pui-btn pui-solid pui-theme wb-send", type: "submit" }, sendIcon, word);
  const newButton = h("button", { class: "pui-btn pui-surface pui-outline wb-new-btn", type: "button" }, icon("plus", 16), "New request");
  const list = h("ul", { class: "pui-card wb-slash", role: "listbox", id: LIST_ID, "aria-label": "Commands", hidden: true });
  const form = h("form", { class: "wb-composer" }, list, field, button, newButton);
  const hint = h("small", { class: "wb-lobby-hint wb-card-hint", id: "wb-say-hint", text: HINT });
  field.setAttribute("aria-describedby", "wb-say-hint");
  const el = h("div", { class: "wb-composer-wrap" }, busy, runLine, notice, label, form, hint);
  let sending = false;
  let blocked = false;       // the project is not accepted
  let commands = [];         // the rows the service gave: {command, arguments, help}
  let shown = [];            // the rows the list now holds
  let active = 0;            // the row that Enter or Tab would fill
  let closed = false;        // Escape or a choice closed the list: it opens again with the next character typed
  const rows = [];

  function optionId(i) {
    return `${LIST_ID}-${i}`;
  }

  function paintActive() {
    rows.forEach((row, i) => {
      row.setAttribute("aria-selected", i === active ? "true" : "false");
      row.classList.toggle("is-active", i === active);
    });
    if (shown.length && !list.hidden) field.setAttribute("aria-activedescendant", optionId(active));
    else field.removeAttribute("aria-activedescendant");
  }

  /** Draw the list for what the field holds now: open when it is one word starting with `/` that some command starts with. */
  function refresh() {
    const next = closed || sending || blocked ? [] : commandMatches(commands, field.value);
    const same = next.length === shown.length && next.every((r, i) => r === shown[i]);
    shown = next;
    if (!same) {
      active = 0;
      rows.length = 0;
      list.replaceChildren(...shown.map((r, i) => {
        const row = h("li", { class: "wb-slash-row", role: "option", id: optionId(i), "aria-selected": "false" },
          h("span", { class: "wb-slash-cmd mono" }, h("strong", { text: r.command }), r.arguments ? ` ${r.arguments}` : " "),
          h("span", { class: "wb-slash-help wb-muted", text: r.help }));
        // the pointer chooses a row without taking the focus from the field
        row.addEventListener("mousedown", (event) => {
          event.preventDefault();
          choose(i);
        });
        rows.push(row);
        return row;
      }));
    }
    list.hidden = shown.length === 0;
    field.setAttribute("aria-expanded", shown.length ? "true" : "false");
    paintActive();
  }

  function choose(i) {
    const row = shown[i];
    if (!row) return;
    field.value = commandFill(row);
    closed = true;
    refresh();
    field.focus();
  }

  function move(step) {
    if (!shown.length) return;
    active = (active + step + shown.length) % shown.length;
    paintActive();
    const row = rows[active];
    if (row && row.scrollIntoView) row.scrollIntoView({ block: "nearest" });
  }

  function submit() {
    if (sending || field.disabled) return;
    onSend(field.value);
  }
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    submit();
  });
  newButton.addEventListener("click", () => onNew());
  field.addEventListener("input", () => {
    closed = false;
    refresh();
  });
  field.addEventListener("blur", () => {
    closed = true;
    refresh();
  });
  field.addEventListener("keydown", (event) => {
    const open = !list.hidden && shown.length > 0;
    if (open && event.key === "ArrowDown") {
      event.preventDefault();
      move(1);
    } else if (open && event.key === "ArrowUp") {
      event.preventDefault();
      move(-1);
    } else if (open && event.key === "Escape") {
      event.preventDefault();      // the frame's Escape does nothing in a field; the list alone closes
      closed = true;
      refresh();
    } else if (open && event.key === "Tab" && !event.shiftKey) {
      event.preventDefault();
      choose(active);
    } else if (event.key === "Enter" && !event.shiftKey && !event.isComposing && !event.ctrlKey && !event.metaKey && !event.altKey) {
      // Enter fills the field from the open list, unless the field already holds exactly the command that is active and it takes no arguments
      if (open && field.value.trim() !== shown[active].command + (shown[active].arguments ? " " : "").trim()) {
        event.preventDefault();
        choose(active);
        return;
      }
      event.preventDefault();
      submit();
    }
  });

  return {
    el,
    /**
     * state: {sending, notice: {title, text} | null, disabled: bool (the project is not accepted), running: {text, href} | null (a run is in progress:
     * the task it names and where to read it; the line shows, Send stays on)}.
     */
    set({ sending: on, notice: shownNotice, disabled, running = null }) {
      runLine.hidden = !running || Boolean(disabled);
      runLink.hidden = !running || !running.text;
      runLink.textContent = running && running.text ? running.text : "";
      if (running && running.href) runLink.setAttribute("href", running.href);
      sending = Boolean(on);
      blocked = Boolean(disabled);
      busy.hidden = !sending;
      el.classList.toggle("is-sending", sending);
      field.disabled = sending || blocked;
      button.disabled = sending || blocked;
      newButton.disabled = sending || blocked;
      if (sending) button.setAttribute("aria-busy", "true");
      else button.removeAttribute("aria-busy");
      sendIcon.hidden = sending;
      word.data = sending ? "Sending..." : "Send";
      notice.hidden = !shownNotice;
      noticeTitle.textContent = shownNotice ? shownNotice.title : "";
      noticeText.textContent = shownNotice ? shownNotice.text : "";
      refresh();
    },
    focus() {
      field.focus();
    },
    text() {
      return field.value;
    },
    clear() {
      field.value = "";
      closed = false;
      refresh();
    },
    /** The commands of the `chat` channel as the service gave them: {command, arguments, help}[]. Until they are known no list opens. */
    setCommands(list_) {
      commands = Array.isArray(list_) ? list_.filter((r) => r && typeof r.command === "string" && r.command.startsWith("/")) : [];
      refresh();
    },
  };
}
