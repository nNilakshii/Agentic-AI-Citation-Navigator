/**
 * The cited work, beside the citing paper (task 2.11).
 *
 * Shows whatever 2.3 could get, and says which it was: the full PDF in a
 * second viewer; only the abstract, as text; or nothing, with the reasons.
 * "Not available" is an answer to show plainly, never a blank pane.
 *
 * Where the citation points inside it (2.12) comes from the localizer: the
 * chosen passage is highlighted and scrolled to, and the other candidates are
 * listed, so the reader can correct a wrong guess or say "none of these". The
 * top answer is called a likely match only when the localizer says it clearly
 * leads (2.7): even then it is right about a third of the time, so it is never
 * presented as certain.
 *
 * Above the PDF, three tabs (3.7): where the citation points; ask about the
 * paper, with answers whose quotes highlight their passage when clicked; and
 * the work's impact. A paper with no text still shows its impact.
 */

import { useMemo, useState } from "react";

import CitedChat from "./CitedChat.jsx";
import CitedImpact from "./CitedImpact.jsx";
import PdfViewer from "./PdfViewer.jsx";
import { anchorLabel } from "../lib/citations.js";
import {
  excerpt,
  passageSentences,
  scrollTarget,
  splitAbstract,
} from "../lib/localization.js";

function hostOf(url) {
  try {
    return new URL(url).host;
  } catch {
    return null;
  }
}

const TABS = [
  { id: "where", label: "Where it points" },
  { id: "ask", label: "Ask" },
  { id: "impact", label: "Impact" },
];

export default function CitedPane({
  bridge,
  citingPaperId,
  pdfUrl,
  onClose,
  onPick,
  onChoose,
}) {
  const { group, index, status, cited, error, loc } = bridge;
  const anchor = group.anchors[index];
  const [tab, setTab] = useState("where");
  // A passage a chat answer quoted (3.7); while set, it is what is highlighted.
  const [evidence, setEvidence] = useState(null);

  const results = loc?.status === "ready" ? loc.result.results : [];
  const chosenPassage =
    loc?.status === "ready" && loc.chosen !== null ? results[loc.chosen]?.passage : null;
  const shownPassage = evidence ?? chosenPassage;

  // Recomputed only when the passage changes: a new scroll request each render
  // would keep yanking the reader back to it.
  const highlight = useMemo(
    () => passageSentences(loc?.citedPaper, shownPassage),
    [loc?.citedPaper, shownPassage],
  );
  const scrollTo = useMemo(() => scrollTarget(highlight), [highlight]);
  const title = cited?.title ?? `Cited work ${anchorLabel(anchor)}`;
  const hasText = status === "ready" && cited.source !== "unavailable";
  const tabs = hasText ? TABS : TABS.filter((t) => t.id === "impact");
  const activeTab = tabs.some((t) => t.id === tab) ? tab : tabs[0].id;

  const choose = (i) => {
    setEvidence(null);
    onChoose(i);
  };

  const panel = status === "ready" && (
    <>
      <div className="cited__tabs" role="tablist" aria-label="About this cited work">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={activeTab === t.id}
            aria-controls={`panel-${t.id}`}
            className={`cited__tabbtn${activeTab === t.id ? " cited__tabbtn--active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div
        className="cited__panel"
        role="tabpanel"
        id={`panel-${activeTab}`}
        aria-labelledby={`tab-${activeTab}`}
      >
        {activeTab === "where" && (
          <Candidates loc={loc} results={results} onChoose={choose} />
        )}
        {activeTab === "ask" && (
          <CitedChat
            paperId={citingPaperId}
            anchorId={anchor.id}
            focusedPassageId={evidence?.id}
            onFocusPassage={setEvidence}
          />
        )}
        {activeTab === "impact" && (
          <CitedImpact paperId={citingPaperId} referenceId={anchor.reference_id} />
        )}
      </div>
    </>
  );

  return (
    <aside className="cited" aria-label="Cited work">
      <header className="cited__header">
        <div className="cited__heading">
          <p className="cited__kicker">Cited work {anchorLabel(anchor)}</p>
          <h2 className="cited__title">
            {status === "loading" ? "Finding the cited paper…" : title}
          </h2>
        </div>
        <button
          type="button"
          className="cited__close"
          aria-label="Close the cited work"
          onClick={onClose}
        >
          ×
        </button>
      </header>

      {group.anchors.length > 1 && (
        <nav className="cited__switch" aria-label="Works named by this citation">
          {group.anchors.map((a, i) => (
            <button
              key={a.id}
              type="button"
              className={`cited__tab${i === index ? " cited__tab--active" : ""}`}
              aria-pressed={i === index}
              onClick={() => onPick(i)}
            >
              {anchorLabel(a)}
            </button>
          ))}
        </nav>
      )}

      {status === "loading" && (
        <p className="cited__status" role="status">
          Fetching the cited paper. The first time can take a few seconds: it is
          downloaded and read like any paper you open.
        </p>
      )}

      {status === "error" && (
        <p className="cited__status cited__status--error" role="alert">
          {error}
        </p>
      )}

      {status === "ready" && cited.source === "full-text" && (
        <>
          <p className="cited__source">
            Full text
            {hostOf(cited.fetched_from) && <> from {hostOf(cited.fetched_from)}</>}
          </p>
          {panel}
          <PdfViewer
            fileUrl={pdfUrl(cited.cited_paper_id)}
            highlightSentences={highlight}
            highlightVariant="cited"
            scrollToPage={scrollTo}
          />
        </>
      )}

      {status === "ready" && cited.source === "abstract" && (
        <>
          {panel}
          <div className="cited__body">
            <p className="cited__notice">
              Only the abstract is available for this paper
              {cited.abstract_from === "openalex" ? " (via OpenAlex)" : ""}.
            </p>
            <Abstract text={cited.abstract} passage={shownPassage} />
            <Reasons attempts={cited.attempts} summary="Why not the full text" />
          </div>
        </>
      )}

      {status === "ready" && cited.source === "unavailable" && (
        <>
          <div className="cited__body">
            <p className="cited__notice">The text of this paper could not be found.</p>
            <Reasons attempts={cited.attempts} summary="What was tried" open />
          </div>
          {panel}
        </>
      )}
    </aside>
  );
}

function Reasons({ attempts, summary, open = false }) {
  if (!attempts?.length) return null;
  return (
    <details className="cited__reasons" open={open}>
      <summary>{summary}</summary>
      <ul>
        {attempts.map((attempt) => (
          <li key={attempt}>{attempt}</li>
        ))}
      </ul>
    </details>
  );
}

function Candidates({ loc, results, onChoose }) {
  if (!loc) return null;
  if (loc.status === "loading") {
    return (
      <p className="cited__status" role="status">
        Looking for the passage this citation points to…
      </p>
    );
  }
  if (loc.status === "error") {
    const notHere = loc.error?.status === 503;
    return (
      <p className="cited__status">
        {notHere
          ? "Finding the cited passage is not available on this server, so the paper opens at the start."
          : `Could not find the cited passage: ${loc.error?.message ?? "unknown error"}`}
      </p>
    );
  }
  if (!results.length) {
    return <p className="cited__status">No candidate passages in this paper.</p>;
  }

  const clear = loc.result.clear_match;
  return (
    <section className="candidates" aria-label="Where this citation points">
      <p className="candidates__lead">
        {clear
          ? "Likely the passage this citation points to — check it, or pick another."
          : "Best guesses for the passage this citation points to, most likely first."}
        {loc.result.source === "abstract" && " Only the abstract could be searched."}
      </p>
      <ol className="candidates__list">
        {results.map((r, i) => {
          const chosen = loc.chosen === i;
          return (
            <li key={r.passage.id}>
              <button
                type="button"
                className={`candidate${chosen ? " candidate--chosen" : ""}`}
                aria-pressed={chosen}
                onClick={() => onChoose(i)}
              >
                <span className="candidate__meta">
                  {i === 0 && clear && <span className="candidate__badge">Likely match</span>}
                  <span>{i + 1}.</span>
                  {r.passage.section_title && (
                    <span className="candidate__section">{r.passage.section_title}</span>
                  )}
                </span>
                <span className="candidate__text">{excerpt(r.passage.text)}</span>
              </button>
            </li>
          );
        })}
      </ol>
      <button
        type="button"
        className="candidates__none"
        aria-pressed={loc.chosen === null}
        onClick={() => onChoose(null)}
      >
        None of these
      </button>
    </section>
  );
}

function Abstract({ text, passage }) {
  const parts = splitAbstract(text, passage);
  if (!parts) return <p className="cited__abstract">{text}</p>;
  return (
    <p className="cited__abstract">
      {parts.before}
      <mark className="cited__mark">{parts.match}</mark>
      {parts.after}
    </p>
  );
}
