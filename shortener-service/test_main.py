import sys
import os

# Make sure this directory is importable regardless of where pytest is run from
sys.path.insert(0, os.path.dirname(__file__))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "shortener"}


def test_shorten_url_creates_short_code():
    response = client.post("/shorten", json={"url": "https://example.com"})
    assert response.status_code == 200
    data = response.json()
    assert len(data["short_code"]) == 7
    assert data["short_code"] in data["short_url"]
    assert data["long_url"] == "https://example.com/"


def test_shorten_url_rejects_invalid_url():
    response = client.post("/shorten", json={"url": "not-a-valid-url"})
    assert response.status_code == 422


def test_redirect_to_long_url():
    create_response = client.post("/shorten", json={"url": "https://www.wikipedia.org"})
    short_code = create_response.json()["short_code"]

    redirect_response = client.get(f"/{short_code}", follow_redirects=False)
    assert redirect_response.status_code == 307
    assert redirect_response.headers["location"] == "https://www.wikipedia.org/"


def test_redirect_not_found_for_unknown_code():
    response = client.get("/thisdoesnotexist")
    assert response.status_code == 404