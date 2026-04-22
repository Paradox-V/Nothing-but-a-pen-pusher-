"""账号管理 API

Blueprint 前缀：/api/account

端点：
  POST /api/account/register    — 注册（需 REGISTRATION_ENABLED=true 或邀请码）
  POST /api/account/login       — 登录
  POST /api/account/logout      — 登出（吊销 Token）
  GET  /api/account/me          — 获取个人信息
  PUT  /api/account/me          — 更新个人信息（邮箱/密码）
  POST /api/account/invite      — 生成邀请码（管理员 Token）
"""

import os
import re
import logging

from flask import Blueprint, g, jsonify, request

from modules.account.db import AccountDB
from utils.jwt_auth import generate_token, require_user_auth

logger = logging.getLogger(__name__)

account_bp = Blueprint("account", __name__, url_prefix="/api/account")

_db = AccountDB()

# 密码强度：至少 8 位，包含字母和数字
_PASSWORD_RE = re.compile(r"^(?=.*[a-zA-Z])(?=.*\d).{8,}$")


def _build_token_response(user: dict) -> dict:
    """生成登录成功的 token 响应。"""
    jti = _db.create_session(user["id"])
    token = generate_token(user["id"], jti, role=user.get("role", "user"))
    return {
        "token": token,
        "expires_in": 72 * 3600,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user.get("email", ""),
            "role": user.get("role", "user"),
        },
    }


@account_bp.route("/register", methods=["POST"])
def register():
    """注册新账号。

    控制策略（优先级从高到低）：
    1. REGISTRATION_ENABLED=true → 开放注册
    2. 请求体携带有效 invite_code → 邀请注册
    3. 否则返回 403
    """
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    email = data.get("email", "").strip()
    invite_code = data.get("invite_code", "").strip()

    # 参数校验
    if not username or not password:
        return jsonify({"error": "用户名和密码不能为空"}), 400
    if not re.match(r"^[a-zA-Z0-9_\u4e00-\u9fff]{2,32}$", username):
        return jsonify({"error": "用户名格式不正确（2-32位字母数字下划线汉字）"}), 400
    if not _PASSWORD_RE.match(password):
        return jsonify({"error": "密码至少 8 位，需包含字母和数字"}), 400

    # 注册权限校验
    registration_enabled = os.environ.get("REGISTRATION_ENABLED", "").lower() == "true"
    if not registration_enabled:
        if not invite_code:
            return jsonify({"error": "注册未开放，请使用邀请码"}), 403
        if not _db.is_invite_code_valid(invite_code):
            return jsonify({"error": "邀请码无效或已过期"}), 403

    try:
        user = _db.create_user(username, password, email=email)
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    except Exception:
        logger.exception("create_user failed")
        return jsonify({"error": "注册失败，请稍后重试"}), 500

    # 使用邀请码
    if invite_code:
        _db.use_invite_code(invite_code, user["id"])

    # 注册后自动登录
    _db.update_user(user["id"], last_login_at=_now())
    return jsonify(_build_token_response(user)), 201


@account_bp.route("/login", methods=["POST"])
def login():
    """用户登录，返回 JWT Token。"""
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({"error": "用户名和密码不能为空"}), 400

    user = _db.verify_password(username, password)
    if not user:
        return jsonify({"error": "用户名或密码错误"}), 401

    if not user.get("enabled"):
        return jsonify({"error": "账号已被禁用，请联系管理员"}), 403

    _db.update_user(user["id"], last_login_at=_now())
    return jsonify(_build_token_response(user))


@account_bp.route("/logout", methods=["POST"])
@require_user_auth
def logout():
    """登出，吊销当前 Token。"""
    jti = getattr(g, "current_user_jti", None)
    if jti:
        _db.revoke_session(jti)
    return jsonify({"ok": True})


@account_bp.route("/me", methods=["GET"])
@require_user_auth
def get_me():
    """获取个人信息。"""
    user = _db.get_user_by_id(g.current_user_id)
    if not user:
        return jsonify({"error": "用户不存在"}), 404
    return jsonify(user)


@account_bp.route("/me", methods=["PUT"])
@require_user_auth
def update_me():
    """更新个人信息（邮箱/密码）。"""
    data = request.get_json(silent=True) or {}
    updates = {}

    if "email" in data:
        updates["email"] = data["email"].strip()

    if "password" in data:
        # 修改密码需提供旧密码
        old_password = data.get("old_password", "")
        if not old_password:
            return jsonify({"error": "修改密码需提供旧密码"}), 400
        user = _db.get_user_by_id(g.current_user_id)
        if not user:
            return jsonify({"error": "用户不存在"}), 404
        # 验证旧密码
        verified = _db.verify_password(user["username"], old_password)
        if not verified:
            return jsonify({"error": "旧密码错误"}), 400
        new_password = data["password"]
        if not _PASSWORD_RE.match(new_password):
            return jsonify({"error": "新密码至少 8 位，需包含字母和数字"}), 400
        updates["password"] = new_password

    if not updates:
        return jsonify({"error": "没有有效的更新字段"}), 400

    user = _db.update_user(g.current_user_id, **updates)
    if not user:
        return jsonify({"error": "更新失败"}), 500
    return jsonify(user)


@account_bp.route("/invite", methods=["POST"])
def create_invite():
    """生成邀请码（需管理员 ADMIN_TOKEN）。"""
    import secrets
    admin_token = os.environ.get("ADMIN_TOKEN", "")
    auth_header = request.headers.get("Authorization", "")
    client_token = auth_header[7:] if auth_header.startswith("Bearer ") else ""

    if not admin_token or not secrets.compare_digest(client_token, admin_token):
        return jsonify({"error": "需要管理员权限"}), 401

    code = _db.create_invite_code(created_by="admin")
    return jsonify({"invite_code": code, "expires_in_hours": 24})


def _now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
