"""Scheduler 通信客户端

Web 进程通过此模块与 scheduler 5001 端口通信。
集中管理 URL、超时、健康检查、降级返回。
"""

import logging

import httpx

logger = logging.getLogger(__name__)

SCHEDULER_URL = "http://127.0.0.1:5001"
DEFAULT_TIMEOUT = 15


def is_scheduler_alive() -> bool:
    """检查 scheduler 向量 API 是否可用"""
    try:
        resp = httpx.get(f"{SCHEDULER_URL}/health", timeout=3)
        data = resp.json()
        return data.get("ok", False) and data.get("model_loaded", False)
    except Exception:
        return False


def scheduler_get(path: str, params: dict | None = None, timeout: int = DEFAULT_TIMEOUT) -> dict | list | None:
    """向 scheduler 发送 GET 请求，失败返回 None"""
    try:
        resp = httpx.get(f"{SCHEDULER_URL}{path}", params=params, timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
        logger.warning("Scheduler GET %s 返回 %d", path, resp.status_code)
        return None
    except httpx.ConnectError:
        logger.warning("Scheduler 不可达: %s", path)
        return None
    except Exception as e:
        logger.error("Scheduler GET %s 失败: %s", path, e)
        return None


def scheduler_post(path: str, json_data: dict | None = None, timeout: int = DEFAULT_TIMEOUT) -> dict | list | None:
    """向 scheduler 发送 POST 请求，失败返回 None"""
    try:
        resp = httpx.post(f"{SCHEDULER_URL}{path}", json=json_data, timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
        logger.warning("Scheduler POST %s 返回 %d", path, resp.status_code)
        return None
    except httpx.ConnectError:
        logger.warning("Scheduler 不可达: %s", path)
        return None
    except Exception as e:
        logger.error("Scheduler POST %s 失败: %s", path, e)
        return None
