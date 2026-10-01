/**
 * "The backend is not running", said once and clearly (task 1.9).
 *
 * The reader is two processes, and the most common broken state — uvicorn not
 * started — used to surface as whatever the first failing request happened to
 * say. This checks on mount so the answer arrives before the first click, and
 * carries the command to fix it rather than describing the problem.
 */

export default function ConnectionBanner({ onRetry, retrying }) {
  return (
    <div className="connection" role="alert">
      <div>
        <strong>The backend isn’t running.</strong> Start it, then reconnect:
        <code className="connection__cmd">
          cd backend &amp;&amp; uvicorn app.main:app --reload --port 8000
        </code>
      </div>
      <button
        type="button"
        className="connection__retry"
        onClick={onRetry}
        disabled={retrying}
      >
        {retrying ? "Checking…" : "Reconnect"}
      </button>
    </div>
  );
}
