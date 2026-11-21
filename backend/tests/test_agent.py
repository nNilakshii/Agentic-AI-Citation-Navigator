"""The citation agent (3.6): a closed tool list, a rules fallback, no new prose."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.api.limits import reset_budgets
from app.api.reader import get_store
from app.core import agent
from app.core.agent import (
    MAX_TOOLS,
    Route,
    ToolError,
    build_prompt,
    read_reply,
    route,
    route_by_rules,
)
from app.core.embedding import get_embedder
from app.llm.client import LLMError, get_llm_client
from app.main import app
from app.models.bibliometrics import Bibliometrics, UseInPaper
from app.scholar.client import get_scholar
from app.scholar.download import get_downloader
from app.scholar.openalex import get_openalex
from tests.test_evidence import Echo
from tests.test_localizer import BagOfWords, NoDownloads, NoScholar, setup_chain


class Router:
    model = "fake-router"

    def __init__(self, reply=None, fail=False):
        self.reply, self.fail, self.calls = reply, fail, 0

    async def generate_json(self, *, prompt, schema, system=None):
        self.calls += 1
        if self.fail:
            raise LLMError("quota")
        return self.reply


# --- the rules --------------------------------------------------------------------


@pytest.mark.parametrize(
    "question, tools",
    [
        ("How is attention computed?", ["evidence"]),
        ("How many times has this paper been cited?", ["impact"]),
        ("Is it influential?", ["impact"]),
        ("Why do the authors cite this?", ["intent"]),
        ("Which passage does this citation refer to?", ["locate"]),
        ("Why is it cited, and how influential is it?", ["impact", "intent"]),
    ],
)
def test_rules_route_by_keyword_and_default_to_evidence(question, tools):
    r = route_by_rules(question)
    assert r.tools == tools and r.by == "rules"


# --- the model's reply ---------------------------------------------------------------


def test_known_tools_are_kept_in_order():
    r = read_reply({"tools": ["impact", "Evidence "]})
    assert r.tools == ["impact", "evidence"] and r.by == "llm" and r.dropped == 0


def test_invented_repeated_and_excess_tools_are_dropped_and_counted():
    r = read_reply(
        {"tools": ["search_web", "intent", "intent", 3, "locate", "impact", "evidence"]}
    )
    assert r.tools == ["intent", "locate", "impact"]
    assert len(r.tools) == MAX_TOOLS and r.dropped == 4


def test_a_reply_with_no_usable_tool_is_none():
    for reply in (
        {},
        {"tools": []},
        {"tools": ["shell"]},
        {"tools": "impact"},
        [],
        None,
    ):
        assert read_reply(reply) is None


def test_prompt_lists_every_tool_and_quotes_question_and_citance():
    prompt = build_prompt("Why  cite\nit?", citance="We follow  the method.")
    assert all(f"- {name}:" in prompt for name in agent.TOOLS)
    assert '"Why cite it?"' in prompt and '"We follow the method."' in prompt


# --- routing ---------------------------------------------------------------------------


def test_the_model_routes_and_its_reply_is_cached(tmp_path):
    llm = Router({"tools": ["intent"]})
    first = asyncio.run(route("What is this for?", llm, cache_dir=tmp_path))
    again = asyncio.run(route("What is this for?", llm, cache_dir=tmp_path))
    assert first.tools == ["intent"] and first.by == "llm"
    assert again.cached and llm.calls == 1


@pytest.mark.parametrize(
    "llm", [Router(fail=True), Router({"tools": ["browse"]}), None]
)
def test_no_model_or_a_bad_reply_falls_back_to_the_rules_uncached(tmp_path, llm):
    r = asyncio.run(route("How many citations does it have?", llm, cache_dir=tmp_path))
    assert r.tools == ["impact"] and r.by == "rules"
    assert not list(tmp_path.iterdir())
    if llm is not None:
        assert r.notes


def test_budget_is_spent_only_when_the_router_model_is_called(tmp_path):
    spent = []
    llm = Router({"tools": ["evidence"]})
    for _ in range(2):
        asyncio.run(route("q?", llm, cache_dir=tmp_path, spend=lambda: spent.append(1)))
    assert spent == [1]


def test_a_refused_budget_falls_back_to_the_rules(tmp_path):
    def refuse():
        raise LLMError("budget spent")

    r = asyncio.run(
        route(
            "Is it influential?",
            Router({"tools": ["evidence"]}),
            cache_dir=tmp_path,
            spend=refuse,
        )
    )
    assert r.by == "rules" and r.tools == ["impact"]


# --- running ---------------------------------------------------------------------------


def test_tools_run_in_route_order_and_one_failure_does_not_sink_the_rest():
    ran = []

    async def ok():
        ran.append("impact")
        return {"counts": 3}

    async def broken():
        ran.append("evidence")
        raise ToolError("no text")

    result = asyncio.run(
        agent.run(
            Route(["evidence", "impact", "locate"], "llm"),
            {"evidence": broken, "impact": ok},
        )
    )
    assert ran == ["evidence", "impact"]
    assert result.parts == {"impact": {"counts": 3}}
    assert result.errors == {
        "evidence": "no text",
        "locate": "this tool is not available here",
    }


# --- the endpoint ------------------------------------------------------------------------


class AgentLLM(Echo):
    """Routes as told, labels intent, and answers evidence like Echo."""

    model = "fake-agent"

    def __init__(self, tools):
        super().__init__()
        self.tools = tools
        self.kinds = []

    async def generate_json(self, *, prompt, schema, system=None):
        kind = next(iter(schema["properties"]))
        self.kinds.append(kind)
        if self.fail:
            raise LLMError("quota")
        if kind == "tools":
            return {"tools": self.tools}
        if kind == "intent":
            return {"intent": "method", "confidence": "high"}
        return await super().generate_json(prompt=prompt, schema=schema, system=system)


@pytest.fixture
def chat(tmp_path, monkeypatch):
    store, citing, citations, resolution = setup_chain(tmp_path)
    store.save_parsed(citing)
    store.save_resolution(resolution)
    monkeypatch.setattr("app.api.reader.build_citation_map", lambda paper: citations)
    monkeypatch.setattr(
        "app.core.localizer.build_citation_map", lambda paper: citations
    )
    monkeypatch.setattr(
        "app.api.reader._resolution", lambda paper, store, scholar: resolution
    )
    monkeypatch.setattr("app.api.reader.AGENT_CACHE", tmp_path / "agent")
    monkeypatch.setattr("app.api.reader.EMBEDDING_CACHE", tmp_path / "emb")

    def fake_impact(paper_id, reference_id, refresh, store, scholar, openalex):
        return Bibliometrics(
            citing_paper_id=paper_id,
            reference_id=reference_id,
            in_this_paper=UseInPaper(mentions=1, sections=["Introduction"]),
            fetched_at="2026-11-20T00:00:00Z",
        )

    monkeypatch.setattr("app.api.reader.reference_bibliometrics", fake_impact)
    llm = AgentLLM(["evidence"])
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
    url = f"/api/reader/papers/{citing.paper_id}/citations/c0000/chat"
    yield TestClient(app), url, llm
    app.dependency_overrides.clear()
    reset_budgets()


def test_chat_routes_to_evidence_and_returns_the_grounded_answer(chat):
    http, url, llm = chat
    body = http.post(url, json={"question": "How is attention computed?"}).json()
    assert body["route"] == ["evidence"] and body["routed_by"] == "llm"
    assert body["evidence"]["status"] == "answered"
    assert body["intent"] is None and body["impact"] is None and body["errors"] == {}


def test_chat_runs_every_routed_tool_side_by_side(chat):
    http, url, llm = chat
    llm.tools = ["intent", "impact", "locate"]
    body = http.post(url, json={"question": "Why cite it, and is it known?"}).json()
    assert body["route"] == ["intent", "impact", "locate"]
    assert body["intent"]["intent"] == "method" and body["intent"]["citance"]
    assert body["impact"]["in_this_paper"]["mentions"] == 1
    assert body["location"]["results"], body["errors"]
    assert body["evidence"] is None


def test_chat_counts_a_question_once_however_many_model_calls(chat, monkeypatch):
    from app.config import get_settings

    http, url, llm = chat
    llm.tools = ["intent", "evidence"]
    monkeypatch.setattr(get_settings(), "ask_limit_per_visitor", 1)
    first = http.post(url, json={"question": "How is attention computed?"})
    assert first.status_code == 200 and first.json()["errors"] == {}
    assert llm.kinds == ["tools", "intent", "answerable"]  # 3 calls, 1 budget unit

    # Budget spent: routing falls back to the rules (free), the evidence tool
    # says why it cannot answer, and nothing fails as a whole.
    second = http.post(url, json={"question": "What does it say about positions?"})
    body = second.json()
    assert second.status_code == 200 and body["routed_by"] == "rules"
    assert body["route"] == ["evidence"] and "evidence" in body["errors"]
    assert len(llm.kinds) == 3


def test_chat_without_a_model_still_answers_from_the_rules(chat):
    http, url, llm = chat
    llm.fail = True
    body = http.post(url, json={"question": "How many times is it cited?"}).json()
    assert body["routed_by"] == "rules" and body["route"] == ["impact"]
    assert body["impact"] is not None and body["route_notes"]


def test_chat_404s_an_unknown_citation_and_rejects_an_empty_question(chat):
    http, url, _ = chat
    assert (
        http.post(url.replace("c0000", "c9999"), json={"question": "q?"}).status_code
        == 404
    )
    assert http.post(url, json={"question": ""}).status_code == 422
