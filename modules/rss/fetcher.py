# coding=utf-8
"""
RSS 抓取器

负责从配置的 RSS 源抓取数据并转换为标准格式
"""

import time
import random
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Optional, Tuple

import requests

from modules.rss.parser import RSSParser
from utils.url_security import validate_url

import logging
logger = logging.getLogger(__name__)


@dataclass
class RSSFeedConfig:
    """RSS 源配置"""
    id: str                     # 源 ID
    name: str                   # 显示名称
    url: str                    # RSS URL
    max_items: int = 0          # 最大条目数（0=不限制）
    enabled: bool = True        # 是否启用
    max_age_days: Optional[int] = None  # 文章最大年龄（天）


class RSSFetcher:
    """RSS 抓取器"""

    def __init__(self, timeout: int = 15, proxy_url: Optional[str] = None):
        """
        初始化抓取器

        Args:
            timeout: 请求超时（秒）
            proxy_url: 代理地址（如 http://127.0.0.1:7890），None 则不使用代理
        """
        self.timeout = timeout
        self.parser = RSSParser()
        self.proxies = (
            {"http": proxy_url, "https": proxy_url}
            if proxy_url else None
        )
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """创建请求会话"""
        session = requests.Session()
        session.headers.update({
            "User-Agent": "NewsAggregator/1.0 RSS Reader",
            "Accept": "application/feed+json, application/json, "
                      "application/rss+xml, application/atom+xml, "
                      "application/xml, text/xml, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        # 禁用环境变量代理，代理按请求级别显式传入
        session.trust_env = False
        return session

    def fetch_feed(
        self, feed_config: RSSFeedConfig
    ) -> Tuple[List[Dict[str, str]], Optional[str]]:
        """
        抓取单个 RSS 源

        Args:
            feed_config: RSS 源配置

        Returns:
            (条目字典列表, 错误信息) 元组
            每个条目字典包含: title, feed_id, url, author, summary, published_at
        """
        try:
            # SSRF 校验（本地 RSSHub 地址放行）
            is_local = feed_config.url.startswith(("http://127.0.0.1", "http://localhost"))
            if not is_local:
                is_safe, error = validate_url(feed_config.url)
                if not is_safe:
                    return [], f"URL 校验失败: {error}"
            if is_local:
                # 本地地址（如 RSSHub Docker 容器）直接请求
                response = self.session.get(
                    feed_config.url, timeout=self.timeout, proxies=None
                )
            else:
                # 外部地址：先直连（5s 超时），失败再走代理
                try:
                    response = self.session.get(
                        feed_config.url, timeout=5, proxies=None
                    )
                except (requests.Timeout, requests.ConnectionError):
                    if self.proxies:
                        response = self.session.get(
                            feed_config.url, timeout=self.timeout,
                            proxies=self.proxies
                        )
                    else:
                        raise
            response.raise_for_status()

            # 使用 bytes 而非 str，避免含非法 UTF-8 代理字符的响应（如 Arxiv RSS）
            parsed_items = self.parser.parse(response.content, feed_config.url)

            # 限制条目数量（0=不限制）
            if feed_config.max_items > 0:
                parsed_items = parsed_items[:feed_config.max_items]

            items: List[Dict[str, str]] = []
            for parsed in parsed_items:
                items.append({
                    "title": parsed.title,
                    "feed_id": feed_config.id,
                    "url": parsed.url,
                    "author": parsed.author or "",
                    "summary": parsed.summary or "",
                    "published_at": parsed.published_at or "",
                })

            logger.info("[RSS] %s: 获取 %d 条", feed_config.name, len(items))
            return items, None

        except requests.Timeout:
            error = f"请求超时 ({self.timeout}s)"
            logger.warning("[RSS] %s: %s", feed_config.name, error)
            return [], error

        except requests.RequestException as e:
            error = f"请求失败: {e}"
            logger.warning("[RSS] %s: %s", feed_config.name, error)
            return [], error

        except ValueError as e:
            error = f"解析失败: {e}"
            logger.warning("[RSS] %s: %s", feed_config.name, error)
            return [], error

        except Exception as e:
            error = f"未知错误: {e}"
            logger.error("[RSS] %s: %s", feed_config.name, error)
            return [], error

    def fetch_and_store(self, db) -> Dict[str, int]:
        """
        抓取所有启用的 RSS 源并存入数据库

        Args:
            db: RSSDB 实例

        Returns:
            {"fetched": int, "failed": int, "total_items": int}
        """
        from modules.rss.db import RSSDB  # noqa: avoid circular at module level

        feeds_data = db.get_feeds(enabled_only=True)

        if not feeds_data:
            logger.info("[RSS] 没有启用的 RSS 源")
            return {"fetched": 0, "failed": 0, "total_items": 0}

        fetched = 0
        failed = 0
        total_items = 0

        logger.info("[RSS] 开始抓取 %d 个 RSS 源...", len(feeds_data))

        for i, feed_data in enumerate(feeds_data):
            # 请求间隔（1-3 秒随机）
            if i > 0:
                interval = random.uniform(1.0, 3.0)
                time.sleep(interval)

            feed_config = RSSFeedConfig(
                id=feed_data["id"],
                name=feed_data["name"],
                url=feed_data["url"],
                max_items=feed_data.get("max_items", 0),
                enabled=True,
                max_age_days=feed_data.get("max_age_days"),
            )

            crawl_time = datetime.now().isoformat()
            items, error = self.fetch_feed(feed_config)

            if error:
                failed += 1
                db.update_feed_status(feed_config.id, error=error)
            else:
                fetched += 1
                total_items += len(items)
                if items:
                    db.insert_items(items, crawl_time)
                db.update_feed_status(feed_config.id, error=None)

        logger.info(
            "[RSS] 抓取完成: %d 个源成功, %d 个失败, 共 %d 条",
            fetched, failed, total_items,
        )
        return {
            "fetched": fetched,
            "failed": failed,
            "total_items": total_items,
        }
