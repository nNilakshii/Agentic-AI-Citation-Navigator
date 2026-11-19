"""The failure taxonomy (2.10): each bucket on a hand-built case, in priority order.

Run from the repo root:  backend/.venv/bin/python -m pytest eval
"""

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE), str(HERE.parents[1] / "backend")]

from analyze_failures import bucket_of, diagnose, summarize, support  # noqa: E402

# Sentences 1-9 in section 0, 10-19 in section 1, 20+ in section 2.
SECTION = {str(i): (0 if i < 10 else 1 if i < 20 else 2) for i in range(1, 30)}
ALL = set(SECTION)


def test_unreachable_wins_over_everything():
    # The gold was filtered out of the candidates, even if a top passage is near it.
    assert bucket_of([["4"]], {"5"}, ALL - {"5"}, SECTION) == "unreachable"


def test_adjacent_is_within_two_sentences():
    assert bucket_of([["7", "8"]], {"10"}, ALL, SECTION) == "adjacent"
    assert bucket_of([["7"]], {"10"}, ALL, SECTION) != "adjacent"


def test_adjacent_beats_ranked_lower():
    top = [["12"], ["20"], ["1"]]
    assert bucket_of(top, {"14", "1"}, ALL, SECTION) == "adjacent"


def test_ranked_lower_needs_gold_in_the_top_five():
    top = [["1"], ["25"], ["26"], ["27"], ["15"]]
    assert bucket_of(top, {"15"}, ALL, SECTION) == "ranked-lower"
    assert bucket_of(top + [["15"]], {"16"}, ALL, SECTION) != "ranked-lower"


def test_same_section_then_elsewhere():
    assert bucket_of([["11"]], {"18"}, ALL, SECTION) == "same-section"
    assert bucket_of([["2"]], {"25"}, ALL, SECTION) == "elsewhere"


def test_support_counts_distinct_content_words():
    # "the" and "of" are stop words; 2 of the query's 3 content words are found.
    assert support(
        "the attention of decoder model", "an attention model"
    ) == pytest.approx(2 / 3)
    assert support("the of", "anything") == 0.0


def test_diagnose_flags_a_distractor_and_leaves_hits_unbucketed():
    text = {"1": "attention decoder model", "2": "unrelated words here"}
    miss = {
        "citance": "X#1",
        "query": "attention decoder",
        "gold": ["2"],
        "top": [{"sentences": ["1"], "score": 1.0}],
        "hit_at_1": False,
    }
    d = diagnose(miss, text, {"1", "2"}, {"1": 0, "2": 0})
    assert d.bucket == "adjacent" and d.distractor and d.support == 0.0

    hit = {**miss, "gold": ["1"], "hit_at_1": True}
    d = diagnose(hit, text, {"1", "2"}, {"1": 0, "2": 0})
    assert d.bucket is None and not d.distractor and d.support == 1.0


def test_summary_shares_are_of_misses():
    text = {"1": "a b", "5": "c d", "25": "e f"}
    rows = [
        {
            "citance": "X#1",
            "query": "a",
            "gold": ["1"],
            "top": [{"sentences": ["1"], "score": 1}],
            "hit_at_1": True,
        },
        {
            "citance": "X#2",
            "query": "c",
            "gold": ["5"],
            "top": [{"sentences": ["25"], "score": 1}],
            "hit_at_1": False,
        },
    ]
    summary = summarize([diagnose(r, text, ALL, SECTION) for r in rows])
    assert summary["misses"] == 1
    assert summary["buckets"]["elsewhere"] == {"n": 1, "share_of_misses": 1.0}
