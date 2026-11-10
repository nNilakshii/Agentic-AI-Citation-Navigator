/**
 * Ranked cited passages -> highlights and scroll targets (task 2.12).
 *
 * The localizer answers with passages as sentence ids of the cited paper; the
 * cited paper's parse holds those sentences' rectangles. Everything drawn
 * goes through the same sentence -> bbox path as the reading path (1.7).
 */

/**
 * The cited paper's sentences for one passage, ready for the highlight layer.
 *
 * @param {{sentences: Array}} citedPaper - The cited paper's parse.
 * @param {{sentence_ids: string[]}} passage
 * @returns {Array<{id, bboxes, focused: true}>}
 */
export function passageSentences(citedPaper, passage) {
  if (!citedPaper?.sentences || !passage) return [];
  const wanted = new Set(passage.sentence_ids);
  return citedPaper.sentences
    .filter((sentence) => wanted.has(sentence.id))
    .map((sentence) => ({ ...sentence, focused: true }));
}

/**
 * Where to scroll so a passage is in view: its first rectangle.
 *
 * @returns {{page: number, y: number}|null} y in PDF points from the page top.
 */
export function scrollTarget(sentences) {
  for (const sentence of sentences) {
    const first = sentence.bboxes?.[0];
    if (first) return { page: first.page, y: first.y0 };
  }
  return null;
}

/** A passage trimmed for a list, on a word boundary. */
export function excerpt(text, limit = 180) {
  const flat = (text ?? "").replace(/\s+/g, " ").trim();
  if (flat.length <= limit) return flat;
  const cut = flat.slice(0, limit);
  return `${cut.slice(0, Math.max(cut.lastIndexOf(" "), limit - 20))}…`;
}

/**
 * The abstract split around a passage, for marking it inline.
 *
 * @returns {{before: string, match: string, after: string}|null}
 */
export function splitAbstract(abstract, passage) {
  if (!abstract || !passage) return null;
  const { start_char: start, end_char: end } = passage;
  if (start < 0 || end > abstract.length || start >= end) return null;
  return {
    before: abstract.slice(0, start),
    match: abstract.slice(start, end),
    after: abstract.slice(end),
  };
}
