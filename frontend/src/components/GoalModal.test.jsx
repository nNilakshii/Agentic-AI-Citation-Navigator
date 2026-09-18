/**
 * The goal modal in isolation (task 1.5) — chiefly the keyboard and focus
 * behaviour, which the App-level tests do not reach.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import GoalModal from "./GoalModal.jsx";
import { READING_GOALS } from "../lib/goals.js";

function setup(props = {}) {
  const onConfirm = vi.fn();
  const onDismiss = vi.fn();
  render(
    <GoalModal
      paperTitle="Attention Is All You Need"
      currentGoalId="skim"
      onConfirm={onConfirm}
      onDismiss={onDismiss}
      {...props}
    />,
  );
  return { onConfirm, onDismiss };
}

describe("presentation", () => {
  it("offers every reading goal with its blurb", () => {
    setup();

    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(READING_GOALS.length);
    for (const goal of READING_GOALS) {
      expect(screen.getByText(goal.label)).toBeInTheDocument();
      expect(screen.getByText(goal.blurb)).toBeInTheDocument();
    }
  });

  it("marks the current goal as checked", () => {
    setup({ currentGoalId: "in-depth" });

    expect(screen.getByRole("radio", { name: /In-depth/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByRole("radio", { name: /Skim/ })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("names the paper being opened", () => {
    setup();
    expect(screen.getByRole("dialog")).toHaveTextContent("Attention Is All You Need");
  });

  it("copes with a paper that has no title", () => {
    setup({ paperTitle: undefined });
    expect(screen.getByRole("dialog")).toHaveTextContent(
      "Your goal shapes what AURA highlights.",
    );
  });

  it("names the pending choice on the confirm button", async () => {
    setup();
    expect(
      screen.getByRole("button", { name: "Start reading · Skim" }),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("radio", { name: /Critique/ }));

    expect(
      screen.getByRole("button", { name: "Start reading · Critique" }),
    ).toBeInTheDocument();
  });
});

describe("choosing", () => {
  it("confirms the selected goal", async () => {
    const { onConfirm } = setup();

    await userEvent.click(screen.getByRole("radio", { name: /Critique/ }));
    await userEvent.click(screen.getByRole("button", { name: /^Start reading/ }));

    expect(onConfirm).toHaveBeenCalledWith("critique");
  });

  it("confirms the current goal when nothing is touched", async () => {
    const { onConfirm } = setup({ currentGoalId: "in-depth" });

    await userEvent.click(screen.getByRole("button", { name: /^Start reading/ }));

    expect(onConfirm).toHaveBeenCalledWith("in-depth");
  });

  it("selecting alone does not confirm", async () => {
    const { onConfirm, onDismiss } = setup();

    await userEvent.click(screen.getByRole("radio", { name: /Critique/ }));

    expect(onConfirm).not.toHaveBeenCalled();
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it("double-clicking an option confirms it outright", async () => {
    const { onConfirm } = setup();

    await userEvent.dblClick(screen.getByRole("radio", { name: /Critique/ }));

    expect(onConfirm).toHaveBeenCalledWith("critique");
  });
});

describe("dismissing", () => {
  it("dismisses on 'Not now'", async () => {
    const { onConfirm, onDismiss } = setup();

    await userEvent.click(screen.getByRole("button", { name: "Not now" }));

    expect(onDismiss).toHaveBeenCalled();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("dismisses on Escape", async () => {
    const { onDismiss } = setup();

    await userEvent.keyboard("{Escape}");

    expect(onDismiss).toHaveBeenCalled();
  });

  it("dismisses on a click that starts and ends on the backdrop", async () => {
    const { onDismiss } = setup();

    await userEvent.click(document.querySelector(".modal__backdrop"));

    expect(onDismiss).toHaveBeenCalled();
  });

  it("stays open when the click lands inside the dialog", async () => {
    const { onDismiss } = setup();

    await userEvent.click(screen.getByRole("dialog"));

    expect(onDismiss).not.toHaveBeenCalled();
  });
});

describe("keyboard", () => {
  it("opens with the current option focused", () => {
    setup({ currentGoalId: "critique" });
    expect(screen.getByRole("radio", { name: /Critique/ })).toHaveFocus();
  });

  it("moves the selection with arrow keys, as a radiogroup should", async () => {
    setup();

    await userEvent.keyboard("{ArrowDown}");

    const second = screen.getByRole("radio", { name: /In-depth/ });
    expect(second).toHaveFocus();
    expect(second).toHaveAttribute("aria-checked", "true");
  });

  it("wraps around at the ends", async () => {
    setup();

    await userEvent.keyboard("{ArrowUp}");

    expect(screen.getByRole("radio", { name: /Critique/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("is one tab stop, not three", () => {
    setup();

    const stops = screen
      .getAllByRole("radio")
      .filter((radio) => radio.getAttribute("tabindex") === "0");
    expect(stops).toHaveLength(1);
  });

  it("keeps Tab inside the dialog", async () => {
    setup();

    // Tab off the last control and focus should come back to the first, not
    // escape to the page behind the modal.
    const confirm = screen.getByRole("button", { name: /^Start reading/ });
    confirm.focus();
    await userEvent.tab();

    expect(screen.getByRole("dialog").contains(document.activeElement)).toBe(true);
  });
});
