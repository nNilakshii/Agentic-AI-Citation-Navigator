"""Localizer v1: find the cited passage by embedding similarity (task 2.5).

For one citation: take the citing sentence, embed it and every candidate
passage of the cited paper (2.4), and rank by cosine similarity.

- **The query is the citing sentence with citation markers removed.**
  "(Devlin et al., 2019)" or "[12]" says which paper, not what about it, and
  author names would pull towards the cited paper's own author line or
  bibliography. Every marker in the sentence goes, not only the clicked one.
- **Overlapping windows are suppressed.** Passages are overlapping windows, so
  without this the top five would be three views of the same sentence. A
  passage that shares a sentence with a better-ranked one is skipped.
- **The source is reported.** Ranking over an abstract answers a weaker
  question than ranking over the full text, and the result says which it was.

- **Scores mix exact terms and meaning (v2).** BM25 and MiniLM, each
  normalised per query, weighted 0.3 / 0.7 — the best of five rankers on
  CL-SciSumm's dev split, confirmed on test (2.7). Scores are in standard
  deviations above the paper's average passage, not cosine similarities.
- **A clear match is flagged by margin, not score.** How far the best passage
  leads the runner-up predicts correctness far better than how high it scores:
  on test, clear matches were right 36% of the time against 23% overall.
"""

from __future__ import annotations

import re

import numpy as np

from app.cache import PaperStore
from app.core.citations import build_citation_map
from app.core.cited_text import fetch_cited_text
from app.core.embedding import Embedder, encode_cached
from app.core.lexical import bm25_scores, hybrid_scores
from app.core.passages import passages_from_abstract, passages_from_paper
from app.core.pdf_parser import PARSER_VERSION
from app.models.citation import CitationMap
from app.models.cited import CitedText, TextSource
from app.models.localization import Localization, LocalizedPassage
from app.models.paper import ParsedPaper
from app.models.passage import Passage, PassageSet
from app.models.resolution import ResolutionMap
from app.scholar.client import SemanticScholar
from app.scholar.download import Downloader
from app.scholar.openalex import OpenAlex

#: Bumped when the query, scoring or suppression changes.
LOCALIZER_VERSION = "2"
DEFAULT_K = 5
#: Lead of the best passage over the runner-up, in hybrid-score units, at and
#: above which a localization is a "clear match" — chosen on the dev split.
CLEAR_MARGIN = 0.75
#: Context taken around an anchor that no sentence contains.
_FALLBACK_CONTEXT = 200

# What is left of "(see Devlin et al., 2019; Liu et al., 2019)" or "[3, 4]"
# once the anchors themselves are cut out.
_EMPTY_BRACKETS = re.compile(
    r"[\(\[]\s*(?:(?:see|e\.g\.|cf\.|i\.e\.)[,.]?\s*)?[,;\s–-]*[\)\]]"
)
_SPACES = re.compile(r"\s+")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([.,;:])")


def citance_query(paper: ParsedPaper, citations: CitationMap, anchor_id: str) -> str:
    """The citing sentence with every citation marker removed."""
    anchor = next((a for a in citations.anchors if a.id == anchor_id), None)
    if anchor is None:
        raise KeyError(anchor_id)
    sentence = next((s for s in paper.sentences if s.id == anchor.sentence_id), None)
    if sentence is not None:
        start, end = sentence.start_char, sentence.end_char
    else:
        start = max(0, anchor.start_char - _FALLBACK_CONTEXT)
        end = min(len(paper.full_text), anchor.end_char + _FALLBACK_CONTEXT)

    # Cut every anchor span inside the window, last first so offsets hold.
    text = paper.full_text
    spans = sorted(
        {
            (a.start_char, a.end_char)
            for a in citations.anchors
            if start <= a.start_char and a.end_char <= end
        },
        reverse=True,
    )
    window = text[start:end]
    for a_start, a_end in spans:
        window = window[: a_start - start] + window[a_end - start :]
    window = _EMPTY_BRACKETS.sub(" ", window)
    window = _SPACES.sub(" ", window)
    return _SPACE_BEFORE_PUNCT.sub(r"\1", window).strip()


def rank_passages(
    query: str,
    passages: list[Passage],
    embedder: Embedder,
    k: int = DEFAULT_K,
    cache_dir=None,
) -> list[LocalizedPassage]:
    """The ``k`` best non-overlapping passages for ``query``."""
    if not passages or not query:
        return []
    vectors = (
        encode_cached(embedder, [p.text for p in passages], cache_dir)
        if cache_dir is not None
        else embedder.encode([p.text for p in passages])
    )
    dense = (vectors @ embedder.encode([query])[0])[None, :]
    lexical = bm25_scores([p.text for p in passages], [query])
    return select_top(passages, hybrid_scores(lexical, dense)[0], k)


def is_clear_match(results: list[LocalizedPassage]) -> bool:
    """The best passage leads the runner-up by at least ``CLEAR_MARGIN``."""
    if len(results) < 2:
        return False
    return results[0].score - results[1].score >= CLEAR_MARGIN


def select_top(
    passages: list[Passage], scores: np.ndarray, k: int = DEFAULT_K
) -> list[LocalizedPassage]:
    """The ``k`` best-scoring passages, skipping any that overlap a better one.

    Shared by the endpoint and the CL-SciSumm harness (2.6), so what is
    evaluated is what is served.
    """
    chosen: list[LocalizedPassage] = []
    taken: list[tuple[int, int]] = []
    for index in np.argsort(-scores, kind="stable"):
        passage = passages[int(index)]
        if any(passage.start_char < e and s < passage.end_char for s, e in taken):
            continue
        chosen.append(
            LocalizedPassage(
                rank=len(chosen) + 1,
                score=round(float(scores[index]), 4),
                passage=passage,
            )
        )
        taken.append((passage.start_char, passage.end_char))
        if len(chosen) == k:
            break
    return chosen


def localize(
    citing: ParsedPaper,
    anchor_id: str,
    resolution: ResolutionMap,
    store: PaperStore,
    scholar: SemanticScholar,
    downloader: Downloader,
    openalex: OpenAlex | None,
    embedder: Embedder,
    k: int = DEFAULT_K,
    cache_dir=None,
) -> Localization:
    """Citation -> cited paper's text (2.3) -> passages (2.4) -> ranking.

    Raises KeyError if the anchor is not in the paper.
    """
    citations = build_citation_map(citing)
    query = citance_query(citing, citations, anchor_id)
    anchor = next(a for a in citations.anchors if a.id == anchor_id)
    result = Localization(
        citing_paper_id=citing.paper_id,
        anchor_id=anchor_id,
        reference_id=anchor.reference_id,
        query=query,
        source=TextSource.UNAVAILABLE,
        model=embedder.model,
        localizer_version=LOCALIZER_VERSION,
    )
    if anchor.reference_id is None:
        result.notes.append("this citation is not linked to a reference entry (2.1)")
        return result

    cited, passages, notes = cited_passages(
        citing, anchor.reference_id, resolution, store, scholar, downloader, openalex
    )
    result.source = cited.source
    result.cited_paper_id = cited.cited_paper_id
    result.notes.extend(notes)
    if passages is None:
        return result

    # The margin needs a runner-up, so rank at least two even when k is 1.
    ranked = rank_passages(query, passages.passages, embedder, max(k, 2), cache_dir)
    result.clear_match = is_clear_match(ranked)
    result.results = ranked[:k]
    return result


def cited_passages(
    citing: ParsedPaper,
    reference_id: str,
    resolution: ResolutionMap,
    store: PaperStore,
    scholar: SemanticScholar,
    downloader: Downloader,
    openalex: OpenAlex | None,
) -> tuple[CitedText, PassageSet | None, list[str]]:
    """The cited work's text (2.3) as candidate passages (2.4), with notes.

    Shared by the localizer and the grounded-evidence tool (3.4), so both
    search exactly the same text. ``None`` passages when there is none.
    """
    cited = fetch_cited_text(
        citing, reference_id, resolution, store, scholar, downloader, openalex
    )
    notes = list(cited.attempts)
    passages: PassageSet | None = None
    if cited.source is TextSource.FULL_TEXT:
        paper = store.load_parsed(cited.cited_paper_id, PARSER_VERSION)
        if paper is not None:
            passages = passages_from_paper(paper)
    elif cited.source is TextSource.ABSTRACT and cited.abstract:
        passages = passages_from_abstract(cited.abstract)
        notes.append("only the abstract was available, so only it was searched")
    if passages is None:
        notes.append("no text of the cited paper to search")
    return cited, passages, notes
