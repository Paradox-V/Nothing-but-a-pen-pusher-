"""
热点选题模块 - Flask Blueprint 路由
"""

import logging
import threading

from flask import Blueprint, jsonify, request

from modules.topic.service import (
    INDUSTRIES,
    expand_query,
    get_query_tokens,
    generate_explanation,
    semantic_search,
)
from modules.topic.title_gen import generate_titles

logger = logging.getLogger(__name__)

topic_bp = Blueprint("topic", __name__)

_gen_lock = threading.Lock()


@topic_bp.route("/api/topic/industries")
def api_industries():
    """返回支持的 16 个行业列表"""
    return jsonify(INDUSTRIES)


@topic_bp.route("/api/topic/generate", methods=["POST"])
def api_generate():
    """
    生成选题建议。

    请求体: {"industry": "AI科技", "keyword": "大模型", "top_k": 5}
    返回: [{hotspot: {...}, titles: [...], explanation: "..."}, ...]
    """
    data = request.get_json(force=True)
    industry = data.get("industry", "")
    keyword = data.get("keyword", "")
    top_k = min(data.get("top_k", 5), 10)

    if not industry or not keyword:
        return jsonify({"error": "请提供行业和关键词"}), 400

    # 1. 查询扩展
    expanded = expand_query(industry, keyword)
    logger.info("选题查询: industry=%s, keyword=%s → expanded=%s", industry, keyword, expanded)

    # 2. 语义检索（内部三级回退：ChromaDB代理 → ChromaDB直连 → SQLite关键词）
    results = semantic_search(expanded, top_k=top_k * 2)

    if not results:
        return jsonify({"error": "暂无新闻数据，请先抓取新闻"}), 404

    # 3. 取 TOP_K，为每条生成标题 + 推荐理由
    results = results[:top_k]

    ai_config = _load_ai_config()

    output = []
    for item in results:
        try:
            titles = generate_titles(item, industry, keyword, ai_config)
            explanation = generate_explanation(item, industry)
            output.append({
                "hotspot": {
                    "id": item.get("id"),
                    "title": item.get("title", ""),
                    "summary": (item.get("content") or "")[:200],
                    "source": item.get("source_name", ""),
                    "url": item.get("url", ""),
                    "date": item.get("created_at", ""),
                    "similarity": item.get("similarity", 0),
                },
                "titles": titles,
                "explanation": explanation,
            })
        except Exception as e:
            logger.error("处理素材 %s 失败: %s", item.get("id"), e)
            output.append({
                "hotspot": {
                    "id": item.get("id"),
                    "title": item.get("title", ""),
                    "summary": (item.get("content") or "")[:200],
                    "source": item.get("source_name", ""),
                    "url": item.get("url", ""),
                    "date": item.get("created_at", ""),
                    "similarity": 0,
                },
                "titles": [f"{item.get('title', '热点')} - 相关分析"],
                "explanation": "生成失败，请重试。",
            })

    return jsonify(output)


@topic_bp.route("/api/topic/regenerate-titles", methods=["POST"])
def api_regenerate_titles():
    """为单条新闻重新生成 3 个选题标题。

    请求体: {"hotspot": {title, summary}, "industry": "AI科技", "keyword": "大模型"}
    返回: {"titles": ["标题1", "标题2", "标题3"]}
    """
    data = request.get_json(force=True)
    industry = data.get("industry", "")
    keyword = data.get("keyword", "")
    hotspot = data.get("hotspot", {})

    if not industry or not keyword:
        return jsonify({"error": "请提供行业和关键词"}), 400

    news_item = {
        "title": hotspot.get("title", ""),
        "content": hotspot.get("summary", ""),
    }

    ai_config = _load_ai_config()
    titles = generate_titles(news_item, industry, keyword, ai_config)
    return jsonify({"titles": titles})


def _load_ai_config() -> dict:
    """加载 AI 配置"""
    try:
        from utils.config import load_config
        cfg = load_config()
        ai = cfg.get("ai", {})
        return {
            "MODEL": ai.get("model", "deepseek/deepseek-chat"),
            "API_KEY": ai.get("api_key", ""),
            "API_BASE": ai.get("base_url", ""),
        }
    except Exception:
        return {}
