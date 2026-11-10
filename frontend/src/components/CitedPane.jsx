/**
 * The cited work, beside the citing paper (task 2.11).
 *
 * Shows whatever 2.3 could get, and says which it was: the full PDF in a
 * second viewer; only the abstract, as text; or nothing, with the reasons.
 * "Not available" is an answer to show plainly, never a blank pane.
 *
 * Jumping to the cited passage inside the PDF is 2.12.
 */

import PdfViewer from "./PdfViewer.jsx";
import { anchorLabel } from "../lib/citations.js";

function hostOf(url) {
  try {
    return new URL(url).host;
  } catch {
    return null;
  }
}

export default function CitedPane({ bridge, pdfUrl, onClose, onPick }) {
  const { group, index, status, cited, error } = bridge;
  const anchor = group.anchors[index];
  const title = cited?.title ?? `Cited work ${anchorLabel(anchor)}`;

  return (
    <aside className="cited" aria-label="Cited work">
      <header className="cited__header">
        <div className="cited__heading">
          <p className="cited__kicker">Cited work {anchorLabel(anchor)}</p>
          <h2 className="cited__title">{status === "loading" ? "Finding the cited paper…" : title}</h2>
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
          <PdfViewer fileUrl={pdfUrl(cited.cited_paper_id)} />
        </>
      )}

      {status === "ready" && cited.source === "abstract" && (
        <div className="cited__body">
          <p className="cited__notice">
            Only the abstract is available for this paper
            {cited.abstract_from === "openalex" ? " (via OpenAlex)" : ""}.
          </p>
          <p className="cited__abstract">{cited.abstract}</p>
          <Reasons attempts={cited.attempts} summary="Why not the full text" />
        </div>
      )}

      {status === "ready" && cited.source === "unavailable" && (
        <div className="cited__body">
          <p className="cited__notice">
            The text of this paper could not be found.
          </p>
          <Reasons attempts={cited.attempts} summary="What was tried" open />
        </div>
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
