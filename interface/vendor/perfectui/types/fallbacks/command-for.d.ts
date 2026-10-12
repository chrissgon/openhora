/**
 * Fallback for `commandfor` / `command` on a button (ARCHITECTURE.md §8).
 *
 * Reads only the native attributes, so the markup is identical to the one a
 * supporting browser handles on its own. Delegated on document, which is what
 * makes it work for elements React or Vue insert later.
 */
/** Side-effect module: this marks the file as ESM so nothing leaks to global scope. */
export {};
