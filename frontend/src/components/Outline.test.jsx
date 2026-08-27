import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import Outline from "./Outline.jsx";
import { paper } from "../test/fixtures.js";

describe("Outline", () => {
  it("lists every section with its page", () => {
    render(<Outline sections={paper.sections} />);

    expect(screen.getByText("1 Introduction")).toBeInTheDocument();
    expect(screen.getByText("Abstract")).toBeInTheDocument();
    // "1 Introduction" starts on backend page 1, shown to the reader as p. 2.
    const introduction = screen.getByRole("button", { name: /1 Introduction/ });
    expect(introduction).toHaveTextContent("p. 2");
  });

  it("reports the clicked section to its parent", async () => {
    const onSelect = vi.fn();
    render(<Outline sections={paper.sections} onSelect={onSelect} />);

    await userEvent.click(screen.getByRole("button", { name: /1 Introduction/ }));

    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ id: 2, title: "1 Introduction", page: 1 }),
    );
  });

  it("marks the active section for assistive technology", () => {
    render(<Outline sections={paper.sections} activeSectionId={1} />);

    const active = screen.getByRole("button", { name: /Abstract/ });
    expect(active).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: /Front matter/ })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("indents a subsection further than its parent", () => {
    render(<Outline sections={paper.sections} />);

    const parent = screen.getByRole("button", { name: /1 Introduction/ });
    const child = screen.getByRole("button", { name: /1.1 Motivation/ });
    expect(parseFloat(child.style.paddingLeft)).toBeGreaterThan(
      parseFloat(parent.style.paddingLeft),
    );
  });

  it("says so when the parser found no sections", () => {
    render(<Outline sections={[]} />);
    expect(screen.getByText(/No sections detected/)).toBeInTheDocument();
  });
});
