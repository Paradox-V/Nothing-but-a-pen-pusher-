"""WCF 微信连接管理 API —— 全部鉴权"""

from flask import Blueprint, Response, jsonify, request, send_file
from io import BytesIO

from modules.wcf import client
from modules.wcf.db import WCFDB
from utils.auth import require_auth

wcf_bp = Blueprint("wcf", __name__, url_prefix="/api/wcf")
_db = WCFDB()


@wcf_bp.route("/health", methods=["GET"])
@require_auth
def health():
    """探活：代理 wcfLink GET /health/live。"""
    ok = client.health_check()
    if ok:
        return jsonify({"ok": True})
    return jsonify({"ok": False}), 503


@wcf_bp.route("/login/start", methods=["POST"])
@require_auth
def login_start():
    """发起扫码登录。"""
    try:
        data = client.login_start()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@wcf_bp.route("/login/status", methods=["GET"])
@require_auth
def login_status():
    """轮询登录状态。"""
    session_id = request.args.get("session_id", "").strip()
    if not session_id:
        return jsonify({"error": "session_id is required"}), 400
    try:
        data = client.login_status(session_id)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@wcf_bp.route("/login/qr", methods=["GET"])
@require_auth
def login_qr():
    """获取二维码 PNG 图片。"""
    session_id = request.args.get("session_id", "").strip()
    if not session_id:
        return jsonify({"error": "session_id is required"}), 400
    try:
        png_bytes = client.login_qr_png(session_id)
        return send_file(BytesIO(png_bytes), mimetype="image/png")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@wcf_bp.route("/accounts", methods=["GET"])
@require_auth
def list_accounts():
    """已登录账号列表。"""
    try:
        accounts = client.list_accounts()
        return jsonify({"items": accounts})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@wcf_bp.route("/bindings", methods=["GET"])
@require_auth
def list_bindings():
    """联系人绑定列表。"""
    bindings = _db.list_bindings()
    # 附加每个绑定的任务列表
    for b in bindings:
        b["task_ids"] = _db.get_binding_tasks(b["id"])
    return jsonify(bindings)


@wcf_bp.route("/bindings/<binding_id>", methods=["PUT"])
@require_auth
def update_binding(binding_id: str):
    """更新联系人（启用/禁用、修改 display_name）。"""
    data = request.json or {}
    binding = _db.get_binding(binding_id)
    if not binding:
        return jsonify({"error": "binding not found"}), 404

    if "enabled" in data:
        _db.set_binding_enabled(binding_id, bool(data["enabled"]))
    if "display_name" in data:
        _db.update_binding_display_name(binding_id, data["display_name"])

    updated = _db.get_binding(binding_id)
    updated["task_ids"] = _db.get_binding_tasks(binding_id)
    return jsonify(updated)


@wcf_bp.route("/bindings/<binding_id>/tasks", methods=["POST"])
@require_auth
def bind_task(binding_id: str):
    """绑定监控任务到联系人。"""
    data = request.json or {}
    task_id = data.get("task_id", "").strip()
    if not task_id:
        return jsonify({"error": "task_id is required"}), 400
    binding = _db.get_binding(binding_id)
    if not binding:
        return jsonify({"error": "binding not found"}), 404
    _db.bind_task(binding_id, task_id)
    return jsonify({"ok": True})


@wcf_bp.route("/bindings/<binding_id>/tasks/<task_id>", methods=["DELETE"])
@require_auth
def unbind_task(binding_id: str, task_id: str):
    """解绑监控任务。"""
    _db.unbind_task(binding_id, task_id)
    return jsonify({"ok": True})
