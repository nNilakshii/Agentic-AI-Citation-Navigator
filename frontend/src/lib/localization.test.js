import { describe, expect, it } from "vitest";

import { excerpt, passageSentences, scrollTarget, splitAbstract } from "./localization.js";

const paper = {
  sentences: [
    { id: "s1", bboxes: [{ page: 0, y0: 50 }] },
    { id: "s2", bboxes: [{ page: 1, y0: 70 }, { page: 1, y0: 82 }] },
    { id: "s3", bboxes: [] },
  ],
};

describe("passageSentences", () => {
  it("returns the passage's sentences, marked focused", () => {
    const found = passageSentences(paper, { sentence_ids: ["s2", "s1"] });
    expect(found.map((s) => s.id)).toEqual(["s1", "s2"]);
    expect(found.every((s) => s.focused)).toBe(true);
  });

  it("is empty without a paper or a passage", () => {
    expect(passageSentences(null, { sentence_ids: ["s1"] })).toEqual([]);
    expect(passageSentences(paper, null)).toEqual([]);
  });
});

describe("scrollTarget", () => {
  it("aims at the passage's first rectangle", () => {
    expect(scrollTarget(passageSentences(paper, { sentence_ids: ["s2"] }))).toEqual({ page: 1, y: 70 });
  });

  it("skips sentences with no rectangles, and gives null for none", () => {
    expect(scrollTarget([{ bboxes: [] }, { bboxes: [{ page: 3, y0: 9 }] }])).toEqual({ page: 3, y: 9 });
    expect(scrollTarget([])).toBeNull();
  });
});

describe("excerpt", () => {
  it("keeps short text and trims long text on a word", () => {
    expect(excerpt("a  short\ntext")).toBe("a short text");
    const long = "word ".repeat(60);
    const cut = excerpt(long, 50);
    expect(cut.endsWith("…")).toBe(true);
    expect(cut.length).toBeLessThanOrEqual(51);
    expect(cut).not.toMatch(/wor…$/);
  });
});

describe("splitAbstract", () => {
  it("splits around the passage", () => {
    expect(splitAbstract("abcdef", { start_char: 2, end_char: 4 })).toEqual({
      before: "ab",
      match: "cd",
      after: "ef",
    });
  });

  it("refuses offsets that do not fit the text", () => {
    expect(splitAbstract("abc", { start_char: 1, end_char: 9 })).toBeNull();
    expect(splitAbstract("abc", null)).toBeNull();
  });
});
