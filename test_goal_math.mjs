import assert from "node:assert/strict";
import test from "node:test";

import { contributionFencePlan } from "./goal_math.mjs";

test("fence derives two planned posts per month from the Monarch contribution", () => {
  assert.deepEqual(contributionFencePlan(73823.06, 80000, 5500), {
    postAmount: 2750,
    posts: 30,
    postsLeft: 3,
    set: 27,
  });
});

test("a funded goal has no posts left", () => {
  assert.deepEqual(contributionFencePlan(80000, 80000, 5500), {
    postAmount: 2750,
    posts: 30,
    postsLeft: 0,
    set: 30,
  });
});

test("a missing contribution cadence does not revive a stale hard-coded amount", () => {
  assert.deepEqual(contributionFencePlan(1000, 80000, 0), {
    postAmount: 0,
    posts: 1,
    postsLeft: 0,
    set: 0,
  });
});
