"""智能问答 API 端点"""

import uuid

from flask import Blueprint, Response, jsonify, request, stream_with_context

from modules.chat.service import ChatService
from utils.auth import require_auth

chat_bp = Blueprint("chat", __name__, url_prefix="/api/chat")
_chat_service = ChatService()


@chat_bp.route("/sessions", methods=["GET"])
def get_sessions():
    """获取会话列表"""
    sessions = _chat_service.db.get_sessions()
    return jsonify(sessions)


@chat_bp.route("/sessions", methods=["POST"])
@require_auth
def create_session():
    """创建新会话"""
    data = request.json or {}
    session_id = str(uuid.uuid4())
    title = data.get("title", "")
    session = _chat_service.db.create_session(session_id, title)
    return jsonify(session), 201


@chat_bp.route("/sessions/<session_id>", methods=["DELETE"])
@require_auth
def delete_session(session_id):
    """删除会话及其消息"""
    ok = _chat_service.db.delete_session(session_id)
    if ok:
        return jsonify({"ok": True})
    return jsonify({"error": "session not found"}), 404


@chat_bp.route("/sessions/<session_id>/messages", methods=["GET"])
def get_messages(session_id):
    """获取会话历史消息"""
    session = _chat_service.db.get_session(session_id)
    if not session:
        return jsonify({"error": "session not found"}), 404
    messages = _chat_service.db.get_messages(session_id)
    return jsonify(messages)


@chat_bp.route("/sessions/<session_id>/chat", methods=["POST"])
@require_auth
def chat(session_id):
    """发送消息，SSE 流式响应"""
    session = _chat_service.db.get_session(session_id)
    if not session:
        return jsonify({"error": "session not found"}), 404

    data = request.json or {}
    question = data.get("message", "").strip()
    if not question:
        return jsonify({"error": "message is required"}), 400

    def generate():
        try:
            for event in _chat_service.chat(session_id, question):
                yield f"data: {event}\n\n"
        except GeneratorExit:
            pass

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
