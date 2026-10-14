// F-2 the project switcher (R-3): a cycle button and a listbox of the projects. On the City it chooses the project the tracking bar
// follows; on another screen it opens the same screen in the chosen project (the page decides: `onSelect`). With one project there is
// nothing to cycle to: the main button is a label (C-1); with several the main button goes to the next project and ends in a swap icon.
// With none the card still opens, with its foot alone (C-20: no header, no "No project" row; F1-D3). While the first read is not back the main button is
// drawn as the prototype's loading frame does, muted and disabled with its swap icon (F1-D4); the chevron stays usable, since "Forget the token" is the way out of a read that never ends. The foot has three rows with icons (A-35): "Add a project...", "Leave this
// project..." (both open the frame's command panel) and "Forget the token"; the two that remove are in the error colour. The colour mode is
// not here any more: it is one button of the top row (R-4).

import { h } from "../dom.js";
import { arrowNav } from "./arrows.js";
import { icon } from "./icons.js";

let counter = 0;

export function createSwitcher({ onSelect, onForgetToken, onOpen, onAdd = () => {}, onLeave = () => {} }) {
  counter += 1;
  const listId = `wb-projects-${counter}`;
  const name = h("strong", { class: "wb-switch-name", text: "No project" });
  const pos = h("span", { class: "wb-switch-pos", text: "" });
  const main = h("button", { class: "pui-btn pui-surface pui-outline wb-switch-main", type: "button", title: "Go to the next project" },
    icon("building-2", 16), name, pos, h("span", { class: "wb-switch-swap", "aria-hidden": "true" }, icon("arrow-left-right", 14)));
  const chevron = h("button", {
    class: "pui-btn pui-surface pui-outline wb-switch-chevron", type: "button", "aria-haspopup": "listbox", "aria-expanded": "false",
    "aria-controls": listId, "aria-label": "Choose a project",
  }, icon("chevron-down", 16));
  // with one project (or none) the main button is a label: no cycling, no place "1/1", no title
  const labelName = h("strong", { class: "wb-switch-name", text: "No project" });
  const label = h("span", { class: "pui-btn pui-surface pui-outline wb-switch-main is-label" }, icon("building-2", 16), labelName);
  const group = h("div", { class: "pui-group-row wb-switch-group" }, main, chevron);
  let shows = "main";      // which of the main button and the label the group holds
  const heading = h("div", { class: "pui-card-header wb-listbox-head", text: "" });
  const list = h("ul", { class: "pui-list pui-hoverable wb-listbox", id: listId, role: "listbox", tabindex: "-1", "aria-label": "Projects" });
  // the foot (R-3, A-35): a row with an icon for each of the three; the two that remove are in the error colour
  const footRow = (cls, name, text, extra = "") => h("button", { class: `pui-btn pui-link ${extra}wb-foot-row ${cls}`, type: "button" }, icon(name, 16), text);
  const addRow = footRow("wb-add-row", "folder-plus", "Add a project\u2026");
  const leaveRow = footRow("wb-leave-row", "folder-minus", "Leave this project\u2026", "pui-error ");
  const forget = footRow("wb-forget", "key-round", "Forget the token", "pui-error ");
  const card = h("div", { class: "pui-card wb-listbox-card", hidden: true }, heading, list,
    h("div", { class: "wb-listbox-foot" }, addRow, leaveRow, h("div", { class: "wb-foot-sep", role: "separator" }), forget));
  const el = h("div", { class: "wb-switcher" }, group, card);

  let projects = [];
  let selected = null;
  let active = 0;
  let open = false;
  let byKeyboard = false;      // the list was opened, or is being driven, from the keyboard: its active row wears the ring (a browser that does not match :focus-visible on a script's focus() still gets it)

  const indexOfSelected = () => Math.max(0, projects.findIndex((p) => p.id === selected));

  function setActive(index) {
    active = Math.max(0, Math.min(projects.length - 1, index));
    const options = [...list.children];
    options.forEach((o, i) => o.classList.toggle("is-active", i === active));
    if (options[active]) list.setAttribute("aria-activedescendant", options[active].id);
    else list.removeAttribute("aria-activedescendant");
  }

  function setOpen(next, { focus = true } = {}) {
    open = Boolean(next);
    card.hidden = !open;
    chevron.setAttribute("aria-expanded", String(open));
    chevron.classList.toggle("is-open", open);
    card.classList.toggle("is-keyboard", open && byKeyboard);
    if (open) {
      onOpen();
      setActive(indexOfSelected());
      (projects.length > 0 ? list : forget).focus();      // with no project the foot is all there is
    } else if (focus && next === false && document.activeElement && el.contains(document.activeElement)) {
      chevron.focus();
    }
  }

  function choose(index) {
    const project = projects[index];
    if (!project) return;
    setOpen(false);
    onSelect(project.id);
  }

  main.addEventListener("click", () => {
    if (projects.length < 2) return;
    const next = projects[(indexOfSelected() + 1) % projects.length];
    setOpen(false, { focus: false });
    onSelect(next.id);
  });
  chevron.addEventListener("pointerdown", () => { byKeyboard = false; });
  chevron.addEventListener("click", () => setOpen(!open));
  chevron.addEventListener("keydown", (event) => {
    byKeyboard = true;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
    }
  });
  list.addEventListener("keydown", (event) => {
    byKeyboard = true;
    card.classList.toggle("is-keyboard", true);
    if (event.key === "ArrowDown") { event.preventDefault(); setActive(active + 1); }
    else if (event.key === "ArrowUp") { event.preventDefault(); setActive(active - 1); }
    else if (event.key === "Home") { event.preventDefault(); setActive(0); }
    else if (event.key === "End") { event.preventDefault(); setActive(projects.length - 1); }
    else if (event.key === "Enter" || event.key === " ") { event.preventDefault(); choose(active); }
  });
  card.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      setOpen(false);
    }
  });
  arrowNav(card, ".wb-foot-row");
  addRow.addEventListener("click", () => {
    setOpen(false, { focus: false });
    onAdd();
  });
  leaveRow.addEventListener("click", () => {
    setOpen(false, { focus: false });
    onLeave(selected);
  });
  forget.addEventListener("click", () => onForgetToken());
  const onPointerDown = (event) => {
    if (open && !el.contains(event.target)) setOpen(false, { focus: false });
  };
  document.addEventListener("pointerdown", onPointerDown);

  return {
    el,
    destroy() { document.removeEventListener("pointerdown", onPointerDown); },
    close() { if (open) setOpen(false, { focus: false }); },
    isOpen: () => open,
    /**
     * projects: [{id, name, badge, sub, accepted}]; selectedId; heading: the card's header text; loading: the projects are not read yet.
     */
    update({ projects: next, selectedId, heading: text, loading = false }) {
      projects = next;
      selected = selectedId;
      heading.textContent = text;
      const index = indexOfSelected();
      const current = projects[index];
      name.textContent = current ? current.name : "No project";
      labelName.textContent = name.textContent;
      pos.textContent = current ? `${index + 1}/${projects.length}` : "";
      leaveRow.disabled = !current;     // nothing to leave while the service shows no project
      main.setAttribute("aria-label", current ? `${current.name}, project ${index + 1} of ${projects.length}, go to the next project` : "No project, loading the projects");
      main.disabled = loading && !current;
      group.classList.toggle("is-loading", loading && !current);
      const wants = projects.length < 2 && !(loading && !current) ? "label" : "main";
      if (shows !== wants) {      // the button and the label swap only when the count crosses one (or the first read ends)
        shows = wants;
        group.replaceChildren(shows === "label" ? label : main, chevron);
      }
      heading.hidden = projects.length === 0;       // F1-D3: with no project the card is its foot alone
      list.hidden = projects.length === 0;
      list.replaceChildren(...projects.map((p, i) => {
        const optionId = `${listId}-o${i}`;
        const row = h("li", { class: `pui-list-item wb-option${p.id === selected ? " is-selected" : ""}`, id: optionId, role: "option", "aria-selected": String(p.id === selected) },
          h("span", { class: "wb-option-text" }, h("strong", { class: "wb-option-name", text: p.name }), h("span", { class: "wb-option-sub", text: p.sub || "" })),
          p.accepted === false
            ? h("span", { class: "pui-badge pui-warn pui-soft", text: "Not accepted" })
            : h("span", { class: "pui-badge pui-warn pui-soft pui-rounded-full", text: String(p.badge ?? 0) }),
          h("span", { class: `wb-check pui-soft pui-success${p.id === selected ? " is-on" : ""}` }, icon("check", 14)));
        row.addEventListener("click", () => choose(i));
        return row;
      }));
      if (open) setActive(Math.min(active, projects.length - 1));
    },
  };
}
