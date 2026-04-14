"""LangChain Agent 工具定义 —— 包装现有数据访问接口"""

import json

from langchain_core.tools import tool

from modules.hotlist.db import HotlistDB
from modules.news.db import NewsDB
from utils.scheduler_client import scheduler_get, scheduler_post


@tool
def search_news_semantic(query: str, top_k: int = 5, category: str = "", source: str = "") -> str:
    """语义搜索新闻库，返回与查询最相关的新闻文章。

    当用户询问特定新闻事件、政策变化、行业动态时使用此工具。
    支持按分类（如"科技AI"、"宏观经济"）和数据源过滤。

    Args:
        query: 搜索查询文本
        top_k: 返回结果数量，默认5条
        category: 可选分类过滤，如"科技AI"、"股市"、"时事"
        source: 可选数据源过滤，如"新浪财经"、"财联社"
    """
    params = {"q": query, "n": str(top_k)}
    if category:
        params["category"] = category
    if source:
        params["source"] = source
    results = scheduler_get("/semantic_search", params=params, timeout=15)
    if not results:
        return json.dumps({"error": "搜索服务不可用或无结果"}, ensure_ascii=False)
    for r in results:
        if r.get("content"):
            r["content"] = r["content"][:300]
    return json.dumps(results, ensure_ascii=False)


@tool
def search_multi_source(query: str, top_k: int = 5) -> str:
    """跨新闻、热榜、RSS三库联合语义搜索。

    当用户的问题可能涉及多种信息来源时使用此工具，
    它会同时在新闻、热榜和RSS中搜索，去重后返回最相关的结果。

    Args:
        query: 搜索查询文本
        top_k: 每个来源返回的最大结果数，默认5
    """
    results = scheduler_post("/chat_search", json_data={"query": query, "top_k": top_k}, timeout=15)
    if not results:
        return json.dumps({"error": "搜索服务不可用或无结果"}, ensure_ascii=False)
    for r in results:
        if r.get("content"):
            r["content"] = r["content"][:300]
    return json.dumps(results, ensure_ascii=False)


@tool
def get_news_categories() -> str:
    """获取新闻库中所有可用分类及其文章数量。

    在需要了解有哪些新闻分类可以过滤，或在回答中展示分类分布时使用。
    """
    try:
        db = NewsDB()
        stats = db.get_category_stats()
        return json.dumps(stats, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool
def get_latest_news(limit: int = 10) -> str:
    """获取最近入库的新闻条目（按时间倒序）。

    当用户想了解最新发生了什么，不指定具体关键词时使用。

    Args:
        limit: 返回条数，默认10
    """
    try:
        db = NewsDB()
        items = db.get_latest(limit=limit)
        for item in items:
            if item.get("content"):
                item["content"] = item["content"][:300]
        return json.dumps(items, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool
def get_hotlist_rankings(platform: str = "", hours: int = 24) -> str:
    """获取各平台热榜排行数据。

    当用户询问某个平台的热搜、热门话题时使用。
    不指定平台则返回所有平台。

    Args:
        platform: 平台名称（可选），如"weibo"、"zhihu"、"bilibili-hot-search"。
                  不传则返回所有平台。
        hours: 回溯时间（小时），默认24
    """
    try:
        db = HotlistDB()
        result = db.get_items(platform=platform or None, hours=hours)
        # result 是 {"items": [...], "total": N, "page": 1, "page_size": 30}
        items = result.get("items", [])
        for item in items:
            item.pop("url", None)
        return json.dumps({
            "items": items[:20],
            "total": result.get("total", 0),
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool
def get_trending_overview() -> str:
    """获取综合热点概览：最新热榜 + 最新新闻。

    当用户想快速了解当前热点趋势概览时使用。
    """
    try:
        hotlist_db = HotlistDB()
        news_db = NewsDB()
        hot = hotlist_db.get_items(hours=6)
        news = news_db.get_latest(5)

        hot_items = hot.get("items", [])[:10]
        for item in hot_items:
            item.pop("url", None)

        news_items = news[:5]
        for item in news_items:
            if item.get("content"):
                item["content"] = item["content"][:200]

        return json.dumps({
            "hotlist": hot_items,
            "latest_news": news_items,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def get_all_tools():
    """返回所有 Agent 工具列表。"""
    return [
        search_news_semantic,
        search_multi_source,
        get_news_categories,
        get_latest_news,
        get_hotlist_rankings,
        get_trending_overview,
    ]
