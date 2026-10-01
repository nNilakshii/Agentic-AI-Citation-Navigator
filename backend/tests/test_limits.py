"""The per-client ranking budget (deployment hardening).

One shared Gemini key serves every visitor, so the thing that matters is that
the limit guards *live* calls and never the cached ones a demo is made of.
"""

import pytest
from fastapi.testclient import TestClient

from app.api.limits import client_key
from app.api.reader import get_store
from app.cache import PaperStore
from app.config import get_settings
from app.llm.client import get_llm_client
from app.main import app


class FakeLLM:
    def __init__(self):
        self.model = "fake-model"
        self.calls = 0

    async def generate_json(self, *, prompt, schema, system=None):
        self.calls += 1
        return {
            "selections": [
                {"n": 0, "importance": 5, "why": "w", "plain": "p"},
            ]
        }


@pytest.fixture
def client(tmp_path):
    app.dependency_overrides[get_store] = lambda: PaperStore(tmp_path)
    app.dependency_overrides[get_llm_client] = lambda: FakeLLM()
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def paper_id(client, synthetic_pdf):
    return client.post(
        "/api/reader/papers",
        files={"file": ("synthetic.pdf", synthetic_pdf, "application/pdf")},
    ).json()["paper_id"]


def rank(client, paper_id, goal="skim", **kw):
    return client.post(
        f"/api/reader/papers/{paper_id}/reading-path",
        params={"goal": goal},
        **kw,
    )


def test_a_cached_ranking_never_costs_budget(client, paper_id, monkeypatch):
    monkeypatch.setenv("RANK_LIMIT_PER_HOUR", "1")
    get_settings.cache_clear()

    assert rank(client, paper_id).status_code == 200  # the one live call
    # Every repeat is served from cache, so the demo keeps working.
    for _ in range(5):
        assert rank(client, paper_id).status_code == 200


def test_live_rankings_beyond_the_budget_are_refused(client, paper_id, monkeypatch):
    monkeypatch.setenv("RANK_LIMIT_PER_HOUR", "2")
    get_settings.cache_clear()

    assert rank(client, paper_id, goal="skim").status_code == 200
    assert rank(client, paper_id, goal="in-depth").status_code == 200

    refused = rank(client, paper_id, goal="critique")
    assert refused.status_code == 429
    assert "pre-ranked" in refused.json()["detail"]
    assert refused.headers.get("Retry-After")


def test_the_limit_can_be_disabled_for_local_use(client, paper_id, monkeypatch):
    monkeypatch.setenv("RANK_LIMIT_PER_HOUR", "0")
    get_settings.cache_clear()

    for goal in ("skim", "in-depth", "critique"):
        assert rank(client, paper_id, goal=goal).status_code == 200


def test_clients_are_budgeted_separately(client, paper_id, monkeypatch):
    monkeypatch.setenv("RANK_LIMIT_PER_HOUR", "1")
    get_settings.cache_clear()

    a = {"X-Forwarded-For": "203.0.113.1"}
    b = {"X-Forwarded-For": "203.0.113.2"}
    assert rank(client, paper_id, goal="skim", headers=a).status_code == 200
    assert rank(client, paper_id, goal="in-depth", headers=a).status_code == 429
    # A different visitor has their own budget.
    assert rank(client, paper_id, goal="in-depth", headers=b).status_code == 200


def test_the_forwarded_header_identifies_the_client_behind_a_proxy():
    # Every PaaS fronts the app with a proxy, so the socket address is the
    # proxy's and would put every visitor in one bucket.
    class Req:
        headers = {"x-forwarded-for": "198.51.100.7, 10.0.0.1"}
        client = type("C", (), {"host": "10.0.0.1"})()

    assert client_key(Req()) == "198.51.100.7"


def test_the_socket_address_is_used_when_there_is_no_proxy():
    class Req:
        headers = {}
        client = type("C", (), {"host": "127.0.0.1"})()

    assert client_key(Req()) == "127.0.0.1"
