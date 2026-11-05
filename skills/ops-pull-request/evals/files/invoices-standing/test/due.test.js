import { test } from "node:test";
import assert from "node:assert/strict";
import { dueLabel } from "../src/due.js";

test("dueLabel prints the ISO date", () => {
  assert.equal(dueLabel("2037-09-25"), "2037-09-25");
});
