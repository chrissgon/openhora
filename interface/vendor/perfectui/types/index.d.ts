/**
 * Fallback loader. The only JS that runs eagerly.
 * Detects native support and dynamically imports only the missing fallbacks.
 * See ARCHITECTURE.md §8.
 */
export interface Feature {
    /** Must match the file name in ./fallbacks */
    name: string;
    /** Returns true when the browser supports the feature natively. */
    supported: () => boolean;
    /** Imports the fallback module. Never called when supported() is true. */
    load: () => Promise<unknown>;
}
/**
 * Registry. Order does not matter: each entry is checked and loaded on its own.
 *
 * The detection expressions were verified in Chrome 153 (September 2026).
 * Re-check them against MDN when touching this file: these property names are
 * young enough to still move.
 */
export declare const features: Feature[];
export declare function loadFallbacks(list?: Feature[]): void;
