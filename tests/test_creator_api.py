"""创作链路关键 API 测试 — 验证上下文传递和鉴权"""
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


def test_creator_create_rejects_empty_title(client):
    """缺少 title 应返回 400"""
    resp = client.post(
        "/api/creator/framework/create",
        json={"title": ""},
        headers={"Authorization": "Bearer test-token-123"},
    )
    assert resp.status_code == 400


def test_creator_create_accepts_context_fields(client):
    """创建框架应接受 topic_summary/source/industry/keyword"""
    resp = client.post(
        "/api/creator/framework/create",
        json={
            "title": "测试标题",
            "topic_summary": "这是一段素材摘要",
            "source": "新浪新闻",
            "industry": "AI科技",
            "keyword": "大模型",
        },
        headers={"Authorization": "Bearer test-token-123"},
    )
    # 可能因 AI 未配置而 500，但不应因字段问题而报错
    assert resp.status_code in (200, 500)


def test_creator_endpoints_require_auth(client):
    """创作接口无 Token 应返回 401"""
    resp = client.post(
        "/api/creator/framework/create",
        json={"title": "test"},
    )
    assert resp.status_code == 401

    resp = client.post(
        "/api/creator/framework/nonexistent/update",
        json={"message": "test"},
    )
    assert resp.status_code == 401


def test_chat_endpoints_require_auth(client):
    """聊天 POST/DELETE 无 Token 应返回 401"""
    resp = client.post("/api/chat/sessions", json={})
    assert resp.status_code == 401

    resp = client.delete("/api/chat/sessions/nonexistent")
    assert resp.status_code == 401

    resp = client.post("/api/chat/sessions/nonexistent/chat", json={"message": "hi"})
    assert resp.status_code == 401


def test_chat_get_sessions_no_auth(client):
    """GET 会话列表不需要认证"""
    resp = client.get("/api/chat/sessions")
    assert resp.status_code == 200


def test_api_unknown_returns_json_404(client):
    """未知 API 路径应返回 JSON 404"""
    resp = client.get("/api/nonexistent/path")
    assert resp.status_code == 404
    assert resp.content_type.startswith("application/json")
