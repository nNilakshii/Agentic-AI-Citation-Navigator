/**
 * Clickable citation markers over one rendered page (task 2.11).
 *
 * Unlike the highlight layer, this one takes clicks — but only on the markers
 * themselves: the layer is click-through everywhere else, so the reader can
 * still select the PDF's text around them.
 */

import { bboxToCss } from "../lib/geometry.js";
import { anchorLabel, padTarget } from "../lib/citations.js";

export default function CitationLayer({ targets, scale, activeKey, onSelect }) {
  if (!targets?.length) return null;

  return (
    <div className="citation-layer" data-testid="citation-layer">
      {targets.map(({ group, bbox }, index) => {
        const { left, top, width, height } = padTarget(bboxToCss(bbox, scale));
        const names = group.anchors.map(anchorLabel).join(", ");
        const active = group.key === activeKey;
        return (
          <button
            key={`${group.key}-${index}`}
            type="button"
            className={`citation-hit${active ? " citation-hit--active" : ""}`}
            aria-label={`Open cited work ${names}`}
            aria-pressed={active}
            title={`Open the cited work ${names}`}
            style={{
              left: `${left}px`,
              top: `${top}px`,
              width: `${width}px`,
              height: `${height}px`,
            }}
            onClick={() => onSelect?.(group)}
          />
        );
      })}
    </div>
  );
}
