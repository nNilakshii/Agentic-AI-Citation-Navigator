"""Bibliometrics for a cited work (task 3.5), against fake databases."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.reader import get_store
from app.cache import PaperStore
from app.core.bibliometrics import bibliometrics_for, is_stale, use_in_paper
from app.main import app
from app.models.citation import CitationAnchor, CitationMap, CitationStyle, Reference
from app.models.paper import PaperSource, ParsedPaper, Section, Sentence
from app.models.resolution import ResolutionMap, ResolvedReference
from app.scholar.client import ScholarError, get_scholar
from app.scholar.openalex import OpenAlexError, get_openalex

NOW = datetime(2026, 11, 10, tzinfo=timezone.utc)


def citing_paper() -> ParsedPaper:
    sentences = [
        Sentence(
            id=f"s{i}",
            text="t",
            start_char=i * 10,
            end_char=i * 10 + 5,
            section_id=sec,
            page=0,
        )
        for i, sec in enumerate([0, 0, 1, 2])
    ]
    return ParsedPaper(
        paper_id="a" * 64,
        parser_version="1",
        source=PaperSource(filename="p.pdf"),
        full_text="x" * 50,
        sections=[
            Section(
                id=0, title="1 Introduction", level=1, start_char=0, end_char=20, page=0
            ),
            Section(
                id=1, title="3 Method", level=1, start_char=20, end_char=30, page=0
            ),
            Section(
                id=2, title="5 Results", level=1, start_char=30, end_char=50, page=0
            ),
        ],
        sentences=sentences,
    )


def citations(*placements: tuple[str, str | None]) -> CitationMap:
    return CitationMap(
        paper_id="a" * 64,
        parser_version="1",
        citation_version="1",
        style=CitationStyle.NUMERIC,
        references=[Reference(id="r001", text="x", start_char=0, end_char=1)],
        anchors=[
            CitationAnchor(
                id=f"c{i}",
                text="1",
                start_char=0,
                end_char=1,
                sentence_id=sid,
                reference_id=ref,
            )
            for i, (sid, ref) in enumerate(placements)
        ],
    )


def item(resolved=True) -> ResolvedReference:
    if not resolved:
        return ResolvedReference(reference_id="r001")
    return ResolvedReference(
        reference_id="r001",
        s2_paper_id="s2",
        title="Attention Is All You Need",
        year=2017,
    )


class FakeScholar:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def paper(self, paper_id, fields="", fresh=False):
        self.calls.append(fresh)
        if self.fail:
            raise ScholarError("429")
        return {
            "title": "Attention Is All You Need",
            "year": 2017,
            "venue": "NeurIPS",
            "citationCount": 202352,
            "influentialCitationCount": 21474,
            "fieldsOfStudy": ["Computer Science"],
            "externalIds": {"DOI": "10.48550/arXiv.1706.03762"},
        }

    # The endpoint resolves references first; nothing to find there.
    def references(self, ref):
        return []

    def batch(self, ids):
        return [None for _ in ids]

    def match_title(self, title):
        return None


class FakeOpenAlex:
    def __init__(self, fail=False, work=True):
        self.fail, self.work = fail, work
        self.dois = []

    def by_doi(self, doi, select="", fresh=False):
        self.dois.append(doi)
        if self.fail:
            raise OpenAlexError("HTTP 503")
        if not self.work:
            return None
        return {
            "title": "Attention Is All You Need",
            "publication_year": 2017,
            "cited_by_count": 136007,
            "counts_by_year": [
                {"year": 2025, "cited_by_count": 28293},
                {"year": 2018, "cited_by_count": 992},
                {"year": 2014, "cited_by_count": 1},  # before publication
                {"year": 2013, "cited_by_count": 2},
            ],
            "cited_by_percentile_year": {"min": 99.9, "max": 100},
        }

    def by_title(self, title, select="", fresh=False):
        return None


def test_both_databases_are_reported_with_their_source():
    result = bibliometrics_for(
        citing_paper(), citations(), item(), FakeScholar(), FakeOpenAlex(), now=NOW
    )
    by_source = {c.source: c for c in result.counts}
    assert by_source["semantic-scholar"].citations == 202352
    assert by_source["semantic-scholar"].influential == 21474
    assert by_source["openalex"].citations == 136007
    assert result.venue == "NeurIPS" and result.fields_of_study == ["Computer Science"]
    assert result.percentile == 99.9
    assert result.fetched_at == "2026-11-10T00:00:00+00:00"


def test_the_trend_starts_at_publication_and_says_what_it_left_out():
    result = bibliometrics_for(
        citing_paper(), citations(), item(), FakeScholar(), FakeOpenAlex(), now=NOW
    )
    assert [y.year for y in result.by_year] == [2018, 2025]
    assert not any(y.partial for y in result.by_year)
    later = bibliometrics_for(
        citing_paper(),
        citations(),
        item(),
        FakeScholar(),
        FakeOpenAlex(),
        now=datetime(2025, 6, 1, tzinfo=timezone.utc),
    )
    assert [y.partial for y in later.by_year] == [False, True]
    assert any("3 citation(s) dated before" in n for n in result.notes)


def test_openalex_is_found_by_the_doi_semantic_scholar_supplies():
    oa = FakeOpenAlex()
    bibliometrics_for(citing_paper(), citations(), item(), FakeScholar(), oa, now=NOW)
    assert oa.dois == ["10.48550/arXiv.1706.03762"]


def test_use_in_paper_counts_mentions_and_orders_sections():
    paper = citing_paper()
    use = use_in_paper(
        paper,
        citations(("s2", "r001"), ("s0", "r001"), ("s1", "r001"), ("s3", "r009")),
        "r001",
    )
    assert use.mentions == 3
    assert use.sections == ["3 Method", "1 Introduction"]


def test_an_unidentified_reference_asks_no_database():
    scholar, oa = FakeScholar(), FakeOpenAlex()
    result = bibliometrics_for(
        citing_paper(),
        citations(("s0", "r001")),
        item(resolved=False),
        scholar,
        oa,
        now=NOW,
    )
    assert result.counts == [] and scholar.calls == [] and oa.dois == []
    assert result.in_this_paper.mentions == 1
    assert "not identified" in result.notes[0]


def test_a_failed_lookup_is_reported_and_the_other_still_used():
    result = bibliometrics_for(
        citing_paper(),
        citations(),
        item(),
        FakeScholar(fail=True),
        FakeOpenAlex(),
        now=NOW,
    )
    assert [
        c.source for c in result.counts
    ] == []  # no DOI without S2, title search finds none
    assert any("Semantic Scholar lookup failed" in n for n in result.notes)
    result = bibliometrics_for(
        citing_paper(),
        citations(),
        item(),
        FakeScholar(),
        FakeOpenAlex(fail=True),
        now=NOW,
    )
    assert [c.source for c in result.counts] == ["semantic-scholar"]
    assert any("OpenAlex lookup failed" in n for n in result.notes)


def test_staleness():
    fresh = (NOW - timedelta(days=29)).isoformat()
    old = (NOW - timedelta(days=30)).isoformat()
    assert not is_stale(fresh, NOW) and is_stale(old, NOW) and is_stale("garbage", NOW)


# --- the endpoint -----------------------------------------------------------------


@pytest.fixture
def api(tmp_path, monkeypatch):
    store = PaperStore(tmp_path)
    paper = citing_paper()
    store.save_parsed(paper)
    resolution = ResolutionMap(
        paper_id=paper.paper_id,
        parser_version="1",
        citation_version="1",
        resolver_version="1",
        items=[item()],
    )
    monkeypatch.setattr("app.api.reader._resolution", lambda p, s, sc: resolution)
    monkeypatch.setattr(
        "app.api.reader.build_citation_map", lambda p: citations(("s0", "r001"))
    )
    scholar, oa = FakeScholar(), FakeOpenAlex()
    app.dependency_overrides.update(
        {
            get_store: lambda: store,
            get_scholar: lambda: scholar,
            get_openalex: lambda: oa,
        }
    )
    yield TestClient(app), paper.paper_id, scholar, oa
    app.dependency_overrides.clear()


def test_endpoint_caches_counts_and_refreshes_on_request(api):
    http, paper_id, scholar, _ = api
    url = f"/api/reader/papers/{paper_id}/references/r001/bibliometrics"
    first = http.get(url).json()
    assert first["in_this_paper"] == {"mentions": 1, "sections": ["1 Introduction"]}
    http.get(url)
    assert scholar.calls == [False]  # second request served from the cache
    http.get(url, params={"refresh": "true"})
    assert scholar.calls == [False, True]  # a refresh bypasses every cache


def test_endpoint_does_not_cache_a_failed_lookup(api):
    http, paper_id, scholar, _ = api
    scholar.fail = True
    url = f"/api/reader/papers/{paper_id}/references/r001/bibliometrics"
    http.get(url)
    scholar.fail = False
    assert http.get(url).json()["counts"][0]["source"] == "semantic-scholar"


def test_endpoint_404s_an_unknown_reference(api):
    http, paper_id, _, _ = api
    assert (
        http.get(
            f"/api/reader/papers/{paper_id}/references/r999/bibliometrics"
        ).status_code
        == 404
    )
