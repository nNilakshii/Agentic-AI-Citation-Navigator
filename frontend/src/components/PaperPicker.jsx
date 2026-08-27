/**
 * Opening a paper (task 1.4): either one of the local samples or a file from
 * disk. Both routes end at the same backend parse, keyed by content hash.
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
  onPickSample,
  onUpload,
}) {
  const fileInput = useRef(null);

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
                  onClick={() => onPickSample?.(name)}
                >
                  {prettify(name)}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
