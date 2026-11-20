"""Citation intent (3.2): one label from a closed list, failures never cached."""

import asyncio

import pytest

from app.core.intent import INTENTS, build_prompt, classify, read_reply
from app.llm.client import LLMError


class FakeLLM:
    model = "fake-llm"

    def __init__(self, reply=None, fail=False):
        self.reply, self.fail, self.calls = reply, fail, 0

    async def generate_json(self, *, prompt, schema, system=None):
        self.calls += 1
        if self.fail:
            raise LLMError("quota")
        return self.reply


def test_a_known_label_is_kept_and_normalised():
    r = read_reply({"intent": " Method ", "confidence": "high"})
    assert (r.intent, r.confidence) == ("method", "high")


def test_anything_else_is_invalid_not_guessed():
    for reply in ({"intent": "uses"}, {"intent": 2}, {}, [], None, "method"):
        r = read_reply(reply)
        assert r.intent is None and r.confidence == "low"


def test_prompt_defines_every_intent_and_quotes_the_text():
    prompt = build_prompt("We  follow\n[3].", section="Methods")
    assert all(f"- {label}:" in prompt for label in INTENTS)
    assert '"We follow [3]."' in prompt
    assert "Section of the citing paper: Methods" in prompt
    assert "Section" not in build_prompt("We follow [3].")


def test_replies_are_cached_and_failures_are_not(tmp_path):
    good = FakeLLM({"intent": "result", "confidence": "medium"})
    first = asyncio.run(classify("as in [2]", good, cache_dir=tmp_path))
    again = asyncio.run(classify("as in [2]", good, cache_dir=tmp_path))
    assert good.calls == 1 and again.cached and not first.cached
    assert again.intent == first.intent == "result"

    with pytest.raises(LLMError):
        asyncio.run(classify("other", FakeLLM(fail=True), cache_dir=tmp_path))
    with pytest.raises(LLMError):
        asyncio.run(classify("other", FakeLLM(["method"]), cache_dir=tmp_path))
    assert len(list(tmp_path.iterdir())) == 1


def test_the_section_is_part_of_the_cache_key(tmp_path):
    llm = FakeLLM({"intent": "method", "confidence": "high"})
    asyncio.run(classify("t", llm, section="Intro", cache_dir=tmp_path))
    asyncio.run(classify("t", llm, section="Methods", cache_dir=tmp_path))
    assert llm.calls == 2
