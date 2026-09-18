/**
 * Draws highlight rectangles over one rendered PDF page.
 *
 * This is the primitive the rejected pdf-component-library would have supplied,
 * and it is deliberately dumb: given bboxes and a scale, position divs. The
 * reading path (1.7) and the cited span (2.12) supply different bboxes to the
 * same component rather than growing new rendering paths.
 *
 * A bbox carrying an `importance` (1-5) is drawn more strongly, so a reader
 * can see at a glance which highlights the ranker was most confident about.
 */

import { bboxToCss } from "../lib/geometry.js";

export default function HighlightLayer({ bboxes, scale, variant = "path" }) {
  if (!bboxes?.length) return null;

  return (
    <div className="highlight-layer" data-testid="highlight-layer" aria-hidden="true">
      {bboxes.map((bbox, index) => {
        const { left, top, width, height } = bboxToCss(bbox, scale);
        const strength = bbox.importance
          ? ` highlight--i${Math.max(1, Math.min(5, bbox.importance))}`
          : "";
        return (
          <div
            key={`${bbox.page}-${index}-${left}-${top}`}
            data-importance={bbox.importance ?? undefined}
            className={`highlight highlight--${variant}${strength}`}
            style={{
              left: `${left}px`,
              top: `${top}px`,
              width: `${width}px`,
              height: `${height}px`,
            }}
          />
        );
      })}
    </div>
  );
}
