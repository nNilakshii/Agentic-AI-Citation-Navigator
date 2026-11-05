"""Load CL-SciSumm Task 1A: citances and their human-annotated cited spans (2.6).

Source: the human-annotated part of the 2019 training set
(``Training-Set-2019/Task1/From-Training-Set-2018`` — 40 reference papers,
753 citances). The canonical ``WING-NUS/scisumm-corpus`` repository is no
longer on GitHub; this reads a complete mirror
(``robinsdeepak/scisumm-corpus-fs``, snapshot 2655830, July 2020), cloned to
``data/raw/scisumm-corpus`` (gitignored). The ScisummNet-2019 part is left out:
its annotations are automatic ("Annotator: Automatic") and many citances are
empty.

Each reference paper is rebuilt from the corpus's own sentence-split XML into
a :class:`ParsedPaper`, so gold sentence ids are our sentence ids and a
sentence-boundary disagreement can never be scored as a localization error.
"""

from __future__ import annotations

import hashlib
import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from app.models.paper import PaperSource, ParsedPaper, Section, Sentence

ROOT = Path(__file__).resolve().parents[2]
CORPUS = (
    ROOT
    / "data"
    / "raw"
    / "scisumm-corpus"
    / "data"
    / "Training-Set-2019"
    / "Task1"
    / "From-Training-Set-2018"
)

_FIELD = re.compile(r"\s*([A-Za-z ]+?)\s*:\s*(.*)")
_SID = re.compile(r"'?(\d+)'?")
_TAG = re.compile(r"<[^>]+>")
# Every citation in the citance, as production (2.5) removes every anchor: the
# annotated marker alone is not enough — it is sometimes misspelled relative to
# the text ("Tillman" vs "Tillmann"), and other works are cited alongside.
_PAREN_CITATION = re.compile(r"\([^()]*?(?:19|20)\d{2}[a-z]?[^()]*?\)")
_NUMERIC_CITATION = re.compile(r"\[\s*\d{1,3}(?:\s*[,–-]\s*\d{1,3})*\s*\]")
# "Smith et al. (2009)" or "Smith et al., 2009" — a closing bracket only with
# its opening one, so "(Smith et al., 1999)" leaves "( )" for the next rule.
_NARRATIVE_CITATION = re.compile(
    r"\b[A-Z][A-Za-z\-]+(?:\s+(?:et al\.?|and\s+[A-Z][A-Za-z\-]+))?"
    r"\s*(?:\((?:19|20)\d{2}[a-z]?\)|,?\s*(?:19|20)\d{2}[a-z]?)"
)
_EMPTY_BRACKETS = re.compile(r"[\(\[]\s*[,;\s–-]*[\)\]]")
_SPACES = re.compile(r"\s+")
_DANGLING_BRACKET = re.compile(r"[\(\[]\s*(?=[.,;:]|$)")
#: Longest first: "â€" alone is the prefix of the others.
_MOJIBAKE = [
    ("â€œ", '"'),
    ("â€\x9d", '"'),
    ("â€™", "'"),
    ("â€˜", "'"),
    ("â€“", "–"),
    ("â€”", "—"),
    ("â€¢", "•"),
    ("â€¦", "..."),
    ("â€", '"'),
]


@dataclass
class Citance:
    paper: str
    number: str
    citing_article: str
    text: str = field(repr=False)
    marker: str
    gold: frozenset[str]
    facet: str

    @property
    def facets(self) -> list[str]:
        """Task 1B facets, normalised: the corpus spells them a dozen ways
        ("Method Citation", "Method_CItation", "['Aim_Citation','Method_Citation']")."""
        found = []
        for word in re.findall(r"[a-z]+", self.facet.lower()):
            word = {"result": "results"}.get(word, word)
            if word in ("aim", "hypothesis", "implication", "method", "results"):
                found.append(word)
        return sorted(set(found)) or ["none"]

    @property
    def key(self) -> str:
        return f"{self.paper}#{self.number}"

    @property
    def query(self) -> str:
        """The citing text with its citations removed (as in 2.5)."""
        text = self.text
        if self.marker and self.marker != "NA":
            text = text.replace(self.marker, " ")
        text = _NARRATIVE_CITATION.sub(" ", text)  # before its "(2009)" goes
        text = _PAREN_CITATION.sub(" ", text)
        text = _NUMERIC_CITATION.sub(" ", text)
        text = _EMPTY_BRACKETS.sub(" ", text)
        text = _DANGLING_BRACKET.sub(" ", text)
        return _SPACES.sub(" ", text).strip()


def papers(corpus: Path = CORPUS) -> list[str]:
    return sorted(p.name for p in corpus.iterdir() if (p / "Reference_XML").is_dir())


def split_of(paper: str) -> str:
    """'dev' or 'test', fixed by the paper id, so 2.7 can tune on dev only."""
    return "dev" if hashlib.sha256(paper.encode()).digest()[0] % 2 == 0 else "test"


def load_reference(paper: str, corpus: Path = CORPUS) -> ParsedPaper:
    """The reference paper as the corpus split it: sentence id = gold sid."""
    xml = corpus / paper / "Reference_XML" / f"{paper}.xml"
    root = ET.fromstring(xml.read_text(encoding="utf-8", errors="replace"))
    text, sections, sentences = "", [], []
    title = None

    def add_section(name: str) -> int:
        sections.append(
            Section(
                id=len(sections),
                title=name,
                level=1,
                start_char=len(text),
                end_char=len(text),
                page=0,
            )
        )
        return len(sections) - 1

    def add_sentences(element: ET.Element, section_id: int | None) -> None:
        nonlocal text, title
        for s in element.iter("S"):
            sentence = _clean(s.text or "")
            sid = (s.get("sid") or "").strip()
            if not sid or not sentence:
                continue
            if title is None and section_id is None:
                title = sentence
            start = len(text)
            text += sentence + "\n"
            sentences.append(
                Sentence(
                    id=sid,
                    text=sentence,
                    start_char=start,
                    end_char=start + len(sentence),
                    section_id=section_id,
                    page=0,
                )
            )
        text += "\n"

    front = add_section("Front matter")
    for child in root:
        if child.tag == "S":
            add_sentences(_wrap(child), front)
        elif child.tag == "ABSTRACT":
            add_sentences(child, add_section("Abstract"))
        elif child.tag == "SECTION":
            heading = _clean(child.get("title") or "").rstrip(". ")
            add_sentences(child, add_section(heading or "Section"))
        sections[-1].end_char = len(text)
    title = next((s.text for s in sentences if s.section_id == front), None)

    return ParsedPaper(
        paper_id=hashlib.sha256(f"clscisumm:{paper}".encode()).hexdigest(),
        parser_version="clscisumm",
        source=PaperSource(filename=f"{paper}.xml", title=title),
        full_text=text,
        sections=[s for s in sections if s.end_char > s.start_char],
        sentences=sentences,
    )


def load_citances(paper: str, corpus: Path = CORPUS) -> list[Citance]:
    """Every annotated citance of one reference paper."""
    found: list[Citance] = []
    for path in sorted((corpus / paper / "annotation").glob("*.ann*.txt")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "Reference Offset" not in line:
                continue
            fields = {}
            for part in line.split(" | "):
                match = _FIELD.match(part)
                if match:
                    fields[match.group(1).strip()] = match.group(2).strip()
            gold = frozenset(_SID.findall(fields.get("Reference Offset", "")))
            text = _clean(_TAG.sub(" ", fields.get("Citation Text", "")))
            if not gold or not text:
                continue
            found.append(
                Citance(
                    paper=paper,
                    number=fields.get("Citance Number", "?"),
                    citing_article=fields.get("Citing Article", "").removesuffix(
                        ".xml"
                    ),
                    text=text,
                    marker=fields.get("Citation Marker", "").strip(),
                    gold=gold,
                    facet=fields.get("Discourse Facet", "").strip(" |"),
                )
            )
    return found


def _clean(raw: str) -> str:
    # The corpus double-escapes some entities ("&amp;quot;"), and some text is
    # UTF-8 that was decoded as cp1252 ("â€œ" for a quotation mark).
    text = html.unescape(html.unescape(raw))
    for broken, fixed in _MOJIBAKE:
        text = text.replace(broken, fixed)
    return _SPACES.sub(" ", text).strip()


def _wrap(element: ET.Element) -> ET.Element:
    holder = ET.Element("_")
    holder.append(element)
    return holder
