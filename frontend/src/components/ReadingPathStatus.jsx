/**
 * Sidebar status for the reading path (task 1.7).
 *
 * Ranking is a several-second LLM call on a cache miss, so silence while it
 * runs reads as "the goal buttons do nothing" — which is exactly the confusion
 * this replaces. Deliberately just a status line: the per-sentence reasons the
 * backend already returns belong in the 1.8 explanation panel.
 */

import { isPartial, pathSummary } from "../lib/readingPath.js";

export default function ReadingPathStatus({ path, busy, error, onRetry }) {
  if (busy) {
    return (
      <p className="sidebar__hint" role="status">
        Finding your reading path…
      </p>
    );
  }

  if (error) {
    return (
      <div className="path-status path-status--error" role="alert">
        <p>{error}</p>
        {onRetry && (
          <button type="button" className="path-status__retry" onClick={onRetry}>
            Try again
          </button>
        )}
      </div>
    );
  }

  if (!path) return null;

  const count = path.items?.length ?? 0;
  if (!count) {
    return (
      <p className="sidebar__hint" role="status">
        Nothing in this paper matched that goal.
      </p>
    );
  }

  return (
    <div className="path-status">
      <p className="sidebar__hint" role="status">
        Highlighting {pathSummary(path)}.
      </p>
      {isPartial(path) && (
        // A truncated path is indistinguishable from a complete one by looking
        // at it, so saying so is the only honest option. See docs/build-log.md.
        <p className="path-status__warning">
          Part of this paper could not be ranked, so some of it is not
          highlighted.{" "}
          {onRetry && (
            <button type="button" className="path-status__retry" onClick={onRetry}>
              Try again
            </button>
          )}
        </p>
      )}
    </div>
  );
}
