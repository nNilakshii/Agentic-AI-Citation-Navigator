/**
 * The daily-budget notice.
 *
 * It exists so an upload fails *before* the reader picks a file, not after
 * they have waited. So the thing worth testing is when it stays quiet.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import BudgetNotice from "./BudgetNotice.jsx";

describe("staying quiet", () => {
  it("says nothing with comfortable headroom", () => {
    const { container } = render(<BudgetNotice remaining={15} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says nothing before the budget is known", () => {
    expect(render(<BudgetNotice remaining={null} />).container).toBeEmptyDOMElement();
    expect(
      render(<BudgetNotice remaining={undefined} />).container,
    ).toBeEmptyDOMElement();
  });

  it("says nothing when the budget is unlimited", () => {
    // -1 is what the backend reports once billing removes the cap.
    const { container } = render(<BudgetNotice remaining={-1} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("warning", () => {
  it("warns as the ceiling approaches", () => {
    render(<BudgetNotice remaining={2} />);
    expect(screen.getByText(/2 new papers can be ranked today/)).toBeInTheDocument();
  });

  it("uses a singular for the last one", () => {
    render(<BudgetNotice remaining={1} />);
    expect(screen.getByText(/1 new paper can be ranked/)).toBeInTheDocument();
  });

  it("says plainly when there are none left", () => {
    render(<BudgetNotice remaining={0} />);
    expect(screen.getByText(/No new papers today/)).toBeInTheDocument();
  });

  it("always says the ready papers still work", () => {
    // The more important half: the demo is not broken, only uploads are.
    for (const remaining of [0, 1, 3]) {
      const { unmount } = render(<BudgetNotice remaining={remaining} />);
      expect(screen.getByText("ready")).toBeInTheDocument();
      unmount();
    }
  });
});
