"""Agent Tool 单元测试"""

import json
import pytest
from unittest.mock import patch, MagicMock


@patch("modules.agent.tools.scheduler_get")
def test_search_news_semantic_success(mock_get):
    from modules.agent.tools import search_news_semantic
    mock_get.return_value = [
        {"title": "AI突破", "content": "最新进展" * 50, "source_name": "新浪"}
    ]
    result = json.loads(search_news_semantic.invoke({"query": "AI", "top_k": 5}))
    assert len(result) == 1
    assert result[0]["title"] == "AI突破"
    assert len(result[0]["content"]) <= 300


@patch("modules.agent.tools.scheduler_get")
def test_search_news_semantic_unavailable(mock_get):
    from modules.agent.tools import search_news_semantic
    mock_get.return_value = None
    result = json.loads(search_news_semantic.invoke({"query": "test"}))
    assert "error" in result


@patch("modules.agent.tools.scheduler_post")
def test_search_multi_source_success(mock_post):
    from modules.agent.tools import search_multi_source
    mock_post.return_value = [
        {"title": "新闻1", "source_name": "微博"},
        {"title": "新闻2", "platform_name": "知乎"},
    ]
    result = json.loads(search_multi_source.invoke({"query": "热点", "top_k": 3}))
    assert len(result) == 2


@patch("modules.agent.tools.NewsDB")
def test_get_news_categories(mock_db_cls):
    from modules.agent.tools import get_news_categories
    mock_db = MagicMock()
    mock_db.get_category_stats.return_value = [
        {"category": "科技AI", "count": 42}
    ]
    mock_db_cls.return_value = mock_db
    result = json.loads(get_news_categories.invoke({}))
    assert result[0]["category"] == "科技AI"


@patch("modules.agent.tools.NewsDB")
def test_get_latest_news(mock_db_cls):
    from modules.agent.tools import get_latest_news
    mock_db = MagicMock()
    mock_db.get_latest.return_value = [
        {"id": 1, "title": "最新新闻", "content": "x" * 400, "source_name": "新浪"}
    ]
    mock_db_cls.return_value = mock_db
    result = json.loads(get_latest_news.invoke({"limit": 5}))
    assert len(result) == 1
    assert len(result[0]["content"]) <= 300


@patch("modules.agent.tools.HotlistDB")
def test_get_hotlist_rankings(mock_db_cls):
    from modules.agent.tools import get_hotlist_rankings
    mock_db = MagicMock()
    mock_db.get_items.return_value = {
        "items": [
            {"title": "热搜1", "platform": "weibo", "platform_name": "微博", "hot_rank": 1, "url": "http://x"}
        ],
        "total": 1,
        "page": 1,
        "page_size": 30,
    }
    mock_db_cls.return_value = mock_db
    result = json.loads(get_hotlist_rankings.invoke({"platform": "weibo", "hours": 24}))
    assert result["total"] == 1
    assert len(result["items"]) == 1


@patch("modules.agent.tools.HotlistDB")
@patch("modules.agent.tools.NewsDB")
def test_get_trending_overview(mock_news_cls, mock_hot_cls):
    from modules.agent.tools import get_trending_overview
    mock_hot = MagicMock()
    mock_hot.get_items.return_value = {
        "items": [{"title": "热搜", "platform": "weibo", "url": "http://x"}],
        "total": 1,
    }
    mock_hot_cls.return_value = mock_hot

    mock_news = MagicMock()
    mock_news.get_latest.return_value = [{"title": "新闻", "content": "内容"}]
    mock_news_cls.return_value = mock_news

    result = json.loads(get_trending_overview.invoke({}))
    assert "hotlist" in result
    assert "latest_news" in result
