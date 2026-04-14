"""wcfLink HTTP API 客户端封装"""

import logging

import httpx

logger = logging.getLogger(__name__)


def _get_base_url() -> str:
    from utils.config import load_config
    config = load_config()
    return config.get("wcf", {}).get("url", "http://127.0.0.1:17890").rstrip("/")


def login_start(base_url: str = "") -> dict:
    """发起微信扫码登录，返回 {session_id, qr_code_url, ...}。"""
    url = (base_url or _get_base_url()) + "/api/accounts/login/start"
    resp = httpx.post(url, json={}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def login_status(session_id: str, base_url: str = "") -> dict:
    """轮询登录状态。"""
    url = (base_url or _get_base_url()) + "/api/accounts/login/status"
    resp = httpx.get(url, params={"session_id": session_id}, timeout=10)
    resp.raise_for_status()
    return resp.json()


def login_qr_png(session_id: str, base_url: str = "") -> bytes:
    """获取二维码 PNG 二进制。"""
    url = (base_url or _get_base_url()) + "/api/accounts/login/qr"
    resp = httpx.get(url, params={"session_id": session_id}, timeout=10)
    resp.raise_for_status()
    return resp.content


def list_accounts(base_url: str = "") -> list:
    """获取已登录账号列表。"""
    url = (base_url or _get_base_url()) + "/api/accounts"
    resp = httpx.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data.get("items", []) if isinstance(data, dict) else data


def list_events(after_id: int = 0, limit: int = 100, base_url: str = "") -> list:
    """拉取事件列表。"""
    url = (base_url or _get_base_url()) + "/api/events"
    resp = httpx.get(url, params={"after_id": after_id, "limit": limit}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data.get("items", []) if isinstance(data, dict) else data


def send_text(account_id: str, to_user_id: str, text: str,
              context_token: str = "", base_url: str = "") -> dict:
    """发送文本消息。"""
    url = (base_url or _get_base_url()) + "/api/messages/send-text"
    payload = {
        "account_id": account_id,
        "to_user_id": to_user_id,
        "text": text,
    }
    if context_token:
        payload["context_token"] = context_token
    resp = httpx.post(url, json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()


def health_check(base_url: str = "") -> bool:
    """探活：调用 wcfLink GET /health/live。"""
    url = (base_url or _get_base_url()) + "/health/live"
    try:
        resp = httpx.get(url, timeout=5)
        return resp.status_code == 200
    except Exception:
        return False
