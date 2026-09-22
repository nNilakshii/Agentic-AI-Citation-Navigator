/**
 * Bounding boxes in PDF points -> CSS pixels on a rendered page.
 *
 * The backend emits bboxes in PDF points with a top-left origin (PyMuPDF's
 * convention), which is already the same orientation as CSS. pdf.js renders a
 * page at `scale`, where one PDF point becomes exactly `scale` pixels, so the
 * transform is a single multiply — provided the scale is derived from the page
 * actually rendered rather than assumed.
 *
 * This module is the whole coordinate story for highlights. Phase 1.7's reading
 * path and Phase 2.12's cited-span jump both draw through it.
 */

/**
 * The scale pdf.js used, measured from the rendered page rather than assumed.
 *
 * @param {number} renderedWidth - Page width in CSS pixels, post-render.
 * @param {number} originalWidth - Page width in PDF points, from onLoadSuccess.
 * @returns {number} Pixels per PDF point; 1 if the inputs are not usable.
 */
export function scaleFor(renderedWidth, originalWidth) {
  if (!renderedWidth || !originalWidth || originalWidth <= 0) return 1;
  return renderedWidth / originalWidth;
}

/**
 * Convert one backend bbox into absolute-positioning CSS values.
 *
 * @param {{x0:number,y0:number,x1:number,y1:number}} bbox
 * @param {number} scale - Pixels per PDF point.
 * @returns {{left:number, top:number, width:number, height:number}}
 */
export function bboxToCss(bbox, scale) {
  const left = bbox.x0 * scale;
  const top = bbox.y0 * scale;
  return {
    left,
    top,
    width: Math.max(0, (bbox.x1 - bbox.x0) * scale),
    height: Math.max(0, (bbox.y1 - bbox.y0) * scale),
  };
}

/**
 * The bboxes belonging to one page, flattened across sentences.
 *
 * Each returned bbox carries its sentence's `importance` when there is one, so
 * the reading path (1.7) can vary highlight intensity without the layer having
 * to look anything up. Sentences without an importance — a plain span
 * highlight — come back unchanged apart from the copy.
 *
 * @param {Array<{bboxes: Array<object>, importance?: number}>} sentences
 * @param {number} pageIndex - 0-based.
 * @returns {Array<object>} Every bbox on that page.
 */
export function bboxesOnPage(sentences, pageIndex) {
  const found = [];
  for (const sentence of sentences ?? []) {
    for (const bbox of sentence.bboxes ?? []) {
      if (bbox.page !== pageIndex) continue;
      if (sentence.importance === undefined && !sentence.focused) {
        found.push(bbox);
        continue;
      }
      found.push({
        ...bbox,
        importance: sentence.importance,
        focused: Boolean(sentence.focused),
      });
    }
  }
  return found;
}
