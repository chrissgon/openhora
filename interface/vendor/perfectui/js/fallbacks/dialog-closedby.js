function i(t) {
  return (t.getAttribute("closedby") ?? "").toLowerCase();
}
function o(t) {
  const n = t.target;
  if (!(n instanceof HTMLDialogElement) || !n.open || i(n) !== "any") return;
  const e = n.getBoundingClientRect();
  t.clientX >= e.left && t.clientX <= e.right && t.clientY >= e.top && t.clientY <= e.bottom || n.close();
}
function c(t) {
  const n = t.target;
  n instanceof HTMLDialogElement && i(n) === "none" && t.preventDefault();
}
typeof document < "u" && (document.addEventListener("click", o), document.addEventListener("cancel", c, !0));
