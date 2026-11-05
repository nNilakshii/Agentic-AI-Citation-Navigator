"""Candidate passages for localization (task 2.4).

Built on hand-made papers, so each test states exactly which sentence sits
where; the regression tests name the sample-paper case they pin.
"""

from fastapi.testclient import TestClient

from app.api.reader import get_store
from app.cache import PaperStore
from app.core.passages import (
    MAX_WINDOW,
    _is_prose,
    passages_from_abstract,
    passages_from_paper,
)
from app.main import app
from app.models.paper import PaperSource, ParsedPaper, Section, Sentence
from app.models.passage import PassageOrigin

PROSE = [
    "We train the encoder on one million citation pairs from the corpus.",
    "The decoder attends over every sentence of the cited paper at once.",
    "This lets the model find the passage that a citation refers to.",
    "Results improve on both datasets when the windows are combined.",
]


def build(sections: list[tuple[str, list[str]]]) -> ParsedPaper:
    """A paper from (heading, sentences) pairs; heading None = front matter."""
    text, secs, sents = "", [], []
    for title, sentences in sections:
        start = len(text)
        if title:
            text += title + "\n"
        sec_id = len(secs)
        for sentence in sentences:
            s = len(text)
            text += sentence + " "
            sents.append(
                Sentence(
                    id=f"s{len(sents):04d}",
                    text=sentence,
                    start_char=s,
                    end_char=s + len(sentence),
                    section_id=sec_id,
                    page=0,
                )
            )
        text += "\n\n"
        secs.append(
            Section(
                id=sec_id,
                title=title or "Front matter",
                level=1,
                start_char=start,
                end_char=len(text),
                page=0,
            )
        )
    return ParsedPaper(
        paper_id="b" * 64,
        parser_version="1",
        source=PaperSource(filename="p.pdf"),
        full_text=text,
        sections=secs,
        sentences=sents,
    )


def sentence_texts(passage_set, paper) -> set[str]:
    by_id = {s.id: s.text for s in paper.sentences}
    return {by_id[i] for p in passage_set.passages for i in p.sentence_ids}


def test_windows_of_one_to_three_sentences_inside_a_section():
    paper = build([("1 Introduction", PROSE)])
    result = passages_from_paper(paper)
    sizes = sorted(len(p.sentence_ids) for p in result.passages)
    # 4 singles, 3 pairs, 2 triples.
    assert sizes == [1] * 4 + [2] * 3 + [3] * 2
    assert max(sizes) == MAX_WINDOW
    for p in result.passages:
        assert p.text == paper.full_text[p.start_char : p.end_char]


def test_a_window_never_crosses_a_section():
    paper = build([("1 Introduction", PROSE[:2]), ("2 Method", PROSE[2:])])
    for p in passages_from_paper(paper).passages:
        sections = {int(i[1:]) // 2 for i in p.sentence_ids}
        assert len(sections) == 1


def test_ids_are_sequential_in_reading_order():
    result = passages_from_paper(build([("1 Introduction", PROSE)]))
    assert [p.id for p in result.passages] == [
        f"p{i:04d}" for i in range(len(result.passages))
    ]
    assert result.passages == sorted(
        result.passages, key=lambda p: (p.start_char, p.end_char)
    )


def test_the_reference_list_is_left_out_and_counted():
    entry = "Smith, J. and Jones, K. 2019. Learning to find cited passages in papers."
    paper = build([("1 Introduction", PROSE), ("References", [entry])])
    result = passages_from_paper(paper)
    assert entry not in sentence_texts(result, paper)
    assert result.excluded["reference list"] == 1


def test_an_appendix_after_the_references_is_kept():
    detail = "We tuned the learning rate on the development set for each task."
    paper = build(
        [
            ("1 Introduction", PROSE),
            ("References", ["Smith, J. 2019. A paper about citations and spans."]),
            ("A Hyperparameter Settings", [detail]),
        ]
    )
    assert detail in sentence_texts(passages_from_paper(paper), paper)


def test_a_false_heading_after_the_references_is_not_an_appendix():
    # Real case: Attention Is All You Need — a running header after the
    # references was taken for a heading, and bibliography text followed it.
    leaked = "Vaswani, A. and Shazeer, N. 2017. Attention is all you need today."
    paper = build(
        [
            ("1 Introduction", PROSE),
            ("References", ["Smith, J. 2019. A paper about citations and spans."]),
            ("7 Published as a conference paper at ICLR", [leaked]),
        ]
    )
    result = passages_from_paper(paper)
    assert leaked not in sentence_texts(result, paper)
    assert result.excluded["after the references, not an appendix"] == 1


def test_acknowledgments_are_left_out():
    thanks = "We thank the anonymous reviewers for their many helpful comments."
    paper = build([("1 Introduction", PROSE), ("Acknowledgments", [thanks])])
    result = passages_from_paper(paper)
    assert thanks not in sentence_texts(result, paper)
    assert result.excluded["acknowledgments"] == 1


def test_front_matter_keeps_the_abstract_but_not_author_lines():
    # When no "Abstract" heading is found, the abstract is in front matter.
    author = "Niki Parmar Google Research nikip@google.com"
    abstract = "We propose a new network architecture based solely on attention."
    paper = build([(None, [author, abstract]), ("1 Introduction", PROSE)])
    kept = sentence_texts(passages_from_paper(paper), paper)
    assert abstract in kept
    assert author not in kept


def test_debris_breaks_a_window_instead_of_joining_it():
    row = "BiLSTM-Attn 82.2 83.2 82.7 80.7 74.4 77.4 67.1 76.2"
    paper = build([("4 Results", [PROSE[0], row, PROSE[1]])])
    result = passages_from_paper(paper)
    assert all(len(p.sentence_ids) == 1 for p in result.passages)
    assert result.excluded["not prose"] == 1


def test_too_short_windows_are_dropped():
    paper = build([("1 Introduction", ["We use four words."])])
    assert passages_from_paper(paper).passages == []


def test_prose_test_on_real_debris():
    assert _is_prose(PROSE[0])
    for debris in [
        "Gold 89.6% 90.0% BART 70.7% 32.4% RAG-Token 77.8% 46.8% RAG-Seq.",
        "i ∈Rdmodel×dk, W V",
        "3.1 Document Classiﬁcation",
        "Niki Parmar∗ Google Research nikip@google.com",
    ]:
        assert not _is_prose(debris), debris


def test_a_references_section_is_left_out_when_the_heading_regex_misses_it():
    # Real case: "Class-Based n-gram Models of Natural Language" (1992). The
    # parser found a "References" section; the citation detector did not.
    paper = build(
        [
            ("1 Introduction", PROSE),
            ("References", ["Mays, E. (1990). In Proceedings."]),
        ]
    )
    paper.full_text = paper.full_text.replace("References\n", "References  \x0c")
    result = passages_from_paper(paper)
    assert result.excluded.get("reference list") == 1


def test_a_paper_with_no_reference_heading_keeps_everything_else():
    result = passages_from_paper(build([("1 Introduction", PROSE)]))
    assert "reference list" not in result.excluded
    assert result.origin is PassageOrigin.FULL_TEXT


def test_abstract_passages_index_into_the_abstract():
    abstract = " ".join(PROSE[:3])
    result = passages_from_abstract(abstract)
    assert result.origin is PassageOrigin.ABSTRACT
    assert result.paper_id is None
    assert len(result.passages) == 3 + 2 + 1
    for p in result.passages:
        assert p.text == abstract[p.start_char : p.end_char]
        assert p.section_title == "Abstract"


def test_endpoint_serves_passages(tmp_path, synthetic_pdf):
    store = PaperStore(tmp_path)
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        paper_id = client.post(
            "/api/reader/papers",
            files={"file": ("p.pdf", synthetic_pdf, "application/pdf")},
        ).json()["paper_id"]
        body = client.get(f"/api/reader/papers/{paper_id}/passages").json()
        assert body["origin"] == "full-text"
        assert body["passages"]
        assert client.get(f"/api/reader/papers/{'f' * 64}/passages").status_code == 404
    finally:
        app.dependency_overrides.clear()
