import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from fastapi.testclient import TestClient
from main import app, check_rate_limit, MAX_TOKENS

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "rate-limiter"
    assert data["redis"] == "connected"


def test_token_bucket_allows_up_to_max_then_blocks():
    client_id = "test-client-burst"

    for i in range(MAX_TOKENS):
        allowed, reason = check_rate_limit(client_id)
        assert allowed is True, f"request {i+1} should have been allowed"

    allowed, reason = check_rate_limit(client_id)
    assert allowed is False


def test_different_clients_have_independent_buckets():
    allowed_a, _ = check_rate_limit("client-a")
    allowed_b, _ = check_rate_limit("client-b")
    assert allowed_a is True
    assert allowed_b is True