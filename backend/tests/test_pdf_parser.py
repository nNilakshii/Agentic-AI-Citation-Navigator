"""Parser tests. The offset contract gets the most attention here: if
``full_text[s.start_char:s.end_char] != s.text`` then every highlight, every
eval overlap score and every grounded citation downstream is silently wrong."""

import pytest

from app.core.pdf_parser import PARSER_VERSION, paper_id_for, parse_pdf


@pytest.fixture
def paper(synthetic_pdf):
    return parse_pdf(synthetic_pdf, "synthetic.pdf")


# --- the offset contract ----------------------------------------------


def test_sentence_offsets_index_into_full_text(paper):
    for sentence in paper.sentences:
        assert paper.full_text[sentence.start_char : sentence.end_char] == sentence.text


def test_sentences_are_ordered_and_do_not_overlap(paper):
    for current, following in zip(paper.sentences, paper.sentences[1:]):
        assert current.end_char <= following.start_char


def test_section_offsets_cover_the_document_without_gaps(paper):
    assert paper.sections
    assert paper.sections[0].start_char == 0
    assert paper.sections[-1].end_char == len(paper.full_text)
    for current, following in zip(paper.sections, paper.sections[1:]):
        assert current.end_char == following.start_char


def test_every_sentence_lands_in_a_section(paper):
    section_ids = {section.id for section in paper.sections}
    for sentence in paper.sentences:
        assert sentence.section_id in section_ids


# --- text quality ------------------------------------------------------


def test_wrapped_lines_are_joined_without_newlines(paper):
    body = [s for s in paper.sentences if "F1 of 0.82" in s.text]
    assert body, "expected the body sentence to survive segmentation"
    assert "\n" not in body[0].text


def test_abbreviations_do_not_split_sentences(paper):
    assert not any(s.text.strip().endswith("et") for s in paper.sentences)
    assert any("et al." in s.text for s in paper.sentences)


# --- structure ---------------------------------------------------------


def test_headings_become_sections(paper):
    titles = [section.title for section in paper.sections]
    assert "1 Introduction" in titles
    assert "2 Method" in titles


def test_front_matter_precedes_the_first_heading(paper):
    assert paper.sections[0].title == "Front matter"
    assert paper.sections[0].start_char == 0


def test_numbered_heading_levels(paper):
    by_title = {section.title: section.level for section in paper.sections}
    assert by_title["1 Introduction"] == 1


def test_title_comes_from_the_largest_type_on_page_one(paper):
    assert paper.source.title == "Localizing Cited Spans in Scientific Papers"


def test_page_count_and_pages(paper):
    assert paper.source.page_count == 2
    assert {sentence.page for sentence in paper.sentences} == {0, 1}


# --- highlight geometry ------------------------------------------------


def test_every_sentence_has_at_least_one_bbox(paper):
    for sentence in paper.sentences:
        assert sentence.bboxes, f"{sentence.id} has no geometry to highlight"


def test_bboxes_are_well_formed_and_on_the_sentence_page(paper):
    for sentence in paper.sentences:
        for bbox in sentence.bboxes:
            assert bbox.x1 > bbox.x0
            assert bbox.y1 > bbox.y0
            assert 0 <= bbox.page < paper.source.page_count
        assert sentence.bboxes[0].page == sentence.page


def test_a_wrapping_sentence_gets_one_bbox_per_line(paper):
    wrapping = max(paper.sentences, key=lambda s: len(s.text))
    assert len(wrapping.bboxes) >= 2


# --- identity and caching ----------------------------------------------


def test_paper_id_is_the_content_hash(synthetic_pdf, paper):
    assert paper.paper_id == paper_id_for(synthetic_pdf)
    assert len(paper.paper_id) == 64


def test_parsing_is_deterministic(synthetic_pdf):
    first = parse_pdf(synthetic_pdf, "a.pdf")
    second = parse_pdf(synthetic_pdf, "a.pdf")
    assert first.full_text == second.full_text
    assert [s.start_char for s in first.sentences] == [
        s.start_char for s in second.sentences
    ]


def test_parser_version_is_recorded(paper):
    assert paper.parser_version == PARSER_VERSION


def test_rejects_non_pdf_bytes():
    with pytest.raises(ValueError, match="not-a-pdf"):
        parse_pdf(b"this is plain text", "not-a-pdf.txt")
