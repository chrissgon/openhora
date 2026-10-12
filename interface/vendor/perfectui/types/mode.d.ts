/**
 * Color mode. Sets data-pui-mode on <html> and persists it in a cookie so the
 * server can render the attribute during SSR and avoid a flash.
 * See ARCHITECTURE.md §7.
 */
export type Mode = "system" | "light" | "dark";
/**
 * Applies a mode and persists it. "system" removes both the attribute and the
 * cookie, falling back to the user's OS preference. No-op during SSR.
 */
export declare function setMode(mode?: Mode): void;
/**
 * Reads the persisted mode. Returns "system" when nothing is stored, which
 * means the OS preference is in use. Returns "system" during SSR.
 */
export declare function getMode(): Mode;
