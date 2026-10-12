// The service's token, for this browser session only. It lives in this module's memory and in sessionStorage (which
// the browser drops when the tab closes). It is never put in a URL, written to any other storage or logged, and nothing in
// this file prints it.

const KEY = "workbench.session.credential";
let memory = null;

/** True when the text has the shape of the service's token: one run of printable characters, 32 to 512 of them. */
export function looksLikeToken(text) {
  return typeof text === "string" && /^[\x21-\x7e]{32,512}$/.test(text);
}

/** The token held for this session, or null. */
export function getToken() {
  if (memory) return memory;
  try {
    const stored = window.sessionStorage.getItem(KEY);
    if (stored && looksLikeToken(stored)) memory = stored;
  } catch (e) {
    // sessionStorage can be blocked; the token then lives in memory only.
  }
  return memory;
}

/** Keep the token for this session. */
export function setToken(token) {
  memory = token;
  try {
    window.sessionStorage.setItem(KEY, token);
  } catch (e) {
    // memory only
  }
}

/** Forget the token. */
export function clearToken() {
  memory = null;
  try {
    window.sessionStorage.removeItem(KEY);
  } catch (e) {
    // nothing to remove
  }
}
