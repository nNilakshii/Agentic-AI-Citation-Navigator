"""Bibliometrics for a cited work (task 3.5): no model, only counted facts.

Three kinds of number, each from where it is actually known:

- **Influence**, from Semantic Scholar: total citations and "influential"
  ones — citations that build on the work rather than mention it.
- **Trend**, from OpenAlex: citations per year, and a percentile among works
  of the same year and field.
- **Use in this paper**, from our own citation map (2.1): how many times the
  citing paper cites the work, and in which sections.

The two databases index different literature and disagree — the Attention
paper had 202k citations on one and 136k on the other — so both are shown
with their source and never averaged. OpenAlex also attributes a few
citations to years before a paper existed (record-matching errors); the
trend starts at the publication year and says how many were left out.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.bibliometrics import Bibliometrics, CitationCount, UseInPaper, YearCount
from app.models.citation import CitationMap
from app.models.paper import ParsedPaper
from app.models.resolution import ResolvedReference
from app.scholar.client import ScholarError, SemanticScholar
from app.scholar.openalex import OpenAlex, OpenAlexError

#: Bumped when the shape or sources change: part of the cache key.
BIBLIOMETRICS_VERSION = "2"
#: How old cached counts may be before they are fetched again.
MAX_AGE_DAYS = 30

S2_FIELDS = (
    "title,year,venue,citationCount,influentialCitationCount,fieldsOfStudy,externalIds"
)
OA_FIELDS = "id,title,doi,publication_year,cited_by_count,counts_by_year,cited_by_percentile_year"


def bibliometrics_for(
    citing: ParsedPaper,
    citations: CitationMap,
    item: ResolvedReference,
    scholar: SemanticScholar,
    openalex: OpenAlex | None,
    fresh: bool = False,
    now: datetime | None = None,
) -> Bibliometrics:
    """Everything known about one cited work's reach, with sources."""
    result = Bibliometrics(
        citing_paper_id=citing.paper_id,
        reference_id=item.reference_id,
        title=item.title,
        year=item.year,
        venue=item.venue,
        in_this_paper=use_in_paper(citing, citations, item.reference_id),
        fetched_at=(now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
    )
    if not item.resolved:
        result.notes.append(
            "the reference was not identified (2.2), so no database was asked"
        )
        return result

    doi = item.doi
    if item.s2_paper_id:
        try:
            meta = scholar.paper(item.s2_paper_id, fields=S2_FIELDS, fresh=fresh) or {}
        except ScholarError as exc:
            result.notes.append(f"Semantic Scholar lookup failed: {exc}")
        else:
            if meta.get("citationCount") is not None:
                result.counts.append(
                    CitationCount(
                        source="semantic-scholar",
                        citations=meta["citationCount"],
                        influential=meta.get("influentialCitationCount"),
                    )
                )
            result.title = result.title or meta.get("title")
            result.year = result.year or meta.get("year")
            result.venue = result.venue or meta.get("venue") or None
            result.fields_of_study = meta.get("fieldsOfStudy") or []
            doi = doi or (meta.get("externalIds") or {}).get("DOI")

    if openalex is not None:
        try:
            work = _openalex_work(openalex, doi, result.title, fresh)
        except OpenAlexError as exc:
            result.notes.append(f"OpenAlex lookup failed: {exc}")
        else:
            if work is None:
                result.notes.append("OpenAlex does not have it")
            else:
                _add_openalex(result, work)
    return result


def use_in_paper(
    citing: ParsedPaper, citations: CitationMap, reference_id: str
) -> UseInPaper:
    """Mentions of one reference in the citing paper, and their sections."""
    sentence_section = {s.id: s.section_id for s in citing.sentences}
    titles = {s.id: s.title for s in citing.sections}
    sections: list[str] = []
    mentions = 0
    for anchor in citations.anchors:
        if anchor.reference_id != reference_id:
            continue
        mentions += 1
        title = titles.get(sentence_section.get(anchor.sentence_id))
        if title and title not in sections:
            sections.append(title)
    return UseInPaper(mentions=mentions, sections=sections)


def is_stale(fetched_at: str, now: datetime | None = None) -> bool:
    try:
        then = datetime.fromisoformat(fetched_at)
    except ValueError:
        return True
    age = (now or datetime.now(timezone.utc)) - then
    return age.days >= MAX_AGE_DAYS


def _openalex_work(
    openalex: OpenAlex, doi: str | None, title: str | None, fresh: bool
) -> dict | None:
    from app.core.resolution import _norm

    if doi:
        work = openalex.by_doi(doi, select=OA_FIELDS, fresh=fresh)
        if work:
            return work
    if title:
        work = openalex.by_title(title, select=OA_FIELDS, fresh=fresh)
        # A title hit counts only if it is the same title (as in 2.3).
        if work and _norm(work.get("title") or "") == _norm(title):
            return work
    return None


def _add_openalex(result: Bibliometrics, work: dict) -> None:
    if work.get("cited_by_count") is not None:
        result.counts.append(
            CitationCount(source="openalex", citations=work["cited_by_count"])
        )
    published = work.get("publication_year") or result.year
    result.year = result.year or published
    early = 0
    years = []
    for row in work.get("counts_by_year") or []:
        year, n = row.get("year"), row.get("cited_by_count", 0)
        if not isinstance(year, int):
            continue
        if published and year < published:
            early += n
            continue
        years.append(YearCount(year=year, citations=n))
    result.by_year = sorted(years, key=lambda y: y.year)
    this_year = int(result.fetched_at[:4])
    for row in result.by_year:
        row.partial = row.year == this_year
    if early:
        result.notes.append(
            f"OpenAlex lists {early} citation(s) dated before the work was "
            "published — record-matching errors — left out of the yearly trend"
        )
    percentile = (work.get("cited_by_percentile_year") or {}).get("min")
    if isinstance(percentile, (int, float)):
        result.percentile = float(percentile)
