"""智能问答 API 端点"""

import uuid

from flask import Blueprint, Response, jsonify, request, stream_with_context

from modules.chat.service import ChatService
from utils.auth import require_auth

chat_bp = Blueprint("chat", __name__, url_prefix="/api/chat")
_chat_service = ChatService()

# Agent 服务惰性初始化单例（避免 import 时加载 langchain）
_agent_service = None


def _get_agent_service():
    global _agent_service
    if _agent_service is None:
        from modules.agent.service import AgentService
        _agent_service = AgentService()
    return _agent_service


@chat_bp.route("/sessions", methods=["GET"])
def get_sessions():
    """获取会话列表"""
    mode = request.args.get("mode")
    sessions = _chat_service.db.get_sessions(mode=mode)
    return jsonify(sessions)


@chat_bp.route("/sessions", methods=["POST"])
@require_auth
def create_session():
    """创建新会话"""
    data = request.json or {}
    session_id = str(uuid.uuid4())
    title = data.get("title", "")
    mode = data.get("mode", "simple")
    session = _chat_service.db.create_session(session_id, title, mode=mode)
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

    # 根据 session mode 选择服务
    if session.get("mode") == "agent":
        stream_fn = _get_agent_service().chat
    else:
        stream_fn = _chat_service.chat

    def generate():
        try:
            for event in stream_fn(session_id, question):
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
