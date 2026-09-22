/**
 * The reading path as a readable list, with explanations (task 1.8).
 *
 * Each entry pairs a plain-language restatement with the sentence it came
 * from. That pairing is the grounding: the explanation is generated prose and
 * the sentence is the evidence for it, so the reader can always check one
 * against the other without leaving the panel (``CLAUDE.md``). An explanation
 * is never shown on its own, and a missing one degrades to the sentence rather
 * than to empty space.
 *
 * Clicking an entry jumps the viewer to it — the panel doubles as a
 * goal-filtered table of contents, which is the actual reading path.
 */

import { pageLabel } from "../lib/outline.js";

export default function ExplanationPanel({ items, activeId, onSelect, goalLabel }) {
  if (!items?.length) return null;

  return (
    <aside className="explain" aria-label="Reading path">
      <header className="explain__header">
        <h2>Your reading path</h2>
        <p className="explain__sub">
          {items.length} passage{items.length === 1 ? "" : "s"}
          {goalLabel ? ` for ${goalLabel}` : ""}, in reading order
        </p>
      </header>

      <ol className="explain__list">
        {items.map((item) => {
          const active = item.id === activeId;
          return (
            <li key={item.id}>
              <button
                type="button"
                className={`explain__item${active ? " explain__item--active" : ""}`}
                aria-current={active ? "true" : undefined}
                onClick={() => onSelect?.(item)}
              >
                <span className="explain__meta">
                  <span
                    className={`explain__pip explain__pip--i${item.importance ?? 3}`}
                    aria-hidden="true"
                  />
                  <span className="explain__rank">
                    {/* Spelled out: a bare "4/5" beside a page number reads as
                        a fraction of the paper rather than a priority. */}
                    Priority {item.importance ?? 3} of 5
                  </span>
                  <span className="explain__page">{pageLabel(item.page)}</span>
                </span>

                {item.plain ? (
                  <span className="explain__plain">{item.plain}</span>
                ) : (
                  // Older cached paths predate plain-language output. Showing
                  // the reason is better than showing a gap.
                  <span className="explain__plain explain__plain--fallback">
                    {item.why}
                  </span>
                )}

                {/* The evidence. Always present, always verbatim from the
                    parse, so the explanation above can be checked. */}
                <blockquote className="explain__quote">{item.text}</blockquote>

                {item.plain && item.why && (
                  <span className="explain__why">{item.why}</span>
                )}
              </button>
            </li>
          );
        })}
      </ol>
    </aside>
  );
}
