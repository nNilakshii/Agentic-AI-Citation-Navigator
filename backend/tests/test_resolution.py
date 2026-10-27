"""Reference resolution (task 2.2), against a fake Semantic Scholar.

No network: every test is about which entry matches which paper, and the
regression tests name the real sample-paper failure each one pins.
"""

import pytest
import requests
from fastapi.testclient import TestClient

from app.api.reader import get_store
from app.cache import PaperStore
from app.core.resolution import _title_score, resolve_references
from app.main import app
from app.models.citation import CitationMap, CitationStyle, Reference
from app.models.paper import PaperSource, ParsedPaper
import time as _time

from app.scholar import client as scholar_module
from app.scholar.client import ScholarError, SemanticScholar, get_scholar


def paper(arxiv="1706.03762v7", title="A Paper"):
    return ParsedPaper(
        paper_id="a" * 64,
        parser_version="1",
        source=PaperSource(filename="p.pdf", title=title, arxiv_id=arxiv),
        full_text="",
    )


def cmap(*entries: tuple[str, str | None]) -> CitationMap:
    return CitationMap(
        paper_id="a" * 64,
        parser_version="1",
        citation_version="1",
        style=CitationStyle.AUTHOR_YEAR,
        references=[
            Reference(id=f"r{i:03d}", text=text, start_char=0, end_char=1, year=year)
            for i, (text, year) in enumerate(entries, start=1)
        ],
    )


def s2(title, year=2017, pid=None, arxiv=None, oa=None):
    return {
        "paperId": pid if pid is not None else f"id-{title[:12]}",
        "title": title,
        "year": year,
        "authors": [{"name": "A. Author"}],
        "externalIds": {"ArXiv": arxiv} if arxiv else {},
        "openAccessPdf": {"url": oa} if oa else None,
    }


class FakeScholar:
    def __init__(self, references=(), batch=None, matches=None, fail=()):
        self._references = [
            {"citedPaper": p, "contexts": ["ctx"], "intents": ["method"]}
            for p in references
        ]
        self._batch = batch or {}
        self._matches = matches or {}
        self._fail = set(fail)
        self.calls = {"references": 0, "batch": 0, "match_title": 0}

    def references(self, ref):
        self.calls["references"] += 1
        if "references" in self._fail:
            raise ScholarError("429")
        return self._references

    def batch(self, ids):
        self.calls["batch"] += 1
        if "batch" in self._fail:
            raise ScholarError("429")
        return [self._batch.get(i) for i in ids]

    def match_title(self, title):
        self.calls["match_title"] += 1
        return self._matches.get(title)


def resolved(result):
    return {i.reference_id: i for i in result.items}


# --- matching by title ------------------------------------------------------------


def test_an_entry_matches_the_citing_papers_reference_by_title():
    entries = cmap(
        ("Ashish Vaswani and others. 2017. Attention is all you need. In NIPS.", "2017")
    )
    fake = FakeScholar(references=[s2("Attention Is All You Need", arxiv="1706.03762")])

    item = resolved(resolve_references(paper(), entries, fake))["r001"]

    assert item.method.value == "s2-references"
    assert item.arxiv_id == "1706.03762"
    assert item.contexts == ["ctx"] and item.intents == ["method"]


def test_hyphens_and_apostrophes_do_not_hide_a_match():
    # Regression: "Semi-\nsupervised" joined to "Semisupervised", "Google’s"
    # with a curly apostrophe and "Sentence- BERT" from a wrap all looked like
    # different titles.
    assert (
        _title_score(
            "Semi-Supervised Classification with GCNs",
            "Kipf. 2017. Semisupervised classification with GCNs.",
        )
        == 1.0
    )
    assert (
        _title_score(
            "Google's Neural Machine Translation System",
            "Wu. 2016. Google’s neural machine translation system.",
        )
        == 1.0
    )
    assert (
        _title_score(
            "Sentence-BERT: Sentence Embeddings",
            "Reimers. 2019. Sentence- BERT: Sentence embeddings.",
        )
        == 1.0
    )


def test_a_sibling_in_a_numbered_series_is_not_a_match():
    # Regression: "The fifth PASCAL ... challenge" matched "The Sixth PASCAL ...
    # Challenge" at 0.86: every word but the one that matters.
    assert (
        _title_score(
            "The Sixth PASCAL Recognizing Textual Entailment Challenge",
            "Bentivogli. 2009. The fifth PASCAL recognizing textual entailment challenge.",
        )
        == 0.0
    )


def test_a_short_title_must_appear_verbatim():
    assert _title_score("Xception", "Chollet. Xception: deep learning.") == 1.0
    assert (
        _title_score("Deep Residual Learning", "Some other deep paper on learning.")
        == 0.0
    )


def test_a_near_match_with_a_far_year_is_rejected_but_a_verbatim_title_is_not():
    entries = cmap(
        (
            "X. 2010. Learning to rank documents with neural networks for retrieval.",
            "2010",
        ),
        ("Y. 2016. Attention is all you need. arXiv.", "2016"),
    )
    near = "Learning to Rank Documents with Neural Networks for Web Retrieval"
    # Guard the fixture itself: this must be a true near-match, not verbatim.
    assert 0.85 <= _title_score(near, entries.references[0].text) < 1.0
    fake = FakeScholar(
        references=[
            s2(near, year=2019),  # near, nine years off: a different paper
            s2(
                "Attention Is All You Need", year=2017
            ),  # verbatim, preprint year differs
        ]
    )

    items = resolved(resolve_references(paper(), entries, fake))

    assert not items["r001"].resolved
    assert items["r002"].resolved


def test_each_semantic_scholar_entry_is_used_once():
    entries = cmap(
        ("A. 2017. Attention is all you need.", "2017"),
        ("B. 2017. Attention is all you need (copy).", "2017"),
    )
    fake = FakeScholar(references=[s2("Attention Is All You Need")])

    items = resolved(resolve_references(paper(), entries, fake))

    assert sum(i.resolved for i in items.values()) == 1


def test_a_title_only_stub_falls_through_to_the_next_method():
    # Regression: Semantic Scholar lists some references with a title but no
    # paper id. Matching one identified nothing and blocked the fallbacks.
    entries = cmap(
        ("A. 2014. Learning phrase representations. CoRR, abs/1406.1078.", "2014")
    )
    fake = FakeScholar(
        references=[s2("Learning Phrase Representations", pid="")],
        batch={
            "arXiv:1406.1078": s2("Learning Phrase Representations", arxiv="1406.1078")
        },
    )

    item = resolved(resolve_references(paper(), entries, fake))["r001"]

    assert item.method.value == "identifier"


# --- identifiers -------------------------------------------------------------------


def test_printed_arxiv_ids_and_dois_are_looked_up_in_one_batch():
    entries = cmap(
        ("A. Layer normalization. arXiv preprint arXiv:1607.06450, 2016.", "2016"),
        ("B. Some paper. doi:10.1145/3544548.3581225.", "2023"),
    )
    fake = FakeScholar(
        batch={
            "arXiv:1607.06450": s2("Layer Normalization", arxiv="1607.06450"),
            "DOI:10.1145/3544548.3581225": s2("Some Paper"),
        }
    )

    items = resolved(resolve_references(paper(), entries, fake))

    assert all(i.method.value == "identifier" for i in items.values())
    assert fake.calls["batch"] == 1


def test_an_arxiv_id_unknown_to_semantic_scholar_is_still_kept():
    # Enough for 2.3 to fetch the paper.
    entries = cmap(("A. Something. arXiv:2101.00001.", "2021"))

    item = resolved(resolve_references(paper(), entries, FakeScholar()))["r001"]

    assert item.arxiv_id == "2101.00001"
    assert item.pdf_url == "https://arxiv.org/pdf/2101.00001"


def test_the_pdf_link_prefers_arxiv_over_the_publisher():
    entries = cmap(("A. 2017. Attention is all you need.", "2017"))
    fake = FakeScholar(
        references=[
            s2(
                "Attention Is All You Need",
                arxiv="1706.03762",
                oa="https://publisher/x.pdf",
            )
        ]
    )

    item = resolved(resolve_references(paper(), entries, fake))["r001"]

    assert item.pdf_url == "https://arxiv.org/pdf/1706.03762"


# --- title search -------------------------------------------------------------------


def test_title_search_is_off_by_default():
    entries = cmap(
        (
            "Alec Radford. 2018. Improving language understanding by generative pre-training.",
            "2018",
        )
    )
    fake = FakeScholar()

    resolve_references(paper(), entries, fake)

    assert fake.calls["match_title"] == 0


def test_title_search_resolves_what_the_cheap_methods_missed():
    title = "Improving language understanding by generative pre-training"
    entries = cmap((f"Alec Radford. 2018. {title}. Technical report.", "2018"))
    fake = FakeScholar(
        matches={
            title: s2("Improving Language Understanding by Generative Pre-Training")
        }
    )

    item = resolved(resolve_references(paper(), entries, fake, title_search=True))[
        "r001"
    ]

    assert item.method.value == "title-search"


# --- the citing paper and failures ----------------------------------------------------


def test_a_paper_without_an_arxiv_id_is_found_by_its_title():
    fake = FakeScholar(
        matches={
            "Some Long Paper Title Here": s2("Some Long Paper Title Here", pid="P1")
        }
    )

    result = resolve_references(
        paper(arxiv=None, title="Some Long Paper Title Here"), cmap(), fake
    )

    assert result.citing_s2_id == "P1"


def test_a_failed_request_marks_the_map_incomplete():
    entries = cmap(("A. 2017. Attention is all you need.", "2017"))
    fake = FakeScholar(
        references=[s2("Attention Is All You Need")], fail={"references"}
    )

    result = resolve_references(paper(), entries, fake)

    assert result.complete is False


# --- the client ------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body
        self.headers = {}
        self.text = ""

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    def request(self, *args, **kwargs):
        self.calls += 1
        return self.responses.pop(0)


_REAL_SLEEP = _time.sleep


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(scholar_module.time, "sleep", lambda s: None)
    monkeypatch.setattr(scholar_module, "_LIMITER", scholar_module._RateLimiter(0))


def test_a_cached_response_is_not_fetched_again(tmp_path):
    session = FakeSession(FakeResponse(200, {"data": [{"citedPaper": {"title": "T"}}]}))
    client = SemanticScholar(api_key="k", cache_dir=tmp_path, session=session)

    client.references("arXiv:1")
    client.references("arXiv:1")

    assert session.calls == 1


def test_a_429_is_retried(tmp_path):
    session = FakeSession(FakeResponse(429), FakeResponse(200, {"data": []}))
    client = SemanticScholar(api_key="k", cache_dir=tmp_path, session=session)

    assert client.references("arXiv:1") == []
    assert session.calls == 2


def test_a_not_found_is_an_answer_and_is_cached(tmp_path):
    session = FakeSession(FakeResponse(404))
    client = SemanticScholar(api_key="k", cache_dir=tmp_path, session=session)

    assert client.match_title("nothing") is None
    assert client.match_title("nothing") is None
    assert session.calls == 1


def test_a_failure_is_never_cached(tmp_path):
    session = FakeSession(*[FakeResponse(503)] * 6, FakeResponse(200, {"data": []}))
    client = SemanticScholar(api_key="k", cache_dir=tmp_path, session=session)

    with pytest.raises(ScholarError):
        client.references("arXiv:1")
    assert (
        client.references("arXiv:1") == []
    )  # tried again, not served a cached failure


def test_the_limiter_spaces_requests(monkeypatch):
    import time

    # The autouse fixture stubs out sleeping for retry tests; this one needs it.
    monkeypatch.setattr(scholar_module.time, "sleep", _REAL_SLEEP)
    limiter = scholar_module._RateLimiter(0.05)
    start = time.monotonic()
    for _ in range(3):
        limiter.wait()
    assert time.monotonic() - start >= 0.1


# --- the endpoints --------------------------------------------------------------------


@pytest.fixture
def api(tmp_path):
    fake = FakeScholar()
    app.dependency_overrides[get_store] = lambda: PaperStore(tmp_path)
    app.dependency_overrides[get_scholar] = lambda: fake
    yield TestClient(app), fake
    app.dependency_overrides.clear()


@pytest.fixture
def paper_id(api, synthetic_pdf):
    client, _ = api
    return client.post(
        "/api/reader/papers",
        files={"file": ("synthetic.pdf", synthetic_pdf, "application/pdf")},
    ).json()["paper_id"]


def test_resolve_then_read_back_from_cache(api, paper_id):
    client, _ = api
    posted = client.post(f"/api/reader/papers/{paper_id}/references/resolve")
    assert posted.status_code == 200

    got = client.get(f"/api/reader/papers/{paper_id}/references/resolved")
    assert got.status_code == 200
    assert got.json() == posted.json()


def test_reading_before_resolving_is_404(api, paper_id):
    client, _ = api
    assert (
        client.get(f"/api/reader/papers/{paper_id}/references/resolved").status_code
        == 404
    )


def test_an_incomplete_resolution_is_served_but_not_cached(
    api, paper_id, tmp_path, monkeypatch
):
    # Same rule as reading paths in 1.6: a map missing entries because a
    # request failed looks like a complete one with more misses, so caching it
    # would make a passing rate limit permanent.
    from app.models.resolution import ResolutionMap

    def incomplete(paper, citations, scholar, *, title_search=False):
        return ResolutionMap(
            paper_id=paper.paper_id,
            parser_version=paper.parser_version,
            citation_version="1",
            resolver_version="1",
            complete=False,
        )

    monkeypatch.setattr("app.api.reader.resolve_references", incomplete)
    client, _ = api

    response = client.post(f"/api/reader/papers/{paper_id}/references/resolve")

    assert response.status_code == 200
    assert response.json()["complete"] is False
    assert not list((tmp_path / "resolutions").glob("*.json"))
    assert (
        client.get(f"/api/reader/papers/{paper_id}/references/resolved").status_code
        == 404
    )
