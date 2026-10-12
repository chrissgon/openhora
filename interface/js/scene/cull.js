// Which labels are drawn: pure, no document. A label is {id, rank, rect: {left, top, right, bottom}}; a lower rank is
// kept first (the selected item, then a decision badge, then a running sign, then a name). A label that overlaps one
// already kept, with a margin, is dropped, and no more than `max` are kept.

export const MAX_LABELS = 12;

/** The ids kept, as a Set. */
export function cull(items, { max = MAX_LABELS, margin = 2 } = {}) {
  const kept = [];
  const order = items.map((item, index) => ({ item, index })).sort((a, b) => a.item.rank - b.item.rank || a.index - b.index);
  for (const { item } of order) {
    if (kept.length >= max) break;
    const r = item.rect;
    const overlaps = kept.some((k) => !(r.right < k.rect.left - margin || r.left > k.rect.right + margin
      || r.bottom < k.rect.top - margin || r.top > k.rect.bottom + margin));
    if (!overlaps) kept.push(item);
  }
  return new Set(kept.map((k) => k.id));
}

/** The rank of a city label: 0 selected, then 1 with decisions waiting, 2 running, 3 a name only. */
export function rankOf({ selected, decisions, running }) {
  if (selected) return 0;
  if (decisions > 0) return 1;
  if (running) return 2;
  return 3;
}
