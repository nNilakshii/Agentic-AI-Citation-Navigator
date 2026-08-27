import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App.jsx";
import { paper, samples } from "./test/fixtures.js";

vi.mock("./lib/api.js");

// pdf.js needs a canvas and a worker, neither of which jsdom provides. The
// viewer is exercised for real in the build + browser smoke test; here it is
// replaced by a probe that records the props App hands it.
vi.mock("./components/PdfViewer.jsx", () => ({
  default: (props) => (
    <div
      data-testid="pdf-viewer-stub"
      data-file-url={props.fileUrl ?? ""}
      data-scroll-page={props.scrollToPage?.page ?? ""}
      data-highlight-count={props.highlightSentences?.length ?? 0}
    >
      {/* Lets a test drive the scroll tracking the real viewer reports. */}
      <button type="button" onClick={() => props.onPageChange?.(0)}>
        scroll to page 0
      </button>
      <button type="button" onClick={() => props.onPageChange?.(1)}>
        scroll to page 1
      </button>
    </div>
  ),
}));

const api = await import("./lib/api.js");

beforeEach(() => {
  api.listSamples.mockResolvedValue(samples);
  api.parseSample.mockResolvedValue(paper);
  api.uploadPaper.mockResolvedValue(paper);
  api.pdfUrl.mockImplementation((id) => `/api/reader/papers/${id}/pdf`);
});

/** Render and let the on-mount samples fetch settle before asserting. */
async function renderApp() {
  render(<App />);
  return screen.findByRole("button", { name: "attention is all you need" });
}

async function openSamplePaper() {
  const sample = await renderApp();
  await userEvent.click(sample);
  await screen.findByText("Attention Is All You Need");
}

describe("opening a paper", () => {
  it("lists the backend's samples on mount", async () => {
    render(<App />);
    expect(await screen.findByRole("button", { name: "bert" })).toBeInTheDocument();
  });

  it("parses the chosen sample and shows its title and metadata", async () => {
    await openSamplePaper();

    expect(api.parseSample).toHaveBeenCalledWith("attention-is-all-you-need.pdf");
    expect(
      screen.getByText("3 pages · 3 sentences · arXiv:1706.03762v7"),
    ).toBeInTheDocument();
  });

  it("points the viewer at the parsed paper's PDF", async () => {
    await openSamplePaper();

    expect(screen.getByTestId("pdf-viewer-stub")).toHaveAttribute(
      "data-file-url",
      `/api/reader/papers/${paper.paper_id}/pdf`,
    );
  });

  it("parses an uploaded file", async () => {
    await renderApp();
    const file = new File([new Uint8Array([1])], "mine.pdf", {
      type: "application/pdf",
    });

    await userEvent.upload(screen.getByLabelText("Open a PDF"), file);

    await waitFor(() => expect(api.uploadPaper).toHaveBeenCalledWith(file));
    expect(await screen.findByText("Attention Is All You Need")).toBeInTheDocument();
  });

  it("shows nothing is open before a paper is chosen", async () => {
    await renderApp();
    expect(screen.getByText("No paper open")).toBeInTheDocument();
  });
});

describe("the outline", () => {
  it("appears only once a paper is open", async () => {
    const sample = await renderApp();
    expect(screen.queryByText("Outline")).not.toBeInTheDocument();

    await userEvent.click(sample);
    await screen.findByText("Attention Is All You Need");

    expect(screen.getByText("Outline")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /1 Introduction/ })).toBeInTheDocument();
  });

  it("asks the viewer to scroll to the section's page", async () => {
    await openSamplePaper();

    await userEvent.click(screen.getByRole("button", { name: /1 Introduction/ }));

    expect(screen.getByTestId("pdf-viewer-stub")).toHaveAttribute(
      "data-scroll-page",
      "1",
    );
  });

  it("highlights the selected section's sentences", async () => {
    await openSamplePaper();
    expect(screen.getByTestId("pdf-viewer-stub")).toHaveAttribute(
      "data-highlight-count",
      "0",
    );

    await userEvent.click(screen.getByRole("button", { name: /Abstract/ }));

    // Exactly the one sentence whose section_id is the Abstract's.
    expect(screen.getByTestId("pdf-viewer-stub")).toHaveAttribute(
      "data-highlight-count",
      "1",
    );
  });

  it("marks the clicked section as current", async () => {
    await openSamplePaper();

    await userEvent.click(screen.getByRole("button", { name: /1 Introduction/ }));

    expect(screen.getByRole("button", { name: /1 Introduction/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  it("follows the reader's scrolling when no section was clicked", async () => {
    await openSamplePaper();

    await userEvent.click(screen.getByRole("button", { name: "scroll to page 1" }));

    expect(screen.getByRole("button", { name: /1 Introduction/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  it("ignores the pages a smooth scroll travels through", async () => {
    // Regression: clicking a section on page 2 made the outline mark whatever
    // section the scroll flew past on page 1, because the observer reports
    // every page in between.
    await openSamplePaper();

    await userEvent.click(screen.getByRole("button", { name: /1.1 Motivation/ }));
    await userEvent.click(screen.getByRole("button", { name: "scroll to page 1" }));

    expect(screen.getByRole("button", { name: /1.1 Motivation/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  it("does not let page-level scrolling undo a click on the same page", async () => {
    // Regression: a page holds several sections, so scroll tracking arriving
    // at the jumped-to page used to re-mark that page's first section and
    // silently move the highlight off what the reader actually chose.
    await openSamplePaper();

    await userEvent.click(screen.getByRole("button", { name: /Abstract/ }));
    await userEvent.click(screen.getByRole("button", { name: "scroll to page 0" }));

    expect(screen.getByRole("button", { name: /Abstract/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(screen.getByRole("button", { name: /Front matter/ })).not.toHaveAttribute(
      "aria-current",
    );
    expect(screen.getByTestId("pdf-viewer-stub")).toHaveAttribute(
      "data-highlight-count",
      "1",
    );
  });
});

describe("the reading goal", () => {
  it("defaults to Skim and is pressed", async () => {
    await renderApp();
    expect(screen.getByRole("button", { name: "Skim" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("switches when another goal is chosen", async () => {
    await renderApp();

    await userEvent.click(screen.getByRole("button", { name: "Critique" }));

    expect(screen.getByRole("button", { name: "Critique" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Skim" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });
});

describe("failures", () => {
  it("shows the backend's message when a parse fails", async () => {
    api.parseSample.mockRejectedValue(new Error("notes.txt is not a PDF"));
    const sample = await renderApp();

    await userEvent.click(sample);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "notes.txt is not a PDF",
    );
  });

  it("reports an unreachable backend instead of rendering an empty list", async () => {
    api.listSamples.mockRejectedValue(new Error("Cannot reach the backend."));
    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Cannot reach the backend.",
    );
  });

  it("clears a previous error on a successful parse", async () => {
    api.parseSample.mockRejectedValueOnce(new Error("boom"));
    const sample = await renderApp();

    await userEvent.click(sample);
    expect(await screen.findByRole("alert")).toBeInTheDocument();

    await userEvent.click(sample);
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });
});
