// What the scene shows for a state, as plain choices with no three.js and no document, so a test can run them:
//   - a window is lit (a warm white, drawn unlit) when the agent of its floor is active, working or waiting for an answer, and dark otherwise,
//     resting or off (R-21; the maintainer's rule of 2026-10-08 lit it only while it worked; there is no in-between state);
//   - a line of the theme colour (the lot's, a floor's, the room's floor) is drawn only for the object the route selected: a hovered
//     object has the outline of its box or its shape (the engine's), never a standing line.

/** The window state of a floor: "lit" when its agent is active (working or waiting for an answer: the caller says), "grey" in every other case (idle, off, not accepted). */
export function windowState(active) {
  return active ? "lit" : "grey";
}

/** The colour of a window state: the warm recipe when lit, the border tone otherwise (the same rule in light and dark). */
export function windowColour(palette, state) {
  return state === "lit" ? palette.warm : palette.windows.grey;
}

/** A lit window is drawn with an unlit material; a grey one takes the light of the scene. */
export function windowUnlit(state) {
  return state === "lit";
}

/** True when the lines of object `id` are drawn: it is the one the route selected (the maintainer's rule: hover is the box alone). */
export function outlineVisible(id, selectedId) {
  return id !== null && id !== undefined && id === selectedId;
}

/** Show the lines of the registered objects ({id, lines}) that the route selected and hide all the others. */
export function applyOutlineVisibility(outlines, selectedId) {
  for (const o of outlines) {
    const on = outlineVisible(o.id, selectedId);
    for (const line of o.lines) line.visible = on;
  }
}

/**
 * What `show(kind, model)` must do, from what was shown before: "none" (the same model), "relabel" (the same structure, other words:
 * only the labels and tooltips change, nothing that moves is built again) or "build". `before` is {signature, structure, built};
 * `structureOf` is the builder's `structure` function or null (then the whole model is its structure).
 */
export function showPlan(before, kind, model, structureOf) {
  const signature = JSON.stringify([kind, model]);
  const structure = JSON.stringify([kind, structureOf ? structureOf(model) : model]);
  let action = "build";
  if (signature === before.signature) action = "none";
  else if (before.built && structure === before.structure) action = "relabel";
  return { action, signature, structure };
}
