import { describe, expect, it } from "vitest";

import { anchorLabel, groupAnchors, padTarget, targetsOnPage } from "./citations.js";

const box = (page, x0 = 0) => ({ page, x0, y0: 0, x1: x0 + 5, y1: 10 });
const anchor = (id, text, ref, start, bboxes = [box(0)]) => ({
  id,
  text,
  start_char: start,
  end_char: start + text.length,
  reference_id: ref,
  bboxes,
});

describe("groupAnchors", () => {
  it("merges anchors that share a span into one target", () => {
    const groups = groupAnchors([
      anchor("c1", "1", "r1", 10),
      anchor("c2", "2", "r2", 10),
      anchor("c3", "3", "r3", 20),
    ]);
    expect(groups.map((g) => g.anchors.map((a) => a.id))).toEqual([["c1", "c2"], ["c3"]]);
  });

  it("drops anchors with no reference or no place on the page", () => {
    const groups = groupAnchors([
      anchor("c1", "1", null, 10),
      anchor("c2", "2", "r2", 20, []),
      anchor("c3", "3", "r3", 30),
    ]);
    expect(groups.map((g) => g.key)).toEqual(["30-31"]);
  });

  it("copes with no anchors at all", () => {
    expect(groupAnchors(undefined)).toEqual([]);
  });
});

describe("targetsOnPage", () => {
  it("gives a wrapped marker one target per rectangle on that page", () => {
    const [group] = groupAnchors([anchor("c1", "Devlin et al.", "r1", 0, [box(0), box(0, 50), box(1)])]);
    expect(targetsOnPage([group], 0)).toHaveLength(2);
    expect(targetsOnPage([group], 1)).toHaveLength(1);
    expect(targetsOnPage([group], 2)).toHaveLength(0);
  });
});

describe("padTarget", () => {
  it("grows a tiny marker about its centre", () => {
    const padded = padTarget({ left: 100, top: 50, width: 4, height: 10 }, 16);
    expect(padded).toEqual({ left: 94, top: 47, width: 16, height: 16 });
  });

  it("leaves a big enough target alone", () => {
    const css = { left: 1, top: 2, width: 40, height: 20 };
    expect(padTarget(css, 16)).toEqual(css);
  });
});

describe("anchorLabel", () => {
  it("brackets numbers and leaves names as printed", () => {
    expect(anchorLabel({ text: "12" })).toBe("[12]");
    expect(anchorLabel({ text: "Devlin et al., 2019" })).toBe("Devlin et al., 2019");
  });
});
