const t = "pui-mode", o = "data-pui-mode";
const n = /(?:^|; )pui-mode=(light|dark)/;
function m(e = "system") {
  if (!(typeof document > "u")) {
    if (e === "system") {
      document.documentElement.removeAttribute(o), document.cookie = `${t}=; path=/; max-age=0; SameSite=Lax`;
      return;
    }
    document.documentElement.setAttribute(o, e), document.cookie = `${t}=${e}; path=/; max-age=31536000; SameSite=Lax`;
  }
}
function u() {
  return typeof document > "u" ? "system" : document.cookie.match(n)?.[1] ?? "system";
}
export {
  u as getMode,
  m as setMode
};
