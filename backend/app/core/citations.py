"""Find the citations in a paper and link each to its reference entry (task 2.1).

Two citation styles cover the sample set, split 4 to 6:

- **numeric** — ``[12]``, ``[3, 7]``, ``[1–4]``, against entries labelled
  ``[12]`` or ``12.``
- **author-year** — ``(Devlin et al., 2019)``, ``(Dai and Le, 2015; Peters et
  al., 2018)``, narrative ``Devlin et al. (2019)``, against entries that begin
  ``Jacob Devlin, Ming-Wei Chang, ... 2019.``

The style is decided from the reference list, never from the body: a numeric
paper still contains ``(JCDL 2016)``, and reading that as a citation would be
wrong. Likewise only body text is scanned for anchors — the reference list is
full of ``[n]`` labels — but appendices after it are scanned, because they cite
too.

Every rule below came from a measured failure on the sample papers, not from a
style guide; the reasons are next to each one.
"""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_right

from app.models.citation import CitationAnchor, CitationMap, CitationStyle, Reference
from app.models.paper import ParsedPaper

#: Bumped when detection or matching changes.
CITATION_VERSION = "1"

# The heading as a whole line. Matching it anywhere caught "Coreference
# Resolution" in Longformer before the real heading.
_HEADING = re.compile(
    r"(?m)^[ \t]*(?:\d+\.?\s+)?(?:References|REFERENCES|Bibliography|BIBLIOGRAPHY)[ \t]*$"
)

_YEAR = r"(?:19|20)\d{2}[a-z]?"
_YEAR_RE = re.compile(rf"(?<!\d)({_YEAR})(?![\d])")

# --- reference list -----------------------------------------------------------

# Labels are found anywhere in the list, not only at line starts: PyMuPDF
# merges runs of entries into one block, so "...To appear. [2] Charles..." and
# "...(2018) 2. AbuRaed, A." are common. Anchoring to line starts found 1 entry
# of ~30 in CL-SciSumm and 1 of ~50 in Semantic Reader.
_BRACKET_LABEL = re.compile(r"(?:(?<=\s)|^)\[(\d{1,3})\]\s+")
# A "2." label must follow the end of an entry, so "volume 2. Springer" inside
# an entry cannot start a new one.
_DOT_LABEL = re.compile(r"(?:(?<=[.)\]]\s)|(?<=[.)\]]\n)|^)\s*(\d{1,3})\.\s+(?=[A-Z])")

# An author-year entry opens with names (no digits) then the year: ACL's
# "Names. 2019." or APA's "Names (2019).". Checked on the *assembled* entry,
# because the year often sits on the next line of the PDF.
_ACL_ENTRY = re.compile(rf"^(?P<authors>[^\d]{{2,800}}?)\.\s+(?P<year>{_YEAR})\.")
_APA_ENTRY = re.compile(rf"^(?P<authors>[^\d]{{2,800}}?)\s*\((?P<year>{_YEAR})\)")

_PAGE_NUMBER = re.compile(r"\d{1,3}")
_ENDS_WITH_INITIAL = re.compile(r"(?:^|[\s.])[A-Z]\.$")
_BLOCK = re.compile(r"(?s)\S.*?(?=\n[ \t]*\n|\Z)")

# --- anchors -------------------------------------------------------------------

_NUMERIC_ANCHOR = re.compile(r"\[(\d{1,3}(?:\s*[,–\-]\s*\d{1,3})*)\]")
_NUMERIC_ITEM = re.compile(r"(\d{1,3})(?:\s*[–\-]\s*(\d{1,3}))?")
_PAREN = re.compile(r"\(([^()]{4,400})\)")
# A note may follow the year — "(Joshi et al., 2017, Wikipedia setting)" — so
# the years need not end the part. The anchor's span still stops at the year.
_PART = re.compile(
    rf"(?P<names>.+?),?\s+(?P<years>{_YEAR}(?:\s*,\s*(?:{_YEAR}|[a-z])(?![a-z]))*)"
    rf"(?:\s*,\s*[^,;]{{1,60}})?\s*$"
)
_NARRATIVE = re.compile(
    rf"(?P<names>[A-Z][\w'’\-]+(?:\s+(?:and|&)\s+[A-Z][\w'’\-]+|\s+et\s+al\.?)?)"
    rf"\s+\((?P<years>{_YEAR}(?:\s*,\s*(?:{_YEAR}|[a-z]))*)\)"
)
_LEADIN = re.compile(r"^(?:e\.g\.,?|i\.e\.,?|see(?:\s+also)?|cf\.,?)\s+", re.I)
_NAME_WORDS = re.compile(
    r"^(?:et|al\.?|and|&|van|von|der|den|de|del|da|di|le|la)$", re.I
)
_MONTHS = re.compile(
    r"^(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?$"
)


def build_citation_map(paper: ParsedPaper) -> CitationMap:
    """Detect the reference list, then every anchor that points into it."""
    text = paper.full_text
    heading = _last_heading(text)
    if heading is None:
        return _empty(paper, CitationStyle.UNKNOWN)

    refs_start, heading_end = heading
    refs_end = _references_end(paper, heading_end)
    body = text[heading_end:refs_end]
    style, references = _parse_references(text, heading_end, refs_end, body)

    # Anchors live in the body and in any appendix after the references.
    regions = [(0, refs_start), (refs_end, len(text))]
    if style is CitationStyle.NUMERIC:
        found = _numeric_anchors(text, regions, references)
    elif style is CitationStyle.AUTHOR_YEAR:
        found = _author_year_anchors(text, regions, references)
    else:
        found = []

    starts = [s.start_char for s in paper.sentences]
    anchors = []
    for index, (start, end, printed, ref_id) in enumerate(
        sorted(found, key=lambda f: (f[0], f[3] or ""))
    ):
        position = bisect_right(starts, start) - 1
        sentence_id = paper.sentences[position].id if position >= 0 else None
        anchors.append(
            CitationAnchor(
                id=f"c{index:04d}",
                text=printed,
                start_char=start,
                end_char=end,
                sentence_id=sentence_id,
                reference_id=ref_id,
            )
        )

    return CitationMap(
        paper_id=paper.paper_id,
        parser_version=paper.parser_version,
        citation_version=CITATION_VERSION,
        style=style,
        references_start=refs_start,
        references_end=refs_end,
        references=references,
        anchors=anchors,
    )


# --- finding the reference list -------------------------------------------------


def _last_heading(text: str) -> tuple[int, int] | None:
    """The References heading's (start, end). The last one, if several."""
    matches = list(_HEADING.finditer(text))
    if not matches:
        return None
    m = matches[-1]
    return m.start(), m.end()


def _references_end(paper: ParsedPaper, after: int) -> int:
    """Where the list stops: the next detected section (an appendix), or the end.

    Five of the ten samples carry appendices after their references; without a
    stop, their text would be folded into the last entry and never scanned for
    the citations it contains.
    """
    later = [s.start_char for s in paper.sections if s.start_char >= after]
    return min(later) if later else len(paper.full_text)


def _parse_references(
    text: str, start: int, end: int, body: str
) -> tuple[CitationStyle, list[Reference]]:
    lead = body.lstrip()
    if re.match(r"\[1\]", lead):
        return CitationStyle.NUMERIC, _numbered(text, start, end, _BRACKET_LABEL)
    if re.match(r"1\.\s", lead):
        return CitationStyle.NUMERIC, _numbered(text, start, end, _DOT_LABEL)
    references = _author_year_entries(text, start, end)
    if not references:
        return CitationStyle.UNKNOWN, []
    return CitationStyle.AUTHOR_YEAR, references


def _numbered(text: str, start: int, end: int, label: re.Pattern) -> list[Reference]:
    """Entries labelled 1, 2, 3, ...

    Labels must increase, allowing a small gap for a mis-extracted one. Without
    the guard a page number or a "2." inside an entry starts a bogus entry —
    the same lesson as section numbering in 1.1: document order is the signal
    that typography alone cannot give.
    """
    body = text[start:end]
    kept: list[re.Match] = []
    last = 0
    for m in label.finditer(body):
        number = int(m.group(1))
        if last < number <= last + 3:
            kept.append(m)
            last = number

    references = []
    for i, m in enumerate(kept):
        # The dot pattern can consume leading whitespace; start at the label.
        lead = len(m.group(0)) - len(m.group(0).lstrip())
        entry_start = start + m.start() + lead
        entry_end = start + (kept[i + 1].start() if i + 1 < len(kept) else len(body))
        raw = text[entry_start:entry_end]
        trimmed_end = entry_start + len(raw.rstrip())
        entry = _clean(text[start + m.end() : trimmed_end])
        years = _YEAR_RE.findall(entry)
        references.append(
            Reference(
                id=f"r{int(m.group(1)):03d}",
                label=m.group(1),
                text=entry,
                start_char=entry_start,
                end_char=trimmed_end,
                first_author=_first_surname(entry),
                # Numeric styles usually put the year last; the first match can
                # be a new-style arXiv id like 2010.12345.
                year=years[-1] if years else None,
            )
        )
    return references


def _author_year_entries(text: str, start: int, end: int) -> list[Reference]:
    """Entries with no labels, rebuilt from line-wrapped blocks.

    A blank line does not end an entry here: the PDF wraps "Alan Akbik, ...,
    Roland Vollgraf." and "2018. Contextual string..." into separate blocks of
    the same entry. A block continues the previous entry when that entry has
    not ended (no closing period, or a trailing hyphen) or when the block does
    not open with a capital. Any assembled entry that still lacks the
    names-then-year opening is folded back into the one before it, which
    catches a venue line like "Association for Computational Linguistics."
    """
    spans: list[list[int]] = []
    for m in _BLOCK.finditer(text, start, end):
        block = m.group(0).strip()
        if _PAGE_NUMBER.fullmatch(block):
            continue  # a page number between entries
        if spans:
            previous = text[spans[-1][0] : spans[-1][1]].rstrip()
            if (
                previous.endswith("-")
                or not previous.endswith(".")
                # "Quoc V." wrapping onto "Le, Mohammad Norouzi, ..." is a
                # first name's initial, not the end of an entry. Treating it as
                # one split Wu et al. 2016 in two, folding Wu into Vaswani's
                # entry and crediting the rest to "Le".
                or _ENDS_WITH_INITIAL.search(previous)
                or not block[0].isupper()
            ):
                spans[-1][1] = m.end()
                continue
        spans.append([m.start(), m.end()])

    merged: list[list[int]] = []
    for s, e in spans:
        if merged and not _entry_opening(_clean(text[s:e])):
            merged[-1][1] = e
        else:
            merged.append([s, e])

    references = []
    for i, (s, e) in enumerate(merged, start=1):
        entry = _clean(text[s:e])
        opening = _entry_opening(entry)
        references.append(
            Reference(
                id=f"r{i:03d}",
                text=entry,
                start_char=s,
                end_char=e,
                first_author=(
                    _first_surname(opening.group("authors")) if opening else None
                ),
                year=opening.group("year") if opening else None,
            )
        )
    return references


def _entry_opening(entry: str) -> re.Match | None:
    return _ACL_ENTRY.match(entry) or _APA_ENTRY.match(entry)


# --- finding anchors ----------------------------------------------------------


def _numeric_anchors(text, regions, references):
    by_label = {r.label: r.id for r in references if r.label}
    highest = max((int(label) for label in by_label), default=0)
    found = []
    for lo, hi in regions:
        for m in _NUMERIC_ANCHOR.finditer(text, lo, hi):
            items = []
            for item in _NUMERIC_ITEM.finditer(m.group(1)):
                first = int(item.group(1))
                last = int(item.group(2)) if item.group(2) else first
                numbers = list(range(first, last + 1)) if last >= first else [first]
                items.append((item, numbers))
            numbers = [n for _, ns in items for n in ns]
            # "[0, 1]" is an interval, not a citation: a number outside the
            # list's labels means this bracket is something else.
            if not numbers or any(n < 1 or n > highest for n in numbers):
                continue
            base = m.start(1)
            for item, ns in items:
                start, end = base + item.start(), base + item.end()
                for n in ns:
                    found.append((start, end, text[start:end], by_label.get(str(n))))
    return found


def _author_year_anchors(text, regions, references):
    index: dict[tuple[str, str], list[str]] = {}
    authors: dict[str, list[str]] = {}
    for r in references:
        if r.first_author and r.year:
            surname = _normalise(r.first_author)
            index.setdefault((surname, r.year), []).append(r.id)
            if r.year[:4] != r.year:
                index.setdefault((surname, r.year[:4]), []).append(r.id)
            opening = _entry_opening(r.text)
            authors[r.id] = _surnames(opening.group("authors")) if opening else []

    def choose(candidates: list[str], names: str) -> str:
        """Pick between entries sharing a first author and a year.

        BERT cites both "Clark and Gardner, 2018" and "Clark et al., 2018";
        SciCite cites two Cohan 2015 papers. Taking the first match credited
        both citations to one entry and left the other looking uncited.
        """
        if len(candidates) == 1:
            return candidates[0]
        cited = _surnames(names)
        if re.search(r"et\s+al", names):
            fits = [c for c in candidates if len(authors.get(c, [])) >= 3]
        elif len(cited) >= 2:
            fits = [c for c in candidates if cited[1] in authors.get(c, [])[1:]]
        else:
            fits = [c for c in candidates if len(authors.get(c, [])) == 1]
        return (fits or candidates)[0]

    def lookup(names: str, year: str) -> str | None:
        # Try each comma-separated chunk in turn: "(GloVe, Pennington et al.,
        # 2014)" names a model before its authors. For a genuine author list
        # the first chunk is the first author and hits first.
        for chunk in re.split(r",", names):
            surname = _normalise(_first_surname(chunk) or "")
            if not surname:
                continue
            hits = index.get((surname, year)) or index.get((surname, year[:4]))
            if hits:
                return choose(hits, chunk if len(names.split(",")) > 1 else names)
        return None

    found = []
    for lo, hi in regions:
        # Parenthetical: "(Dai et al., 2019; Radford et al., 2019)" — one
        # anchor per cited work, each with its own span.
        for m in _PAREN.finditer(text, lo, hi):
            offset = m.start(1)
            for part in re.finditer(r"[^;]+", m.group(1)):
                raw = part.group(0)
                lead = len(raw) - len(raw.lstrip())
                piece = raw.strip()
                skip = _LEADIN.match(piece)
                if skip:
                    lead += skip.end()
                    piece = piece[skip.end() :]
                parsed = _PART.match(piece)
                if not parsed or not _looks_like_names(parsed.group("names")):
                    continue
                start = offset + part.start() + lead
                end = start + parsed.end("years")
                for year in _years(parsed.group("years")):
                    found.append(
                        (
                            start,
                            end,
                            text[start:end],
                            lookup(parsed.group("names"), year),
                        )
                    )
        # Narrative: "Devlin et al. (2019)". A bare capitalised word before a
        # year is only kept when it matches an entry — "Recently (2019)" is
        # prose, not a citation.
        for m in _NARRATIVE.finditer(text, lo, hi):
            names = m.group("names")
            multi = " and " in names or " & " in names or re.search(r"et\s+al", names)
            for year in _years(m.group("years")):
                ref_id = lookup(names, year)
                if ref_id or multi:
                    found.append((m.start(), m.end(), m.group(0), ref_id))
    return found


# --- helpers ------------------------------------------------------------------


def _years(spec: str) -> list[str]:
    """'2018a,b' -> ['2018a', '2018b']; '2019, 2020' -> ['2019', '2020']."""
    years: list[str] = []
    for token in re.split(r"\s*,\s*", spec.strip()):
        if re.fullmatch(_YEAR, token):
            years.append(token)
        elif re.fullmatch(r"[a-z]", token) and years:
            years.append(years[-1][:4] + token)
    return years


def _looks_like_names(names: str) -> bool:
    """A citation's author part, not a venue or a stray phrase.

    All-caps tokens are venues ("JCDL 2016", "NAACL 2019"), digits never appear
    in a surname, and an author list does not run to a sentence.
    """
    # PDFs sometimes extract accents as standalone characters ("ˇReh˚uˇrek").
    # They are modifier symbols (˚, Sk) or modifier letters (ˇ, Lm), and they
    # hide the capital that marks a name.
    names = "".join(ch for ch in names if unicodedata.category(ch) not in ("Sk", "Lm"))
    words = names.replace(",", " ").split()
    if not words or len(words) > 8 or any(ch.isdigit() for ch in names):
        return False
    content = [w for w in words if not _NAME_WORDS.match(w)]
    if not content:
        return False
    first = content[0]
    if len(content) == 1 and _MONTHS.match(first):
        return False  # "(May 2020)" is a date, not May et al.
    return first[0].isupper() and any(ch.islower() for ch in first)


def _first_surname(authors: str) -> str | None:
    """'Jacob Devlin, Ming-Wei Chang, ...' -> 'Devlin'; 'Devlin et al.' -> 'Devlin'.

    The last word of the first name is compared, so "Bart van Merrienboer" and
    "van Merrienboer et al." meet at "Merrienboer". "Surname, I." lists (APA,
    and CL-SciSumm's numbered list) have no space in the first chunk, so the
    chunk itself is taken.
    """
    head = re.split(r",|\s+and\s+|\s+&\s+|\s+et\s+al", authors.strip(), maxsplit=1)[0]
    words = [w.strip(".'’") for w in head.split() if w.strip(".'’")]
    return words[-1] if words else None


def _surnames(authors: str) -> list[str]:
    """Normalised surname of each author: 'A B, C D, and E F' -> ['b','d','f']."""
    cleaned = re.sub(r"\s+et\s+al\.?", "", authors)
    people = [p for p in re.split(r",\s*|\s+and\s+|\s+&\s+", cleaned) if p.strip()]
    out = []
    for person in people:
        surname = _first_surname(person)
        if surname:
            out.append(_normalise(surname))
    return out


def _normalise(name: str) -> str:
    """Compare names without case, accents, hyphens or apostrophes."""
    folded = unicodedata.normalize("NFKD", name)
    return "".join(ch for ch in folded if ch.isalpha() and ch.isascii()).lower()


def _clean(raw: str) -> str:
    """Collapse PDF line breaks; rejoin words hyphenated across lines."""
    joined = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", raw)
    return re.sub(r"\s+", " ", joined).strip()


def _empty(paper: ParsedPaper, style: CitationStyle) -> CitationMap:
    return CitationMap(
        paper_id=paper.paper_id,
        parser_version=paper.parser_version,
        citation_version=CITATION_VERSION,
        style=style,
    )
