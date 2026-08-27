/**
 * AURA Citation Navigator — reader shell (tasks 1.3, 1.4).
 *
 * Sidebar: pick a paper, pick a reading goal, navigate the section outline.
 * Main:    the PDF, scrolling continuously, with a highlight overlay per page.
 *
 * The reading goal is captured but not yet acted on — goal-conditioned ranking
 * is task 1.6, and it will feed `highlightSentences` here without the viewer
 * needing to change.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import Outline from "./components/Outline.jsx";
import PaperPicker from "./components/PaperPicker.jsx";
import PdfViewer from "./components/PdfViewer.jsx";
import * as api from "./lib/api.js";
import { paperSubtitle, sectionAt } from "./lib/outline.js";

export const READING_GOALS = ["Skim", "In-depth", "Critique"];

/**
 * How long a jump is given to finish before scroll tracking is believed again.
 * Comfortably longer than a smooth scroll, and self-clearing, so the outline can
 * never get stuck ignoring the reader.
 */
const JUMP_SETTLE_MS = 1200;

export default function App() {
  const [goal, setGoal] = useState(READING_GOALS[0]);
  const [samples, setSamples] = useState([]);
  const [paper, setPaper] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [scrollToPage, setScrollToPage] = useState(null);
  const [activeSectionId, setActiveSectionId] = useState(null);
  const [selectedSection, setSelectedSection] = useState(null);
  const jumpedAt = useRef(0);

  useEffect(() => {
    api
      .listSamples()
      .then(setSamples)
      .catch((cause) => setError(cause.message));
  }, []);

  const load = useCallback(async (loader) => {
    setBusy(true);
    setError(null);
    try {
      const parsed = await loader();
      setPaper(parsed);
      setSelectedSection(null);
      setActiveSectionId(parsed.sections?.[0]?.id ?? null);
      setScrollToPage({ page: 0 });
    } catch (cause) {
      setError(cause.message);
    } finally {
      setBusy(false);
    }
  }, []);

  const handleSelectSection = useCallback((section) => {
    setSelectedSection(section);
    setActiveSectionId(section.id);
    jumpedAt.current = Date.now();
    // A new object each time, so re-clicking a section scrolls back to it.
    setScrollToPage({ page: section.page });
  }, []);

  // While scrolling, mark whichever section owns the top of the visible page.
  const handlePageChange = useCallback(
    (pageIndex) => {
      if (!paper?.sections?.length) return;

      // Scroll tracking is page-level, so it is coarser than a click: one page
      // holds several sections. Two ways it would otherwise undo a choice the
      // reader just made — both observed in the browser, not in theory:
      //
      // 1. A smooth scroll travels *through* the pages in between, and the
      //    observer reports each one, so the outline ends up marking whatever
      //    section the jump flew past. Ignore reports until the scroll settles.
      if (Date.now() - jumpedAt.current < JUMP_SETTLE_MS) return;
      // 2. On arrival, the target page's *first* section is not necessarily the
      //    one clicked. An explicit selection wins on its own page.
      if (selectedSection?.page === pageIndex) return;

      const first = paper.sentences?.find((sentence) => sentence.page === pageIndex);
      const section = first ? sectionAt(paper.sections, first.start_char) : null;
      if (section) setActiveSectionId(section.id);
    },
    [paper, selectedSection],
  );

  // Until goal-conditioned ranking exists (1.6), highlighting the selected
  // section's sentences is what proves the offset -> bbox chain end to end.
  const highlightSentences = useMemo(() => {
    if (!paper || !selectedSection) return [];
    return paper.sentences.filter(
      (sentence) => sentence.section_id === selectedSection.id,
    );
  }, [paper, selectedSection]);

  return (
    <div className="app">
      <aside className="sidebar">
        <header className="sidebar__header">
          <h1>AURA</h1>
          <p className="sidebar__tagline">Citation Navigator</p>
        </header>

        <PaperPicker
          samples={samples}
          currentFilename={paper?.source?.filename}
          busy={busy}
          onPickSample={(name) => load(() => api.parseSample(name))}
          onUpload={(file) => load(() => api.uploadPaper(file))}
        />

        <section className="sidebar__section">
          <p className="picker__label">Reading goal</p>
          <div className="goal-picker" role="group" aria-label="Reading goal">
            {READING_GOALS.map((option) => (
              <button
                key={option}
                type="button"
                className={option === goal ? "active" : ""}
                aria-pressed={option === goal}
                onClick={() => setGoal(option)}
              >
                {option}
              </button>
            ))}
          </div>
          <p className="sidebar__hint">
            Goal-adaptive highlighting arrives in task 1.6.
          </p>
        </section>

        {paper && (
          <section className="sidebar__section sidebar__section--grow">
            <p className="picker__label">Outline</p>
            <Outline
              sections={paper.sections}
              activeSectionId={activeSectionId}
              onSelect={handleSelectSection}
            />
          </section>
        )}
      </aside>

      <main className="reader">
        <header className="reader__header">
          <div>
            <h2>{paper?.source?.title ?? "No paper open"}</h2>
            {paper && <p className="reader__meta">{paperSubtitle(paper)}</p>}
          </div>
          {busy && <span className="reader__busy">Parsing…</span>}
        </header>

        {error && (
          <p className="reader__error" role="alert">
            {error}
          </p>
        )}

        <PdfViewer
          fileUrl={paper ? api.pdfUrl(paper.paper_id) : null}
          highlightSentences={highlightSentences}
          scrollToPage={scrollToPage}
          onPageChange={handlePageChange}
        />
      </main>
    </div>
  );
}
