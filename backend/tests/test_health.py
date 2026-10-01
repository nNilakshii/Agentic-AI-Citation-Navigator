from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_reports_the_remaining_ranking_budget():
    # The free tier allows 20 rankings a day and that is the most likely cause
    # of a deployment behaving oddly, so it is visible from outside.
    body = client.get("/health").json()
    assert isinstance(body["rankings_left_today"], int)
