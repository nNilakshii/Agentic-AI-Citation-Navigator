/**
 * Joining a reading path back to the parse (task 1.7).
 *
 * The backend returns spans, not rectangles, so this join is what turns a
 * ranking into something drawable. Getting it wrong highlights the wrong text.
 */

import { describe, expect, it } from "vitest";

import { isPartial, pathSentences, pathSummary } from "./readingPath.js";
import { paper, readingPath } from "../test/fixtures.js";

describe("pathSentences", () => {
  it("resolves each item to its sentence, carrying importance and reason", () => {
    const resolved = pathSentences(paper, readingPath);

    expect(resolved).toHaveLength(2);
    expect(resolved[0].id).toBe("s00001");
    expect(resolved[0].importance).toBe(5);
    expect(resolved[0].why).toBe("states the core claim");
  });

  it("takes geometry from the parse, never from the path", () => {
    // The path carries no bboxes at all; they have to come from the sentence.
    const resolved = pathSentences(paper, readingPath);

    expect(resolved[0].bboxes).toEqual(
      paper.sentences.find((s) => s.id === "s00001").bboxes,
    );
    expect(resolved[1].bboxes).toHaveLength(2);
  });

  it("ignores an item whose sentence is not in the paper", () => {
    // Only reachable if a path outlives the parse it was built against.
    const stale = {
      ...readingPath,
      items: [...readingPath.items, { sentence_id: "s99999", importance: 5, why: "x" }],
    };

    expect(pathSentences(paper, stale)).toHaveLength(2);
  });

  it("returns nothing when either side is missing", () => {
    expect(pathSentences(null, readingPath)).toEqual([]);
    expect(pathSentences(paper, null)).toEqual([]);
    expect(pathSentences(paper, { ...readingPath, items: [] })).toEqual([]);
  });

  it("does not mutate the paper's sentences", () => {
    pathSentences(paper, readingPath);

    expect(paper.sentences.find((s) => s.id === "s00001").importance).toBeUndefined();
  });
});

describe("pathSummary", () => {
  it("reports how much of the paper is highlighted", () => {
    expect(pathSummary(readingPath)).toBe("2 of 3 sentences");
  });

  it("copes with a paper that had nothing to rank", () => {
    expect(pathSummary({ items: [], n_sentences_considered: 0 })).toMatch(/Nothing/);
  });
});

describe("isPartial", () => {
  it("is false for a complete path", () => {
    expect(isPartial(readingPath)).toBe(false);
  });

  it("is true when a batch failed", () => {
    // A truncated path looks exactly like a complete one, so this flag is the
    // only way the UI can be honest about it. See docs/build-log.md.
    expect(isPartial({ ...readingPath, n_batches_failed: 1 })).toBe(true);
  });

  it("is false for no path at all", () => {
    expect(isPartial(null)).toBe(false);
  });
});
