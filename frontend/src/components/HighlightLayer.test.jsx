import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import HighlightLayer from "./HighlightLayer.jsx";

const bboxes = [
  { page: 0, x0: 72, y0: 100, x1: 300, y1: 112 },
  { page: 0, x0: 72, y0: 114, x1: 250, y1: 126 },
];

describe("HighlightLayer", () => {
  it("draws one rectangle per bbox", () => {
    const { container } = render(<HighlightLayer bboxes={bboxes} scale={1} />);
    expect(container.querySelectorAll(".highlight")).toHaveLength(2);
  });

  it("positions a rectangle from the bbox and scale", () => {
    const { container } = render(<HighlightLayer bboxes={[bboxes[0]]} scale={2} />);

    const rect = container.querySelector(".highlight");
    expect(rect.style.left).toBe("144px");
    expect(rect.style.top).toBe("200px");
    expect(rect.style.width).toBe("456px");
    expect(rect.style.height).toBe("24px");
  });

  it("renders nothing when there is nothing to highlight", () => {
    const { container } = render(<HighlightLayer bboxes={[]} scale={1} />);
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByTestId("highlight-layer")).not.toBeInTheDocument();
  });

  it("applies the variant class, so 1.7 and 2.12 can look different", () => {
    const { container } = render(
      <HighlightLayer bboxes={[bboxes[0]]} scale={1} variant="cited" />,
    );
    expect(container.querySelector(".highlight--cited")).toBeInTheDocument();
  });

  it("is hidden from assistive technology, being pure decoration", () => {
    render(<HighlightLayer bboxes={bboxes} scale={1} />);
    expect(screen.getByTestId("highlight-layer")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
  });
});

describe("importance (1.7)", () => {
  it("draws a more important span more strongly", () => {
    render(
      <HighlightLayer
        bboxes={[
          { page: 0, x0: 0, y0: 0, x1: 10, y1: 10, importance: 5 },
          { page: 0, x0: 0, y0: 20, x1: 10, y1: 30, importance: 1 },
        ]}
        scale={1}
      />,
    );

    const drawn = screen.getByTestId("highlight-layer").children;
    expect(drawn[0]).toHaveClass("highlight--i5");
    expect(drawn[1]).toHaveClass("highlight--i1");
  });

  it("clamps an out-of-range importance rather than emitting a bad class", () => {
    render(
      <HighlightLayer
        bboxes={[{ page: 0, x0: 0, y0: 0, x1: 10, y1: 10, importance: 99 }]}
        scale={1}
      />,
    );

    expect(screen.getByTestId("highlight-layer").firstChild).toHaveClass(
      "highlight--i5",
    );
  });

  it("falls back to the plain variant when there is no importance", () => {
    render(<HighlightLayer bboxes={[{ page: 0, x0: 0, y0: 0, x1: 10, y1: 10 }]} scale={1} />);

    const drawn = screen.getByTestId("highlight-layer").firstChild;
    expect(drawn).toHaveClass("highlight--path");
    expect(drawn.className).not.toMatch(/highlight--i\d/);
  });
});
