/**
 * The explanation panel (task 1.8).
 *
 * The property that matters is grounding: an explanation is generated prose,
 * so it must never appear without the sentence it came from.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import ExplanationPanel from "./ExplanationPanel.jsx";

const items = [
  {
    id: "s00001",
    text: "We propose a new architecture based solely on attention.",
    page: 0,
    importance: 5,
    why: "states the core claim",
    plain: "The authors say their new model beats what came before.",
  },
  {
    id: "s00002",
    text: "Our model achieves 28.4 BLEU on WMT 2014 English-to-German.",
    page: 7,
    importance: 3,
    why: "headline number",
    plain: "It scores 28.4 on a standard translation benchmark.",
  },
];

function setup(props = {}) {
  const onSelect = vi.fn();
  render(<ExplanationPanel items={items} onSelect={onSelect} {...props} />);
  return { onSelect };
}

describe("grounding", () => {
  it("always shows the source sentence beside the explanation", () => {
    setup();

    for (const item of items) {
      expect(screen.getByText(item.plain)).toBeInTheDocument();
      // The sentence is the evidence the explanation is checked against.
      expect(screen.getByText(item.text)).toBeInTheDocument();
    }
  });

  it("quotes the sentence verbatim", () => {
    setup();

    const quotes = document.querySelectorAll(".explain__quote");
    expect([...quotes].map((q) => q.textContent)).toEqual(items.map((i) => i.text));
  });

  it("falls back to the reason rather than a gap when there is no explanation", () => {
    // Paths cached before 1.8 have no `plain`.
    setup({ items: [{ ...items[0], plain: "" }] });

    expect(screen.getByText("states the core claim")).toBeInTheDocument();
    expect(screen.getByText(items[0].text)).toBeInTheDocument();
  });
});

describe("presentation", () => {
  it("lists every passage in the order given", () => {
    setup();

    const entries = document.querySelectorAll(".explain__item");
    expect(entries).toHaveLength(2);
    expect(entries[0].textContent).toContain(items[0].plain);
  });

  it("counts the passages and names the goal", () => {
    setup({ goalLabel: "skim" });
    expect(screen.getByText(/2 passages for skim/)).toBeInTheDocument();
  });

  it("uses a singular for one passage", () => {
    setup({ items: [items[0]] });
    expect(screen.getByText(/1 passage[^s]/)).toBeInTheDocument();
  });

  it("shows each passage's page and priority", () => {
    setup();

    expect(screen.getByText("p. 8")).toBeInTheDocument();
    expect(screen.getByText("Priority 5 of 5")).toBeInTheDocument();
  });

  it("renders nothing when there is no path", () => {
    const { container } = render(<ExplanationPanel items={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("navigation", () => {
  it("reports the passage the reader picked", async () => {
    const { onSelect } = setup();

    await userEvent.click(screen.getByText(items[1].plain));

    expect(onSelect).toHaveBeenCalledWith(items[1]);
  });

  it("marks the active passage for assistive tech", () => {
    setup({ activeId: "s00002" });

    const entries = document.querySelectorAll(".explain__item");
    expect(entries[1]).toHaveAttribute("aria-current", "true");
    expect(entries[0]).not.toHaveAttribute("aria-current");
  });

  it("is reachable by keyboard", async () => {
    const { onSelect } = setup();

    await userEvent.tab();
    await userEvent.keyboard("{Enter}");

    expect(onSelect).toHaveBeenCalledWith(items[0]);
  });
});
