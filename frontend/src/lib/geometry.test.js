import { describe, expect, it } from "vitest";

import { bboxToCss, bboxesOnPage, scaleFor } from "./geometry.js";
import { paper } from "../test/fixtures.js";

describe("scaleFor", () => {
  it("is the ratio of rendered pixels to PDF points", () => {
    expect(scaleFor(1224, 612)).toBe(2);
    expect(scaleFor(612, 612)).toBe(1);
  });

  it("falls back to 1 before the page has been measured", () => {
    expect(scaleFor(0, 612)).toBe(1);
    expect(scaleFor(800, 0)).toBe(1);
    expect(scaleFor(undefined, undefined)).toBe(1);
  });
});

describe("bboxToCss", () => {
  const bbox = { page: 0, x0: 72, y0: 100, x1: 300, y1: 112 };

  it("maps points to pixels at scale 1", () => {
    expect(bboxToCss(bbox, 1)).toEqual({
      left: 72,
      top: 100,
      width: 228,
      height: 12,
    });
  });

  it("scales every dimension together", () => {
    expect(bboxToCss(bbox, 2)).toEqual({
      left: 144,
      top: 200,
      width: 456,
      height: 24,
    });
  });

  it("never produces a negative size from an inverted box", () => {
    const inverted = { page: 0, x0: 300, y0: 112, x1: 72, y1: 100 };
    const css = bboxToCss(inverted, 1);
    expect(css.width).toBe(0);
    expect(css.height).toBe(0);
  });

  it("keeps a highlight inside the page it was measured on", () => {
    // A 612x792pt page rendered 800px wide.
    const scale = scaleFor(800, 612);
    const css = bboxToCss({ page: 0, x0: 0, y0: 0, x1: 612, y1: 792 }, scale);
    expect(css.left).toBe(0);
    expect(css.width).toBeCloseTo(800, 5);
    expect(css.height).toBeCloseTo(792 * (800 / 612), 5);
  });
});

describe("bboxesOnPage", () => {
  it("collects boxes across sentences for one page", () => {
    expect(bboxesOnPage(paper.sentences, 0)).toHaveLength(2);
  });

  it("keeps every box of a sentence that wraps", () => {
    expect(bboxesOnPage(paper.sentences, 1)).toHaveLength(2);
  });

  it("returns nothing for a page with no text", () => {
    expect(bboxesOnPage(paper.sentences, 2)).toEqual([]);
  });

  it("tolerates missing input", () => {
    expect(bboxesOnPage(undefined, 0)).toEqual([]);
    expect(bboxesOnPage([{ page: 0 }], 0)).toEqual([]);
  });
});

describe("importance propagation (1.7)", () => {
  it("carries a sentence's importance onto each of its bboxes", () => {
    const sentences = [
      {
        importance: 4,
        bboxes: [
          { page: 0, x0: 0, y0: 0, x1: 1, y1: 1 },
          { page: 0, x0: 2, y0: 2, x1: 3, y1: 3 },
        ],
      },
    ];

    const found = bboxesOnPage(sentences, 0);

    expect(found).toHaveLength(2);
    expect(found.every((b) => b.importance === 4)).toBe(true);
  });

  it("leaves a sentence without importance untouched", () => {
    const bbox = { page: 0, x0: 0, y0: 0, x1: 1, y1: 1 };

    expect(bboxesOnPage([{ bboxes: [bbox] }], 0)[0]).toBe(bbox);
  });
});
