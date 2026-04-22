"""监控任务 API 端点 —— 全部鉴权"""

import json

from flask import Blueprint, Response, jsonify, request

from modules.monitor.service import get_monitor_service
from utils.auth import require_auth

monitor_bp = Blueprint("monitor", __name__, url_prefix="/api/monitor")
_monitor_svc = get_monitor_service()


@monitor_bp.route("/tasks", methods=["GET"])
@require_auth
def get_tasks():
    """获取监控任务列表（push_config 脱敏）"""
    tasks = _monitor_svc.get_tasks()
    return jsonify(tasks)


@monitor_bp.route("/tasks", methods=["POST"])
@require_auth
def create_task():
    """创建监控任务"""
    data = request.json or {}
    name = data.get("name", "").strip()
    keywords = data.get("keywords", [])
    if not name or not keywords:
        return jsonify({"error": "name and keywords are required"}), 400

    # 从用户 JWT 获取 owner_id（若有）
    owner_id = None
    try:
        from utils.jwt_auth import get_current_user_id, optional_user_auth
        from flask import g
        owner_id = getattr(g, "current_user_id", None)
    except Exception:
        pass

    task = _monitor_svc.create_task(
        name=name,
        keywords=keywords,
        filters=data.get("filters"),
        schedule=data.get("schedule", "daily_morning"),
        push_config=data.get("push_config", []),
        owner_id=owner_id,
    )
    return jsonify(task), 201


@monitor_bp.route("/tasks/<task_id>", methods=["GET"])
@require_auth
def get_task(task_id):
    """获取任务详情（push_config 脱敏）"""
    task = _monitor_svc.get_task(task_id)
    if not task:
        return jsonify({"error": "task not found"}), 404
    return jsonify(task)


@monitor_bp.route("/tasks/<task_id>", methods=["PUT"])
@require_auth
def update_task(task_id):
    """部分更新任务（只允许修改用户字段）"""
    data = request.json or {}
    # 只允许用户修改 _USER_FIELDS，过滤掉内部字段如 last_run_at
    from modules.monitor.db import MonitorDB
    user_data = {k: v for k, v in data.items() if k in MonitorDB._USER_FIELDS}
    if not user_data:
        return jsonify({"error": "no valid fields to update"}), 400

    result = _monitor_svc.update_task(task_id, **user_data)
    if not result:
        return jsonify({"error": "task not found"}), 404
    return jsonify(result)


@monitor_bp.route("/tasks/<task_id>", methods=["DELETE"])
@require_auth
def delete_task(task_id):
    """删除监控任务"""
    ok = _monitor_svc.delete_task(task_id)
    if ok:
        return jsonify({"ok": True})
    return jsonify({"error": "task not found"}), 404


@monitor_bp.route("/tasks/<task_id>/run", methods=["POST"])
@require_auth
def run_task(task_id):
    """手动触发监控任务执行（后台线程，立即返回）"""
    if _monitor_svc.is_task_running(task_id):
        return jsonify({"status": "skipped", "reason": "任务正在执行中"}), 409
    import threading
    t = threading.Thread(target=_monitor_svc.run_task, args=(task_id,), daemon=True)
    t.start()
    return jsonify({"status": "started"})


@monitor_bp.route("/tasks/<task_id>/logs", methods=["GET"])
@require_auth
def get_push_logs(task_id):
    """获取推送日志"""
    logs = _monitor_svc.get_push_logs(task_id)
    return jsonify(logs)


@monitor_bp.route("/test-push", methods=["POST"])
@require_auth
def test_push():
    """测试推送渠道"""
    data = request.json or {}
    push_config = data.get("push_config", [])
    if not push_config:
        return jsonify({"error": "push_config is required"}), 400

    result = _monitor_svc.test_push(push_config)
    return jsonify(result)
