const t = [
  {
    // Baseline newly since December 2025, so this only serves older versions.
    name: "command-for",
    supported: () => "commandForElement" in HTMLButtonElement.prototype,
    load: () => import("./fallbacks/command-for.js")
  },
  {
    // Missing in Safari.
    name: "dialog-closedby",
    supported: () => "closedBy" in HTMLDialogElement.prototype,
    load: () => import("./fallbacks/dialog-closedby.js")
  },
  {
    // Chromium only.
    name: "interest-for",
    supported: () => "interestForElement" in HTMLButtonElement.prototype,
    load: () => import("./fallbacks/interest-for.js")
  },
  {
    // Chromium only.
    name: "anchor-positioning",
    supported: () => CSS.supports("anchor-name: --a"),
    load: () => import("./fallbacks/anchor-positioning.js")
  },
  {
    // No native attribute exists, so this always loads. Replace the check if
    // one ever ships.
    name: "checkbox-indeterminate",
    supported: () => !1,
    load: () => import("./fallbacks/checkbox-indeterminate.js")
  }
];
function n(e = t) {
  if (!(typeof document > "u"))
    for (const o of e)
      o.supported() || o.load();
}
n();
export {
  t as features,
  n as loadFallbacks
};
