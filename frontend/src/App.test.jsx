import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App.jsx";
import { paper, readingPath, samples } from "./test/fixtures.js";

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
  api.fetchReadingPath.mockResolvedValue(readingPath);
});

/** Render and let the on-mount samples fetch settle before asserting. */
async function renderApp() {
  render(<App />);
  return screen.findByRole("button", { name: "attention is all you need" });
}

/**
 * Open a paper and get past the goal modal (1.5), which every test about the
 * reader underneath it has to do first.
 */
async function openSamplePaper() {
  const sample = await renderApp();
  await userEvent.click(sample);
  await screen.findByRole("dialog");
  await userEvent.click(screen.getByRole("button", { name: /^Start reading/ }));
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
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
    // An uploaded paper asks for a goal just like a sample does.
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("shows nothing is open before a paper is chosen", async () => {
    await renderApp();
    expect(screen.getByText("No paper open")).toBeInTheDocument();
  });
});

describe("the outline", () => {
  it("appears only once a paper is open", async () => {
    await renderApp();
    expect(screen.queryByText("Outline")).not.toBeInTheDocument();

    await openSamplePaper();

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

  it("jumps to a section without painting it", async () => {
    // Up to 1.6 clicking a section highlighted its sentences, as a stand-in
    // for the ranker. The reading path owns highlighting now, and two
    // highlight systems on one page read as noise.
    await openSamplePaper();
    const before = screen
      .getByTestId("pdf-viewer-stub")
      .getAttribute("data-highlight-count");

    await userEvent.click(screen.getByRole("button", { name: /Abstract/ }));

    expect(screen.getByTestId("pdf-viewer-stub")).toHaveAttribute(
      "data-highlight-count",
      before,
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
  });
});

describe("the reading goal (1.5)", () => {
  it("defaults to Skim and is pressed", async () => {
    await renderApp();
    expect(screen.getByRole("button", { name: "Skim" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("switches when another goal is chosen in the sidebar", async () => {
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

  it("does not ask for a goal before a paper is open", async () => {
    await renderApp();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("asks for a goal when a paper opens", async () => {
    const sample = await renderApp();

    await userEvent.click(sample);

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    // The paper being opened is named, so the choice has context.
    expect(dialog).toHaveTextContent("Attention Is All You Need");
  });

  it("applies the goal confirmed in the modal", async () => {
    const sample = await renderApp();
    await userEvent.click(sample);
    await screen.findByRole("dialog");

    await userEvent.click(screen.getByRole("radio", { name: /Critique/ }));
    await userEvent.click(screen.getByRole("button", { name: /^Start reading/ }));

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Critique" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("leaves the goal alone when the modal is dismissed", async () => {
    const sample = await renderApp();
    await userEvent.click(sample);
    await screen.findByRole("dialog");

    // Select Critique but back out — the choice was never confirmed.
    await userEvent.click(screen.getByRole("radio", { name: /Critique/ }));
    await userEvent.click(screen.getByRole("button", { name: "Not now" }));

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Skim" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("closes on Escape without changing the goal", async () => {
    const sample = await renderApp();
    await userEvent.click(sample);
    await screen.findByRole("dialog");

    await userEvent.click(screen.getByRole("radio", { name: /Critique/ }));
    await userEvent.keyboard("{Escape}");

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Skim" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("asks again for the next paper, since it is a new reading session", async () => {
    await openSamplePaper();

    await userEvent.click(screen.getByRole("button", { name: "bert" }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("can be reopened from the sidebar once a paper is open", async () => {
    await openSamplePaper();

    await userEvent.click(
      screen.getByRole("button", { name: "What do these mean?" }),
    );

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("offers no reopen link before any paper is open", async () => {
    await renderApp();
    expect(
      screen.queryByRole("button", { name: "What do these mean?" }),
    ).not.toBeInTheDocument();
  });

  it("does not ask for a goal when the parse failed", async () => {
    api.parseSample.mockRejectedValue(new Error("boom"));
    const sample = await renderApp();

    await userEvent.click(sample);

    await screen.findByRole("alert");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("the reading path (1.7)", () => {
  it("ranks the paper for the chosen goal once it opens", async () => {
    await openSamplePaper();

    expect(api.fetchReadingPath).toHaveBeenCalledWith(paper.paper_id, "skim");
  });

  it("does not rank while the goal is still being chosen", async () => {
    // Ranking on paper load would spend one call on the default goal and
    // another on whatever the reader picks — two calls against a budget of
    // five per minute, for one opened paper.
    const sample = await renderApp();

    await userEvent.click(sample);
    await screen.findByRole("dialog");

    expect(api.fetchReadingPath).not.toHaveBeenCalled();
  });

  it("ranks only the confirmed goal, not the default as well", async () => {
    const sample = await renderApp();
    await userEvent.click(sample);
    await screen.findByRole("dialog");

    await userEvent.click(screen.getByRole("radio", { name: /Critique/ }));
    await userEvent.click(screen.getByRole("button", { name: /^Start reading/ }));

    await waitFor(() => expect(api.fetchReadingPath).toHaveBeenCalledTimes(1));
    expect(api.fetchReadingPath).toHaveBeenCalledWith(paper.paper_id, "critique");
  });

  it("ranks the current goal when the modal is dismissed", async () => {
    const sample = await renderApp();
    await userEvent.click(sample);
    await screen.findByRole("dialog");

    await userEvent.click(screen.getByRole("button", { name: "Not now" }));

    await waitFor(() =>
      expect(api.fetchReadingPath).toHaveBeenCalledWith(paper.paper_id, "skim"),
    );
  });

  it("highlights the path's sentences, not the selected section's", async () => {
    await openSamplePaper();

    // Both items in the fixture path resolve to real sentences.
    expect(screen.getByTestId("pdf-viewer-stub")).toHaveAttribute(
      "data-highlight-count",
      "2",
    );
  });

  it("does not rank anything before a paper is open", async () => {
    await renderApp();
    expect(api.fetchReadingPath).not.toHaveBeenCalled();
  });

  it("re-ranks when the goal changes", async () => {
    await openSamplePaper();
    api.fetchReadingPath.mockClear();

    await userEvent.click(screen.getByRole("button", { name: "Critique" }));

    await waitFor(() =>
      expect(api.fetchReadingPath).toHaveBeenCalledWith(paper.paper_id, "critique"),
    );
  });

  it("re-ranks for the goal confirmed in the modal", async () => {
    const sample = await renderApp();
    await userEvent.click(sample);
    await screen.findByRole("dialog");

    await userEvent.click(screen.getByRole("radio", { name: /In-depth/ }));
    await userEvent.click(screen.getByRole("button", { name: /^Start reading/ }));

    await waitFor(() =>
      expect(api.fetchReadingPath).toHaveBeenCalledWith(paper.paper_id, "in-depth"),
    );
  });

  it("says how much of the paper is highlighted", async () => {
    await openSamplePaper();

    expect(await screen.findByText(/2 of 3 sentences/)).toBeInTheDocument();
  });

  it("shows progress while ranking, since it is a slow call", async () => {
    let release;
    api.fetchReadingPath.mockReturnValue(
      new Promise((resolve) => {
        release = () => resolve(readingPath);
      }),
    );
    const sample = await renderApp();
    await userEvent.click(sample);
    await screen.findByRole("dialog");
    await userEvent.click(screen.getByRole("button", { name: /^Start reading/ }));

    expect(await screen.findByText(/Finding your reading path/)).toBeInTheDocument();

    release();
    await waitFor(() =>
      expect(screen.queryByText(/Finding your reading path/)).not.toBeInTheDocument(),
    );
  });

  it("reports a ranking failure without breaking the reader", async () => {
    api.fetchReadingPath.mockRejectedValue(new Error("quota exhausted"));

    await openSamplePaper();

    expect(await screen.findByText("quota exhausted")).toBeInTheDocument();
    // The PDF is still there; only the highlights are missing.
    expect(screen.getByTestId("pdf-viewer-stub")).toHaveAttribute(
      "data-highlight-count",
      "0",
    );
  });

  it("can retry a failed ranking", async () => {
    api.fetchReadingPath.mockRejectedValueOnce(new Error("quota exhausted"));
    await openSamplePaper();
    await screen.findByText("quota exhausted");

    await userEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText(/2 of 3 sentences/)).toBeInTheDocument();
  });

  it("warns when part of the paper was never ranked", async () => {
    // A truncated path is indistinguishable from a complete one by looking at
    // it, so the reader has to be told. See docs/build-log.md.
    api.fetchReadingPath.mockResolvedValue({ ...readingPath, n_batches_failed: 1 });

    await openSamplePaper();

    expect(await screen.findByText(/could not be ranked/)).toBeInTheDocument();
  });

  it("says so when nothing matched the goal", async () => {
    api.fetchReadingPath.mockResolvedValue({ ...readingPath, items: [] });

    await openSamplePaper();

    expect(await screen.findByText(/Nothing in this paper matched/)).toBeInTheDocument();
  });

  it("drops the previous paper's highlights when another is opened", async () => {
    await openSamplePaper();
    api.fetchReadingPath.mockReturnValue(new Promise(() => {})); // never settles

    await userEvent.click(screen.getByRole("button", { name: "bert" }));

    // The old path must not sit over the new paper while the new one loads.
    await waitFor(() =>
      expect(screen.getByTestId("pdf-viewer-stub")).toHaveAttribute(
        "data-highlight-count",
        "0",
      ),
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
