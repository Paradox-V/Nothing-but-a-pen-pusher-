"""JWT 用户鉴权工具

生成/验证 JWT，提供用户鉴权装饰器。
密钥从 JWT_SECRET 环境变量读取，未配置时生成随机密钥（重启失效，仅适合开发环境）。
"""

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from flask import g, jsonify, request

logger = logging.getLogger(__name__)

_RANDOM_SECRET = None


def _get_secret() -> str:
    """获取 JWT 密钥，优先读取环境变量 JWT_SECRET。"""
    global _RANDOM_SECRET
    secret = os.environ.get("JWT_SECRET", "")
    if secret:
        return secret
    # 未配置时使用进程级随机密钥（重启后所有 token 失效）
    if _RANDOM_SECRET is None:
        _RANDOM_SECRET = secrets.token_hex(32)
        logger.warning(
            "JWT_SECRET 未配置，使用随机密钥。重启后所有用户 Token 将失效，"
            "生产环境请务必设置 JWT_SECRET 环境变量。"
        )
    return _RANDOM_SECRET


def generate_token(user_id: str, jti: str, role: str = "user",
                   expires_in_hours: int = 72) -> str:
    """生成用户 JWT。

    Args:
        user_id: 用户 ID（存入 sub 字段）
        jti: Session ID（用于吊销）
        role: 用户角色
        expires_in_hours: 过期时间（小时）

    Returns:
        JWT 字符串
    """
    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub": user_id,
        "jti": jti,
        "role": role,
        "iat": now,
        "exp": now + timedelta(hours=expires_in_hours),
    }
    return jwt.encode(payload, _get_secret(), algorithm="HS256")


def decode_token(token: str) -> dict:
    """解码并验证 JWT。

    Returns:
        payload 字典

    Raises:
        jwt.ExpiredSignatureError: Token 已过期
        jwt.InvalidTokenError: Token 无效
    """
    return jwt.decode(token, _get_secret(), algorithms=["HS256"])


def _extract_bearer_token() -> str | None:
    """从请求 Header 中提取 Bearer Token。"""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None


def require_user_auth(f):
    """用户鉴权装饰器：验证 JWT，注入 g.current_user_id 和 g.current_user_role。

    失败返回 401。
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        token = _extract_bearer_token()
        if not token:
            return jsonify({"error": "未提供认证 Token"}), 401

        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token 已过期，请重新登录"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "无效的 Token"}), 401

        # 验证 session 是否被吊销
        try:
            from modules.account.db import AccountDB
            db = AccountDB()
            if not db.is_session_valid(payload["jti"]):
                return jsonify({"error": "Token 已失效，请重新登录"}), 401
        except Exception:
            pass  # DB 不可用时跳过吊销检查

        g.current_user_id = payload["sub"]
        g.current_user_role = payload.get("role", "user")
        g.current_user_jti = payload["jti"]
        return f(*args, **kwargs)
    return decorated


def optional_user_auth(f):
    """可选用户鉴权装饰器：有 Token 时注入用户信息，无 Token 时继续执行。

    g.current_user_id 为 None 表示未登录。
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        g.current_user_id = None
        g.current_user_role = None
        g.current_user_jti = None

        token = _extract_bearer_token()
        if token:
            try:
                payload = decode_token(token)
                # 验证 session 是否被吊销
                try:
                    from modules.account.db import AccountDB
                    db = AccountDB()
                    if db.is_session_valid(payload["jti"]):
                        g.current_user_id = payload["sub"]
                        g.current_user_role = payload.get("role", "user")
                        g.current_user_jti = payload["jti"]
                except Exception:
                    g.current_user_id = payload["sub"]
                    g.current_user_role = payload.get("role", "user")
                    g.current_user_jti = payload["jti"]
            except jwt.InvalidTokenError:
                pass  # 无效 token，视为未登录
        return f(*args, **kwargs)
    return decorated


def get_current_user_id() -> str | None:
    """获取当前请求的用户 ID（需在鉴权装饰器之后调用）。"""
    return getattr(g, "current_user_id", None)


def get_current_user_role() -> str | None:
    """获取当前请求的用户角色。"""
    return getattr(g, "current_user_role", None)
