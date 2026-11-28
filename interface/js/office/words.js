// The words of the office, one table per language. Only English exists in slice 1: the lookup takes the language so that the project's language
// setting (decision O2) can choose a table later without a change to a caller. A key with a count has one form per plural rule of the language
// (`.one`, `.other`); the state words equal the floors list's (floor-model.js `stateWords`), and a test keeps them equal.

export const EN = Object.freeze({
  "office.title": "Office",
  "office.room": "All areas",
  "office.waiting.one": "{n} decision waiting for you",
  "office.waiting.other": "{n} decisions waiting for you",
  "office.decisions.one": "{n} decision",
  "office.decisions.other": "{n} decisions",
  "office.list": "Agents in the office",
  "office.loading": "Loading the agents...",
  "office.fallback": "This browser cannot draw the office. Every agent is listed below.",
  "office.overflow.one": "1 more agent is not drawn; it is listed below.",
  "office.overflow.other": "{n} more agents are not drawn; they are listed below.",
  "office.figure": "{name}, {state}",
  "state.working": "Running",
  "state.waiting": "Waiting for you",
  "state.ready": "Queued",
  "state.idle": "Idle",
  "state.off": "Off, mode is stopped",
});

const TABLES = { en: EN };

/** The text of `key` in `language`; with a number `n` the plural form of that language; a missing key falls back to English, then to the key itself. */
export function word(key, { n, language = "en", vars = {} } = {}) {
  const table = TABLES[language] || EN;
  let keys = [key];
  if (typeof n === "number") {
    let rule = "other";
    try {
      rule = new Intl.PluralRules(language).select(n);
    } catch (e) {
      rule = "other";
    }
    keys = [`${key}.${rule}`, `${key}.other`];
  }
  let text = key;
  for (const source of [table, EN]) {
    const found = keys.find((k) => typeof source[k] === "string");
    if (found) {
      text = source[found];
      break;
    }
  }
  const values = { ...vars };
  if (typeof n === "number") values.n = n;
  for (const [name, value] of Object.entries(values)) text = text.split(`{${name}}`).join(String(value));
  return text;
}
