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
