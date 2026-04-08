"""
文案创作模块 - Flask Blueprint 路由
"""

import logging

from flask import Blueprint, jsonify, request

from modules.creator.framework import (
    FrameworkStatus,
    create_framework,
    confirm_framework,
    get_framework,
    store_framework,
    update_framework,
)
from modules.creator.article import start_article_generation, get_task_status

logger = logging.getLogger(__name__)

creator_bp = Blueprint("creator", __name__)


@creator_bp.route("/api/creator/framework/create", methods=["POST"])
def api_framework_create():
    """
    创建文案框架。

    请求体: {"title": "...", "requirements": "...", "industry": "...", "keyword": "..."}
    """
    data = request.get_json(force=True)
    title = data.get("title", "")
    if not title:
        return jsonify({"error": "请提供标题"}), 400

    try:
        fw = create_framework(
            title=title,
            requirements=data.get("requirements", ""),
            industry=data.get("industry", ""),
            keyword=data.get("keyword", ""),
        )
        return jsonify(fw.to_dict())
    except Exception as e:
        logger.error("创建框架失败: %s", e)
        return jsonify({"error": str(e)}), 500


@creator_bp.route("/api/creator/framework/<fw_id>")
def api_framework_get(fw_id: str):
    """获取框架详情"""
    fw = get_framework(fw_id)
    if not fw:
        return jsonify({"error": "框架不存在"}), 404
    return jsonify(fw.to_dict())


@creator_bp.route("/api/creator/framework/<fw_id>/update", methods=["POST"])
def api_framework_update(fw_id: str):
    """
    对话调整框架。

    请求体: {"message": "...", "regenerate": false}
    """
    fw = get_framework(fw_id)
    if not fw:
        return jsonify({"error": "框架不存在"}), 404

    data = request.get_json(force=True)
    message = data.get("message", "")
    regenerate = data.get("regenerate", False)

    if not message:
        return jsonify({"error": "请输入反馈内容"}), 400

    try:
        fw = update_framework(fw, message, regenerate)
        return jsonify(fw.to_dict())
    except Exception as e:
        logger.error("更新框架失败: %s", e)
        return jsonify({"error": str(e)}), 500


@creator_bp.route("/api/creator/framework/<fw_id>/save", methods=["POST"])
def api_framework_save(fw_id: str):
    """直接保存用户手动编辑的框架内容"""
    fw = get_framework(fw_id)
    if not fw:
        return jsonify({"error": "框架不存在"}), 404

    data = request.get_json(force=True)
    if data.get("article_structure"):
        fw.article_structure = data["article_structure"]
    if data.get("writing_approach"):
        fw.writing_approach = data["writing_approach"]
    fw.chat_history.append({"role": "user", "content": "（手动编辑了框架内容）"})
    fw.chat_history.append({"role": "assistant", "content": "已保存您的编辑。"})
    store_framework(fw)
    return jsonify(fw.to_dict())


@creator_bp.route("/api/creator/framework/<fw_id>/confirm", methods=["POST"])
def api_framework_confirm(fw_id: str):
    """确认框架"""
    fw = get_framework(fw_id)
    if not fw:
        return jsonify({"error": "框架不存在"}), 404

    fw = confirm_framework(fw)
    return jsonify(fw.to_dict())


@creator_bp.route("/api/creator/framework/<fw_id>/generate", methods=["POST"])
def api_article_generate(fw_id: str):
    """
    根据框架生成文章 + 配图。

    请求体: {"image_count": 3}
    返回: {"task_id": "..."}
    """
    fw = get_framework(fw_id)
    if not fw:
        return jsonify({"error": "框架不存在"}), 404

    data = request.get_json(force=True) if request.is_json else {}
    image_count = min(data.get("image_count", 0), 5)

    try:
        task_id = start_article_generation(fw_id, image_count)
        return jsonify({"task_id": task_id})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error("启动生成失败: %s", e)
        return jsonify({"error": str(e)}), 500


@creator_bp.route("/api/creator/task/<task_id>/status")
def api_task_status(task_id: str):
    """轮询任务状态"""
    task = get_task_status(task_id)
    if not task:
        return jsonify({"error": "任务不存在"}), 404
    return jsonify(task)


@creator_bp.route("/api/creator/task/<task_id>/result")
def api_task_result(task_id: str):
    """获取任务结果（含完整文章和图片）"""
    task = get_task_status(task_id)
    if not task:
        return jsonify({"error": "任务不存在"}), 404
    if task["status"] != "completed":
        return jsonify({"error": "任务未完成", "status": task["status"]}), 400

    # 返回完整结果，包括完整文章
    fw = get_framework(task["result"]["framework_id"])
    result = task["result"].copy()
    if fw:
        result["article"] = fw.final_article
        result["images"] = fw.images
        result["framework"] = fw.to_dict()
    return jsonify(result)
