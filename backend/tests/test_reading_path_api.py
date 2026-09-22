"""The reading-path endpoints (task 1.6).

The LLM is always faked here: these tests are about caching, error mapping and
the request contract, none of which should cost quota to verify.
"""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.reader import get_store
from app.cache import PaperStore
from app.core.reading_path import RANKER_VERSION
from app.llm.client import LLMError, LLMNotConfigured, get_llm_client
from app.main import app
from app.models.reading import ReadingGoal

FRONTEND_GOALS = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "goals.js"
)


class FakeLLM:
    def __init__(self, error=None):
        self.model = "fake-model"
        self.error = error
        self.calls = 0

    async def generate_json(self, *, prompt, schema, system=None):
        self.calls += 1
        if self.error:
            raise self.error
        # Always pick the first two sentences shown.
        return {
            "selections": [
                {
                    "n": 0,
                    "importance": 5,
                    "why": "states the core claim",
                    "plain": "In plain terms: this is the main point.",
                },
                {
                    "n": 1,
                    "importance": 3,
                    "why": "supporting detail",
                    "plain": "In plain terms: this backs up the point above.",
                },
            ]
        }


@pytest.fixture
def llm():
    return FakeLLM()


@pytest.fixture
def client(tmp_path, llm):
    app.dependency_overrides[get_store] = lambda: PaperStore(tmp_path)
    app.dependency_overrides[get_llm_client] = lambda: llm
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def paper_id(client, synthetic_pdf):
    response = client.post(
        "/api/reader/papers",
        files={"file": ("synthetic.pdf", synthetic_pdf, "application/pdf")},
    )
    return response.json()["paper_id"]


def rank(client, paper_id, goal="skim", **params):
    return client.post(
        f"/api/reader/papers/{paper_id}/reading-path", params={"goal": goal, **params}
    )


# --- the happy path ----------------------------------------------------


def test_ranking_returns_a_path_of_real_spans(client, paper_id):
    response = rank(client, paper_id)
    assert response.status_code == 200

    path = response.json()
    assert path["goal"] == "skim"
    assert path["paper_id"] == paper_id
    assert path["ranker_version"] == RANKER_VERSION
    assert path["items"]

    paper = client.get(f"/api/reader/papers/{paper_id}").json()
    by_id = {s["id"]: s for s in paper["sentences"]}
    for item in path["items"]:
        source = by_id[item["sentence_id"]]
        assert item["text"] == source["text"]
        assert item["start_char"] == source["start_char"]
        assert item["end_char"] == source["end_char"]
        # The span must actually cut the claimed text out of the document.
        assert paper["full_text"][item["start_char"] : item["end_char"]] == item["text"]


def test_each_item_carries_a_reason_for_the_explanation_panel(client, paper_id):
    path = rank(client, paper_id).json()
    assert all(item["why"] for item in path["items"])
    assert all(1 <= item["importance"] <= 5 for item in path["items"])


def test_each_item_carries_a_plain_language_explanation(client, paper_id):
    # 1.8 shows this beside the sentence, so it travels on the same response
    # rather than costing a second LLM call.
    path = rank(client, paper_id).json()
    assert all(item["plain"] for item in path["items"])


@pytest.mark.parametrize("goal", [g.value for g in ReadingGoal])
def test_every_goal_is_accepted(client, paper_id, goal):
    assert rank(client, paper_id, goal=goal).status_code == 200


def test_an_unknown_goal_is_rejected(client, paper_id):
    assert rank(client, paper_id, goal="speedread").status_code == 422


def test_the_goal_is_required(client, paper_id):
    response = client.post(f"/api/reader/papers/{paper_id}/reading-path")
    assert response.status_code == 422


# --- caching -----------------------------------------------------------


def test_a_second_request_is_served_from_cache(client, paper_id, llm):
    first = rank(client, paper_id).json()
    calls_after_first = llm.calls

    second = rank(client, paper_id).json()

    assert llm.calls == calls_after_first, "cached path should not call the LLM"
    assert second == first


def test_force_re_ranks(client, paper_id, llm):
    rank(client, paper_id)
    before = llm.calls

    rank(client, paper_id, force=True)

    assert llm.calls > before


def test_each_goal_is_cached_separately(client, paper_id, llm):
    rank(client, paper_id, goal="skim")
    after_skim = llm.calls

    rank(client, paper_id, goal="critique")
    assert llm.calls > after_skim

    rank(client, paper_id, goal="skim")
    assert llm.calls == after_skim + 1, "skim should still be cached"


def test_the_cache_file_is_keyed_by_parser_and_ranker_version(
    client, paper_id, tmp_path
):
    rank(client, paper_id, goal="in-depth")

    files = list((tmp_path / "reading_paths").glob("*.json"))
    assert len(files) == 1
    assert re.match(
        rf"^{paper_id}\.v\d+\.in-depth\.r{RANKER_VERSION}\.json$", files[0].name
    )


def test_a_corrupt_cache_file_is_treated_as_a_miss(client, paper_id, tmp_path, llm):
    rank(client, paper_id)
    cached = next((tmp_path / "reading_paths").glob("*.json"))
    cached.write_text("{ truncated", encoding="utf-8")
    before = llm.calls

    response = rank(client, paper_id)

    assert response.status_code == 200
    assert llm.calls > before


# --- the read-only GET -------------------------------------------------


def test_get_returns_404_before_a_path_is_built(client, paper_id, llm):
    response = client.get(
        f"/api/reader/papers/{paper_id}/reading-path", params={"goal": "skim"}
    )
    assert response.status_code == 404
    assert llm.calls == 0, "the read-only route must never spend quota"


def test_get_returns_the_path_once_built(client, paper_id):
    posted = rank(client, paper_id).json()

    got = client.get(
        f"/api/reader/papers/{paper_id}/reading-path", params={"goal": "skim"}
    )

    assert got.status_code == 200
    assert got.json() == posted


# --- failures ----------------------------------------------------------


def test_an_unknown_paper_is_404(client):
    assert rank(client, "b" * 64).status_code == 404


def test_a_malformed_paper_id_is_422(client):
    assert rank(client, "not-a-hash").status_code == 422


def test_a_missing_api_key_reports_503_with_the_fix(client, paper_id):
    app.dependency_overrides[get_llm_client] = lambda: FakeLLM(
        error=LLMNotConfigured("GEMINI_API_KEY is not set. Add it to .env")
    )

    response = rank(client, paper_id)

    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["detail"]


def test_an_upstream_failure_reports_502(client, paper_id):
    app.dependency_overrides[get_llm_client] = lambda: FakeLLM(
        error=LLMError("quota exhausted")
    )

    response = rank(client, paper_id)

    assert response.status_code == 502


def test_a_failed_ranking_is_not_cached(client, paper_id, tmp_path):
    app.dependency_overrides[get_llm_client] = lambda: FakeLLM(
        error=LLMError("transient")
    )
    rank(client, paper_id)

    assert not list((tmp_path / "reading_paths").glob("*.json"))


# --- the goals endpoint and the frontend contract ----------------------


def test_goals_endpoint_describes_every_goal(client):
    goals = client.get("/api/reader/goals").json()

    assert {g["id"] for g in goals} == {g.value for g in ReadingGoal}
    for goal in goals:
        assert goal["label"] and goal["criteria"] and goal["excludes"]


def test_backend_and_frontend_agree_on_goal_ids():
    # The ids are the wire format between src/lib/goals.js (task 1.5) and this
    # endpoint. Drift would mean the UI silently asks for a goal that 422s.
    source = FRONTEND_GOALS.read_text(encoding="utf-8")
    frontend_ids = set(re.findall(r'id:\s*"([a-z-]+)"', source))

    assert frontend_ids == {goal.value for goal in ReadingGoal}


# --- partial results must never be cached ------------------------------


class HalfFailingLLM:
    """Fails the first batch, succeeds on the rest — a rate limit, in effect."""

    def __init__(self):
        self.model = "fake-model"
        self.calls = 0

    async def generate_json(self, *, prompt, schema, system=None):
        self.calls += 1
        if self.calls == 1:
            raise LLMError("429 rate limited")
        return {"selections": [{"n": 0, "importance": 4, "why": "w"}]}


def test_a_partial_path_is_served_but_not_cached(client, paper_id, tmp_path):
    # Regression: a rate-limited batch used to be cached as if complete, so a
    # transient 429 permanently truncated that paper's reading path. The
    # sentences in a partial path are real, so nothing about the result itself
    # reveals the problem — only n_batches_failed does.
    from app.core import reading_path as rp

    original = rp.BATCH_SIZE
    rp.BATCH_SIZE = 2  # force several batches out of a small paper
    try:
        app.dependency_overrides[get_llm_client] = lambda: HalfFailingLLM()
        response = client.post(
            f"/api/reader/papers/{paper_id}/reading-path", params={"goal": "in-depth"}
        )
    finally:
        rp.BATCH_SIZE = original

    assert response.status_code == 200
    body = response.json()
    assert body["n_batches_failed"] == 1
    assert not list(
        (tmp_path / "reading_paths").glob("*.json")
    ), "an incomplete path must not be cached"


def test_a_complete_path_reports_no_failures_and_is_cached(client, paper_id, tmp_path):
    body = rank(client, paper_id).json()

    assert body["n_batches_failed"] == 0
    assert body["n_batches"] >= 1
    assert list((tmp_path / "reading_paths").glob("*.json"))
