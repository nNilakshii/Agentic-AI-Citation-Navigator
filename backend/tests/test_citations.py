"""Citation detection and linking (task 2.1).

Each test pins a rule found by running on the sample papers; the regression
tests name the failure they guard against.
"""

import pytest
from fastapi.testclient import TestClient

from app.api.reader import get_store
from app.cache import PaperStore
from app.core.citations import build_citation_map
from app.main import app
from app.models.citation import CitationStyle
from app.models.paper import PaperSource, ParsedPaper, Section, Sentence


def make_paper(text: str, sections: list[tuple[str, int]] | None = None) -> ParsedPaper:
    """A paper whose sentences are the text's lines, so anchors get a sentence."""
    sentences, pos = [], 0
    for i, line in enumerate(text.split("\n")):
        if line.strip():
            sentences.append(
                Sentence(
                    id=f"s{i:05d}",
                    text=line,
                    start_char=pos,
                    end_char=pos + len(line),
                    page=0,
                )
            )
        pos += len(line) + 1
    return ParsedPaper(
        paper_id="a" * 64,
        parser_version="1",
        source=PaperSource(filename="p.pdf"),
        full_text=text,
        sections=[
            Section(id=i, title=t, level=1, start_char=s, end_char=s + 1, page=0)
            for i, (t, s) in enumerate(sections or [])
        ],
        sentences=sentences,
    )


def cited(text: str) -> list[tuple[str, str | None]]:
    """(anchor text, cited reference label or first author) for a paper."""
    m = build_citation_map(make_paper(text))
    refs = {r.id: r for r in m.references}
    out = []
    for a in m.anchors:
        r = refs.get(a.reference_id)
        out.append((a.text, (r.label or f"{r.first_author} {r.year}") if r else None))
    return out


NUMERIC = """LSTMs [1] and GRUs [2, 3] dominate [1–3].
Values lie in [0, 1] and [9].

References

[1] Sepp Hochreiter and Jurgen Schmidhuber. Long short-term memory. 1997.
[2] Kyunghyun Cho and others. Learning phrase representations. 2014. [3] Junyoung Chung. Gated units. 2014.
"""

AUTHOR_YEAR = """BERT (Devlin et al., 2019) builds on ELMo (Peters et al., 2018a,b).
Vectors (GloVe, Pennington et al., 2014) and TriviaQA (Joshi et al., 2017, Wikipedia setting).
Devlin et al. (2019) note this. Recently (2019) things changed (May 2020).
Venues like (JCDL 2016) are not citations; see (e.g., Clark and Gardner, 2018).
Also (Clark et al., 2018) and ( ˇReh˚uˇrek and Sojka, 2010).

References

Jacob Devlin, Ming-Wei Chang, Kenton Lee, and Kristina
Toutanova. 2019. BERT: Pre-training of deep bidirectional transformers.

Christopher Clark and Matt Gardner. 2018. Simple and effective multi-paragraph reading comprehension.

Kevin Clark, Minh-Thang Luong, Christopher D Manning, and Quoc Le. 2018. Semi-supervised sequence modeling.

Mandar Joshi, Eunsol Choi, Daniel S. Weld, and Luke Zettlemoyer.

2017. TriviaQA: A large scale reading comprehension dataset.

Jeffrey Pennington, Richard Socher, and Christopher D.

Manning. 2014. GloVe: Global vectors for word representation.

Matthew Peters, Mark Neumann, and Luke Zettlemoyer. 2018a. Deep contextualized word representations. In NAACL.

Association for Computational Linguistics.

Matthew Peters, Sebastian Ruder, and Noah A. Smith. 2018b. To tune or not to tune.

Radim ˇReh˚uˇrek and Petr Sojka. 2010. Software framework for topic modelling.
"""


# --- finding the reference list -------------------------------------------------


def test_the_heading_must_be_a_whole_line():
    # Regression: a loose match caught "Coreference Resolution" in Longformer
    # before the real References heading.
    text = "6.2 Coreference Resolution\n\nWe cite [1].\n\nReferences\n\n[1] A B. Title. 2020.\n"
    m = build_citation_map(make_paper(text))
    assert text[m.references_start :].startswith("References")
    assert len(m.references) == 1


def test_no_reference_list_means_no_citations():
    m = build_citation_map(make_paper("A paper with no bibliography (Smith, 2020)."))
    assert m.style is CitationStyle.UNKNOWN
    assert m.references == [] and m.anchors == []


def test_the_list_stops_at_the_appendix_and_the_appendix_is_scanned():
    text = (
        "Body cites [1].\n\nReferences\n\n[1] A B. One. 2020.\n[2] C D. Two. 2021.\n\n"
        "A Appendix\n\nThe appendix cites [2].\n"
    )
    paper = make_paper(text, sections=[("A Appendix", text.index("A Appendix"))])
    m = build_citation_map(paper)
    assert len(m.references) == 2
    assert {a.text for a in m.anchors} == {"1", "2"}


# --- numeric ------------------------------------------------------------------------


def test_numeric_entries_are_numbered_in_order():
    m = build_citation_map(make_paper(NUMERIC))
    assert m.style is CitationStyle.NUMERIC
    assert [r.label for r in m.references] == ["1", "2", "3"]


def test_labels_are_found_mid_line():
    # Regression: PyMuPDF merges entries into one block ("...2014. [3] Junyoung"),
    # and a line-start-only rule found 1 entry of ~50 in Semantic Reader.
    m = build_citation_map(make_paper(NUMERIC))
    assert m.references[2].text.startswith("Junyoung Chung")


def test_dot_labels_follow_the_end_of_an_entry():
    # Regression: CL-SciSumm writes "(2018) 2. AbuRaed, A." mid-line; "volume 2."
    # inside an entry must not start one.
    text = (
        "Cites [1] and [2].\n\nReferences\n\n"
        "1. Aburaed, A.: Lastus. In: Proc. volume 2. Springer (2018) 2. AbuRaed, A.: Taln. (2019)\n"
    )
    m = build_citation_map(make_paper(text))
    assert [r.label for r in m.references] == ["1", "2"]
    assert "volume 2. Springer" in m.references[0].text


def test_each_number_in_a_bracket_is_its_own_anchor():
    anchors = cited(NUMERIC)
    assert ("2", "2") in anchors and ("3", "3") in anchors


def test_a_range_cites_every_number_in_it():
    labels = [label for text, label in cited(NUMERIC) if text == "1–3"]
    assert labels == ["1", "2", "3"]


def test_an_interval_or_out_of_range_number_is_not_a_citation():
    # "[0, 1]" is maths; "[9]" names no entry in a three-entry list.
    texts = [t for t, _ in cited(NUMERIC)]
    assert "0" not in texts and "9" not in texts


def test_reference_labels_are_not_read_as_citations():
    m = build_citation_map(make_paper(NUMERIC))
    assert all(a.start_char < m.references_start for a in m.anchors)


# --- author-year ----------------------------------------------------------------


def test_author_year_entries_are_rebuilt_across_line_wraps():
    # The year often sits on the next block: "...Zettlemoyer.\n\n2017. TriviaQA".
    m = build_citation_map(make_paper(AUTHOR_YEAR))
    assert m.style is CitationStyle.AUTHOR_YEAR
    joshi = [r for r in m.references if r.first_author == "Joshi"]
    assert joshi and joshi[0].year == "2017"


def test_an_initial_at_a_line_end_does_not_end_an_entry():
    # Regression: "Christopher D.\n\nManning" was split, crediting the entry to
    # "Manning" and folding Pennington into the previous entry.
    m = build_citation_map(make_paper(AUTHOR_YEAR))
    authors = [r.first_author for r in m.references]
    assert "Pennington" in authors and "Manning" not in authors


def test_a_venue_line_is_folded_into_its_entry():
    m = build_citation_map(make_paper(AUTHOR_YEAR))
    peters = [r for r in m.references if r.year == "2018a"][0]
    assert peters.text.endswith("Association for Computational Linguistics.")


def test_parenthetical_and_narrative_citations_link():
    anchors = dict(cited(AUTHOR_YEAR))
    assert anchors["Devlin et al., 2019"] == "Devlin 2019"
    assert anchors["Devlin et al. (2019)"] == "Devlin 2019"


def test_years_with_letters_link_to_each_entry():
    labels = [label for text, label in cited(AUTHOR_YEAR) if text.startswith("Peters")]
    assert labels == ["Peters 2018a", "Peters 2018b"]


def test_a_model_name_before_the_authors_is_skipped():
    # Regression: "(GloVe, Pennington et al., 2014)" looked for an author "GloVe".
    assert (
        dict(cited(AUTHOR_YEAR))["GloVe, Pennington et al., 2014"] == "Pennington 2014"
    )


def test_a_note_after_the_year_is_allowed_and_left_out_of_the_span():
    # Regression: "(Joshi et al., 2017, Wikipedia setting)" was not detected.
    assert dict(cited(AUTHOR_YEAR))["Joshi et al., 2017"] == "Joshi 2017"


def test_same_author_and_year_is_split_by_the_rest_of_the_list():
    # Regression: both citations went to the first Clark 2018 entry, leaving the
    # other looking uncited.
    m = build_citation_map(make_paper(AUTHOR_YEAR))
    refs = {r.id: r for r in m.references}
    by_text = {a.text: refs[a.reference_id] for a in m.anchors if a.reference_id}
    assert by_text["Clark and Gardner, 2018"].text.startswith("Christopher Clark")
    assert by_text["Clark et al., 2018"].text.startswith("Kevin Clark")


def test_accents_extracted_as_separate_characters_still_match():
    # Regression: Specter's "ˇReh˚uˇrek" did not start with a capital.
    anchors = dict(cited(AUTHOR_YEAR))
    key = [t for t in anchors if "Sojka" in t][0]
    assert anchors[key] is not None


@pytest.mark.parametrize("phrase", ["May 2020", "JCDL 2016", "Recently (2019)"])
def test_dates_venues_and_prose_are_not_citations(phrase):
    assert all(phrase not in text for text, _ in cited(AUTHOR_YEAR))


def test_a_lead_in_is_not_part_of_the_citation():
    texts = [t for t, _ in cited(AUTHOR_YEAR)]
    assert "Clark and Gardner, 2018" in texts


def test_every_anchor_points_at_real_text_and_a_sentence():
    m = build_citation_map(make_paper(AUTHOR_YEAR))
    for a in m.anchors:
        assert AUTHOR_YEAR[a.start_char : a.end_char] == a.text
        assert a.sentence_id is not None


# --- the endpoint ---------------------------------------------------------------


@pytest.fixture
def client(tmp_path):
    app.dependency_overrides[get_store] = lambda: PaperStore(tmp_path)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_the_endpoint_returns_a_map(client, synthetic_pdf):
    paper_id = client.post(
        "/api/reader/papers",
        files={"file": ("synthetic.pdf", synthetic_pdf, "application/pdf")},
    ).json()["paper_id"]

    response = client.get(f"/api/reader/papers/{paper_id}/citations")

    assert response.status_code == 200
    body = response.json()
    assert body["paper_id"] == paper_id
    assert {"style", "references", "anchors", "citation_version"} <= set(body)


def test_the_endpoint_404s_for_an_unknown_paper(client):
    assert client.get(f"/api/reader/papers/{'b' * 64}/citations").status_code == 404


def test_the_endpoint_rejects_a_malformed_id(client):
    assert client.get("/api/reader/papers/nope/citations").status_code == 422
