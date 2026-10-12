const c = {
  "show-modal": (o) => o.showModal?.(),
  close: (o) => o.close?.(),
  "request-close": (o) => {
    const e = o;
    typeof e.requestClose == "function" ? e.requestClose() : e.close?.();
  },
  "show-popover": (o) => o.showPopover?.(),
  "hide-popover": (o) => o.hidePopover?.(),
  "toggle-popover": (o) => o.togglePopover?.()
};
function r(o) {
  if (!(o.target instanceof Element)) return;
  const e = o.target.closest(
    "button[commandfor][command]"
  );
  if (!e || e.disabled) return;
  const t = e.getAttribute("commandfor"), n = e.getAttribute("command")?.toLowerCase();
  if (!t || !n) return;
  const s = document.getElementById(t);
  s && c[n]?.(s);
}
typeof document < "u" && document.addEventListener("click", r);
