/**
 * AURA Citation Navigator — reader shell (tasks 1.3-1.9).
 *
 * Sidebar: pick a paper, pick a reading goal, navigate the section outline.
 * Main:    the PDF, scrolling continuously, with the reading path highlighted.
 *
 * Opening a paper asks for a reading goal (1.5), which is ranked into a reading
 * path by the backend (1.6) and drawn over the pages here (1.7). Changing the
 * goal re-fetches; the backend caches per goal, so switching back is instant.
 * The right-hand panel lists that path with plain-language explanations (1.8).
 *
 * Citations in the PDF are clickable (2.11): clicking one fetches the cited
 * work and opens it beside the citing paper, in place of the reading-path
 * panel, until it is closed. The pane then asks where in the cited work the
 * citation points (2.12): the best passage is highlighted and scrolled to,
 * with the other candidates listed so the reader can correct it.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import BudgetNotice from "./components/BudgetNotice.jsx";
import CitedPane from "./components/CitedPane.jsx";
import ConnectionBanner from "./components/ConnectionBanner.jsx";
import ExplanationPanel from "./components/ExplanationPanel.jsx";
import GoalModal from "./components/GoalModal.jsx";
import GoalPicker from "./components/GoalPicker.jsx";
import Outline from "./components/Outline.jsx";
import PaperPicker from "./components/PaperPicker.jsx";
import PdfViewer from "./components/PdfViewer.jsx";
import ReadingPathStatus from "./components/ReadingPathStatus.jsx";
import * as api from "./lib/api.js";
import { groupAnchors } from "./lib/citations.js";
import { DEFAULT_GOAL_ID, goalById } from "./lib/goals.js";
import { paperSubtitle, sectionAt } from "./lib/outline.js";
import { pathSentences } from "./lib/readingPath.js";

/**
 * How long a jump is given to finish before scroll tracking is believed again.
 * Comfortably longer than a smooth scroll, and self-clearing, so the outline can
 * never get stuck ignoring the reader.
 */
const JUMP_SETTLE_MS = 1200;

export default function App() {
  const [goalId, setGoalId] = useState(DEFAULT_GOAL_ID);
  const [askingGoal, setAskingGoal] = useState(false);
  const [samples, setSamples] = useState([]);
  const [paper, setPaper] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [scrollToPage, setScrollToPage] = useState(null);
  const [activeSectionId, setActiveSectionId] = useState(null);
  const [selectedSection, setSelectedSection] = useState(null);
  const [readingPath, setReadingPath] = useState(null);
  const [pathBusy, setPathBusy] = useState(false);
  const [pathError, setPathError] = useState(null);
  // Bumped to re-run the ranking effect. Setting goalId to its current value
  // would not: React bails out of a state update that changes nothing.
  const [pathAttempt, setPathAttempt] = useState(0);
  const [activePathId, setActivePathId] = useState(null);
  // null = not checked yet, so the banner never flashes before the first answer.
  const [backendUp, setBackendUp] = useState(null);
  const [reconnecting, setReconnecting] = useState(false);
  const [coverage, setCoverage] = useState(null);
  const [budgetLeft, setBudgetLeft] = useState(null);
  const jumpedAt = useRef(0);
  const [citationGroups, setCitationGroups] = useState([]);
  // The open cited work: {group, index, status, cited, error, loc}, or null.
  // `loc` is the ranking: {status, result, citedPaper, chosen, error}.
  const [bridge, setBridge] = useState(null);

  const connect = useCallback(async () => {
    const status = await api.fetchStatus();
    setBackendUp(status !== null);
    if (status === null) return;
    setBudgetLeft(status.rankings_left_today ?? null);
    try {
      const [sampleNames, rows] = await Promise.all([
        api.listSamples(),
        // Not fatal: without it the picker simply marks nothing.
        api.fetchCoverage().catch(() => null),
      ]);
      setSamples(sampleNames);
      setCoverage(rows);
      setError(null);
    } catch (cause) {
      setError(cause.message);
    }
  }, []);

  useEffect(() => {
    connect();
  }, [connect]);

  const handleReconnect = useCallback(async () => {
    setReconnecting(true);
    try {
      await connect();
    } finally {
      setReconnecting(false);
    }
  }, [connect]);

  const load = useCallback(async (loader) => {
    setBusy(true);
    setError(null);
    try {
      const parsed = await loader();
      setPaper(parsed);
      setReadingPath(null);
      setPathError(null);
      setSelectedSection(null);
      setActiveSectionId(parsed.sections?.[0]?.id ?? null);
      setScrollToPage({ page: 0 });
      setCitationGroups([]);
      setBridge(null);
      // A new paper is a new reading session, so the goal is asked again
      // rather than inherited silently from the last one.
      setAskingGoal(true);
    } catch (cause) {
      setError(cause.message);
    } finally {
      setBusy(false);
    }
  }, []);

  // Rank the paper for the current goal. Re-runs when either changes; the
  // backend caches per (paper, goal), so switching back to a goal already seen
  // returns immediately without spending quota.
  //
  // Nothing is ranked while the goal modal is open. Ranking on paper load
  // would spend a call on the default goal, and a second on whatever the
  // reader then picks — two LLM calls against a 20-a-day budget for one
  // opened paper.
  useEffect(() => {
    if (!paper || askingGoal) return undefined;

    // A goal switched twice in quick succession must not let the slower, older
    // request overwrite the newer one's highlights.
    let current = true;
    setPathBusy(true);
    setPathError(null);
    api
      .fetchReadingPath(paper.paper_id, goalId)
      .then((path) => {
        if (!current) return;
        setReadingPath(path);
        setActivePathId(null);
      })
      .catch((cause) => {
        if (!current) return;
        setReadingPath(null);
        setPathError(cause.message);
      })
      .finally(() => {
        if (!current) return;
        setPathBusy(false);
        // A live ranking changes both: this paper is now ready, and the day's
        // budget is one smaller. Cheap, and keeps the markers honest.
        api.fetchStatus().then((s) => {
          if (current && s) setBudgetLeft(s.rankings_left_today ?? null);
        });
        api.fetchCoverage().then(
          (rows) => current && setCoverage(rows),
          () => {},
        );
      });

    return () => {
      current = false;
    };
  }, [paper, goalId, askingGoal, pathAttempt]);

  // Citations are a convenience on top of reading: if they cannot be loaded,
  // the paper simply has no clickable markers.
  useEffect(() => {
    if (!paper) return undefined;
    let current = true;
    api
      .fetchCitations(paper.paper_id)
      .then((map) => current && setCitationGroups(groupAnchors(map.anchors)))
      .catch(() => current && setCitationGroups([]));
    return () => {
      current = false;
    };
  }, [paper]);

  const openCited = useCallback((group, index = 0) => {
    setBridge({ group, index, status: "loading", cited: null, error: null });
  }, []);

  // Fetch whichever cited work is open. Keyed on the anchor, so clicking a
  // second citation before the first answers can never show the first's text.
  const openAnchorId = bridge?.group.anchors[bridge.index]?.id;
  useEffect(() => {
    if (!paper || !bridge || bridge.status !== "loading") return undefined;
    const anchor = bridge.group.anchors[bridge.index];
    let current = true;
    api
      .fetchCitedText(paper.paper_id, anchor.reference_id)
      .then((cited) => {
        if (current) setBridge((b) => b && { ...b, status: "ready", cited });
      })
      .catch((cause) => {
        if (current) {
          setBridge((b) => b && { ...b, status: "error", error: cause.message });
        }
      });
    return () => {
      current = false;
    };
  }, [paper, openAnchorId, bridge?.status]);

  // Once the cited work is in, ask where the citation points within it, and —
  // for a PDF — fetch its parse, which holds the sentences' rectangles.
  //
  // Keyed on the cited answer itself, not on whether a ranking exists yet:
  // this effect sets `loc`, and a dependency it changes would cancel it.
  const openCitedAnswer = bridge?.status === "ready" ? bridge.cited : null;
  useEffect(() => {
    if (!paper || !openCitedAnswer || bridge.loc) return undefined;
    const anchor = bridge.group.anchors[bridge.index];
    const { cited } = bridge;
    if (cited.source === "unavailable") return undefined;
    let current = true;
    setBridge((b) => b && { ...b, loc: { status: "loading" } });
    // Settled separately: without passage finding (a 503 on a server with no
    // embedding model) the parse is still what lets a chat quote be shown.
    Promise.allSettled([
      api.localizeCitation(paper.paper_id, anchor.id),
      cited.source === "full-text" ? api.getPaper(cited.cited_paper_id) : null,
    ]).then(([ranked, parsed]) => {
      if (!current) return;
      const citedPaper = parsed.status === "fulfilled" ? parsed.value : null;
      const result = ranked.status === "fulfilled" ? ranked.value : null;
      // A malformed answer must cost the ranking, not the open paper.
      const fault =
        ranked.status === "rejected"
          ? ranked.reason
          : !Array.isArray(result?.results)
            ? new Error("the passage ranking came back incomplete")
            : null;
      setBridge(
        (b) =>
          b && {
            ...b,
            loc: fault
              ? { status: "error", error: fault, citedPaper }
              : {
                  status: "ready",
                  result,
                  citedPaper,
                  chosen: result.results.length ? 0 : null,
                },
          },
      );
    });
    return () => {
      current = false;
    };
  }, [paper, openAnchorId, openCitedAnswer]);

  const chooseCandidate = useCallback((chosen) => {
    setBridge((b) => b?.loc && { ...b, loc: { ...b.loc, chosen } });
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

  // The reading path is now what gets highlighted. Clicking a section still
  // jumps to it, but no longer paints it — two highlight systems competing for
  // the same page read as noise.
  const highlightSentences = useMemo(
    () => pathSentences(paper, readingPath, activePathId),
    [paper, readingPath, activePathId],
  );

  // Clicking an explanation jumps to its passage and marks it current, which
  // is also what draws the focus ring on that highlight.
  const handleSelectPathItem = useCallback((item) => {
    setActivePathId(item.id);
    setSelectedSection(null);
    jumpedAt.current = Date.now();
    setScrollToPage({ page: item.page });
  }, []);

  return (
    <div className={`app${bridge ? " app--bridge" : ""}`}>
      <aside className="sidebar">
        <header className="sidebar__header">
          <h1>AURA</h1>
          <p className="sidebar__tagline">Citation Navigator</p>
        </header>

        <PaperPicker
          samples={samples}
          currentFilename={paper?.source?.filename}
          busy={busy}
          coverage={coverage}
          goalId={goalId}
          onPickSample={(name) => load(() => api.parseSample(name))}
          onUpload={(file) => load(() => api.uploadPaper(file))}
        />

        <BudgetNotice remaining={budgetLeft} />

        <GoalPicker
          goalId={goalId}
          onChange={setGoalId}
          onReopen={paper ? () => setAskingGoal(true) : undefined}
        />

        {paper && (
          <ReadingPathStatus
            path={readingPath}
            busy={pathBusy}
            error={pathError}
            onRetry={() => setPathAttempt((n) => n + 1)}
          />
        )}

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
        {backendUp === false && (
          <ConnectionBanner onRetry={handleReconnect} retrying={reconnecting} />
        )}

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
          citationGroups={citationGroups}
          activeCitationKey={bridge?.group.key}
          onCitationClick={openCited}
        />
      </main>

      {bridge ? (
        <CitedPane
          // A fresh pane per cited work: its tab, chat and quoted passage
          // belong to that work, not the next one opened.
          key={bridge.group.anchors[bridge.index].id}
          bridge={bridge}
          citingPaperId={paper.paper_id}
          pdfUrl={api.pdfUrl}
          onClose={() => setBridge(null)}
          onPick={(index) => openCited(bridge.group, index)}
          onChoose={chooseCandidate}
        />
      ) : (
        <ExplanationPanel
          items={highlightSentences}
          activeId={activePathId}
          onSelect={handleSelectPathItem}
          goalLabel={goalById(goalId).label.toLowerCase()}
        />
      )}

      {askingGoal && paper && (
        <GoalModal
          paperTitle={paper.source?.title}
          currentGoalId={goalId}
          onConfirm={(chosen) => {
            setGoalId(chosen);
            setAskingGoal(false);
          }}
          onDismiss={() => setAskingGoal(false)}
        />
      )}
    </div>
  );
}
