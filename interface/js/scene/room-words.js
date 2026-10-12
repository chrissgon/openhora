// The words a room's three objects say when the pointer is on them (round 4, `floor.html` and `lobby.html`): the dark tooltip over the owl, the board and the bookcase. Pure: no three.js
// and no document. The owl names its agent and its state from the model's tip, and says where a click goes when it is asking something (R-31); the board counts its notes by state;
// the bookcase counts its documents; `tooltipPlace` keeps the box inside the canvas.

/** What the owl's tooltip says: the agent and its state (the model's words), and `open the Inbox` when it asks something. */
export function agentTip(words, asks) {
  const base = words || "";
  return asks ? `${base}${base ? " · " : ""}open the Inbox` : base;
}

/**
 * The board's tooltip: `Tasks · 1 running, 1 left`, counting the notes by state in the order done, running, left, failed; none yet when it has none. `left` is the plate's own
 * count (the planned and the blocked tasks) when the model gives it, so that the tooltip and the plate say the same number; a note of a task that is neither (one that is
 * requested, say) is drawn as still to do and is not counted.
 */
export function tasksTip(notes, left = null) {
  const list = Array.isArray(notes) ? notes : [];
  const count = (state) => list.filter((n) => n === state).length;
  const parts = [[count("done"), "done"], [count("run"), "running"], [typeof left === "number" ? left : count("left"), "left"], [count("fail"), "failed"]]
    .filter(([n]) => n > 0).map(([n, word]) => `${n} ${word}`);
  return parts.length ? `Tasks · ${parts.join(", ")}` : "Tasks · none yet";
}

/** The bookcase's tooltip: `Documents · 7`, or `Documents · none yet`; `Documents` while they are unread (`null`). */
export function documentsTip(count) {
  if (typeof count !== "number") return "Documents";
  return count > 0 ? `Documents · ${count}` : "Documents · none yet";
}

/** True when the owl is asking something: its agent waits and has a decision open, so a click on it goes to the Inbox. */
export function asking(floor) {
  return floor.state === "waiting" && floor.decisions > 0;
}

/**
 * Where a tooltip of `wide` by `tall` pixels goes in a canvas of `size` {w, h}: {x, y} for its custom properties. Over an object (`above`, the object's top on the screen: the
 * box is centred on x and stands its height and ten pixels over y) it is moved in by half its width from the sides and let down under the top; at the pointer (`at`) it
 * stands to the right of it and low, and stays inside on the right.
 */
export function tooltipPlace({ above = null, at = { x: 0, y: 0 }, size, wide = 0, tall = 0, edge = 4 }) {
  if (!above) return { x: Math.min(size.w - 20, at.x + 14), y: at.y + 16 };
  const half = wide / 2 + edge;
  return { x: Math.min(Math.max(above.x, half), Math.max(half, size.w - half)), y: Math.max(above.y, tall + 10 + edge) };
}
