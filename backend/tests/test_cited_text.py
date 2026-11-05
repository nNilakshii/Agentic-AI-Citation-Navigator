"""Fetching a cited paper's text (task 2.3), with no network.

Two halves: the downloader's guards (it fetches URLs a third party chose, on a
public server), and the fallback ladder full text -> abstract -> unavailable.
"""

import socket

import pytest
import requests
from fastapi.testclient import TestClient

from app.api.reader import get_store
from app.cache import PaperStore
from app.core.cited_text import fetch_cited_text
from app.main import app
from app.models.cited import TextSource
from app.models.paper import PaperSource, ParsedPaper
from app.models.resolution import ResolutionMap, ResolvedReference
from app.scholar import download
from app.scholar.client import ScholarError, get_scholar
from app.scholar.download import Downloader, DownloadError, check_url, get_downloader
from app.scholar.openalex import OpenAlex, OpenAlexError, abstract_text, get_openalex

# --- the downloader ---------------------------------------------------------


@pytest.fixture
def dns(monkeypatch):
    """Resolve hostnames from a dict; no pacing sleeps."""
    table = {"arxiv.org": "151.101.1.1", "example.org": "93.184.215.14"}

    def fake_getaddrinfo(host, port, *args, **kwargs):
        if host not in table:
            raise socket.gaierror(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (table[host], port))]

    monkeypatch.setattr(download.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(download._PACER, "wait", lambda host: None)
    return table


class Response:
    def __init__(self, status=200, body=b"%PDF-1.7 ...", headers=None):
        self.status_code = status
        self.headers = headers or {}
        self._body = body
        self.closed = False

    def iter_content(self, chunk_size):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]

    def close(self):
        self.closed = True


class Session:
    def __init__(self, responses):
        self._responses = dict(responses)
        self.requested = []

    def get(self, url, **kwargs):
        self.requested.append(url)
        reply = self._responses[url]
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1", "0.0.0.0"],
)
def test_internal_addresses_are_refused(dns, address):
    # 169.254.169.254 is the cloud metadata service: the classic SSRF target.
    dns["evil.example"] = address
    with pytest.raises(DownloadError, match="non-public"):
        check_url("https://evil.example/paper.pdf")


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "ftp://example.org/a.pdf", "https:///nohost"]
)
def test_only_http_urls_are_fetched(dns, url):
    with pytest.raises(DownloadError, match="not an http"):
        check_url(url)


def test_a_pdf_is_returned(dns):
    session = Session({"https://arxiv.org/pdf/1": Response()})
    assert Downloader(session).fetch_pdf("https://arxiv.org/pdf/1").startswith(b"%PDF-")


def test_every_redirect_hop_is_checked(dns):
    # A public link that redirects inward must be stopped at the redirect.
    dns["internal.example"] = "10.1.2.3"
    session = Session(
        {
            "https://example.org/a.pdf": Response(
                302, headers={"Location": "http://internal.example/secret"}
            )
        }
    )
    with pytest.raises(DownloadError, match="non-public"):
        Downloader(session).fetch_pdf("https://example.org/a.pdf")
    assert session.requested == ["https://example.org/a.pdf"]


def test_a_relative_redirect_is_followed(dns):
    session = Session(
        {
            "https://example.org/a": Response(301, headers={"Location": "/b.pdf"}),
            "https://example.org/b.pdf": Response(),
        }
    )
    assert Downloader(session).fetch_pdf("https://example.org/a").startswith(b"%PDF-")


def test_redirect_loops_end(dns):
    loop = Response(302, headers={"Location": "https://example.org/a"})
    session = Session({"https://example.org/a": loop})
    with pytest.raises(DownloadError, match="too many redirects"):
        Downloader(session).fetch_pdf("https://example.org/a")


def test_an_html_landing_page_is_not_a_pdf(dns):
    page = Response(body=b"<!doctype html><title>Sign in</title>")
    session = Session({"https://example.org/a.pdf": page})
    with pytest.raises(DownloadError, match="did not return a PDF"):
        Downloader(session).fetch_pdf("https://example.org/a.pdf")


def test_the_size_cap_holds_while_streaming(dns, monkeypatch):
    # No Content-Length, so the cap has to be enforced on the bytes themselves.
    monkeypatch.setattr(download, "MAX_BYTES", 100)
    big = Response(body=b"%PDF-" + b"x" * 200)
    session = Session({"https://example.org/a.pdf": big})
    with pytest.raises(DownloadError, match="limit"):
        Downloader(session).fetch_pdf("https://example.org/a.pdf")
    assert big.closed


def test_a_declared_oversize_is_refused_before_reading(dns, monkeypatch):
    monkeypatch.setattr(download, "MAX_BYTES", 100)
    big = Response(headers={"Content-Length": "5000"})
    session = Session({"https://example.org/a.pdf": big})
    with pytest.raises(DownloadError, match="limit"):
        Downloader(session).fetch_pdf("https://example.org/a.pdf")


def test_http_errors_and_timeouts_become_reasons(dns):
    session = Session(
        {
            "https://example.org/gone.pdf": Response(404),
            "https://example.org/slow.pdf": requests.Timeout(),
        }
    )
    with pytest.raises(DownloadError, match="HTTP 404"):
        Downloader(session).fetch_pdf("https://example.org/gone.pdf")
    with pytest.raises(DownloadError, match="Timeout"):
        Downloader(session).fetch_pdf("https://example.org/slow.pdf")


def test_the_pacer_spaces_requests_to_one_host(monkeypatch):
    clock = {"now": 100.0}
    slept = []
    monkeypatch.setattr(download.time, "monotonic", lambda: clock["now"])

    def sleep(seconds):
        slept.append(seconds)
        clock["now"] += seconds

    monkeypatch.setattr(download.time, "sleep", sleep)
    pacer = download._HostPacer()
    pacer.wait("arxiv.org")
    pacer.wait("arxiv.org")
    pacer.wait("example.org")  # another host is not held up
    assert slept == [pytest.approx(3.0)]


# --- the fallback ladder ----------------------------------------------------


CITING = ParsedPaper(
    paper_id="c" * 64,
    parser_version="1",
    source=PaperSource(filename="citing.pdf"),
    full_text="",
)


def resolution(**fields) -> ResolutionMap:
    return ResolutionMap(
        paper_id=CITING.paper_id,
        parser_version="1",
        citation_version="1",
        resolver_version="1",
        items=[ResolvedReference(reference_id="r001", title="Cited Work", **fields)],
    )


class FakeDownloader:
    def __init__(self, replies):
        self._replies = replies
        self.requested = []

    def fetch_pdf(self, url):
        self.requested.append(url)
        reply = self._replies.get(url, DownloadError("HTTP 404"))
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeScholar:
    def __init__(self, abstract=None, fail=False, ids=None, oa=None):
        self._abstract = abstract
        self._fail = fail
        self._ids = ids or {}
        self._oa = oa
        self.calls = 0

    # The endpoint resolves references (2.2) first; nothing to find here.
    def references(self, ref):
        return []

    def batch(self, ids):
        return [None for _ in ids]

    def match_title(self, title):
        return None

    def paper(self, paper_id, fields="title,abstract"):
        self.calls += 1
        if self._fail:
            raise ScholarError("429")
        return {
            "title": "Cited Work",
            "abstract": self._abstract,
            "externalIds": self._ids,
            "openAccessPdf": {"url": self._oa or ""},
        }


ARXIV = "https://arxiv.org/pdf/2001.00001"
OA = "https://example.org/oa.pdf"


def test_arxiv_is_tried_before_the_open_access_link(tmp_path, synthetic_pdf):
    store = PaperStore(tmp_path)
    fetcher = FakeDownloader({ARXIV: synthetic_pdf, OA: synthetic_pdf})
    res = resolution(s2_paper_id="s", arxiv_id="2001.00001", open_access_pdf=OA)
    result = fetch_cited_text(CITING, "r001", res, store, FakeScholar(), fetcher)

    assert result.source is TextSource.FULL_TEXT
    assert result.fetched_from == ARXIV
    assert fetcher.requested == [ARXIV]
    assert result.n_sentences > 0
    # The cited paper is now an ordinary paper the reader can open.
    assert store.load_parsed(result.cited_paper_id, "1") is not None
    assert store.pdf_path(result.cited_paper_id).exists()


def test_a_failed_link_falls_through_to_the_next(tmp_path, synthetic_pdf):
    fetcher = FakeDownloader({ARXIV: DownloadError("HTTP 503"), OA: synthetic_pdf})
    res = resolution(s2_paper_id="s", arxiv_id="2001.00001", open_access_pdf=OA)
    result = fetch_cited_text(
        CITING, "r001", res, PaperStore(tmp_path), FakeScholar(), fetcher
    )
    assert result.source is TextSource.FULL_TEXT
    assert result.fetched_from == OA
    assert result.attempts == [f"{ARXIV}: HTTP 503"]


def test_no_pdf_falls_back_to_the_abstract(tmp_path):
    fetcher = FakeDownloader({OA: DownloadError("the link did not return a PDF")})
    res = resolution(s2_paper_id="s", open_access_pdf=OA)
    result = fetch_cited_text(
        CITING, "r001", res, PaperStore(tmp_path), FakeScholar("We study X."), fetcher
    )
    assert result.source is TextSource.ABSTRACT
    assert result.abstract == "We study X."
    assert result.cited_paper_id is None
    assert "did not return a PDF" in result.attempts[0]


def test_an_unparseable_pdf_falls_back_too(tmp_path):
    fetcher = FakeDownloader({OA: b"%PDF-1.7 truncated garbage"})
    res = resolution(s2_paper_id="s", open_access_pdf=OA)
    result = fetch_cited_text(
        CITING, "r001", res, PaperStore(tmp_path), FakeScholar("Abs."), fetcher
    )
    assert result.source is TextSource.ABSTRACT
    assert "could not be parsed" in result.attempts[0]


def test_unavailable_says_why(tmp_path):
    res = resolution(s2_paper_id="s")
    result = fetch_cited_text(
        CITING, "r001", res, PaperStore(tmp_path), FakeScholar(None), FakeDownloader({})
    )
    assert result.source is TextSource.UNAVAILABLE
    assert result.attempts == ["Semantic Scholar has no abstract for it"]


def test_an_unidentified_reference_is_unavailable_without_any_request(tmp_path):
    scholar, fetcher = FakeScholar("Abs."), FakeDownloader({})
    result = fetch_cited_text(
        CITING, "r001", resolution(), PaperStore(tmp_path), scholar, fetcher
    )
    assert result.source is TextSource.UNAVAILABLE
    assert "not identified" in result.attempts[0]
    assert scholar.calls == 0 and fetcher.requested == []


def test_an_abstract_lookup_failure_is_reported(tmp_path):
    res = resolution(s2_paper_id="s")
    result = fetch_cited_text(
        CITING,
        "r001",
        res,
        PaperStore(tmp_path),
        FakeScholar(fail=True),
        FakeDownloader({}),
    )
    assert result.source is TextSource.UNAVAILABLE
    assert "lookup failed" in result.attempts[0]


def test_an_unknown_reference_is_a_key_error(tmp_path):
    with pytest.raises(KeyError):
        fetch_cited_text(
            CITING,
            "r999",
            resolution(),
            PaperStore(tmp_path),
            FakeScholar(),
            FakeDownloader({}),
        )


def test_a_fetched_pdf_is_never_downloaded_twice(tmp_path, synthetic_pdf):
    store = PaperStore(tmp_path)
    res = resolution(s2_paper_id="s", arxiv_id="2001.00001")
    first = FakeDownloader({ARXIV: synthetic_pdf})
    fetch_cited_text(CITING, "r001", res, store, FakeScholar(), first)

    second = FakeDownloader({})
    again = fetch_cited_text(CITING, "r001", res, store, FakeScholar(), second)
    assert again.source is TextSource.FULL_TEXT
    assert second.requested == []


def test_a_failure_is_not_remembered(tmp_path, synthetic_pdf):
    # arXiv down today must not mean "unavailable" forever (the 1.6 lesson).
    store = PaperStore(tmp_path)
    res = resolution(s2_paper_id="s", arxiv_id="2001.00001")
    down = FakeDownloader({ARXIV: DownloadError("HTTP 503")})
    assert (
        fetch_cited_text(CITING, "r001", res, store, FakeScholar(), down).source
        is TextSource.UNAVAILABLE
    )
    up = FakeDownloader({ARXIV: synthetic_pdf})
    assert (
        fetch_cited_text(CITING, "r001", res, store, FakeScholar(), up).source
        is TextSource.FULL_TEXT
    )


def test_an_acl_id_from_a_fresh_lookup_gives_the_pdf(tmp_path, synthetic_pdf):
    # Real case: "Purpose and Polarity of Citation" resolved with no link, but a
    # direct lookup knows its ACL id (N13-1067), and the Anthology hosts it.
    acl = "https://aclanthology.org/N13-1067.pdf"
    fetcher = FakeDownloader({acl: synthetic_pdf})
    scholar = FakeScholar(None, ids={"ACL": "N13-1067"})
    result = fetch_cited_text(
        CITING,
        "r001",
        resolution(s2_paper_id="s"),
        PaperStore(tmp_path),
        scholar,
        fetcher,
    )
    assert result.source is TextSource.FULL_TEXT
    assert result.fetched_from == acl


def test_an_arxiv_doi_names_the_arxiv_pdf(tmp_path, synthetic_pdf):
    # Real case: SciBERT matched a record whose only id was 10.48550/arXiv.1903.10676.
    url = "https://arxiv.org/pdf/1903.10676"
    fetcher = FakeDownloader({url: synthetic_pdf})
    res = resolution(s2_paper_id="s", doi="10.48550/arXiv.1903.10676")
    result = fetch_cited_text(
        CITING, "r001", res, PaperStore(tmp_path), FakeScholar(), fetcher
    )
    assert result.fetched_from == url
    assert fetcher.requested == [url]


def test_a_link_that_failed_is_not_tried_again_after_the_lookup(tmp_path):
    fetcher = FakeDownloader({ARXIV: DownloadError("HTTP 503")})
    scholar = FakeScholar("Abs.", ids={"ArXiv": "2001.00001"})
    res = resolution(s2_paper_id="s", arxiv_id="2001.00001")
    result = fetch_cited_text(
        CITING, "r001", res, PaperStore(tmp_path), scholar, fetcher
    )
    assert result.source is TextSource.ABSTRACT
    assert fetcher.requested == [ARXIV]


# --- OpenAlex, for abstracts Semantic Scholar withholds -----------------------


class FakeOpenAlex:
    def __init__(self, by_doi=None, by_title=None, fail=False):
        self._doi = by_doi or {}
        self._title = by_title
        self._fail = fail
        self.calls = []

    def by_doi(self, doi):
        self.calls.append(("doi", doi))
        if self._fail:
            raise OpenAlexError("HTTP 503")
        return self._doi.get(doi)

    def by_title(self, title):
        self.calls.append(("title", title))
        if self._fail:
            raise OpenAlexError("HTTP 503")
        return self._title


def work(title="Cited Work", words=("We", "study", "X."), pdf=None):
    return {
        "title": title,
        "abstract_inverted_index": {w: [i] for i, w in enumerate(words)},
        "best_oa_location": {"pdf_url": pdf} if pdf else None,
    }


def test_abstract_text_rebuilds_word_order():
    index = {"the": [0, 3], "cat": [1], "saw": [2], "dog": [4]}
    assert abstract_text({"abstract_inverted_index": index}) == "the cat saw the dog"
    assert abstract_text({"abstract_inverted_index": None}) is None


def test_openalex_supplies_the_abstract_semantic_scholar_withheld(tmp_path):
    # Real case: "Physicists Reading Physics" — elided by the publisher on S2.
    oa = FakeOpenAlex(by_doi={"10.1/x": work()})
    res = resolution(s2_paper_id="s", doi="10.1/x")
    result = fetch_cited_text(
        CITING,
        "r001",
        res,
        PaperStore(tmp_path),
        FakeScholar(None),
        FakeDownloader({}),
        oa,
    )
    assert result.source is TextSource.ABSTRACT
    assert result.abstract == "We study X."
    assert result.abstract_from == "openalex"
    assert "Semantic Scholar has no abstract for it" in result.attempts


def test_a_semantic_scholar_abstract_says_where_it_came_from(tmp_path):
    oa = FakeOpenAlex(by_doi={"10.1/x": work()})
    res = resolution(s2_paper_id="s", doi="10.1/x")
    result = fetch_cited_text(
        CITING,
        "r001",
        res,
        PaperStore(tmp_path),
        FakeScholar("S2."),
        FakeDownloader({}),
        oa,
    )
    assert result.abstract_from == "semantic-scholar"
    assert oa.calls == []  # OpenAlex is only asked when needed


def test_a_title_hit_counts_only_if_it_is_the_same_title(tmp_path):
    oa = FakeOpenAlex(by_title=work(title="Cited Work, Revisited"))
    result = fetch_cited_text(
        CITING,
        "r001",
        resolution(s2_paper_id="s"),
        PaperStore(tmp_path),
        FakeScholar(None),
        FakeDownloader({}),
        oa,
    )
    assert result.source is TextSource.UNAVAILABLE
    assert "OpenAlex does not have it" in result.attempts


def test_a_title_hit_with_different_case_and_punctuation_counts(tmp_path):
    oa = FakeOpenAlex(by_title=work(title="cited  work"))
    result = fetch_cited_text(
        CITING,
        "r001",
        resolution(s2_paper_id="s"),
        PaperStore(tmp_path),
        FakeScholar(None),
        FakeDownloader({}),
        oa,
    )
    assert result.source is TextSource.ABSTRACT


def test_an_openalex_pdf_is_tried_before_its_abstract(tmp_path, synthetic_pdf):
    url = "https://example.org/oa-from-openalex.pdf"
    oa = FakeOpenAlex(by_doi={"10.1/x": work(pdf=url)})
    res = resolution(s2_paper_id="s", doi="10.1/x")
    result = fetch_cited_text(
        CITING,
        "r001",
        res,
        PaperStore(tmp_path),
        FakeScholar(None),
        FakeDownloader({url: synthetic_pdf}),
        oa,
    )
    assert result.source is TextSource.FULL_TEXT
    assert result.fetched_from == url


def test_an_openalex_failure_is_reported(tmp_path):
    result = fetch_cited_text(
        CITING,
        "r001",
        resolution(s2_paper_id="s"),
        PaperStore(tmp_path),
        FakeScholar(None),
        FakeDownloader({}),
        FakeOpenAlex(fail=True),
    )
    assert result.source is TextSource.UNAVAILABLE
    assert any("OpenAlex lookup failed" in a for a in result.attempts)


def test_an_unidentified_reference_never_reaches_openalex(tmp_path):
    oa = FakeOpenAlex(by_title=work())
    fetch_cited_text(
        CITING,
        "r001",
        resolution(),
        PaperStore(tmp_path),
        FakeScholar(),
        FakeDownloader({}),
        oa,
    )
    assert oa.calls == []


class OASession:
    def __init__(self, status=200, body=None, headers=None):
        self.status, self.body, self.params = status, body, []
        self.headers = headers or {}

    def get(self, url, params=None, timeout=None):
        self.params.append(params)
        status, body, hdrs = self.status, self.body, self.headers

        class R:
            status_code = status
            headers = hdrs

            def json(self):
                return body

        return R()


def test_title_search_strips_filter_syntax(tmp_path, monkeypatch):
    # Real case: "TVM: An Automated ..." found nothing — ':' is filter syntax.
    monkeypatch.setattr("app.scholar.openalex.MIN_INTERVAL", 0)
    session = OASession(body={"results": [work()]})
    client = OpenAlex(email="e@x", api_key="", cache_dir=tmp_path, session=session)
    client.by_title("TVM: An Automated, End-to-End Compiler")
    sent = session.params[0]["filter"]
    assert ":" not in sent.removeprefix("title.search:") and "," not in sent


def test_openalex_caches_answers_without_the_email(tmp_path, monkeypatch):
    monkeypatch.setattr("app.scholar.openalex.MIN_INTERVAL", 0)
    session = OASession(status=404)
    client = OpenAlex(
        email="someone@example.edu", api_key="", cache_dir=tmp_path, session=session
    )
    assert client.by_doi("10.1/none") is None
    assert client.by_doi("10.1/none") is None
    assert client.network_calls == 1  # the 404 was cached as an answer
    assert session.params[0]["mailto"] == "someone@example.edu"
    for path in tmp_path.iterdir():
        assert "someone" not in path.read_text()


def test_openalex_honours_retry_after_and_sends_the_key(tmp_path, monkeypatch):
    # Keyless search under load answers 429 with Retry-After ~30s.
    monkeypatch.setattr("app.scholar.openalex.MIN_INTERVAL", 0)
    slept = []
    monkeypatch.setattr("app.scholar.openalex.time.sleep", slept.append)
    session = OASession(status=429, headers={"Retry-After": "32"})
    client = OpenAlex(email=None, api_key="k", cache_dir=tmp_path, session=session)
    with pytest.raises(OpenAlexError):
        client.by_title("Cited Work")
    assert slept == [32.0, 32.0]
    assert session.params[0]["api_key"] == "k"
    assert list(tmp_path.iterdir()) == []


def test_openalex_failures_are_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr("app.scholar.openalex.MIN_INTERVAL", 0)
    monkeypatch.setattr("app.scholar.openalex.time.sleep", lambda s: None)
    client = OpenAlex(
        email=None, api_key="", cache_dir=tmp_path, session=OASession(status=503)
    )
    with pytest.raises(OpenAlexError):
        client.by_doi("10.1/x")
    assert list(tmp_path.iterdir()) == []


# --- the endpoint -----------------------------------------------------------


def test_endpoint_fetches_and_404s(tmp_path, synthetic_pdf, monkeypatch):
    store = PaperStore(tmp_path)
    client = TestClient(app)
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_scholar] = lambda: FakeScholar("Abs.")
    app.dependency_overrides[get_downloader] = lambda: FakeDownloader({})
    app.dependency_overrides[get_openalex] = lambda: FakeOpenAlex()
    try:
        uploaded = client.post(
            "/api/reader/papers",
            files={"file": ("p.pdf", synthetic_pdf, "application/pdf")},
        ).json()
        paper_id = uploaded["paper_id"]
        missing = client.post(f"/api/reader/papers/{paper_id}/references/r999/text")
        assert missing.status_code == 404
        unknown = client.post(f"/api/reader/papers/{'f' * 64}/references/r001/text")
        assert unknown.status_code == 404
    finally:
        app.dependency_overrides.clear()
