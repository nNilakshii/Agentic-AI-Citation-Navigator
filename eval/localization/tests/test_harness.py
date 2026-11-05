"""The CL-SciSumm harness (2.6): metrics on hand-worked cases, and the loader
on a miniature corpus written in the real files' formats.

Run from the repo root:  backend/.venv/bin/python -m pytest eval
"""

import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE), str(HERE.parents[1] / "backend")]

from clscisumm import Citance, load_citances, load_reference, split_of  # noqa: E402
from metrics import Counts, averaged_over_papers, hit_at_k, rouge_l  # noqa: E402

# --- metrics ------------------------------------------------------------------


def test_counts_pool_sentence_ids():
    c = Counts()
    c.add({"1", "2"}, {"2", "3"})  # tp 1, fp 1, fn 1
    c.add({"5"}, {"5"})  # tp 1
    assert (c.tp, c.fp, c.fn) == (2, 1, 1)
    p, r, f = c.prf()
    assert p == pytest.approx(2 / 3) and r == pytest.approx(2 / 3)
    assert f == pytest.approx(2 / 3)


def test_official_style_averages_papers_not_citances():
    # One paper with 1 citance (perfect), one with 3 (all wrong): the paper
    # average is 0.5, while pooling citances would give 0.25.
    good, bad = Counts(), Counts()
    good.add({"1"}, {"1"})
    for _ in range(3):
        bad.add({"9"}, {"1"})
    assert averaged_over_papers([good, bad])[2] == pytest.approx(0.5)
    pooled = Counts()
    pooled.add({"1"}, {"1"})
    for _ in range(3):
        pooled.add({"9"}, {"1"})
    assert pooled.prf()[2] == pytest.approx(0.25)


def test_empty_predictions_score_zero_not_crash():
    c = Counts()
    c.add(set(), {"1"})
    assert c.prf() == (0.0, 0.0, 0.0)
    assert averaged_over_papers([]) == (0.0, 0.0, 0.0)


def test_hit_at_k_needs_one_shared_sentence_within_k():
    ranked = [{"1"}, {"2", "3"}, {"7"}]
    assert not hit_at_k(ranked, {"3"}, 1)
    assert hit_at_k(ranked, {"3"}, 2)
    assert not hit_at_k(ranked, {"9"}, 3)


def test_rouge_l_on_known_values():
    assert rouge_l("the cat sat", "the cat sat") == pytest.approx(1.0)
    assert rouge_l("", "the cat") == 0.0
    # LCS("a b c d", "a c d e") = 3 -> P 3/4, R 3/4.
    assert rouge_l("a b c d", "a c d e") == pytest.approx(0.75)


# --- loader -------------------------------------------------------------------

REFERENCE_XML = """<PAPER>
<S sid="0">A Toy Parser for Testing</S>
  <ABSTRACT>
    <S sid ="1" ssid = "1">We present a toy parser with &amp;quot;quoted&amp;quot; words.</S>
  </ABSTRACT>
  <SECTION title="Introduction. " number = "1">
    <S sid ="2" ssid = "1">Parsing is the task of recovering syntactic structure from text.</S>
    <S sid ="3" ssid = "2">Our parser reaches high accuracy on the standard benchmark set.</S>
  </SECTION>
</PAPER>
"""

ANNOTATION = (
    "Citance Number: 1 | Reference Article:  T00-0001.xml | Citing Article:  "
    "C01-0001.xml | Citation Marker Offset:  ['4'] | Citation Marker:  Toy, 2000 | "
    'Citation Offset:  [\'4\'] | Citation Text: <S sid ="4" ssid = "4">A parser '
    "(Toy, 2000) and others (Smith et al., 1999) reach high accuracy.</S> | "
    "Reference Offset:  ['3'] | Reference Text: <S sid =\"3\">x</S> | "
    "Discourse Facet:  ['Method_Citation','Results_Citation'] | Annotator:  A |\n\n"
    "Citance Number: 2 | Reference Article: T00-0001 | Citing Article: C02-0002 | "
    "Citation Marker Offset: '1' | Citation Marker: Tooy, 2000 | Citation Offset: '1' | "
    'Citation Text: <S sid ="1">Toy (2000) recover structure â€œwellâ€.</S> | '
    "Reference Offset: ['2','3'] | Reference Text: <S sid =\"2\">x</S> | "
    "Discourse Facet: Method Citation | Annotator: B |\n"
)


@pytest.fixture
def corpus(tmp_path):
    paper = tmp_path / "T00-0001"
    (paper / "Reference_XML").mkdir(parents=True)
    (paper / "annotation").mkdir()
    (paper / "Reference_XML" / "T00-0001.xml").write_text(REFERENCE_XML)
    (paper / "annotation" / "T00-0001.ann.txt").write_text(ANNOTATION)
    return tmp_path


def test_reference_sentence_ids_are_the_gold_ids(corpus):
    paper = load_reference("T00-0001", corpus)
    assert [s.id for s in paper.sentences] == ["0", "1", "2", "3"]
    assert paper.source.title == "A Toy Parser for Testing"
    assert [s.title for s in paper.sections] == [
        "Front matter",
        "Abstract",
        "Introduction",
    ]
    assert '"quoted"' in paper.sentences[1].text  # double-escaped entity repaired
    for s in paper.sentences:
        assert paper.full_text[s.start_char : s.end_char] == s.text


def test_citances_parse_both_annotation_formats(corpus):
    first, second = load_citances("T00-0001", corpus)
    assert first.gold == {"3"} and second.gold == {"2", "3"}
    assert first.facets == ["method", "results"]
    assert second.facets == ["method"]
    assert second.citing_article == "C02-0002"


def test_the_query_drops_every_citation_even_a_misspelled_marker(corpus):
    first, second = load_citances("T00-0001", corpus)
    assert first.query == "A parser and others reach high accuracy."
    # The marker says "Tooy"; the text says "Toy (2000)" — removed regardless.
    assert second.query == 'recover structure "well".'


def test_split_is_fixed_by_paper_id():
    assert split_of("C00-2123") == split_of("C00-2123")
    assert {split_of(f"P{i:02d}-1000") for i in range(20)} == {"dev", "test"}


def test_a_citance_with_no_gold_is_skipped(tmp_path):
    paper = tmp_path / "T00-0002" / "annotation"
    paper.mkdir(parents=True)
    (paper / "T00-0002.ann.txt").write_text(
        "Citance Number: 1 | Citation Text: <S>Some text.</S> | Reference Offset: [] |\n"
    )
    assert load_citances("T00-0002", tmp_path) == []


def test_citance_key_names_paper_and_number():
    c = Citance("P1", "7", "C1", "t", "m", frozenset({"1"}), "")
    assert c.key == "P1#7" and c.facets == ["none"]


# --- rankers and confidence (2.7) ----------------------------------------------

from analyze_confidence import curve  # noqa: E402
from rankers import _z, bm25_scores, hybrid_scores  # noqa: E402


def test_bm25_prefers_the_passage_sharing_rare_terms():
    passages = [
        "the model is trained on the data",
        "we use a maximum entropy parser for the treebank",
        "the results are reported on the data",
    ]
    scores = bm25_scores(passages, ["maximum entropy parser"])
    assert scores[0].argmax() == 1
    assert scores[0, 0] == 0.0  # no shared non-stopword term


def test_bm25_ignores_stopwords():
    scores = bm25_scores(["the of and", "parser"], ["the of and"])
    assert scores.max() == 0.0


def test_hybrid_mixes_normalised_scores():
    lexical = np.array([[0.0, 10.0, 0.0]])
    dense = np.array([[0.9, 0.1, 0.1]])
    assert hybrid_scores(lexical, dense, 1.0).argmax() == 0
    assert hybrid_scores(lexical, dense, 0.0).argmax() == 1
    # z-normalisation makes the scales comparable: a constant row is all zeros.
    assert np.allclose(_z(np.array([[3.0, 3.0]])), 0)


def test_confidence_curve_counts_only_answers_above_threshold():
    rows = [
        {"top": [{"score": 0.9, "sentences": ["1"]}], "gold": ["1"], "hit_at_1": True},
        {"top": [{"score": 0.5, "sentences": ["2"]}], "gold": ["1"], "hit_at_1": False},
    ]
    (t0, share0, acc0, _), (t1, share1, acc1, _) = curve(rows, [0.0, 0.8])
    assert (share0, acc0) == (1.0, 0.5)
    assert (share1, acc1) == (0.5, 1.0)
