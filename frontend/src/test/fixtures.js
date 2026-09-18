/**
 * A miniature ParsedPaper, shaped exactly like the backend's response so the
 * tests break if the two ever drift apart.
 */

export const paper = {
  paper_id: "a".repeat(64),
  parser_version: "1",
  source: {
    filename: "attention-is-all-you-need.pdf",
    title: "Attention Is All You Need",
    arxiv_id: "1706.03762v7",
    page_count: 3,
  },
  full_text: "Front matter text. Abstract text here. Introduction text follows.",
  sections: [
    { id: 0, title: "Front matter", level: 1, start_char: 0, end_char: 19, page: 0 },
    { id: 1, title: "Abstract", level: 1, start_char: 19, end_char: 39, page: 0 },
    {
      id: 2,
      title: "1 Introduction",
      level: 1,
      start_char: 39,
      end_char: 65,
      page: 1,
    },
    {
      id: 3,
      title: "1.1 Motivation",
      level: 2,
      start_char: 65,
      end_char: 65,
      page: 2,
    },
  ],
  sentences: [
    {
      id: "s00000",
      text: "Front matter text.",
      start_char: 0,
      end_char: 18,
      section_id: 0,
      page: 0,
      bboxes: [{ page: 0, x0: 72, y0: 100, x1: 300, y1: 112 }],
    },
    {
      id: "s00001",
      text: "Abstract text here.",
      start_char: 19,
      end_char: 38,
      section_id: 1,
      page: 0,
      bboxes: [{ page: 0, x0: 72, y0: 130, x1: 320, y1: 142 }],
    },
    {
      id: "s00002",
      text: "Introduction text follows.",
      start_char: 39,
      end_char: 65,
      section_id: 2,
      page: 1,
      bboxes: [
        { page: 1, x0: 72, y0: 90, x1: 400, y1: 102 },
        { page: 1, x0: 72, y0: 104, x1: 250, y1: 116 },
      ],
    },
  ],
};

export const samples = ["attention-is-all-you-need.pdf", "bert.pdf"];

/**
 * A ReadingPath over `paper`, shaped exactly like the backend's response.
 * Two of the three sentences, on two different pages, with different
 * importances — enough to exercise the join, the per-page split and the
 * intensity classes.
 */
export const readingPath = {
  paper_id: paper.paper_id,
  parser_version: "1",
  ranker_version: "1",
  goal: "skim",
  model: "fake-model",
  n_sentences_considered: 3,
  n_hallucinated_ids: 0,
  n_batches: 1,
  n_batches_failed: 0,
  items: [
    {
      sentence_id: "s00001",
      start_char: 19,
      end_char: 38,
      page: 0,
      section_id: 1,
      text: "Abstract text here.",
      importance: 5,
      why: "states the core claim",
    },
    {
      sentence_id: "s00002",
      start_char: 39,
      end_char: 65,
      page: 1,
      section_id: 2,
      text: "Introduction text follows.",
      importance: 2,
      why: "background framing",
    },
  ],
};
