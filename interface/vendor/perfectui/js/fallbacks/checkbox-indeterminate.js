const i = "input[type=checkbox][indeterminate]";
function n() {
  for (const t of document.querySelectorAll(i))
    t.indeterminate || (t.indeterminate = !0);
}
function o(t) {
  const e = t.target;
  t.animationName === "pui-indeterminate" && e instanceof HTMLInputElement && !e.indeterminate && (e.indeterminate = !0);
}
function a(t) {
  const e = t.target;
  e instanceof HTMLInputElement && e.matches(i) && e.removeAttribute("indeterminate");
}
typeof document < "u" && (document.addEventListener("change", a, !0), document.addEventListener("animationstart", o, !0), document.addEventListener("pointerdown", n, !0), document.addEventListener("focusin", n, !0), n());
