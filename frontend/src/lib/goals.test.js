/**
 * The goal definitions (task 1.5). These ids are the contract with the 1.6
 * ranking endpoint, so the tests here are mostly about them not drifting.
 */

import { describe, expect, it } from "vitest";

import { DEFAULT_GOAL_ID, READING_GOALS, goalById } from "./goals.js";

describe("the goal list", () => {
  it("is the three goals the project scoped", () => {
    expect(READING_GOALS.map((goal) => goal.id)).toEqual([
      "skim",
      "in-depth",
      "critique",
    ]);
  });

  it("gives every goal the fields its consumers render", () => {
    for (const goal of READING_GOALS) {
      expect(goal.label).toBeTruthy();
      expect(goal.blurb).toBeTruthy();
      // `criteria` is what 1.6 will put in the ranking prompt.
      expect(goal.criteria).toBeTruthy();
    }
  });

  it("has a default that actually exists", () => {
    expect(READING_GOALS.some((goal) => goal.id === DEFAULT_GOAL_ID)).toBe(true);
  });
});

describe("goalById", () => {
  it("finds a goal", () => {
    expect(goalById("critique").label).toBe("Critique");
  });

  it("falls back to the default rather than returning undefined", () => {
    // Callers render straight off this, so a bad id must not crash the UI.
    expect(goalById("nonsense").id).toBe(DEFAULT_GOAL_ID);
    expect(goalById(undefined).id).toBe(DEFAULT_GOAL_ID);
  });
});
