"""LangChain Agent 工具定义 —— 包装现有数据访问接口"""

import json
import os
from contextvars import ContextVar

from langchain_core.tools import tool

from modules.hotlist.db import HotlistDB
from modules.news.db import NewsDB
from utils.scheduler_client import scheduler_get, scheduler_post

# ── Agent 上下文（线程安全） ──────────────────────────────────────
# 存储当前 Agent 调用的微信绑定上下文（binding_id, account_id, user_id）
_agent_context: ContextVar[dict] = ContextVar("_agent_context", default={})


def set_agent_context(ctx: dict):
    """设置当前 Agent 调用的上下文（binding_id, account_id, user_id）。"""
    _agent_context.set(ctx)


def get_agent_context() -> dict:
    """获取当前 Agent 调用的上下文。"""
    return _agent_context.get()


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


# ── 监控任务工具 ────────────────────────────────────────────────

@tool
def create_monitor_task(name: str, keywords: list, schedule: str = "daily_morning") -> str:
    """创建新的关键词监控任务，并自动绑定到当前微信联系人。

    当用户要求新建一个关键词监控、追踪某个话题时使用。
    创建后系统会在指定时间（早8点或晚8点）自动搜索并推送报告。

    Args:
        name: 任务名称，如"AI行业动态"
        keywords: 监控关键词列表，如 ["人工智能", "ChatGPT", "大模型"]
        schedule: 推送时间，"daily_morning"（早8点）或 "daily_evening"（晚8点）
    """
    if not name or not keywords:
        return json.dumps({"error": "任务名称和关键词不能为空"}, ensure_ascii=False)

    valid_schedules = {"daily_morning", "daily_evening"}
    if schedule not in valid_schedules:
        schedule = "daily_morning"

    try:
        from modules.monitor.service import get_monitor_service
        svc = get_monitor_service()

        # 获取当前微信上下文
        ctx = get_agent_context()
        binding_id = ctx.get("binding_id")
        account_id = ctx.get("account_id")
        user_id = ctx.get("user_id")

        # 构建推送配置：推送给当前联系人
        push_config = []
        if account_id and user_id:
            context_token = ctx.get("context_token", "")
            push_config = [{
                "type": "wcf",
                "account_id": account_id,
                "to_user_id": user_id,
                "context_token": context_token,
            }]

        task = svc.create_task(
            name=name,
            keywords=keywords,
            filters=None,
            schedule=schedule,
            push_config=push_config,
        )

        # 将任务绑定到微信联系人
        if binding_id and task.get("id"):
            try:
                from modules.wcf.db import WCFDB
                wdb = WCFDB()
                wdb.bind_task(binding_id, task["id"])
            except Exception:
                pass

        schedule_label = "每天早8点" if schedule == "daily_morning" else "每天晚8点"
        return json.dumps({
            "success": True,
            "task_id": task.get("id"),
            "name": name,
            "keywords": keywords,
            "schedule": f"{schedule_label}推送",
            "message": f"已创建监控任务「{name}」，将在{schedule_label}推送报告",
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"创建任务失败: {e}"}, ensure_ascii=False)


@tool
def list_my_monitor_tasks() -> str:
    """查询当前微信联系人已绑定的监控任务列表。

    当用户询问"我有哪些监控任务"、"我的订阅"等时使用。
    """
    try:
        ctx = get_agent_context()
        binding_id = ctx.get("binding_id")

        if not binding_id:
            return json.dumps({"error": "当前会话未绑定微信联系人"}, ensure_ascii=False)

        from modules.wcf.db import WCFDB
        from modules.monitor.db import MonitorDB
        wdb = WCFDB()
        mdb = MonitorDB()

        task_ids = wdb.get_binding_tasks(binding_id)
        if not task_ids:
            return json.dumps({"tasks": [], "message": "当前未绑定任何监控任务"}, ensure_ascii=False)

        tasks = []
        for tid in task_ids:
            task = mdb.get_task(tid)
            if task:
                tasks.append({
                    "id": task["id"],
                    "name": task.get("name", ""),
                    "keywords": task.get("keywords", []),
                    "schedule": task.get("schedule", ""),
                    "is_active": task.get("is_active", 1),
                })

        return json.dumps({"tasks": tasks, "total": len(tasks)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool
def run_monitor_task(task_name: str) -> str:
    """手动触发指定监控任务立即执行，并将报告推送到当前微信对话。

    当用户要求"现在就运行监控"、"立即获取报告"时使用。
    会模糊匹配任务名称（包含即可）。

    Args:
        task_name: 任务名称（支持模糊匹配，如输入"AI"可匹配"AI行业动态"）
    """
    try:
        ctx = get_agent_context()
        binding_id = ctx.get("binding_id")
        account_id = ctx.get("account_id")
        user_id = ctx.get("user_id")

        if not binding_id:
            return json.dumps({"error": "当前会话未绑定微信联系人"}, ensure_ascii=False)

        from modules.wcf.db import WCFDB
        from modules.monitor.db import MonitorDB
        from modules.monitor.service import get_monitor_service

        wdb = WCFDB()
        mdb = MonitorDB()
        svc = get_monitor_service()

        task_ids = wdb.get_binding_tasks(binding_id)
        if not task_ids:
            return json.dumps({"error": "当前未绑定任何监控任务"}, ensure_ascii=False)

        # 模糊匹配任务名称
        matched = []
        for tid in task_ids:
            task = mdb.get_task_raw(tid)
            if task and task_name.lower() in task.get("name", "").lower():
                matched.append(tid)

        if not matched:
            return json.dumps({
                "error": f"未找到名称包含「{task_name}」的任务，"
                         "请使用 list_my_monitor_tasks 查看可用任务",
            }, ensure_ascii=False)

        if len(matched) > 1:
            task_names = [mdb.get_task(t).get("name", t) for t in matched]
            return json.dumps({
                "error": f"找到多个匹配任务: {task_names}，请提供更精确的名称",
            }, ensure_ascii=False)

        task_id = matched[0]
        context_token = ctx.get("context_token", "")
        override_push = [{
            "type": "wcf",
            "account_id": account_id,
            "to_user_id": user_id,
            "context_token": context_token,
        }] if account_id and user_id else None

        result = svc.run_task(task_id, override_push_config=override_push)
        if result.get("status") == "success":
            return json.dumps({
                "success": True,
                "message": f"任务已执行完毕，报告已发送",
            }, ensure_ascii=False)
        else:
            return json.dumps({
                "success": False,
                "error": result.get("error", "执行失败"),
            }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ── RSS 工具 ────────────────────────────────────────────────────

@tool
def search_rss_by_topic(topic: str, max_results: int = 5) -> str:
    """在网上搜寻与指定话题相关的 RSS 订阅源。

    当用户想要订阅某个主题的信息流、新闻源时使用。
    返回候选 RSS 源列表，用户确认后可用 subscribe_rss 工具订阅。

    Args:
        topic: 话题关键词，如"AI人工智能"、"A股股市"、"科技创业"
        max_results: 返回结果数量，默认5
    """
    try:
        from utils.rss_search import RSSSearcher
        from utils.config import load_config
        config = load_config()
        searcher = RSSSearcher(config.get("rss_search", {}))
        results = searcher.search(topic, max_results=max_results)
        if not results:
            return json.dumps({
                "results": [],
                "message": f"未找到与「{topic}」相关的 RSS 源，请尝试其他关键词",
            }, ensure_ascii=False)
        return json.dumps({
            "topic": topic,
            "results": results,
            "message": f"找到 {len(results)} 个相关 RSS 源，请告知是否订阅",
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool
def subscribe_rss(feed_url: str, feed_name: str) -> str:
    """将指定 RSS 源添加到系统订阅列表。

    在用户明确表示要订阅某个 RSS 源后调用。
    注意：订阅前请先用 search_rss_by_topic 获取可用源。

    Args:
        feed_url: RSS 源的 URL 地址
        feed_name: 给这个 RSS 源起的名称（如"机器之心 - AI资讯"）
    """
    try:
        from utils.url_security import validate_url
        is_safe, err = validate_url(feed_url)
        if not is_safe:
            return json.dumps({"error": f"URL 不安全: {err}"}, ensure_ascii=False)

        from modules.rss.db import RSSDB
        db = RSSDB()

        # 检查是否已存在
        existing = db.get_feeds(enabled_only=False)
        for f in existing:
            if f["url"] == feed_url:
                return json.dumps({
                    "success": False,
                    "message": f"该 RSS 源已存在，名称为「{f['name']}」",
                }, ensure_ascii=False)

        # 获取 owner_id（若有用户上下文）
        ctx = get_agent_context()
        owner_id = ctx.get("user_id")

        feed_id = db.add_feed(feed_name, feed_url, owner_id=owner_id)
        return json.dumps({
            "success": True,
            "feed_id": feed_id,
            "name": feed_name,
            "message": f"已成功订阅「{feed_name}」",
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """当内部信源（新闻库、RSS、热榜）搜索无结果时，使用 Tavily 进行网络搜索。

    这是最后的搜索手段。请优先使用内部工具（search_news_semantic、
    search_multi_source、search_rss_by_topic 等），仅在它们返回无结果
    或结果不足时才调用此工具。

    Args:
        query: 搜索查询文本
        max_results: 返回结果数量，默认5
    """
    try:
        import requests as _requests
        from utils.config import load_config

        config = load_config()
        ws_cfg = config.get("web_search", {})
        api_key = ws_cfg.get("api_key", "") or os.environ.get("TAVILY_API_KEY", "")

        if not api_key:
            return json.dumps({"error": "网络搜索未配置 API key"}, ensure_ascii=False)

        resp = _requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
                "include_answer": False,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("results", []):
            url = item.get("url", "")
            # 从 URL 提取域名作为来源
            source_name = ""
            if url:
                try:
                    from urllib.parse import urlparse
                    source_name = urlparse(url).netloc
                except Exception:
                    pass
            results.append({
                "title": item.get("title", ""),
                "url": url,
                "content": item.get("content", "")[:300],
                "source_name": source_name,
                "source_type": "web",
            })

        if not results:
            return json.dumps({
                "results": [],
                "message": f"网络搜索也未找到与「{query}」相关的结果",
            }, ensure_ascii=False)

        return json.dumps({"results": results, "total": len(results)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"网络搜索失败: {e}"}, ensure_ascii=False)


def get_all_tools():
    """返回所有 Agent 工具列表。"""
    return [
        search_news_semantic,
        search_multi_source,
        get_news_categories,
        get_latest_news,
        get_hotlist_rankings,
        get_trending_overview,
        create_monitor_task,
        list_my_monitor_tasks,
        run_monitor_task,
        search_rss_by_topic,
        subscribe_rss,
        web_search,
    ]

