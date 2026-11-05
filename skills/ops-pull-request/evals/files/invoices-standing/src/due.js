// The label printed on an invoice for its due date, e.g. "2037-09-25".
export function dueLabel(isoDate) {
  const date = new Date(isoDate);
  return date.toLocaleDateString("en-CA");
}
