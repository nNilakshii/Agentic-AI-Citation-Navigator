/**
 * Citation markers as click targets (task 2.11).
 *
 * The backend reports one anchor per cited work, so "[1–3]" arrives as three
 * anchors sharing one span. On the page that is one place to click, so anchors
 * are grouped by span here; the cited pane then lets the reader switch between
 * the works a group names.
 */

/** Smallest click target, in CSS pixels: a bare "7" is only ~5pt wide. */
export const MIN_TARGET_PX = 16;

/**
 * Linked, placeable anchors grouped by their span, in reading order.
 *
 * @param {Array<{id, start_char, end_char, reference_id, bboxes}>} anchors
 * @returns {Array<{key: string, anchors: Array, bboxes: Array}>}
 */
export function groupAnchors(anchors) {
  const groups = new Map();
  for (const anchor of anchors ?? []) {
    // Unlinked anchors have nowhere to go, and unplaced ones nowhere to be
    // clicked; both would only be dead targets.
    if (!anchor.reference_id || !anchor.bboxes?.length) continue;
    const key = `${anchor.start_char}-${anchor.end_char}`;
    if (!groups.has(key)) groups.set(key, { key, anchors: [], bboxes: anchor.bboxes });
    groups.get(key).anchors.push(anchor);
  }
  return [...groups.values()];
}

/**
 * The click targets on one page: one per rectangle, as a marker can wrap.
 *
 * @returns {Array<{group, bbox}>}
 */
export function targetsOnPage(groups, pageIndex) {
  const found = [];
  for (const group of groups ?? []) {
    for (const bbox of group.bboxes) {
      if (bbox.page === pageIndex) found.push({ group, bbox });
    }
  }
  return found;
}

/**
 * Grow a rectangle about its centre to at least ``min`` pixels each way.
 *
 * @param {{left, top, width, height}} css
 */
export function padTarget(css, min = MIN_TARGET_PX) {
  const width = Math.max(css.width, min);
  const height = Math.max(css.height, min);
  return {
    left: css.left - (width - css.width) / 2,
    top: css.top - (height - css.height) / 2,
    width,
    height,
  };
}

/** A short label for one anchor, as printed: "[7]" for numbers. */
export function anchorLabel(anchor) {
  return /^\d+$/.test(anchor.text) ? `[${anchor.text}]` : anchor.text;
}
