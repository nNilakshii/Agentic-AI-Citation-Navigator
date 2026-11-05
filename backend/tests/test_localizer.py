"""Localizer v1 (task 2.5), with a bag-of-words fake embedder.

The fake makes similarity mean "shares words", so each test can say which
passage should win and why, and nothing loads torch.
"""

import re

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api.reader import get_store
from app.cache import PaperStore
from app.core.embedding import encode_cached, get_embedder
from app.core.localizer import citance_query, localize, rank_passages
from app.core.pdf_parser import PARSER_VERSION
from app.main import app
from app.models.citation import CitationAnchor, CitationMap, CitationStyle, Reference
from app.models.cited import TextSource
from app.models.paper import PaperSource, ParsedPaper, Section, Sentence
from app.models.passage import Passage
from app.models.resolution import ResolutionMap, ResolvedReference
from app.scholar.client import get_scholar
from app.scholar.download import get_downloader
from app.scholar.openalex import get_openalex

DIM = 512


class BagOfWords:
    model = "fake-bow"

    def __init__(self):
        self.calls = 0

    def encode(self, texts):
        self.calls += 1
        out = np.zeros((len(texts), DIM), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in re.findall(r"[a-z]+", text.lower()):
                out[row, hash(word) % DIM] += 1
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(norms == 0, 1, norms)


def paper_from(sentences: list[str], paper_id: str = "c" * 64) -> ParsedPaper:
    text, sents = "1 Introduction\n", []
    for i, sentence in enumerate(sentences):
        start = len(text)
        text += sentence + " "
        sents.append(
            Sentence(
                id=f"s{i:04d}",
                text=sentence,
                start_char=start,
                end_char=start + len(sentence),
                section_id=0,
                page=0,
            )
        )
    return ParsedPaper(
        paper_id=paper_id,
        parser_version=PARSER_VERSION,
        source=PaperSource(filename="p.pdf"),
        full_text=text,
        sections=[
            Section(
                id=0,
                title="1 Introduction",
                level=1,
                start_char=0,
                end_char=len(text),
                page=0,
            )
        ],
        sentences=sents,
    )


def anchors_for(
    paper: ParsedPaper, markers: list[tuple[str, str | None]]
) -> CitationMap:
    found = []
    for i, (marker, ref) in enumerate(markers):
        start = paper.full_text.index(marker)
        sentence = next(
            s for s in paper.sentences if s.start_char <= start < s.end_char
        )
        found.append(
            CitationAnchor(
                id=f"c{i:04d}",
                text=marker,
                start_char=start,
                end_char=start + len(marker),
                sentence_id=sentence.id,
                reference_id=ref,
            )
        )
    return CitationMap(
        paper_id=paper.paper_id,
        parser_version=paper.parser_version,
        citation_version="1",
        style=CitationStyle.AUTHOR_YEAR,
        references=[Reference(id="r001", text="x", start_char=0, end_char=1)],
        anchors=found,
    )


def passage(text, start, end, pid="p"):
    return Passage(id=pid, text=text, start_char=start, end_char=end)


# --- the query --------------------------------------------------------------


def test_the_query_drops_every_marker_and_its_brackets():
    paper = paper_from(
        [
            "Masked language models (Devlin et al., 2019; Liu et al., 2019) learn context."
        ]
    )
    citations = anchors_for(
        paper, [("Devlin et al., 2019", "r001"), ("Liu et al., 2019", None)]
    )
    assert (
        citance_query(paper, citations, "c0000")
        == "Masked language models learn context."
    )


def test_the_query_drops_numeric_markers():
    paper = paper_from(["Transformers [12, 14] replaced recurrence entirely."])
    citations = anchors_for(paper, [("12", "r001"), ("14", None)])
    assert (
        citance_query(paper, citations, "c0000")
        == "Transformers replaced recurrence entirely."
    )


def test_the_query_keeps_a_narrative_sentence_readable():
    paper = paper_from(["We follow the setup of Devlin et al. (2019) for fine-tuning."])
    citations = anchors_for(paper, [("Devlin et al. (2019)", "r001")])
    assert (
        citance_query(paper, citations, "c0000")
        == "We follow the setup of for fine-tuning."
    )


def test_an_unknown_anchor_is_a_key_error():
    paper = paper_from(["A sentence with no citation in it at all."])
    with pytest.raises(KeyError):
        citance_query(paper, anchors_for(paper, []), "c0099")


# --- ranking ----------------------------------------------------------------


def test_the_most_similar_passage_ranks_first():
    passages = [
        passage("we tokenize the corpus with byte pair encoding", 0, 40, "p0"),
        passage(
            "attention weights are computed with scaled dot products", 50, 90, "p1"
        ),
        passage("results on the glue benchmark improve by two points", 100, 140, "p2"),
    ]
    ranked = rank_passages("scaled dot product attention", passages, BagOfWords(), k=3)
    assert ranked[0].passage.id == "p1"
    assert [r.rank for r in ranked] == [1, 2, 3]
    assert [r.score for r in ranked] == sorted((r.score for r in ranked), reverse=True)


def test_overlapping_windows_are_suppressed():
    # p0 and p01 cover the same sentence; only the better one may appear.
    passages = [
        passage("scaled dot product attention", 0, 30, "p0"),
        passage("scaled dot product attention is fast", 0, 40, "p01"),
        passage("attention heads attend to positions", 41, 80, "p1"),
    ]
    ranked = rank_passages("scaled dot product attention", passages, BagOfWords(), k=3)
    ids = [r.passage.id for r in ranked]
    assert ids[0] == "p0"
    assert "p01" not in ids
    assert ids == ["p0", "p1"]


class Blind:
    """Sees every text as the same vector: meaning can rank nothing."""

    model = "fake-blind"

    def encode(self, texts):
        return np.ones((len(texts), 4), dtype=np.float32) / 2


def test_exact_terms_count_alongside_meaning():
    # With the embedding side blind, only BM25 can find the passage sharing
    # the citance's rare terms — so a hit here proves the lexical side is used.
    passages = [
        passage("evaluation uses the standard split of the corpus", 0, 50, "p0"),
        passage("we describe the maxent parser in detail", 60, 100, "p1"),
        passage("the tagger handles unknown words with suffixes", 110, 160, "p2"),
    ]
    ranked = rank_passages("maxent parser", passages, Blind(), k=3)
    assert ranked[0].passage.id == "p1"


def test_a_clear_match_needs_a_clear_lead():
    from app.core.localizer import CLEAR_MARGIN, is_clear_match
    from app.models.localization import LocalizedPassage

    def result(*scores):
        return [
            LocalizedPassage(
                rank=i + 1, score=s, passage=passage("x", i * 10, i * 10 + 5)
            )
            for i, s in enumerate(scores)
        ]

    assert is_clear_match(result(2.0, 2.0 - CLEAR_MARGIN))
    assert not is_clear_match(result(2.0, 2.0 - CLEAR_MARGIN + 0.01))
    assert not is_clear_match(result(3.0))  # no runner-up, no margin


def test_k_limits_the_results():
    passages = [
        passage(f"word{i} attention", i * 20, i * 20 + 15, f"p{i}") for i in range(10)
    ]
    assert len(rank_passages("attention", passages, BagOfWords(), k=4)) == 4


def test_nothing_to_rank_gives_nothing():
    assert rank_passages("attention", [], BagOfWords()) == []
    assert rank_passages("", [passage("attention", 0, 9)], BagOfWords()) == []


def test_embeddings_are_cached_by_model_and_texts(tmp_path):
    embedder = BagOfWords()
    first = encode_cached(embedder, ["a b", "c d"], tmp_path)
    again = encode_cached(embedder, ["a b", "c d"], tmp_path)
    assert embedder.calls == 1
    assert np.array_equal(first, again)
    encode_cached(embedder, ["a b", "c e"], tmp_path)  # new texts, new key
    assert embedder.calls == 2


# --- the whole chain ----------------------------------------------------------


CITED_SENTENCES = [
    "We tokenize every document with byte pair encoding before training.",
    "Attention is computed with scaled dot products over all positions.",
    "The model improves results on the translation benchmark considerably.",
]


class NoScholar:
    def paper(self, paper_id, fields=""):
        return {"abstract": "Attention is computed with scaled dot products here."}


class NoDownloads:
    def fetch_pdf(self, url):
        raise AssertionError("the cited paper was already stored")


def setup_chain(tmp_path, resolved=True):
    store = PaperStore(tmp_path)
    citing = paper_from(
        [
            "Scaled dot product attention (Vaswani et al., 2017) is computed over positions."
        ]
    )
    citations = anchors_for(citing, [("Vaswani et al., 2017", "r001")])
    cited = paper_from(CITED_SENTENCES, paper_id="d" * 64)
    store.save_parsed(cited)
    store.save_fetched("https://arxiv.org/pdf/1706.03762", cited.paper_id)
    item = ResolvedReference(reference_id="r001", title="Attention")
    if resolved:
        item.s2_paper_id, item.arxiv_id = "s2", "1706.03762"
    resolution = ResolutionMap(
        paper_id=citing.paper_id,
        parser_version="1",
        citation_version="1",
        resolver_version="1",
        items=[item],
    )
    return store, citing, citations, resolution


def test_localize_ranks_the_cited_full_text(tmp_path, monkeypatch):
    store, citing, citations, resolution = setup_chain(tmp_path)
    monkeypatch.setattr("app.core.localizer.build_citation_map", lambda p: citations)
    result = localize(
        citing,
        "c0000",
        resolution,
        store,
        NoScholar(),
        NoDownloads(),
        None,
        BagOfWords(),
        k=2,
    )
    assert result.source is TextSource.FULL_TEXT
    assert result.cited_paper_id == "d" * 64
    assert "Vaswani" not in result.query
    assert result.results[0].passage.text == CITED_SENTENCES[1]
    assert result.localizer_version == "2"
    assert len(result.results) == 2


def test_localize_falls_back_to_the_abstract(tmp_path, monkeypatch):
    store, citing, citations, resolution = setup_chain(tmp_path)
    resolution.items[0].arxiv_id = None  # no PDF link; S2 has an abstract
    monkeypatch.setattr("app.core.localizer.build_citation_map", lambda p: citations)
    result = localize(
        citing,
        "c0000",
        resolution,
        store,
        NoScholar(),
        NoDownloads(),
        None,
        BagOfWords(),
    )
    assert result.source is TextSource.ABSTRACT
    assert result.results[0].passage.section_title == "Abstract"
    assert any("only the abstract" in n for n in result.notes)


def test_an_unlinked_citation_says_so(tmp_path, monkeypatch):
    store, citing, citations, resolution = setup_chain(tmp_path)
    citations.anchors[0].reference_id = None
    monkeypatch.setattr("app.core.localizer.build_citation_map", lambda p: citations)
    result = localize(
        citing,
        "c0000",
        resolution,
        store,
        NoScholar(),
        NoDownloads(),
        None,
        BagOfWords(),
    )
    assert result.results == []
    assert result.source is TextSource.UNAVAILABLE
    assert "not linked" in result.notes[0]


def test_an_unidentified_reference_gives_no_results_and_reasons(tmp_path, monkeypatch):
    store, citing, citations, resolution = setup_chain(tmp_path, resolved=False)
    monkeypatch.setattr("app.core.localizer.build_citation_map", lambda p: citations)
    result = localize(
        citing,
        "c0000",
        resolution,
        store,
        NoScholar(),
        NoDownloads(),
        None,
        BagOfWords(),
    )
    assert result.results == []
    assert any("not identified" in n for n in result.notes)
    assert "no text of the cited paper to search" in result.notes


def test_a_missing_embedding_library_is_a_clear_error(monkeypatch):
    # The production image leaves out torch; the endpoint must say so, not 500.
    import builtins

    from app.core.embedding import EmbedderUnavailable, SentenceTransformerEmbedder

    real_import = builtins.__import__

    def no_st(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_st)
    with pytest.raises(EmbedderUnavailable):
        SentenceTransformerEmbedder().encode(["text"])


def test_endpoint_404s_an_unknown_citation(tmp_path, synthetic_pdf):
    store = PaperStore(tmp_path)

    class EmptyScholar:
        def references(self, ref):
            return []

        def batch(self, ids):
            return [None for _ in ids]

        def match_title(self, title):
            return None

    app.dependency_overrides.update(
        {
            get_store: lambda: store,
            get_scholar: lambda: EmptyScholar(),
            get_downloader: lambda: NoDownloads(),
            get_openalex: lambda: None,
            get_embedder: lambda: BagOfWords(),
        }
    )
    try:
        client = TestClient(app)
        paper_id = client.post(
            "/api/reader/papers",
            files={"file": ("p.pdf", synthetic_pdf, "application/pdf")},
        ).json()["paper_id"]
        response = client.post(
            f"/api/reader/papers/{paper_id}/citations/c9999/localize"
        )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
