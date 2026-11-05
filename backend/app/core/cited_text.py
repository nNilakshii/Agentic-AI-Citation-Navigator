"""Get a cited paper's text, down the fallback ladder (task 2.3).

For one reference: try its PDF (arXiv, then the ACL Anthology, then the
open-access link), parse it with the same pipeline as any uploaded paper, and store it — so the
cited paper becomes an ordinary paper the reader can open, highlight and cite
from. If no PDF can be had, fall back to its abstract; if not even that,
say so.

The links from resolution (2.2) are not the last word. Semantic Scholar's
reference lists carry sparser records than a direct lookup of the same paper:
in the samples, papers with an ACL Anthology id or an arXiv DOI often came
with no link at all. So when those links fail or are missing, one fresh
lookup — the same request that fetches the abstract — is mined for more.

Semantic Scholar also withholds many abstracts at the publisher's request, so
the last stop before "unavailable" is OpenAlex: by DOI, else by title, and a
title hit counts only if it is the same title — a wrong abstract presented as
the cited paper's would be worse than none.

Only successes are remembered. A failed download may be a passing outage, and
caching it would turn that into a permanent "unavailable" — the 1.6 lesson.
"""

from __future__ import annotations

import re

from app.cache import PaperStore
from app.core.pdf_parser import PARSER_VERSION, parse_pdf
from app.models.cited import CitedText, TextSource
from app.models.paper import ParsedPaper
from app.core.resolution import _norm
from app.models.resolution import ResolutionMap, ResolvedReference
from app.scholar.client import ScholarError, SemanticScholar
from app.scholar.download import Downloader, DownloadError
from app.scholar.openalex import OpenAlex, OpenAlexError, abstract_text

META_FIELDS = "title,abstract,externalIds,openAccessPdf"
_ARXIV_DOI = re.compile(r"^10\.48550/arxiv\.(.+)$", re.IGNORECASE)


def fetch_cited_text(
    citing: ParsedPaper,
    reference_id: str,
    resolution: ResolutionMap,
    store: PaperStore,
    scholar: SemanticScholar,
    downloader: Downloader,
    openalex: OpenAlex | None = None,
) -> CitedText:
    """The best text available for one cited work. Raises KeyError if unknown."""
    item = next((i for i in resolution.items if i.reference_id == reference_id), None)
    if item is None:
        raise KeyError(reference_id)

    base = {
        "citing_paper_id": citing.paper_id,
        "reference_id": reference_id,
        "title": item.title,
    }
    attempts: list[str] = []
    if not item.resolved:
        attempts.append(
            "the reference was not identified (2.2), so there is no link to follow"
        )

    # Rung 1: a PDF, from the links resolution found.
    tried: list[str] = []
    found = _try_pdfs(_pdf_urls(item), tried, item, base, store, downloader, attempts)
    if found:
        return found

    # Rung 1 again, then rung 2: one fresh lookup gives more links and the abstract.
    meta: dict = {}
    if item.s2_paper_id:
        try:
            meta = scholar.paper(item.s2_paper_id, fields=META_FIELDS) or {}
        except ScholarError as exc:
            attempts.append(f"Semantic Scholar lookup failed: {exc}")
        else:
            more = _meta_urls(meta)
            found = _try_pdfs(more, tried, item, base, store, downloader, attempts)
            if found:
                return found
            if meta.get("abstract"):
                return _abstract(base, meta["abstract"], "semantic-scholar", attempts)
            attempts.append("Semantic Scholar has no abstract for it")

    # Rung 2 again: OpenAlex, for what Semantic Scholar would not show.
    if openalex is not None and item.resolved and item.title:
        doi = item.doi or (meta.get("externalIds") or {}).get("DOI")
        try:
            work = _openalex_work(openalex, doi, item.title)
        except OpenAlexError as exc:
            attempts.append(f"OpenAlex lookup failed: {exc}")
        else:
            if work is None:
                attempts.append("OpenAlex does not have it")
            else:
                oa_pdf = (work.get("best_oa_location") or {}).get("pdf_url")
                found = _try_pdfs(
                    _ordered(oa_pdf), tried, item, base, store, downloader, attempts
                )
                if found:
                    return found
                abstract = abstract_text(work)
                if abstract:
                    return _abstract(base, abstract, "openalex", attempts)
                attempts.append("OpenAlex has no abstract for it")

    # Rung 3: say so.
    return CitedText(**base, source=TextSource.UNAVAILABLE, attempts=attempts)


def _try_pdfs(
    urls: list[str],
    tried: list[str],
    item: ResolvedReference,
    base: dict,
    store: PaperStore,
    downloader: Downloader,
    attempts: list[str],
) -> CitedText | None:
    """The first of ``urls`` that yields a parseable PDF, skipping any tried."""
    for url in urls:
        if url in tried:
            continue
        tried.append(url)
        known = store.load_fetched(url)
        if known:
            parsed = store.load_parsed(known, PARSER_VERSION)
            if parsed is not None:
                return _full_text(base, parsed, url, attempts)
        try:
            data = downloader.fetch_pdf(url)
        except DownloadError as exc:
            attempts.append(f"{url}: {exc.reason}")
            continue
        try:
            parsed = parse_pdf(data, _filename(item))
        except ValueError as exc:
            attempts.append(f"{url}: downloaded, but could not be parsed ({exc})")
            continue
        if not parsed.sentences:
            # A scanned PDF: pages of images with no text layer.
            attempts.append(f"{url}: downloaded, but it has no extractable text")
            continue
        store.save_pdf(parsed.paper_id, data)
        store.save_parsed(parsed)
        store.save_fetched(url, parsed.paper_id)
        return _full_text(base, parsed, url, attempts)
    return None


def _openalex_work(openalex: OpenAlex, doi: str | None, title: str) -> dict | None:
    """The OpenAlex record for this paper, by DOI or an exactly matching title."""
    if doi:
        work = openalex.by_doi(doi)
        if work:
            return work
    work = openalex.by_title(title)
    if work and _norm(work.get("title") or "") == _norm(title):
        return work
    return None


def _abstract(base: dict, text: str, origin: str, attempts: list[str]) -> CitedText:
    return CitedText(
        **base,
        source=TextSource.ABSTRACT,
        abstract=text,
        abstract_from=origin,
        attempts=attempts,
    )


def _pdf_urls(item: ResolvedReference) -> list[str]:
    """arXiv first, then the open-access link."""
    arxiv = item.arxiv_id or _arxiv_from_doi(item.doi)
    return _ordered(
        f"https://arxiv.org/pdf/{arxiv}" if arxiv else None, item.open_access_pdf
    )


def _meta_urls(meta: dict) -> list[str]:
    """Links from a direct Semantic Scholar lookup: arXiv, ACL, open access.

    The ACL Anthology hosts every ACL paper free to read, at a URL built from
    its id; Semantic Scholar often knows the id but lists no link.
    """
    ids = meta.get("externalIds") or {}
    arxiv = ids.get("ArXiv") or _arxiv_from_doi(ids.get("DOI"))
    acl = ids.get("ACL")
    return _ordered(
        f"https://arxiv.org/pdf/{arxiv}" if arxiv else None,
        f"https://aclanthology.org/{acl}.pdf" if acl else None,
        (meta.get("openAccessPdf") or {}).get("url"),
    )


def _arxiv_from_doi(doi: str | None) -> str | None:
    """arXiv's own DOIs (10.48550/arXiv.X) name the arXiv id."""
    match = _ARXIV_DOI.match(doi or "")
    return match.group(1) if match else None


def _ordered(*urls: str | None) -> list[str]:
    seen: list[str] = []
    for url in urls:
        if url and url not in seen:
            seen.append(url)
    return seen


def _full_text(
    base: dict, parsed: ParsedPaper, url: str, attempts: list[str]
) -> CitedText:
    return CitedText(
        **base,
        source=TextSource.FULL_TEXT,
        cited_paper_id=parsed.paper_id,
        fetched_from=url,
        n_sentences=len(parsed.sentences),
        attempts=attempts,
    )


def _filename(item: ResolvedReference) -> str:
    stem = item.arxiv_id or item.s2_paper_id or item.reference_id
    return f"{stem}.pdf"
