"""Work out which real paper each reference entry is (task 2.2).

Three methods, tried cheapest first:

1. **The citing paper's own reference list** on Semantic Scholar — one request
   returns every work it cites, with titles, ids and open-access links. Each
   parsed entry is matched to one of those by title.
2. **Identifiers printed in the entry** — arXiv ids and DOIs, looked up in a
   single batched request.
3. **Title search**, one request per remaining entry. Off by default: at one
   request per second it turns a sub-second call into a minute.

Searching per entry first is the obvious design and the wrong one under a
1-request-per-second key: ~2,000 references would take half an hour.

Matching is by title, because a reference entry always contains the cited
work's title verbatim (or nearly), while author and venue formatting vary by
style. The title must account for most of its words inside the entry text.
"""

from __future__ import annotations

import re
import unicodedata

from app.models.citation import CitationMap, Reference
from app.models.paper import ParsedPaper
from app.models.resolution import ResolutionMap, ResolutionMethod, ResolvedReference
from app.scholar.client import ScholarError, SemanticScholar

#: Bumped when matching changes; part of the cache key.
RESOLVER_VERSION = "1"

#: Share of a title's words that must appear in the entry for a match.
MIN_CONFIDENCE = 0.85

#: Titles this short ("Xception", "GloVe") would match anywhere by word overlap,
#: so they must appear verbatim.
SHORT_TITLE_WORDS = 3

#: Ceiling on per-entry searches in one resolution, so a long bibliography
#: cannot tie up the shared rate limiter for minutes.
MAX_TITLE_SEARCHES = 60

_ARXIV = re.compile(
    r"(?:arXiv:\s*|arxiv\.org/(?:abs|pdf)/|abs/)(\d{4}\.\d{4,5})(?:v\d+)?", re.I
)
_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s,;]+)")
_SENTENCE = re.compile(r"(?<![A-Z])\.\s+")
# A dash takes any whitespace around it with it: the PDF gives "Sentence- BERT"
# (a wrap that kept its space), Semantic Scholar "Sentence-BERT", and a title
# may carry "2018 - Using". Deleting the dash alone left a word break on one
# side only.
_JOINERS = re.compile(r"['’‘`]|\s*[\-‐‑‒–—]\s*")

#: Words that tell apart the papers of one series: "The fifth PASCAL ...
#: challenge" and "The Sixth PASCAL ... Challenge" share every other word.
_SERIES_WORDS = re.compile(
    r"^(?:\d+|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
    r"[ivx]+|\d+(?:st|nd|rd|th))$"
)


def resolve_references(
    paper: ParsedPaper,
    citations: CitationMap,
    scholar: SemanticScholar,
    *,
    title_search: bool = False,
) -> ResolutionMap:
    """Resolve every entry in ``citations`` it can, without exceeding the quota."""
    items = {r.id: ResolvedReference(reference_id=r.id) for r in citations.references}
    complete = True

    # 1. What the citing paper itself cites, according to Semantic Scholar.
    citing_ref, citing_id = _citing_paper(paper, scholar)
    if citing_ref:
        try:
            edges = scholar.references(citing_ref)
        except ScholarError:
            complete, edges = False, []
        _assign_by_title(items, citations.references, edges)

    # 2. arXiv ids and DOIs printed in the entries that are still open.
    printed = {}
    for ref in citations.references:
        if not items[ref.id].resolved:
            ident = _identifier(ref.text)
            if ident:
                printed[ref.id] = ident
    if printed:
        try:
            found = scholar.batch(list(printed.values()))
        except ScholarError:
            complete, found = False, [None] * len(printed)
        for (ref_id, ident), meta in zip(printed.items(), found):
            item = items[ref_id]
            if meta:
                _fill(item, meta, ResolutionMethod.IDENTIFIER, 1.0)
            elif ident.startswith("arXiv:"):
                # Semantic Scholar does not know it, but an arXiv id is enough
                # to fetch the paper in 2.3.
                item.arxiv_id = ident.split(":", 1)[1]
                item.method = ResolutionMethod.IDENTIFIER
                item.confidence = 1.0

    # 3. One search per entry, only when asked for.
    if title_search:
        open_refs = [r for r in citations.references if not items[r.id].resolved]
        for ref in open_refs[:MAX_TITLE_SEARCHES]:
            title = _guess_title(ref)
            if not title:
                continue
            try:
                meta = scholar.match_title(title)
            except ScholarError:
                complete = False
                continue
            if meta and meta.get("title"):
                score = _title_score(meta["title"], ref.text)
                if score >= MIN_CONFIDENCE:
                    _fill(items[ref.id], meta, ResolutionMethod.TITLE_SEARCH, score)

    return ResolutionMap(
        paper_id=paper.paper_id,
        parser_version=paper.parser_version,
        citation_version=citations.citation_version,
        resolver_version=RESOLVER_VERSION,
        citing_s2_id=citing_id,
        items=[items[r.id] for r in citations.references],
        complete=complete,
    )


# --- the citing paper -----------------------------------------------------------


def _citing_paper(
    paper: ParsedPaper, scholar: SemanticScholar
) -> tuple[str | None, str | None]:
    """How to ask Semantic Scholar for this paper's references.

    An arXiv id needs no lookup. Without one (an uploaded PDF) the paper's own
    title is matched first, and accepted only if it really is the same title.
    """
    arxiv = paper.source.arxiv_id
    if arxiv:
        return f"arXiv:{re.sub(r'v\d+$', '', arxiv)}", None
    title = paper.source.title or ""
    if len(title.split()) < 4:
        return None, None
    try:
        meta = scholar.match_title(title)
    except ScholarError:
        return None, None
    if meta and _title_score(meta.get("title") or "", title) >= 0.9:
        return meta["paperId"], meta["paperId"]
    return None, None


# --- matching -------------------------------------------------------------------


def _assign_by_title(items, references: list[Reference], edges: list[dict]) -> None:
    """Pair entries with the citing paper's references, one to one.

    Every pair scoring above the threshold is ranked and taken greedily, so
    each Semantic Scholar entry is used once and each parsed entry gets its
    best available match.
    """
    pairs = []
    for ref in references:
        for index, edge in enumerate(edges):
            cited = edge.get("citedPaper") or {}
            title = cited.get("title")
            # Some of Semantic Scholar's entries are title-only stubs with no
            # paper id. Matching one identifies nothing, and would stop the
            # entry falling through to the identifier and search steps.
            if not title or not cited.get("paperId"):
                continue
            score = _title_score(title, ref.text)
            if score < MIN_CONFIDENCE:
                continue
            # A near-match on title with a far-off year is a different paper
            # with a similar name. A verbatim title is trusted regardless:
            # preprint and publication years legitimately differ.
            if score < 1.0 and not _years_agree(ref.year, cited.get("year")):
                continue
            pairs.append((score, ref.id, index))

    used_refs, used_edges = set(), set()
    for score, ref_id, index in sorted(pairs, key=lambda p: -p[0]):
        if ref_id in used_refs or index in used_edges:
            continue
        used_refs.add(ref_id)
        used_edges.add(index)
        edge = edges[index]
        item = items[ref_id]
        _fill(item, edge["citedPaper"], ResolutionMethod.S2_REFERENCES, score)
        item.contexts = [c for c in (edge.get("contexts") or []) if c]
        item.intents = [i for i in (edge.get("intents") or []) if i]


def _title_score(title: str, entry_text: str) -> float:
    """1.0 if the title appears verbatim; else the share of its words present."""
    t, e = _norm(title), _norm(entry_text)
    if not t:
        return 0.0
    if f" {t} " in f" {e} ":
        return 1.0
    words = t.split()
    if len(words) <= SHORT_TITLE_WORDS:
        return 0.0
    present = set(e.split())
    missing = [w for w in words if w not in present]
    # A near-match missing an ordinal or a number is a sibling in a series
    # (fifth vs sixth challenge, shared task 2017 vs 2018), not the same paper.
    if any(_SERIES_WORDS.match(w) for w in missing):
        return 0.0
    return (len(words) - len(missing)) / len(words)


def _years_agree(entry_year: str | None, s2_year: int | None) -> bool:
    if not entry_year or not s2_year:
        return True
    return abs(int(entry_year[:4]) - int(s2_year)) <= 1


def _fill(item: ResolvedReference, meta: dict, method, confidence: float) -> None:
    ids = meta.get("externalIds") or {}
    item.method = method
    item.confidence = round(confidence, 3)
    item.s2_paper_id = meta.get("paperId")
    item.title = meta.get("title")
    item.year = meta.get("year")
    item.authors = [a.get("name") for a in meta.get("authors") or [] if a.get("name")]
    item.venue = meta.get("venue") or None
    item.arxiv_id = ids.get("ArXiv")
    item.doi = ids.get("DOI")
    item.open_access_pdf = (meta.get("openAccessPdf") or {}).get("url") or None


# --- reading an entry ---------------------------------------------------------


def _identifier(text: str) -> str | None:
    m = _ARXIV.search(text)
    if m:
        return f"arXiv:{m.group(1)}"
    m = _DOI.search(text)
    if m:
        return f"DOI:{m.group(1).rstrip('.')}"
    return None


def _guess_title(ref: Reference) -> str | None:
    """The title part of an entry, for searching. Only used as a last resort.

    ACL puts it after "YEAR."; LNCS after the author list's colon; numeric
    styles in the second sentence. Initials ("Quoc V. Le") never end one.
    """
    text = ref.text
    if ref.year:
        m = re.search(rf"\b{re.escape(ref.year)}\.\s+(.+?)(?<![A-Z])\.\s", text + " ")
        if m and len(m.group(1).split()) >= 3:
            return m.group(1)
    m = re.match(r"[^:]{3,300}?:\s+(.+?)(?<![A-Z])\.\s", text + " ")
    if m and len(m.group(1).split()) >= 3:
        return m.group(1)
    parts = _SENTENCE.split(text)
    if len(parts) >= 2 and len(parts[1].split()) >= 3:
        return parts[1]
    return None


def _norm(text: str) -> str:
    """Lowercase ASCII words only. NFKD also unpicks PDF ligatures (ﬁ -> fi).

    Hyphens and apostrophes are deleted rather than turned into spaces. The PDF
    joins a word broken across lines ("Semi-\nsupervised" -> "Semisupervised"),
    and "Google’s" uses a curly apostrophe; keeping either as a word break made
    the same title look different on each side, and missed Kipf & Welling's
    GCN paper among others.
    """
    folded = unicodedata.normalize("NFKD", text)
    unjoined = _JOINERS.sub("", folded)
    ascii_only = unjoined.encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_only).split())
