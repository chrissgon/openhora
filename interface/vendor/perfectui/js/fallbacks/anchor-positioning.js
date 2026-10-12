const p = ["top", "bottom", "start", "end"], A = ["start", "center", "end"], P = {
  top: "bottom",
  bottom: "top",
  start: "end",
  end: "start"
};
let s = null;
function G(n) {
  const e = n.id;
  if (!e) return null;
  const t = CSS.escape(e);
  return document.querySelector(
    `[popovertarget="${t}"], [interestfor="${t}"], [commandfor="${t}"]`
  );
}
function b(n, e) {
  for (const t of p)
    if (n.classList.contains(`pui-${t}`)) return t;
  return e ? "top" : "bottom";
}
function E(n, e) {
  for (const t of A)
    if (n.classList.contains(`pui-align-${t}`)) return t;
  return e ? "center" : "start";
}
const g = (n, e, t) => Math.min(Math.max(n, e), t);
function m(n) {
  const e = G(n);
  if (!e) return;
  const t = e.getBoundingClientRect(), i = n.getBoundingClientRect(), a = n.getAttribute("popover") === "hint", r = getComputedStyle(n).direction === "rtl", h = {
    top: t.top,
    bottom: window.innerHeight - t.bottom,
    start: r ? window.innerWidth - t.right : t.left,
    end: r ? t.left : window.innerWidth - t.right
  }, u = {
    top: i.height,
    bottom: i.height,
    start: i.width,
    end: i.width
  };
  let o = b(n, a);
  const d = P[o];
  h[o] < u[o] + 4 && h[d] >= u[d] + 4 && (o = d);
  let c, l;
  if (o === "top" || o === "bottom") {
    c = o === "top" ? t.top - i.height - 4 : t.bottom + 4;
    const f = E(n, a);
    l = f === "center" ? t.left + (t.width - i.width) / 2 : f === "end" !== r ? t.right - i.width : t.left;
  } else
    l = o === "start" !== r ? t.left - i.width - 4 : t.right + 4, c = t.top + (t.height - i.height) / 2;
  n.style.position = "fixed", n.style.margin = "0", n.style.top = `${g(c, 4, window.innerHeight - i.height - 4)}px`, n.style.left = `${g(l, 4, window.innerWidth - i.width - 4)}px`;
}
function L(n) {
  const e = n.target;
  !(e instanceof HTMLElement) || !e.hasAttribute("popover") || (n.newState === "open" ? (s = e, m(e)) : s === e && (s = null));
}
function w() {
  s && m(s);
}
typeof document < "u" && (document.addEventListener("toggle", L, !0), window.addEventListener("resize", w), window.addEventListener("scroll", w, !0));
