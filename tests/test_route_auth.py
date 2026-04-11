"""验证所有写接口都需要鉴权"""
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


WRITE_ENDPOINTS = [
    ("/api/news/fetch", "POST"),
    ("/api/hotlist/fetch", "POST"),
    ("/api/rss/feeds", "POST"),
    ("/api/rss/fetch", "POST"),
    ("/api/rss/discover", "POST"),
    ("/api/rss/discover/custom", "POST"),
    ("/api/topic/generate", "POST"),
    ("/api/creator/framework/create", "POST"),
    ("/api/chat/sessions", "POST"),
]


@pytest.mark.parametrize("path,method", WRITE_ENDPOINTS)
def test_write_endpoints_require_auth(client, path, method):
    """无 Token 时写接口应返回 401"""
    fn = getattr(client, method.lower())
    resp = fn(path, json={})
    assert resp.status_code == 401, f"{method} {path} 未拦截无 Token 请求"


@pytest.mark.parametrize("path,method", WRITE_ENDPOINTS)
def test_write_endpoints_accept_valid_token(client, path, method):
    """有效 Token 时写接口不应返回 401"""
    fn = getattr(client, method.lower())
    resp = fn(path, json={}, headers={"Authorization": "Bearer test-token-123"})
    assert resp.status_code != 401, f"{method} {path} 有效 Token 被拒绝"
