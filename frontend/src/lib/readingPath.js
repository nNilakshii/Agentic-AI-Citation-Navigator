/**
 * Turning a backend reading path into something highlightable (task 1.7).
 *
 * The backend returns spans, not rectangles — `PathItem` carries
 * `sentence_id`, offsets and an importance, but no bboxes. That is deliberate
 * (``docs/architecture.md``: spans are the currency, the UI resolves them), so
 * the join back to geometry happens here, against the parse already in memory.
 */

/**
 * Attach each path item's importance to the sentence it points at.
 *
 * An item whose sentence is missing is dropped rather than rendered without
 * geometry. The backend guarantees every id is real, so this only fires if a
 * path outlives the parse it was built against — which the cache's
 * parser-version key is there to prevent.
 *
 * @param {object|null} paper - A ParsedPaper.
 * @param {object|null} path - A ReadingPath.
 * @returns {Array<object>} Sentences carrying `importance` and `why`.
 */
export function pathSentences(paper, path) {
  if (!paper?.sentences?.length || !path?.items?.length) return [];

  const byId = new Map(paper.sentences.map((sentence) => [sentence.id, sentence]));
  const resolved = [];
  for (const item of path.items) {
    const sentence = byId.get(item.sentence_id);
    if (!sentence) continue;
    resolved.push({ ...sentence, importance: item.importance, why: item.why });
  }
  return resolved;
}

/** A short summary line for the sidebar, e.g. "14 of 306 sentences". */
export function pathSummary(path) {
  if (!path) return "";
  const shown = path.items?.length ?? 0;
  const considered = path.n_sentences_considered ?? 0;
  if (!considered) return "Nothing to rank in this paper.";
  return `${shown} of ${considered} sentences`;
}

/**
 * Whether part of the paper never got ranked.
 *
 * A truncated path looks exactly like a complete one — the sentences in it are
 * real — so the only honest way to show it is to say so. See the 1.6 entry in
 * ``docs/build-log.md``.
 */
export function isPartial(path) {
  return Boolean(path && (path.n_batches_failed ?? 0) > 0);
}
