/**
 * Says when new papers can no longer be ranked today (task 1.9 follow-up).
 *
 * The demo runs on a free API tier with a small daily allowance shared by
 * everyone. When it is gone, an upload fails after the reader has already
 * chosen a file and waited — so this says it beforehand instead. Cached
 * papers are unaffected and keep working, which is the more important half
 * of the message.
 *
 * Renders nothing while there is comfortable headroom: a budget readout on
 * every visit would be noise.
 */

/** Below this, the reader is close enough to the ceiling to deserve warning. */
const LOW_WATER = 3;

export default function BudgetNotice({ remaining }) {
  // -1 means unlimited (billing enabled); null means not known yet.
  if (remaining === null || remaining === undefined || remaining < 0) return null;
  if (remaining > LOW_WATER) return null;

  if (remaining === 0) {
    return (
      <p className="budget budget--out" role="status">
        <strong>No new papers today.</strong> This demo ranks papers with a free
        API tier that resets daily. Papers marked <em>ready</em> still open
        instantly — only new uploads have to wait.
      </p>
    );
  }

  return (
    <p className="budget" role="status">
      {remaining} new paper{remaining === 1 ? "" : "s"} can be ranked today.
      Papers marked <em>ready</em> don't count against it.
    </p>
  );
}
