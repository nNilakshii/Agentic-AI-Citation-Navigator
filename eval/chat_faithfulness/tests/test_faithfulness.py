"""Faithfulness scoring (3.8): verdicts read strictly, off-topic kept apart."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from run_faithfulness_eval import judge_prompt, read_verdict, summarize  # noqa: E402


def test_a_verdict_is_read_and_normalised():
    v = read_verdict(
        {"verdict": " Partial", "unsupported_part": " in 2014 ", "quote_enough": False}
    )
    assert v == {
        "verdict": "partial",
        "unsupported_part": "in 2014",
        "quote_enough": False,
    }


def test_an_unusable_verdict_is_not_scored():
    for reply in ({"verdict": "mostly"}, {}, [], None):
        assert read_verdict(reply) is None
    assert read_verdict({"verdict": "supported"})["quote_enough"] is None


def test_the_judge_sees_passage_statement_and_quote():
    p = judge_prompt("It  uses\nattention.", "uses attention", "We use attention.")
    assert '"It uses attention."' in p and '"We use attention."' in p
    assert '"uses attention"' in p


def answer(aid, kind, status, n_claims=1, dropped=0):
    return {
        "id": aid,
        "kind": kind,
        "status": status,
        "claims": [{}] * n_claims,
        "dropped": dropped,
    }


def stmt(aid, kind, verdict, enough=True):
    return {"answer": aid, "kind": kind, "verdict": verdict, "quote_enough": enough}


def test_summary_scores_answerable_statements_and_answers():
    answers = [
        answer("a", "contribution", "answered", 2, dropped=1),
        answer("b", "specific", "answered", 1),
        answer("c", "off-topic", "insufficient", 0),
    ]
    judged = [
        stmt("a", "contribution", "supported"),
        stmt("a", "contribution", "partial", enough=False),
        stmt("b", "specific", "supported"),
    ]
    s = summarize(answers, judged, {})
    assert abs(s["faithfulness"] - 2 / 3) < 1e-9
    assert s["answers_fully_supported"] == 0.5
    assert s["dropped_by_quote_check"] == 0.25  # 1 dropped of 4 made
    assert s["by_kind"]["off-topic"]["insufficient"] == 1.0
    assert s["by_kind"]["off-topic"]["supported"] is None


def test_an_answered_off_topic_question_does_not_count_toward_faithfulness():
    s = summarize(
        [answer("x", "off-topic", "answered")],
        [stmt("x", "off-topic", "unsupported")],
        {},
    )
    assert s["faithfulness"] is None
    assert s["by_kind"]["off-topic"]["answered"] == 1.0
