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
const SLOW_AFTER_SECONDS = 8;

export default function ReadingPathStatus({ path, busy, error, onRetry }) {
  const [elapsed, setElapsed] = useState(0);

  // A ticking count, not just a message: a measured 62s wait behind a rate
  // limit is indistinguishable from a hung request if nothing on screen moves.
  useEffect(() => {
    if (!busy) {
      setElapsed(0);
      return undefined;
    }
    const started = Date.now();
    const timer = setInterval(
      () => setElapsed(Math.floor((Date.now() - started) / 1000)),
      1000,
    );
    return () => clearInterval(timer);
  }, [busy]);

  if (busy) {
    return (
      <div className="path-status">
        <p className="sidebar__hint" role="status">
          Finding your reading path
          {elapsed >= SLOW_AFTER_SECONDS ? ` — ${elapsed}s` : "…"}
        </p>
        {elapsed >= SLOW_AFTER_SECONDS && (
          <p className="path-status__waiting">
            Ranking a paper for the first time costs one API call, and the
            free tier allows 20 a day. If the quota is busy this waits for it —
            a minute or two is normal, and it will finish on its own.
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
