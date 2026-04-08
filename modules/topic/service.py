"""
热点选题模块 - 核心服务

用户输入行业+关键词 → 查询扩展 → 语义检索 → 生成标题
检索优先级：ChromaDB 语义搜索 > SQLite 关键词搜索 > 最新新闻兜底
"""

import logging
import os
import sqlite3
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# 16 个行业同义词词典（移植自 ms-DYP query_processor.py）
EXPANSION_DICT: dict[str, list[str]] = {
    "AI科技": ["人工智能", "大模型", "机器学习", "深度学习", "算法", "数据", "技术", "应用"],
    "财富金融": ["投资", "理财", "股票", "基金", "金融市场", "资产", "收益", "风险"],
    "科技创新": ["科技", "技术", "研发", "专利", "发明", "成果", "进步", "应用"],
    "创新创业": ["创业", "创新", "初创", "孵化", "融资", "创投", "风投", "孵化器"],
    "民生百科": ["民生", "常识", "知识", "实用", "日常", "生活", "问题", "服务"],
    "健康养生": ["健康", "养生", "保健", "医疗", "疾病", "预防", "调理", "饮食"],
    "时尚娱乐": ["时尚", "娱乐", "潮流", "明星", "电影", "电视剧", "综艺", "音乐"],
    "美食生活": ["美食", "烹饪", "餐厅", "食谱", "推荐", "文化", "分享", "制作"],
    "旅行分享": ["旅行", "旅游", "景点", "攻略", "游记", "酒店", "机票", "体验"],
    "星座情感": ["星座", "运势", "情感", "爱情", "婚姻", "心理", "性格", "配对"],
    "体育健身": ["体育", "健身", "运动", "赛事", "运动员", "训练", "比赛", "健康"],
    "美容美体": ["美容", "美体", "护肤", "化妆", "整形", "保养", "产品", "服务"],
    "汽车评论": ["汽车", "车型", "车评", "试驾", "新闻", "保养", "维修", "改装"],
    "楼市房市": ["楼市", "房产", "房价", "购房", "租房", "政策", "市场", "投资"],
    "职场分享": ["职场", "工作", "职业发展", "面试", "晋升", "技能", "经验", "故事"],
    "母婴教育": ["母婴", "育儿", "早教", "儿童教育", "产品", "服务", "知识", "亲子"],
}

INDUSTRIES = list(EXPANSION_DICT.keys())


def expand_query(industry: str, keyword: str) -> str:
    """扩展查询：行业 + 关键词 + 行业同义词"""
    terms = [industry, keyword]
    if industry in EXPANSION_DICT:
        terms.extend(EXPANSION_DICT[industry][:4])
    return " ".join(terms)


def get_query_tokens(industry: str, keyword: str) -> list[str]:
    """从行业+关键词中提取所有搜索 token"""
    tokens = set()
    # 基础 token
    tokens.add(keyword)
    tokens.add(industry)
    # 行业扩展词
    if industry in EXPANSION_DICT:
        for w in EXPANSION_DICT[industry][:4]:
            tokens.add(w)
    # 关键词拆分（中文按 2-4 字切分）
    if len(keyword) >= 2:
        for i in range(len(keyword) - 1):
            tokens.add(keyword[i:i+2])
    return [t for t in tokens if len(t) >= 2]


def semantic_search(query: str, top_k: int = 10) -> list[dict]:
    """
    语义搜索，三级回退：
    1. 调度器 5001 端口 ChromaDB 代理
    2. 直接 ChromaDB（加载 embedding 模型）
    3. SQLite 关键词搜索
    """
    # 级别 1：调度器代理
    results = _search_via_scheduler(query, top_k)
    if results:
        return results

    # 级别 2：直接 ChromaDB
    results = _search_via_chromadb(query, top_k)
    if results:
        return results

    # 级别 3：SQLite 关键词搜索（query 中的词做匹配）
    return _search_via_sqlite(query, top_k)


def _search_via_scheduler(query: str, top_k: int) -> list[dict]:
    """通过调度器 5001 端口代理"""
    try:
        resp = httpx.get(
            "http://127.0.0.1:5001/semantic_search",
            params={"q": query, "n": str(top_k)},
            timeout=10,
        )
        results = resp.json()
        if isinstance(results, list) and results:
            return results
    except Exception:
        pass
    return []


_chroma_engine = None


def _search_via_chromadb(query: str, top_k: int) -> list[dict]:
    """直接加载 ChromaDB + embedding 模型做语义搜索"""
    global _chroma_engine
    try:
        if _chroma_engine is None:
            from modules.news.vector import NewsVectorEngine
            engine = NewsVectorEngine()
            engine.initialize()
            if engine.collection.count() == 0:
                logger.info("ChromaDB 无数据，跳过")
                return []
            _chroma_engine = engine

        return _chroma_engine.semantic_search(query, n=top_k)
    except Exception as e:
        logger.warning("ChromaDB 直接搜索失败: %s", e)
        return []


def _search_via_sqlite(query: str, top_k: int) -> list[dict]:
    """SQLite 关键词搜索：按相关度评分排序"""
    # 核心词（用户输入的 keyword + industry）权重高，扩展词权重低
    all_tokens = list(dict.fromkeys(t for t in query.split() if len(t) >= 2))
    if not all_tokens:
        return _latest_news(top_k)

    # 前 2 个是核心词（industry, keyword），其余是扩展词
    core_tokens = all_tokens[:2]
    expand_tokens = all_tokens[2:]

    try:
        conn = sqlite3.connect("data/news.db")
        conn.row_factory = sqlite3.Row

        candidates = {}
        for token in all_tokens:
            rows = conn.execute(
                "SELECT id, title, content, source_name, url, created_at, category "
                "FROM news WHERE title LIKE ? OR content LIKE ? "
                "ORDER BY id DESC LIMIT 50",
                (f"%{token}%", f"%{token}%"),
            ).fetchall()
            for r in rows:
                candidates[r["id"]] = r

        conn.close()

        if not candidates:
            return _latest_news(top_k)

        scored = []
        for rid, r in candidates.items():
            title = r["title"] or ""
            content = r["content"] or ""

            # 核心词匹配：标题+3, 内容+1
            core_score = 0
            for t in core_tokens:
                if t in title: core_score += 3
                if t in content: core_score += 1

            # 扩展词匹配：标题+1, 内容+0.5
            expand_score = 0
            for t in expand_tokens:
                if t in title: expand_score += 1
                if t in content: expand_score += 0.5

            total_score = core_score + expand_score

            # 相似度：以核心词为基准
            # 核心词满分 = len(core_tokens) * 4 (标题3+内容1)
            core_max = len(core_tokens) * 4
            core_ratio = min(core_score / core_max, 1.0) if core_max > 0 else 0

            # 扩展词作为加分（最多+0.25）
            expand_bonus = min(expand_score / 8, 0.25) if expand_tokens else 0

            sim = round(min(core_ratio * 0.75 + expand_bonus + 0.25, 1.0), 2)
            # 如果核心词完全没命中，大幅降权
            if core_score == 0:
                sim = round(sim * 0.3, 2)

            scored.append((total_score, sim, r))

        scored.sort(key=lambda x: -x[0])

        return [
            {
                "id": r["id"],
                "title": r["title"],
                "content": r["content"],
                "source_name": r["source_name"],
                "url": r["url"],
                "created_at": r["created_at"],
                "category": r["category"],
                "similarity": sim,
            }
            for _, sim, r in scored[:top_k]
        ]

    except Exception as e:
        logger.error("SQLite 关键词搜索失败: %s", e)
        return _latest_news(top_k)


def _latest_news(top_k: int) -> list[dict]:
    """最终兜底：返回最新新闻"""
    try:
        conn = sqlite3.connect("data/news.db")
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, title, content, source_name, url, created_at, category "
            "FROM news ORDER BY id DESC LIMIT ?",
            (top_k,),
        ).fetchall()
        conn.close()
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "content": r["content"],
                "source_name": r["source_name"],
                "url": r["url"],
                "created_at": r["created_at"],
                "category": r["category"],
                "similarity": 0.0,
            }
            for r in rows
        ]
    except Exception:
        return []


def generate_explanation(news_item: dict, industry: str) -> str:
    """生成推荐理由"""
    title = news_item.get("title", "")
    categories = news_item.get("category", "")
    if isinstance(categories, str):
        categories = categories.split(",")

    expansion_words = EXPANSION_DICT.get(industry, [])
    all_keywords = [industry] + expansion_words
    for kw in all_keywords:
        if kw in title or any(kw in c for c in categories):
            return f"该新闻与{industry}领域直接相关，核心话题涉及「{kw}」，适合作为选题素材。"

    return f"该新闻与{industry}领域存在关联，核心话题为「{title[:30]}」，值得深入挖掘。"
