/**
 * Fallback for CSS anchor positioning (ARCHITECTURE.md §8).
 *
 * Places an open popover next to the element that opened it. The anchor is
 * found from the native attributes that already point at the popover, so this
 * module needs no state shared with the other fallbacks and no attribute of
 * its own.
 *
 * The side comes from the same classes the CSS uses — `pui-top`, `pui-bottom`,
 * `pui-start`, `pui-end` — falling back to the default of each component: a
 * tooltip sits above its anchor, a menu below it. Either flips to the opposite
 * side when the preferred one does not fit, which is what
 * position-try-fallbacks does natively.
 */
/** Side-effect module: this marks the file as ESM so nothing leaks to global scope. */
export {};
