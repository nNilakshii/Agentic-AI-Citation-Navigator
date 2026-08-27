/**
 * Draws highlight rectangles over one rendered PDF page.
 *
 * This is the primitive the rejected pdf-component-library would have supplied,
 * and it is deliberately dumb: given bboxes and a scale, position divs. Phase
 * 1.7 (reading path) and Phase 2.12 (cited span) supply different bboxes to the
 * same component rather than growing new rendering paths.
 */

import { bboxToCss } from "../lib/geometry.js";

export default function HighlightLayer({ bboxes, scale, variant = "path" }) {
  if (!bboxes?.length) return null;

  return (
    <div className="highlight-layer" data-testid="highlight-layer" aria-hidden="true">
      {bboxes.map((bbox, index) => {
        const { left, top, width, height } = bboxToCss(bbox, scale);
        return (
          <div
            key={`${bbox.page}-${index}-${left}-${top}`}
            className={`highlight highlight--${variant}`}
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
