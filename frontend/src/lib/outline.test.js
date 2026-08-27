import { describe, expect, it } from "vitest";

import { pageLabel, paperSubtitle, sectionAt, withDepths } from "./outline.js";
import { paper } from "../test/fixtures.js";

describe("withDepths", () => {
  it("maps level 1 to depth 0 and level 2 to depth 1", () => {
    expect(withDepths(paper.sections).map((s) => s.depth)).toEqual([0, 0, 0, 1]);
  });

  it("clamps a jump in levels to one step of indent", () => {
    const jumpy = [{ level: 1 }, { level: 4 }, { level: 5 }];
    expect(withDepths(jumpy).map((s) => s.depth)).toEqual([0, 1, 2]);
  });

  it("treats a missing level as top level", () => {
    expect(withDepths([{ title: "x" }]).map((s) => s.depth)).toEqual([0]);
  });

  it("returns an empty list for missing input", () => {
    expect(withDepths(undefined)).toEqual([]);
  });
});

describe("sectionAt", () => {
  it("finds the section containing an offset", () => {
    expect(sectionAt(paper.sections, 0).title).toBe("Front matter");
    expect(sectionAt(paper.sections, 25).title).toBe("Abstract");
    expect(sectionAt(paper.sections, 39).title).toBe("1 Introduction");
  });

  it("treats end_char as exclusive", () => {
    expect(sectionAt(paper.sections, 19).title).toBe("Abstract");
  });

  it("returns null past the end of the document", () => {
    expect(sectionAt(paper.sections, 10_000)).toBeNull();
  });
});

describe("pageLabel", () => {
  it("converts a 0-based page index to a 1-based label", () => {
    expect(pageLabel(0)).toBe("p. 1");
    expect(pageLabel(14)).toBe("p. 15");
  });
});

describe("paperSubtitle", () => {
  it("summarises a parsed paper", () => {
    expect(paperSubtitle(paper)).toBe("3 pages · 3 sentences · arXiv:1706.03762v7");
  });

  it("works from a summary that has counts but no sentences array", () => {
    const summary = { source: { page_count: 1 }, n_sentences: 42 };
    expect(paperSubtitle(summary)).toBe("1 page · 42 sentences");
  });

  it("is empty with no paper", () => {
    expect(paperSubtitle(null)).toBe("");
  });
});
