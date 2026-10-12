/**
 * Fallback for `interestfor` (ARCHITECTURE.md §8).
 *
 * Shows the target when the user shows interest in the trigger: hovering it,
 * focusing it with the keyboard, or pressing and holding on a touch screen.
 * That last path is why v0's tooltip did not work on mobile.
 *
 * Positioning is not this module's job — the anchor-positioning fallback
 * handles it when the browser lacks CSS anchor positioning too.
 */
/** Side-effect module: this marks the file as ESM so nothing leaks to global scope. */
export {};
