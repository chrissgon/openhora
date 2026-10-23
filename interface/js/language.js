// What the request form's language choice says, as pure functions with no document and no network (so a test runs them). The language is the one the
// deliverables of a request are written in: the project's `language` setting (runtime.json) unless the person picks another here, a choice the service records on
// the request and shows on the plan card before approval. Nothing is decided here: the rule of a tag is the service's (runtime/language.py); this only stops a
// text the rule would refuse from being sent.

/** The rule of a tag: two lower-case letters, optionally a hyphen and two upper-case letters (en, pt-BR). The service checks it again. */
export const TAG_RULE = /^[a-z]{2}(-[A-Z]{2})?$/;
export const TAG_PROBLEM = "A language is two lower-case letters, optionally a hyphen and two upper-case letters, such as en or pt-BR.";
export const LANGUAGE_HINT = "The language the deliverables are written in. Another tag typed below wins over the list. The plan shows the choice before you approve it.";
export const LISTED = Object.freeze(["en", "pt-BR", "es", "fr", "de"]);

/** The options of the language select: the project's own first ("Project language (pt-BR)", or "(en)" when the project sets none), then the short list. */
export function languageOptions(projectLanguage) {
  const project = typeof projectLanguage === "string" && TAG_RULE.test(projectLanguage) ? projectLanguage : "en";
  return [{ value: "", label: `Project language (${project})` }, ...LISTED.map((tag) => ({ value: tag, label: tag }))];
}

/** What the form sends: {value} (a tag, or "" for the project's) or {problem} when the typed text is not a tag. The typed text wins over the select. */
export function chosenLanguage(selected, typed) {
  const text = typeof typed === "string" ? typed.trim() : "";
  if (text) return TAG_RULE.test(text) ? { value: text } : { problem: TAG_PROBLEM };
  const tag = typeof selected === "string" ? selected : "";
  return tag && TAG_RULE.test(tag) ? { value: tag } : { value: "" };
}
