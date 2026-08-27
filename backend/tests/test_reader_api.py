import pytest
from fastapi.testclient import TestClient

from app.api.reader import get_store
from app.cache import PaperStore
from app.main import app


@pytest.fixture
def client(tmp_path):
    """A client whose cache lives in a tmp dir, not the developer's data/cache."""
    app.dependency_overrides[get_store] = lambda: PaperStore(tmp_path)
    yield TestClient(app)
    app.dependency_overrides.clear()


def upload(client, pdf_bytes, **params):
    return client.post(
        "/api/reader/papers",
        files={"file": ("synthetic.pdf", pdf_bytes, "application/pdf")},
        params=params,
    )


def test_upload_returns_a_parsed_paper(client, synthetic_pdf):
    response = upload(client, synthetic_pdf)
    assert response.status_code == 200

    paper = response.json()
    assert len(paper["paper_id"]) == 64
    assert paper["sentences"]
    assert paper["sections"]
    assert paper["source"]["page_count"] == 2


def test_upload_is_idempotent_and_served_from_cache(client, synthetic_pdf, monkeypatch):
    first = upload(client, synthetic_pdf).json()

    def fail_if_called(*args, **kwargs):
        raise AssertionError("second upload should have hit the cache")

    monkeypatch.setattr("app.api.reader.parse_pdf", fail_if_called)
    second = upload(client, synthetic_pdf).json()
    assert second["paper_id"] == first["paper_id"]


def test_force_reparses(client, synthetic_pdf):
    first = upload(client, synthetic_pdf).json()
    second = upload(client, synthetic_pdf, force=True).json()
    assert second["paper_id"] == first["paper_id"]
    assert second["full_text"] == first["full_text"]


def test_get_paper_round_trips(client, synthetic_pdf):
    paper_id = upload(client, synthetic_pdf).json()["paper_id"]

    response = client.get(f"/api/reader/papers/{paper_id}")
    assert response.status_code == 200
    assert response.json()["paper_id"] == paper_id


def test_outline_returns_sections_only(client, synthetic_pdf):
    paper_id = upload(client, synthetic_pdf).json()["paper_id"]

    response = client.get(f"/api/reader/papers/{paper_id}/outline")
    assert response.status_code == 200
    titles = [section["title"] for section in response.json()]
    assert "1 Introduction" in titles


def test_pdf_bytes_are_served_back(client, synthetic_pdf):
    paper_id = upload(client, synthetic_pdf).json()["paper_id"]

    response = client.get(f"/api/reader/papers/{paper_id}/pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content == synthetic_pdf


def test_list_papers_summarises_without_full_text(client, synthetic_pdf):
    upload(client, synthetic_pdf)

    response = client.get("/api/reader/papers")
    assert response.status_code == 200
    [summary] = response.json()
    assert summary["n_sentences"] > 0
    assert "full_text" not in summary


def test_unknown_paper_is_404(client):
    response = client.get(f"/api/reader/papers/{'a' * 64}")
    assert response.status_code == 404


def test_malformed_paper_id_is_422(client):
    response = client.get("/api/reader/papers/not-a-hash")
    assert response.status_code == 422


def test_non_pdf_upload_is_rejected(client):
    response = client.post(
        "/api/reader/papers",
        files={"file": ("notes.txt", b"just text", "text/plain")},
    )
    assert response.status_code == 422


def test_empty_upload_is_rejected(client):
    response = client.post(
        "/api/reader/papers",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert response.status_code == 422


def test_sample_traversal_is_refused(client):
    response = client.post("/api/reader/papers/samples/..%2F..%2Fetc%2Fpasswd")
    assert response.status_code == 404
