"""RSS 源搜索工具 — 多后端支持

后端优先级（自动选择）：
  1. Feedly Cloud Search（免费，无需 Key）
  2. 站内语义搜索 + RSSHub 发现（基于现有数据）
"""

import json
import logging
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


class RSSSearcher:
    """多后端 RSS 源搜索器。"""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.backends = self.config.get("backends", ["feedly", "internal"])
        self.feedly_locale = self.config.get("feedly_locale", "zh")
        self.max_results = self.config.get("max_results", 10)
        self.verify_feeds = self.config.get("verify_feeds", True)

    def search(self, topic: str, max_results: int | None = None) -> list[dict]:
        """搜索与话题相关的 RSS 源。

        Args:
            topic: 话题关键词（如 "人工智能"、"A股"）
            max_results: 返回数量（默认使用 config 值）

        Returns:
            候选 RSS 源列表，每项含：
            {feed_url, name, description, website, subscribers, verified}
        """
        n = max_results or self.max_results
        results = []
        seen_urls: set[str] = set()

        for backend in self.backends:
            if len(results) >= n:
                break
            try:
                if backend == "feedly":
                    items = self._search_feedly(topic, n)
                elif backend == "internal":
                    items = self._search_internal(topic, n)
                else:
                    continue

                for item in items:
                    url = item.get("feed_url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        results.append(item)
            except Exception as e:
                logger.warning("RSS 搜索 backend=%s 失败: %s", backend, e)

        # 验证 Feed 可访问性
        if self.verify_feeds:
            results = self._verify_feeds(results[:n])

        return results[:n]

    def _search_feedly(self, topic: str, count: int) -> list[dict]:
        """通过 Feedly Cloud Search API 搜索。"""
        try:
            resp = httpx.get(
                "https://cloud.feedly.com/v3/search/feeds",
                params={
                    "query": topic,
                    "count": min(count, 20),
                    "locale": self.feedly_locale,
                },
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0 (compatible; RSS-Aggregator/1.0)"},
            )
            if resp.status_code != 200:
                return []

            data = resp.json()
            results = []
            for item in data.get("results", []):
                feed_id = item.get("feedId", "")
                feed_url = feed_id.replace("feed/", "", 1) if feed_id.startswith("feed/") else feed_id
                if not feed_url:
                    continue
                results.append({
                    "feed_url": feed_url,
                    "name": item.get("title", ""),
                    "description": item.get("description", ""),
                    "website": item.get("website", ""),
                    "subscribers": item.get("subscribers", 0),
                    "verified": False,
                    "source": "feedly",
                })
            return results
        except Exception as e:
            logger.debug("Feedly 搜索失败: %s", e)
            return []

    def _search_internal(self, topic: str, count: int) -> list[dict]:
        """基于现有语义搜索发现相关 RSS 源。"""
        try:
            from utils.scheduler_client import scheduler_post
            news_items = scheduler_post(
                "/chat_search",
                json_data={"query": topic, "top_k": 20},
                timeout=15,
            )
            if not news_items or not isinstance(news_items, list):
                return []

            # 提取来源 RSS feed（source_type == 'rss' 的条目）
            rss_feeds: dict[str, dict] = {}
            for item in news_items:
                if item.get("source_type") != "rss":
                    continue
                feed_id = item.get("feed_id", "")
                feed_name = item.get("source_name", "")
                if not feed_id or feed_id in rss_feeds:
                    continue
                # 查找实际 Feed URL
                try:
                    from modules.rss.db import RSSDB
                    db = RSSDB()
                    feed = db.get_feed(feed_id)
                    if feed and feed.get("url"):
                        rss_feeds[feed_id] = {
                            "feed_url": feed["url"],
                            "name": feed_name or feed.get("name", feed_id),
                            "description": f"与「{topic}」相关的内容",
                            "website": "",
                            "subscribers": 0,
                            "verified": True,
                            "source": "internal",
                        }
                except Exception:
                    pass

            return list(rss_feeds.values())[:count]
        except Exception as e:
            logger.debug("内部搜索失败: %s", e)
            return []

    def _verify_feeds(self, feeds: list[dict]) -> list[dict]:
        """验证 Feed URL 可访问性（超时 5s，并发）。"""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _check(feed: dict) -> dict:
            if feed.get("verified"):
                return feed
            try:
                resp = httpx.head(
                    feed["feed_url"], timeout=5,
                    follow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; RSS-Aggregator/1.0)"},
                )
                feed["verified"] = resp.status_code < 400
            except Exception:
                feed["verified"] = False
            return feed

        verified = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_check, f): f for f in feeds}
            for future in as_completed(futures):
                try:
                    verified.append(future.result())
                except Exception:
                    pass

        # 按 verified（True 优先）+ subscribers 排序
        verified.sort(key=lambda x: (not x.get("verified"), -x.get("subscribers", 0)))
        return verified

    def verify_feed(self, feed_url: str) -> dict:
        """验证单个 Feed URL，返回预览信息。"""
        try:
            resp = httpx.get(
                feed_url, timeout=8, follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; RSS-Aggregator/1.0)"},
            )
            if resp.status_code != 200:
                return {"valid": False, "error": f"HTTP {resp.status_code}"}

            # 简单解析 Feed 标题和条目数
            import feedparser
            parsed = feedparser.parse(resp.text)
            title = parsed.feed.get("title", "")
            entries = parsed.entries[:3]
            sample_items = [{"title": e.get("title", "")} for e in entries]
            return {
                "valid": True,
                "name": title,
                "sample_items": sample_items,
                "entry_count": len(parsed.entries),
            }
        except Exception as e:
            return {"valid": False, "error": str(e)}
