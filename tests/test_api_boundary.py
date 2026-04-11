"""验证 API 边界行为：未知 /api/* 路径返回 JSON 404"""
import os
import pytest

os.environ["ADMIN_TOKEN"] = "test-token-123"
os.environ["FLASK_ENV"] = "development"

from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_unknown_api_returns_json_404(client):
    """未知 /api/* 路径应返回 JSON 格式的 404"""
    resp = client.get("/api/nonexistent/endpoint")
    assert resp.status_code == 404
    assert resp.content_type.startswith("application/json")
    data = resp.get_json()
    assert "error" in data


def test_unknown_api_post_returns_json_404(client):
    """未知 /api/* POST 路径也应返回 JSON 404"""
    resp = client.post("/api/nonexistent/endpoint", json={})
    assert resp.status_code == 404
    assert resp.content_type.startswith("application/json")


def test_known_api_still_works(client):
    """已知 /api/* 路由应正常响应"""
    resp = client.get("/api/status")
    assert resp.status_code == 200
