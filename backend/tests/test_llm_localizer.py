"""The LLM re-ranker (2.8): numbers only, nothing lost, failures never cached."""

import asyncio

import pytest

from app.core.llm_localizer import PICKS, apply_reply, build_prompt, rerank
from app.llm.client import LLMError
from app.models.localization import LocalizedPassage
from app.models.passage import Passage


class FakeLLM:
    model = "fake-llm"

    def __init__(self, reply=None, fail=False):
        self.reply = reply
        self.fail = fail
        self.calls = 0

    async def generate_json(self, *, prompt, schema, system=None):
        self.calls += 1
        if self.fail:
            raise LLMError("quota")
        return self.reply


def shortlist(n=6):
    return [
        LocalizedPassage(
            rank=i + 1,
            score=float(n - i),
            passage=Passage(
                id=f"p{i}",
                text=f"Passage number {i}.",
                start_char=10 * i,
                end_char=10 * i + 8,
                section_title="Method" if i == 2 else None,
            ),
        )
        for i in range(n)
    ]


def ids(result):
    return [r.passage.id for r in result.results]


def test_model_order_first_then_the_hybrid_order():
    r = apply_reply(
        {"ranking": [3, 1], "any_fits": True, "confidence": "high"}, shortlist()
    )
    assert ids(r) == ["p2", "p0", "p1", "p3", "p4", "p5"]
    assert [x.rank for x in r.results] == [1, 2, 3, 4, 5, 6]
    assert r.results[0].score == 4.0  # the hybrid score is kept, not invented
    assert (r.picked, r.dropped, r.confidence) == (2, 0, "high")


def test_unknown_repeated_and_non_integer_numbers_are_dropped():
    reply = {
        "ranking": [0, 7, 2, 2, True, "1", 2.0, 4],
        "any_fits": True,
        "confidence": "low",
    }
    r = apply_reply(reply, shortlist())
    assert ids(r)[:2] == ["p1", "p3"]
    assert (r.picked, r.dropped) == (2, 6)
    assert sorted(ids(r)) == sorted(ids(apply_reply({}, shortlist())))  # nothing lost


def test_at_most_picks_numbers_are_taken():
    r = apply_reply(
        {"ranking": [6, 5, 4, 3, 2, 1], "any_fits": True, "confidence": "high"},
        shortlist(),
    )
    assert r.picked == PICKS and r.dropped == 1


def test_a_useless_reply_keeps_the_hybrid_order():
    for reply in ({}, {"ranking": "first"}, {"ranking": None}, []):
        r = apply_reply(reply, shortlist())
        assert ids(r) == [f"p{i}" for i in range(6)]
        assert r.confidence == "low" and r.any_fits is True


def test_prompt_numbers_passages_and_names_sections():
    prompt = build_prompt("They  use\nattention.", shortlist(3), "Some Title")
    assert "Cited paper: Some Title" in prompt
    assert '"They use attention."' in prompt
    assert (
        "[1] Passage number 0." in prompt and "[3] (Method) Passage number 2." in prompt
    )


def test_replies_are_cached_and_failures_are_not(tmp_path):
    good = FakeLLM({"ranking": [2], "any_fits": True, "confidence": "medium"})
    first = asyncio.run(rerank("q", shortlist(), good, cache_dir=tmp_path))
    again = asyncio.run(rerank("q", shortlist(), good, cache_dir=tmp_path))
    assert good.calls == 1 and again.cached and not first.cached
    assert ids(again) == ids(first)

    bad = FakeLLM(fail=True)
    with pytest.raises(LLMError):
        asyncio.run(rerank("other question", shortlist(), bad, cache_dir=tmp_path))
    assert len(list(tmp_path.iterdir())) == 1


def test_a_non_object_reply_is_an_error_and_not_cached(tmp_path):
    with pytest.raises(LLMError):
        asyncio.run(rerank("q", shortlist(), FakeLLM([1, 2]), cache_dir=tmp_path))
    assert not list(tmp_path.iterdir())


def test_empty_shortlist_makes_no_call():
    llm = FakeLLM({"ranking": [1]})
    r = asyncio.run(rerank("q", [], llm))
    assert r.results == [] and llm.calls == 0
