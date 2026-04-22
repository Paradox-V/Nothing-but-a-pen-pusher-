"""管理员 Dashboard API

Blueprint 前缀：/api/admin
全部端点需要 ADMIN_TOKEN 鉴权。

端点：
  GET  /api/admin/overview        — 系统概览
  GET  /api/admin/users           — 用户列表
  PUT  /api/admin/users/<id>      — 更新用户（启用/禁用/角色）
  DELETE /api/admin/users/<id>    — 删除用户
  GET  /api/admin/tasks           — 监控任务列表（跨用户）
  GET  /api/admin/push-logs       — 全局推送日志
  GET  /api/admin/wcf-bindings    — 微信绑定列表
  GET  /api/admin/rss-feeds       — RSS 源列表
  POST /api/admin/broadcast       — 向所有微信联系人广播消息
  GET  /api/admin/invite          — 生成邀请码（与 account 路由共用）
"""

import logging

from flask import Blueprint, jsonify, request

from utils.auth import require_auth

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")

MAX_PAGE_SIZE = 200
VALID_ROLES = {"user", "admin"}
MAX_BROADCAST_LEN = 2000


@admin_bp.route("/overview", methods=["GET"])
@require_auth
def overview():
    """系统概览：各模块统计信息 + 健康状态。"""
    data = {}

    # 用户统计
    try:
        from modules.account.db import AccountDB
        adb = AccountDB()
        data["users"] = {
            "total": adb.get_user_count(),
        }
    except Exception:
        data["users"] = {"total": 0}

    # 监控任务统计
    try:
        from modules.monitor.db import MonitorDB
        mdb = MonitorDB()
        all_tasks = mdb.get_tasks()
        active_tasks = [t for t in all_tasks if t.get("is_active")]
        push_stats = mdb.get_today_push_stats()
        data["monitor"] = {
            "total_tasks": len(all_tasks),
            "active_tasks": len(active_tasks),
            "today_push_success": push_stats.get("success", 0),
            "today_push_fail": push_stats.get("fail", 0),
        }
    except Exception:
        data["monitor"] = {"total_tasks": 0, "active_tasks": 0}

    # RSS 统计
    try:
        from modules.rss.db import RSSDB
        rdb = RSSDB()
        feeds = rdb.get_feeds(enabled_only=False)
        enabled_feeds = [f for f in feeds if f.get("enabled")]
        data["rss"] = {
            "total_feeds": len(feeds),
            "enabled_feeds": len(enabled_feeds),
        }
    except Exception:
        data["rss"] = {"total_feeds": 0, "enabled_feeds": 0}

    # 新闻统计
    try:
        from modules.news.db import NewsDB
        ndb = NewsDB()
        data["news"] = {"total": ndb.get_count()}
    except Exception:
        data["news"] = {"total": 0}

    # 微信绑定统计
    try:
        from modules.wcf.db import WCFDB
        wdb = WCFDB()
        bindings = wdb.list_bindings()
        enabled_bindings = [b for b in bindings if b.get("enabled")]
        data["wcf"] = {
            "bindings": len(bindings),
            "enabled_bindings": len(enabled_bindings),
        }
    except Exception:
        data["wcf"] = {"bindings": 0, "enabled_bindings": 0}

    # Scheduler 状态
    try:
        from utils.scheduler_client import is_scheduler_alive
        data["scheduler"] = {"alive": is_scheduler_alive()}
    except Exception:
        data["scheduler"] = {"alive": False}

    # AI 状态
    try:
        from ai import AI_AVAILABLE
        data["ai"] = {"available": AI_AVAILABLE}
    except Exception:
        data["ai"] = {"available": False}

    return jsonify(data)


# ── 用户管理 ──────────────────────────────────────────────────

@admin_bp.route("/users", methods=["GET"])
@require_auth
def list_users():
    """用户列表（分页）。"""
    page = request.args.get("page", 1, type=int)
    page_size = min(request.args.get("page_size", 20, type=int), MAX_PAGE_SIZE)
    try:
        from modules.account.db import AccountDB
        db = AccountDB()
        result = db.list_users(page=page, page_size=page_size)
        return jsonify(result)
    except Exception:
        logger.exception("list_users failed")
        return jsonify({"error": "获取用户列表失败"}), 500


@admin_bp.route("/users/<user_id>", methods=["PUT"])
@require_auth
def update_user(user_id: str):
    """更新用户（启用/禁用/角色/邮箱）。"""
    data = request.get_json(silent=True) or {}
    allowed = {"enabled", "role", "email"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"error": "没有有效的更新字段"}), 400
    if "role" in updates and updates["role"] not in VALID_ROLES:
        return jsonify({"error": f"无效角色，允许值: {VALID_ROLES}"}), 400

    try:
        from modules.account.db import AccountDB
        db = AccountDB()
        user = db.update_user(user_id, **updates)
        if not user:
            return jsonify({"error": "用户不存在"}), 404
        return jsonify(user)
    except Exception:
        logger.exception("update_user failed: %s", user_id)
        return jsonify({"error": "更新用户失败"}), 500


@admin_bp.route("/users/<user_id>", methods=["DELETE"])
@require_auth
def delete_user(user_id: str):
    """删除用户。"""
    try:
        from modules.account.db import AccountDB
        db = AccountDB()
        ok = db.delete_user(user_id)
        if not ok:
            return jsonify({"error": "用户不存在"}), 404
        return jsonify({"ok": True})
    except Exception:
        logger.exception("delete_user failed: %s", user_id)
        return jsonify({"error": "删除用户失败"}), 500


# ── 任务管理 ──────────────────────────────────────────────────

@admin_bp.route("/tasks", methods=["GET"])
@require_auth
def list_tasks():
    """全局监控任务列表（跨用户）。"""
    page = request.args.get("page", 1, type=int)
    page_size = min(request.args.get("page_size", 20, type=int), MAX_PAGE_SIZE)
    owner_id = request.args.get("owner_id")

    try:
        from modules.monitor.db import MonitorDB
        db = MonitorDB()
        tasks = db.get_tasks()
        if owner_id:
            tasks = [t for t in tasks if t.get("owner_id") == owner_id]
        total = len(tasks)
        offset = (page - 1) * page_size
        items = tasks[offset: offset + page_size]
        return jsonify({"items": items, "total": total, "page": page, "page_size": page_size})
    except Exception:
        logger.exception("list_tasks failed")
        return jsonify({"error": "获取任务列表失败"}), 500


@admin_bp.route("/push-logs", methods=["GET"])
@require_auth
def get_push_logs():
    """全局推送日志（分页、可按 task_id/status 过滤）。"""
    page = request.args.get("page", 1, type=int)
    page_size = min(request.args.get("page_size", 50, type=int), MAX_PAGE_SIZE)
    task_id = request.args.get("task_id")
    status = request.args.get("status")

    try:
        from modules.monitor.db import MonitorDB
        db = MonitorDB()
        result = db.get_all_push_logs(
            limit=page_size, page=page,
            task_id=task_id or None,
            status=status or None,
        )
        return jsonify(result)
    except Exception:
        logger.exception("get_push_logs failed")
        return jsonify({"error": "获取推送日志失败"}), 500


@admin_bp.route("/wcf-bindings", methods=["GET"])
@require_auth
def list_wcf_bindings():
    """微信联系人绑定列表。"""
    try:
        from modules.wcf.db import WCFDB
        db = WCFDB()
        bindings = db.list_bindings()
        return jsonify(bindings)
    except Exception:
        logger.exception("list_wcf_bindings failed")
        return jsonify({"error": "获取微信绑定列表失败"}), 500


@admin_bp.route("/broadcast", methods=["POST"])
@require_auth
def broadcast():
    """向所有已启用的微信联系人广播消息。"""
    data = request.get_json(silent=True) or {}
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "消息内容不能为空"}), 400
    if len(message) > MAX_BROADCAST_LEN:
        return jsonify({"error": f"消息长度不能超过 {MAX_BROADCAST_LEN} 字符"}), 400

    try:
        from modules.wcf.db import WCFDB
        from modules.wcf import client
        db = WCFDB()
        bindings = db.list_bindings(enabled_only=True)
        success = 0
        failed = 0
        for b in bindings:
            try:
                client.send_text(
                    b["account_id"], b["user_id"], message,
                    context_token=b.get("context_token", "")
                )
                success += 1
            except Exception as e:
                logger.warning("广播失败 %s: %s", b["user_id"], e)
                failed += 1
        return jsonify({"success": success, "failed": failed, "total": len(bindings)})
    except Exception:
        logger.exception("broadcast failed")
        return jsonify({"error": "广播发送失败"}), 500


@admin_bp.route("/rss-feeds", methods=["GET"])
@require_auth
def list_rss_feeds():
    """全局 RSS 源列表（跨用户）。"""
    page = request.args.get("page", 1, type=int)
    page_size = min(request.args.get("page_size", 50, type=int), MAX_PAGE_SIZE)

    try:
        from modules.rss.db import RSSDB
        db = RSSDB()
        feeds = db.get_feeds(enabled_only=False)
        total = len(feeds)
        offset = (page - 1) * page_size
        items = feeds[offset: offset + page_size]
        return jsonify({"items": items, "total": total, "page": page, "page_size": page_size})
    except Exception:
        logger.exception("list_rss_feeds failed")
        return jsonify({"error": "获取 RSS 源列表失败"}), 500


@admin_bp.route("/invite", methods=["POST"])
@require_auth
def create_invite():
    """生成邀请码（有效期 24 小时）。"""
    try:
        from modules.account.db import AccountDB
        db = AccountDB()
        code = db.create_invite_code(created_by="admin")
        return jsonify({"invite_code": code, "expires_in_hours": 24})
    except Exception:
        logger.exception("create_invite failed")
        return jsonify({"error": "生成邀请码失败"}), 500
