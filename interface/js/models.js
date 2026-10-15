// What the model pickers say, worked out from what the service returned: pure functions with no document and no network, so they run under a test.
// The inputs are the `models` list of the `skills` operation (one line for each model of the gate file: how many skills of the scope it is reliable for, its price
// with the day it was read) and `default_model`. Nothing is decided here: a band is the operation's word, a price is the table's, and the page recommends nothing but
// what the service names (`recommended` of a skill); the person's choice is never gated by a band (decision D34).

import { costWords, priceDate, priceWords } from "./views/control-model.js";

export const DEFAULT_LABEL = "Chosen for you (the project's default)";
export const AUTO_LABEL = "auto: the cheapest model that is reliable for the skill";
export const MODEL_HINT = "A model you name runs even where it has no reliable evidence; its deliveries then wait for you. auto picks the cheapest model with proof.";

/** "5 of 12 skills reliable" for one model's line of the service; "no skill in scope" when it has none. */
export function reliableWords(line) {
  const total = line && Number.isFinite(line.skills) ? line.skills : 0;
  const reliable = line && Number.isFinite(line.reliable) ? line.reliable : 0;
  if (!total) return "no skill in scope";
  return `reliable for ${reliable} of ${total} ${total === 1 ? "skill" : "skills"}`;
}

export const REVIEWED_WORDS = "output reviewed";
export const RECOMMENDED_WORDS = "recommended";

/** "<n> through community evidence alone: output reviewed" when some of the model's reliable skills rest on community evidence only; "" otherwise. */
export function communityWords(line) {
  const n = line && Number.isFinite(line.community_only) ? line.community_only : 0;
  return n > 0 ? `${n === 1 ? "one skill" : `${n} skills`} through community evidence alone: ${REVIEWED_WORDS}` : "";
}

/**
 * The label of a model in a request picker: "<id> · reliable for 5 of 12 skills · about $0.0012 a run · $0.02 in, $0.72 out per million tokens (read 2026-10-01)", then the
 * community words (the pair is ranked and chosen, its output is reviewed) and "recommended" for the model the service names (`recommended_model`: the cheapest reliable one).
 */
export function modelLabel(line, recommended = null) {
  const price = line && line.price ? `${priceWords(line.price)} (${priceDate(line.price)})` : "no price known";
  const parts = [line.model, reliableWords(line), costWords(line), price, communityWords(line)];
  if (recommended && line.model === recommended) parts.push(RECOMMENDED_WORDS);
  return parts.filter(Boolean).join(" · ");
}

/**
 * The label of a model in an agent's picker, from its `model_commands` line over the skills of the agent's pack: "<id> · reliable for 3 of 5 skills · about $0.0012 a run",
 * the community words and "recommended". auto and default say what they do; a line without figures (an older service) is the model's id alone.
 */
export function agentModelLabel(line, recommended = null) {
  if (!line || typeof line.model !== "string") return "";
  if (line.model === "default") return "default (the request's, else the project's)";
  if (line.model === "auto") return "auto (the cheapest model that is reliable for each skill)";
  if (!Number.isFinite(line.skills)) return line.model;
  const parts = [line.model, reliableWords(line), costWords(line), communityWords(line)];
  if (recommended && line.model === recommended) parts.push(RECOMMENDED_WORDS);
  return parts.filter(Boolean).join(" · ");
}

/**
 * The options of a model picker: [{value, label}]. The first is the choice that names nothing (the request's tasks follow the agent's model, the project's default
 * or auto), then auto, then one option for every model of the service's list. `defaultModel` is the project's default_model (null: auto), which the first label says;
 * `recommended` is the model the service recommends (`recommended_model` of the `skills` operation), which its label says.
 */
export function modelOptions(models, defaultModel, recommended = null) {
  const named = defaultModel ? `, ${defaultModel}` : ", auto";
  const lines = (Array.isArray(models) ? models : []).filter((line) => line && typeof line.model === "string" && line.model);
  return [
    { value: "", label: `${DEFAULT_LABEL}${named}` },
    { value: "auto", label: AUTO_LABEL },
    ...lines.map((line) => ({ value: line.model, label: modelLabel(line, recommended) })),
  ];
}

/** The words a request line shows for the model the person chose; "" when none was chosen. */
export function requestModelWords(model) {
  return typeof model === "string" && model ? `Model: ${model}` : "";
}
