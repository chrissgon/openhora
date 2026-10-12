const f = "--pui-interest-anchor";
let s, o = null, d = null;
function i(t) {
  return t instanceof Element ? t.closest("[interestfor]") : null;
}
function r(t) {
  const n = i(t)?.getAttribute("interestfor");
  return n ? document.getElementById(n) : null;
}
function c(t, n) {
  clearTimeout(s), s = setTimeout(t, n);
}
function a(t, n) {
  if (o === t) return;
  u(), o = t, d = n, CSS.supports("anchor-name: --a") && (n.style.setProperty("anchor-name", f), t.style.setProperty("position-anchor", f));
  const e = t.showPopover;
  try {
    e?.call(t, { source: n });
  } catch {
    e?.call(t);
  }
}
function u() {
  o?.hidePopover?.(), o?.style.removeProperty("position-anchor"), d?.style.removeProperty("anchor-name"), o = null, d = null;
}
function p(t) {
  const n = i(t.target), e = r(t.target);
  n && e && c(() => a(e, n), 300);
}
function m(t) {
  r(t.target) && c(u, 150);
}
function E(t) {
  if (t.pointerType !== "touch") return;
  const n = i(t.target), e = r(t.target);
  n && e && c(() => a(e, n), 500);
}
function l() {
  clearTimeout(s);
}
function g(t) {
  const n = i(t.target), e = r(t.target);
  n && e && a(e, n);
}
function y(t) {
  r(t.target) && c(u, 150);
}
function L(t) {
  t.key === "Escape" && u();
}
typeof document < "u" && (document.addEventListener("pointerover", p), document.addEventListener("pointerout", m), document.addEventListener("pointerdown", E), document.addEventListener("pointerup", l), document.addEventListener("pointercancel", l), document.addEventListener("focusin", g), document.addEventListener("focusout", y), document.addEventListener("keydown", L));
