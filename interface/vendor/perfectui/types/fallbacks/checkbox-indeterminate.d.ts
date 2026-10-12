/**
 * Fallback for the `indeterminate` attribute on a checkbox
 * (ARCHITECTURE.md §8.4).
 *
 * There is no native attribute for this — `indeterminate` is a property only —
 * so this module always loads. It is the single exception to the rule that a
 * fallback reads native attributes only.
 *
 * No MutationObserver (ARCHITECTURE.md rule 9): the attribute is applied at
 * load, when a `.pui-checkbox` carrying it renders (the stylesheet gives it a
 * zero-length animation, whose `animationstart` bubbles to `document`), and on
 * the next interaction, which covers pages that disable animations (ADR-0001).
 */
/** Side-effect module: this marks the file as ESM so nothing leaks to global scope. */
export {};
