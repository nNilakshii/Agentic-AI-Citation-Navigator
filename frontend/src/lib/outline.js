/**
 * Turning the backend's flat section list into what the sidebar needs.
 *
 * The backend returns sections in reading order, each with a `level` (1 for
 * "3 Model", 2 for "3.1 Encoder"). Levels are a heuristic and can skip — a
 * document may jump straight from level 1 to level 3 — so nothing here assumes
 * they are well-formed.
 */

/** Indentation applied per nesting level, in pixels. */
export const INDENT_PER_LEVEL = 14;

/**
 * Normalise levels so the deepest indent is never more than one step past its
 * parent, which keeps a mis-detected "3.2.1" from indenting off the sidebar.
 *
 * @param {Array<{level:number}>} sections
 * @returns {Array<object>} Sections with an added `depth` (0-based).
 */
export function withDepths(sections) {
  const result = [];
  let previousDepth = 0;
  for (const section of sections ?? []) {
    const level = Number.isFinite(section.level) ? section.level : 1;
    const depth = Math.max(0, Math.min(level - 1, previousDepth + 1));
    result.push({ ...section, depth });
    previousDepth = depth;
  }
  return result;
}

/**
 * The section containing a character offset.
 *
 * @param {Array<{start_char:number, end_char:number}>} sections
 * @param {number} offset
 * @returns {object|null}
 */
export function sectionAt(sections, offset) {
  for (const section of sections ?? []) {
    if (offset >= section.start_char && offset < section.end_char) return section;
  }
  return null;
}

/**
 * Format a page number for display. Backend pages are 0-based; readers count
 * from 1.
 *
 * @param {number} pageIndex
 * @returns {string}
 */
export function pageLabel(pageIndex) {
  return `p. ${(pageIndex ?? 0) + 1}`;
}

/**
 * A short, human-readable summary line for a parsed paper.
 *
 * @param {object} paper - A ParsedPaper or PaperSummary.
 * @returns {string}
 */
export function paperSubtitle(paper) {
  if (!paper) return "";
  const pages = paper.source?.page_count ?? 0;
  const sentences = paper.sentences?.length ?? paper.n_sentences ?? 0;
  const parts = [`${pages} page${pages === 1 ? "" : "s"}`];
  if (sentences) parts.push(`${sentences} sentences`);
  if (paper.source?.arxiv_id) parts.push(`arXiv:${paper.source.arxiv_id}`);
  return parts.join(" · ");
}
