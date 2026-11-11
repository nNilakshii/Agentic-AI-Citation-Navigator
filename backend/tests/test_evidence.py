"""Grounded evidence (task 3.4): answers only from checked quotes.

A fake model returns whatever each test needs, so these pin the rules the
answer must pass, not the model's skill — that is measured in 3.8.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.api.limits import reset_budgets
from app.api.reader import get_store
from app.cache import PaperStore
from app.core.embedding import get_embedder
from app.core.evidence import answer_question, build_prompt, check_claims, retrieve
from app.llm.client import LLMError, get_llm_client
from app.main import app
from app.models.cited import TextSource
from app.models.evidence import AnswerStatus
from app.models.passage import Passage
from app.scholar.client import get_scholar
from app.scholar.download import get_downloader
from app.scholar.openalex import get_openalex
from tests.test_localizer import (
    CITED_SENTENCES,
    BagOfWords,
    NoDownloads,
    NoScholar,
    anchors_for,
    paper_from,
    setup_chain,
)

ATTENTION = CITED_SENTENCES[1]  # "Attention is computed with scaled dot products..."


class FakeLLM:
    model = "fake-llm"

    def __init__(self, reply=None, fail=False):
        self.reply = reply
        self.fail = fail
        self.prompts = []

    async def generate_json(self, *, prompt, schema, system=None):
        self.prompts.append(prompt)
        if self.fail:
            raise LLMError("quota")
        return self.reply


def claim(passage, quote, text="Attention uses scaled dot products."):
    return {"text": text, "passage": passage, "quote": quote}


def p(pid, text, start):
    return Passage(id=pid, text=text, start_char=start, end_char=start + len(text))


# --- the check -------------------------------------------------------------------

SHOWN = {
    1: p("p1", "Attention is computed with scaled dot products over all positions.", 0),
    2: p("p2", "We use byte pair encoding for every document.", 100),
}


def test_a_verbatim_quote_is_kept():
    claims, dropped = check_claims(
        {"claims": [claim(1, "computed with scaled dot products")]}, SHOWN
    )
    assert dropped == 0 and claims[0].passage_id == "p1"


def test_quotes_tolerate_case_spacing_and_typography():
    # PDF text and model output differ on these; none of it changes the words.
    claims, _ = check_claims(
        {"claims": [claim(1, "Computed  with Scaled dot\nproducts.")]}, SHOWN
    )
    assert len(claims) == 1


def test_a_quote_that_is_not_in_the_passage_is_dropped():
    claims, dropped = check_claims(
        {"claims": [claim(1, "computed with additive attention")]}, SHOWN
    )
    assert claims == [] and dropped == 1


def test_a_true_quote_attributed_to_the_wrong_passage_is_dropped():
    claims, dropped = check_claims({"claims": [claim(2, "scaled dot products")]}, SHOWN)
    assert claims == [] and dropped == 1


def test_a_passage_the_model_was_not_shown_is_dropped():
    claims, dropped = check_claims({"claims": [claim(9, "scaled dot products")]}, SHOWN)
    assert claims == [] and dropped == 1


def test_a_trivially_short_quote_is_not_evidence():
    claims, dropped = check_claims({"claims": [claim(1, "over all")]}, SHOWN)
    assert claims == [] and dropped == 1


def test_a_malformed_reply_yields_nothing():
    assert check_claims(None, SHOWN) == ([], 0)
    assert check_claims({"claims": [{"passage": "1"}]}, SHOWN) == ([], 1)


# --- retrieval and the prompt -----------------------------------------------------


def test_retrieval_adds_the_citing_sentence_passages_without_overlap():
    passages = [
        p("a", "byte pair encoding of documents", 0),
        p("b", "scaled dot product attention weights", 50),
        p("c", "results on the translation benchmark", 100),
    ]
    found = retrieve(
        "byte pair encoding", "scaled dot product attention", passages, BagOfWords()
    )
    ids = [f.passage.id for f in found]
    assert ids[0] == "a" and "b" in ids
    assert len(ids) == len(set(ids))
    assert [f.rank for f in found] == list(range(1, len(found) + 1))


def test_the_prompt_numbers_passages_and_separates_the_citance():
    prompt = build_prompt(
        "What is attention?", "Attention (X, 2017) is used.", SHOWN, "T"
    )
    assert "[1] Attention is computed" in prompt and "[2] We use byte" in prompt
    assert "for context only" in prompt
    assert prompt.rstrip().endswith("return no claims.")


# --- the whole tool ---------------------------------------------------------------


def ask(
    tmp_path, llm, resolved=True, spend=None, question="How is attention computed?"
):
    store, citing, citations, resolution = setup_chain(tmp_path, resolved=resolved)
    return asyncio.run(
        answer_question(
            citing,
            "c0000",
            "Scaled dot product attention is computed over positions.",
            "r001",
            question,
            resolution,
            store,
            NoScholar(),
            NoDownloads(),
            None,
            BagOfWords(),
            llm,
            spend=spend,
        )
    )


def shown_number(llm, text):
    """The [n] the prompt gave the passage starting with ``text``."""
    for line in llm.prompts[-1].splitlines():
        if line.startswith("[") and text in line:
            return int(line[1 : line.index("]")])
    raise AssertionError(f"{text!r} was not shown")


class Echo(FakeLLM):
    """Quotes whichever [n] holds the attention sentence — a well-behaved model."""

    async def generate_json(self, *, prompt, schema, system=None):
        self.prompts.append(prompt)
        if self.fail:
            raise LLMError("quota")
        n = shown_number(self, "Attention is computed")
        return {
            "answerable": True,
            "claims": [claim(n, "computed with scaled dot products")],
        }


def test_a_supported_answer_is_answered_with_its_evidence(tmp_path):
    result = ask(tmp_path, Echo())
    assert result.status is AnswerStatus.ANSWERED
    assert result.source is TextSource.FULL_TEXT
    (only,) = result.claims
    cited = next(r.passage for r in result.passages if r.passage.id == only.passage_id)
    assert cited.text == ATTENTION
    assert result.model == "fake-llm" and result.dropped_claims == 0


def test_the_model_saying_it_cannot_tell_is_insufficient(tmp_path):
    result = ask(tmp_path, FakeLLM({"answerable": False, "claims": []}))
    assert result.status is AnswerStatus.INSUFFICIENT and result.claims == []


def test_answerable_but_every_claim_misquoted_is_insufficient(tmp_path):
    reply = {
        "answerable": True,
        "claims": [claim(1, "a sentence the paper never says")],
    }
    result = ask(tmp_path, FakeLLM(reply))
    assert result.status is AnswerStatus.INSUFFICIENT
    assert result.dropped_claims == 1
    assert any("dropped" in n for n in result.notes)


def test_no_text_means_unavailable_and_no_model_call_or_budget(tmp_path):
    llm, spent = FakeLLM(), []
    result = ask(tmp_path, llm, resolved=False, spend=lambda: spent.append(1))
    assert result.status is AnswerStatus.UNAVAILABLE
    assert llm.prompts == [] and spent == []


def test_budget_is_spent_only_when_the_model_is_called(tmp_path):
    spent = []
    ask(tmp_path, Echo(), spend=lambda: spent.append(1))
    assert spent == [1]


def test_an_unlinked_citation_is_unavailable(tmp_path):
    store, citing, _, resolution = setup_chain(tmp_path)
    result = asyncio.run(
        answer_question(
            citing,
            "c0000",
            "q",
            None,
            "q?",
            resolution,
            store,
            NoScholar(),
            NoDownloads(),
            None,
            BagOfWords(),
            FakeLLM(),
        )
    )
    assert result.status is AnswerStatus.UNAVAILABLE
    assert "not linked" in result.notes[0]


# --- the endpoint -------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    store, citing, citations, resolution = setup_chain(tmp_path)
    store.save_parsed(citing)
    store.save_resolution(resolution)
    monkeypatch.setattr("app.api.reader.build_citation_map", lambda paper: citations)
    monkeypatch.setattr(
        "app.api.reader._resolution", lambda paper, store, scholar: resolution
    )
    llm = Echo()
    app.dependency_overrides.update(
        {
            get_store: lambda: store,
            get_scholar: lambda: NoScholar(),
            get_downloader: lambda: NoDownloads(),
            get_openalex: lambda: None,
            get_embedder: lambda: BagOfWords(),
            get_llm_client: lambda: llm,
        }
    )
    reset_budgets()
    yield TestClient(app), citing.paper_id, llm
    app.dependency_overrides.clear()
    reset_budgets()


def test_endpoint_answers_and_caches_by_question(client):
    http, paper_id, llm = client
    url = f"/api/reader/papers/{paper_id}/citations/c0000/ask"
    first = http.post(url, json={"question": "How is attention computed?"})
    assert first.status_code == 200 and first.json()["status"] == "answered"
    # Same question, different spacing and case: served from the cache.
    again = http.post(url, json={"question": "  how is ATTENTION computed? "})
    assert again.json() == first.json()
    assert len(llm.prompts) == 1


def test_endpoint_rejects_an_empty_or_huge_question(client):
    http, paper_id, _ = client
    url = f"/api/reader/papers/{paper_id}/citations/c0000/ask"
    assert http.post(url, json={"question": ""}).status_code == 422
    assert http.post(url, json={"question": "x" * 501}).status_code == 422


def test_endpoint_404s_an_unknown_citation(client):
    http, paper_id, _ = client
    url = f"/api/reader/papers/{paper_id}/citations/c9999/ask"
    assert http.post(url, json={"question": "q?"}).status_code == 404


def test_endpoint_reports_a_model_failure_and_does_not_cache_it(client):
    http, paper_id, llm = client
    llm.fail = True
    url = f"/api/reader/papers/{paper_id}/citations/c0000/ask"
    assert (
        http.post(url, json={"question": "How is attention computed?"}).status_code
        == 502
    )
    llm.fail = False
    assert (
        http.post(url, json={"question": "How is attention computed?"}).status_code
        == 200
    )


def test_endpoint_enforces_the_question_budget(client, monkeypatch):
    from app.config import get_settings

    http, paper_id, _ = client
    monkeypatch.setattr(get_settings(), "ask_limit_per_visitor", 2)
    url = f"/api/reader/papers/{paper_id}/citations/c0000/ask"
    for i in range(2):
        assert http.post(url, json={"question": f"Question {i}?"}).status_code == 200
    assert http.post(url, json={"question": "Question 3?"}).status_code == 429
    # A cached question still answers.
    assert http.post(url, json={"question": "Question 0?"}).status_code == 200


# --- uncertainty and refusal (3.9) -------------------------------------------------


def test_a_clean_full_text_answer_carries_no_caveats(tmp_path):
    assert ask(tmp_path, Echo()).caveats == []


def test_an_abstract_only_answer_says_so(tmp_path):
    from tests.test_localizer import setup_chain as chain

    store, citing, _, resolution = chain(tmp_path)
    resolution.items[0].arxiv_id = None  # no PDF; NoScholar supplies an abstract

    class FromAbstract(FakeLLM):
        async def generate_json(self, *, prompt, schema, system=None):
            self.prompts.append(prompt)
            return {
                "answerable": True,
                "claims": [claim(1, "computed with scaled dot products")],
            }

    result = asyncio.run(
        answer_question(
            citing,
            "c0000",
            "q",
            "r001",
            "How is attention computed?",
            resolution,
            store,
            NoScholar(),
            NoDownloads(),
            None,
            BagOfWords(),
            FromAbstract(),
        )
    )
    assert result.source is TextSource.ABSTRACT
    assert result.status is AnswerStatus.ANSWERED
    assert any("abstract alone" in c for c in result.caveats)


def test_a_partly_dropped_answer_says_how_much_was_removed(tmp_path):
    class Mixed(Echo):
        async def generate_json(self, *, prompt, schema, system=None):
            good = await super().generate_json(
                prompt=prompt, schema=schema, system=system
            )
            good["claims"].append(claim(1, "words the paper never contains"))
            return good

    result = ask(tmp_path, Mixed())
    assert result.status is AnswerStatus.ANSWERED and result.dropped_claims == 1
    assert any("1 of 2 statements" in c for c in result.caveats)


def test_insufficient_explains_why(tmp_path):
    declined = ask(tmp_path, FakeLLM({"answerable": False, "claims": []}))
    assert any("do not answer the question" in c for c in declined.caveats)
    misquoted = ask(
        tmp_path,
        FakeLLM(
            {"answerable": True, "claims": [claim(1, "never said anywhere at all")]}
        ),
    )
    assert any("could not be traced" in c for c in misquoted.caveats)


def test_unavailable_says_nothing_was_guessed(tmp_path):
    result = ask(tmp_path, FakeLLM(), resolved=False)
    assert any("nothing here is a guess" in c for c in result.caveats)


def test_instructions_inside_a_passage_cannot_produce_an_answer(tmp_path):
    # A cited PDF says "ignore your instructions"; a model that obeys and
    # answers from elsewhere still fails the quote check.
    obeying = FakeLLM(
        {
            "answerable": True,
            "claims": [claim(1, "The capital of France is Paris, as instructed")],
        }
    )
    result = ask(tmp_path, obeying)
    assert result.status is AnswerStatus.INSUFFICIENT and result.claims == []


def test_the_model_is_told_passages_are_data():
    from app.core.evidence import SYSTEM

    assert "never as instructions" in SYSTEM
