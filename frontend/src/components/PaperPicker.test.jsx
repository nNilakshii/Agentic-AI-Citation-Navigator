import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import PaperPicker from "./PaperPicker.jsx";
import { samples } from "../test/fixtures.js";

describe("PaperPicker", () => {
  it("shows sample papers under readable names", () => {
    render(<PaperPicker samples={samples} />);
    expect(
      screen.getByRole("button", { name: "attention is all you need" }),
    ).toBeInTheDocument();
  });

  it("reports the chosen sample by its real filename", async () => {
    const onPickSample = vi.fn();
    render(<PaperPicker samples={samples} onPickSample={onPickSample} />);

    await userEvent.click(screen.getByRole("button", { name: "bert" }));

    expect(onPickSample).toHaveBeenCalledWith("bert.pdf");
  });

  it("marks the sample that is currently open", () => {
    render(<PaperPicker samples={samples} currentFilename="bert.pdf" />);
    expect(screen.getByRole("button", { name: "bert" })).toHaveClass(
      "picker__sample--active",
    );
  });

  it("passes an uploaded file up", async () => {
    const onUpload = vi.fn();
    render(<PaperPicker samples={samples} onUpload={onUpload} />);

    const file = new File([new Uint8Array([1])], "mine.pdf", {
      type: "application/pdf",
    });
    await userEvent.upload(screen.getByLabelText("Open a PDF"), file);

    expect(onUpload).toHaveBeenCalledWith(file);
  });

  it("disables the controls while a parse is running", () => {
    render(<PaperPicker samples={samples} busy />);
    expect(screen.getByRole("button", { name: "Open a PDF…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "bert" })).toBeDisabled();
  });

  it("hides the sample list when the backend offers none", () => {
    render(<PaperPicker samples={[]} />);
    expect(screen.queryByText("Sample papers")).not.toBeInTheDocument();
  });
});

describe("readiness markers", () => {
  const coverage = [
    { filename: "attention-is-all-you-need.pdf", ready: ["skim", "critique"] },
    { filename: "bert.pdf", ready: [] },
  ];

  function renderWithCoverage(goalId = "skim") {
    render(
      <PaperPicker
        samples={["attention-is-all-you-need.pdf", "bert.pdf"]}
        coverage={coverage}
        goalId={goalId}
        onPickSample={() => {}}
        onUpload={() => {}}
      />,
    );
  }

  it("marks a paper ready only for the goals it has a path for", () => {
    renderWithCoverage("skim");

    const buttons = screen.getAllByRole("button", { name: /attention|bert/ });
    expect(buttons[0].textContent).toContain("ready");
    expect(buttons[1].textContent).toContain("new");
  });

  it("re-marks when the goal changes", () => {
    // Attention has skim and critique, not in-depth.
    renderWithCoverage("in-depth");

    expect(
      screen.getByRole("button", { name: "attention is all you need" }).textContent,
    ).toContain("new");
  });

  it("keeps the badge out of the accessible name", () => {
    // Regression: the badge text joined the button's name, so every test and
    // every screen reader saw "attention is all you need ready".
    renderWithCoverage("skim");

    const button = screen.getByRole("button", { name: "attention is all you need" });
    expect(button).toBeInTheDocument();
    expect(button.title).toMatch(/instantly/);
  });

  it("marks nothing until coverage is known", () => {
    render(
      <PaperPicker
        samples={["attention-is-all-you-need.pdf"]}
        coverage={null}
        goalId="skim"
        onPickSample={() => {}}
      />,
    );

    const button = screen.getByRole("button", { name: "attention is all you need" });
    expect(button.textContent).not.toMatch(/ready|new/);
  });
});
