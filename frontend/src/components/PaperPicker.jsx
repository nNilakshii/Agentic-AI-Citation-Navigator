/**
 * Opening a paper (task 1.4): either one of the local samples or a file from
 * disk. Both routes end at the same backend parse, keyed by content hash.
 *
 * Papers already ranked for the current goal are marked. On a free API tier
 * the difference is stark — instant versus seconds of waiting, or nothing at
 * all once the day's budget is spent — and a reader should be able to see it
 * before clicking rather than after.
 */

import { useRef } from "react";

/** Turn "attention-is-all-you-need.pdf" into "attention is all you need". */
function prettify(filename) {
  return filename.replace(/\.pdf$/i, "").replace(/[-_]/g, " ");
}

export default function PaperPicker({
  samples,
  currentFilename,
  busy,
  coverage,
  goalId,
  onPickSample,
  onUpload,
}) {
  const fileInput = useRef(null);

  // filename -> goals that already have a path. Absent while coverage loads,
  // in which case nothing is marked rather than everything being marked slow.
  const readyFor = new Map(
    (coverage ?? []).map((row) => [row.filename, row.ready ?? []]),
  );
  const knowsCoverage = Boolean(coverage);

  return (
    <div className="picker">
      <button
        type="button"
        className="picker__upload"
        onClick={() => fileInput.current?.click()}
        disabled={busy}
      >
        Open a PDF…
      </button>
      <input
        ref={fileInput}
        type="file"
        accept="application/pdf,.pdf"
        className="picker__file"
        aria-label="Open a PDF"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) onUpload?.(file);
          event.target.value = ""; // allow re-picking the same file
        }}
      />

      {samples?.length > 0 && (
        <>
          <p className="picker__label">Sample papers</p>
          <ul className="picker__samples">
            {samples.map((name) => (
              <li key={name}>
                <button
                  type="button"
                  className={`picker__sample${
                    name === currentFilename ? " picker__sample--active" : ""
                  }`}
                  disabled={busy}
                  // The badge is aria-hidden and the state rides on `title`,
                  // which contributes to the accessible *description* rather
                  // than the name. A screen reader still hears it; the
                  // button stays addressable by the paper's name alone.
                  title={
                    knowsCoverage
                      ? readyFor.get(name)?.includes(goalId)
                        ? "Already ranked for this goal — opens instantly"
                        : "Not ranked for this goal yet — needs an API call"
                      : undefined
                  }
                  onClick={() => onPickSample?.(name)}
                >
                  <span className="picker__sample-name">{prettify(name)}</span>
                  {knowsCoverage &&
                    (readyFor.get(name)?.includes(goalId) ? (
                      <span className="picker__ready" aria-hidden="true">
                        ready
                      </span>
                    ) : (
                      <span className="picker__slow" aria-hidden="true">
                        new
                      </span>
                    ))}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
