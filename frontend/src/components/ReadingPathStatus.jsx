/**
 * Sidebar status for the reading path (task 1.7).
 *
 * Ranking is a several-second LLM call on a cache miss, so silence while it
 * runs reads as "the goal buttons do nothing" — which is exactly the confusion
 * this replaces. Deliberately just a status line: the per-sentence reasons the
 * backend already returns belong in the 1.8 explanation panel.
 */

import { useEffect, useState } from "react";

import { isPartial, pathSummary } from "../lib/readingPath.js";

/**
 * When a wait stops looking like latency and starts looking like a hang.
 *
 * A cold ranking is ~5s. Beyond this the backend is almost certainly sitting
 * out a rate limit — free-tier Gemini answers a 429 with a ~45s retryDelay and
 * the client waits exactly that long — so the reader deserves to be told the
 * difference between "working" and "queued behind a quota".
 */
const SLOW_AFTER_MS = 8000;

export default function ReadingPathStatus({ path, busy, error, onRetry }) {
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    if (!busy) {
      setSlow(false);
      return undefined;
    }
    const timer = setTimeout(() => setSlow(true), SLOW_AFTER_MS);
    return () => clearTimeout(timer);
  }, [busy]);

  if (busy) {
    return (
      <div className="path-status">
        <p className="sidebar__hint" role="status">
          Finding your reading path…
        </p>
        {slow && (
          <p className="path-status__waiting">
            Still going. The free API tier allows 5 requests a minute, so this
            can wait up to a minute before it retries.
          </p>
        )}
      </div>
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
