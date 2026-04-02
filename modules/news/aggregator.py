"""
新闻模块 - AKTools 信源聚合器

从 ak_source_aggregator.py 提取的 AKSourceAggregator 类，
整合 8 个 AKTools 财经新闻接口，统一输出标准 JSON 格式。
支持 httpx 异步并发获取、基于内容哈希的去重、单信源异常隔离。
"""

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any, Callable

import httpx

from modules.news.db import NewsDB

logger = logging.getLogger(__name__)


class AKSourceAggregator:
    """AKTools 信源统合聚合器"""

    BASE_URL = "http://49.232.239.68:8080/api/public"

    SOURCE_REGISTRY: dict[str, dict[str, Any]] = {
        "stock_info_global_sina": {
            "display": "新浪快讯",
            "tags": ["财经", "全球"],
            "params": None,
        },
        "news_cctv": {
            "display": "央视新闻联播",
            "tags": ["央视", "时事"],
            "params": lambda: {
                "date": (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
            },
        },
        "futures_news_shmet": {
            "display": "上海金属网",
            "tags": ["期货", "金属"],
            "params": None,
        },
        "stock_news_main_cx": {
            "display": "财联社电报(摘要)",
            "tags": ["财联社", "电报"],
            "params": None,
        },
        "stock_info_global_cls": {
            "display": "财联社电报",
            "tags": ["财联社", "电报"],
            "params": None,
        },
        "stock_info_global_em": {
            "display": "东方财富快讯",
            "tags": ["东方财富", "财经"],
            "params": None,
        },
        "stock_info_global_futu": {
            "display": "富途快讯",
            "tags": ["富途", "全球"],
            "params": None,
        },
        "stock_info_global_ths": {
            "display": "同花顺直播",
            "tags": ["同花顺", "财经"],
            "params": None,
        },
    }

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 30.0,
        db: NewsDB | None = None,
    ):
        self.base_url = base_url or self.BASE_URL
        self.timeout = timeout
        self.db = db or NewsDB()
        self._seen_hashes: set[str] = set()

    # ── 工具方法 ────────────────────────────────────────────

    @staticmethod
    def _extract_title(content: str, max_len: int = 20) -> str:
        if not content:
            return ""
        start, end = content.find("【"), content.find("】")
        if start != -1 and end != -1 and end > start:
            return content[start + 1 : end]
        return content[:max_len].strip()

    @staticmethod
    def _normalize_timestamp(raw: Any) -> str | None:
        if raw is None:
            return None
        s = str(raw).strip()
        if not s:
            return None
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y%m%d",
        ):
            try:
                return datetime.strptime(s, fmt).isoformat()
            except ValueError:
                continue
        return s

    @staticmethod
    def _normalize_title(title: str) -> str:
        """归一化标题用于去重：去除【】包裹符，统一空白。"""
        t = title.strip()
        # 剥离最外层 【...】
        if t.startswith("【"):
            end = t.find("】")
            if end != -1:
                t = t[end + 1:].strip()
        # 合并多余空白
        return " ".join(t.split())

    @staticmethod
    def _dedup_hash(title: str, content: str) -> str:
        """
        去重哈希：优先基于归一化标题。
        仅在标题为空或极短（<4字）时回退到内容哈希。
        """
        norm = AKSourceAggregator._normalize_title(title)
        if len(norm) >= 4:
            return hashlib.md5(norm.encode("utf-8")).hexdigest()
        # 标题无意义时退回到内容前 200 字
        text = content[:200] if content else ""
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _to_list(data: Any) -> list[dict]:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("data", "result", "items", "records"):
                v = data.get(key)
                if isinstance(v, list):
                    return v
            return [data]
        return []

    # ── 各信源解析器 ────────────────────────────────────────

    def _parse_sina(self, items: list[dict]) -> list[dict]:
        out = []
        for it in items:
            content = it.get("内容", "")
            out.append({
                "source_name": "新浪快讯",
                "title": self._extract_title(content),
                "content": content,
                "timestamp": self._normalize_timestamp(it.get("时间")),
                "url": None,
                "tags": ["财经", "全球"],
            })
        return out

    def _parse_cctv(self, items: list[dict]) -> list[dict]:
        out = []
        for it in items:
            title = it.get("title", "")
            content = it.get("content", "")
            if not title:
                title = self._extract_title(content)
            out.append({
                "source_name": "央视新闻联播",
                "title": title,
                "content": content,
                "timestamp": self._normalize_timestamp(it.get("date")),
                "url": None,
                "tags": ["央视", "时事"],
            })
        return out

    def _parse_shmet(self, items: list[dict]) -> list[dict]:
        out = []
        for it in items:
            content = it.get("内容", "")
            out.append({
                "source_name": "上海金属网",
                "title": self._extract_title(content),
                "content": content,
                "timestamp": self._normalize_timestamp(it.get("发布时间")),
                "url": None,
                "tags": ["期货", "金属"],
            })
        return out

    def _parse_cls_summary(self, items: list[dict]) -> list[dict]:
        out = []
        for it in items:
            summary = it.get("summary", "")
            tag = it.get("tag", "")
            out.append({
                "source_name": "财联社电报(摘要)",
                "title": self._extract_title(summary),
                "content": summary,
                "timestamp": None,
                "url": it.get("url"),
                "tags": [tag] if tag else ["财联社"],
            })
        return out

    def _parse_cls_full(self, items: list[dict]) -> list[dict]:
        out = []
        for it in items:
            title = it.get("标题", "")
            content = it.get("内容", "")
            if not title:
                title = self._extract_title(content)
            date_part = str(it.get("发布日期", ""))
            time_part = str(it.get("发布时间", ""))
            if date_part and time_part:
                try:
                    dt = datetime.strptime(date_part[:10], "%Y-%m-%d")
                    parts = time_part.split(":")
                    dt = dt.replace(
                        hour=int(parts[0]),
                        minute=int(parts[1]),
                        second=int(parts[2].split(".")[0]),
                    )
                    ts = dt.isoformat()
                except Exception:
                    ts = self._normalize_timestamp(date_part)
            else:
                ts = self._normalize_timestamp(date_part or None)
            out.append({
                "source_name": "财联社电报",
                "title": title,
                "content": content,
                "timestamp": ts,
                "url": None,
                "tags": ["财联社"],
            })
        return out

    def _parse_em(self, items: list[dict]) -> list[dict]:
        out = []
        for it in items:
            title = it.get("标题", "")
            content = it.get("摘要", "")
            if not title:
                title = self._extract_title(content)
            out.append({
                "source_name": "东方财富快讯",
                "title": title,
                "content": content,
                "timestamp": self._normalize_timestamp(it.get("发布时间")),
                "url": it.get("链接"),
                "tags": ["东方财富", "财经"],
            })
        return out

    def _parse_futu(self, items: list[dict]) -> list[dict]:
        out = []
        for it in items:
            title = it.get("标题", "")
            content = it.get("内容", "")
            if not title:
                title = self._extract_title(content)
            out.append({
                "source_name": "富途快讯",
                "title": title,
                "content": content,
                "timestamp": self._normalize_timestamp(it.get("发布时间")),
                "url": it.get("链接"),
                "tags": ["富途", "全球"],
            })
        return out

    def _parse_ths(self, items: list[dict]) -> list[dict]:
        out = []
        for it in items:
            title = it.get("标题", "")
            content = it.get("内容", "")
            if not title:
                title = self._extract_title(content)
            out.append({
                "source_name": "同花顺直播",
                "title": title,
                "content": content,
                "timestamp": self._normalize_timestamp(it.get("发布时间")),
                "url": it.get("链接"),
                "tags": ["同花顺", "财经"],
            })
        return out

    _PARSER_MAP: dict[str, Callable] = {
        "stock_info_global_sina": _parse_sina,
        "news_cctv": _parse_cctv,
        "futures_news_shmet": _parse_shmet,
        "stock_news_main_cx": _parse_cls_summary,
        "stock_info_global_cls": _parse_cls_full,
        "stock_info_global_em": _parse_em,
        "stock_info_global_futu": _parse_futu,
        "stock_info_global_ths": _parse_ths,
    }

    # ── 核心获取逻辑 ────────────────────────────────────────

    async def _fetch_one(
        self, client: httpx.AsyncClient, endpoint: str
    ) -> list[dict]:
        cfg = self.SOURCE_REGISTRY[endpoint]
        url = f"{self.base_url}/{endpoint}"
        params = cfg["params"]() if callable(cfg["params"]) else None
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        items = self._to_list(resp.json())
        parser = self._PARSER_MAP[endpoint]
        return parser(self, items)

    async def fetch_all(self) -> tuple[list[dict], dict[str, dict]]:
        """
        并发获取所有信源并内存去重。

        Returns
        -------
        (items, sources_status)
            items: 去重后的标准格式新闻列表
            sources_status: {endpoint: {ok, count, error, display_name}}
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            tasks = [
                self._fetch_one(client, ep) for ep in self.SOURCE_REGISTRY
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        all_items: list[dict] = []
        sources_status: dict[str, dict] = {}
        self._seen_hashes.clear()

        for ep, result in zip(self.SOURCE_REGISTRY, results):
            cfg = self.SOURCE_REGISTRY[ep]
            if isinstance(result, Exception):
                sources_status[ep] = {
                    "ok": False, "count": 0,
                    "error": str(result), "display_name": cfg["display"],
                }
                logger.error("[%s] %s", ep, result)
            else:
                sources_status[ep] = {
                    "ok": True, "count": len(result),
                    "error": None, "display_name": cfg["display"],
                }
                all_items.extend(result)

        all_items.sort(key=lambda x: x.get("timestamp") or "", reverse=True)

        # 按归一化标题分组去重：同标题只保留内容最长的版本
        groups: dict[str, dict] = {}
        for item in all_items:
            h = self._dedup_hash(item["title"], item["content"])
            if h not in groups or len(item.get("content", "")) > len(groups[h].get("content", "")):
                groups[h] = item

        deduped = sorted(groups.values(), key=lambda x: x.get("timestamp") or "", reverse=True)

        return deduped, sources_status

    def _is_duplicate(self, title: str, content: str) -> bool:
        h = self._dedup_hash(title, content)
        if h in self._seen_hashes:
            return True
        self._seen_hashes.add(h)
        return False

    # ── 抓取 + 入库 一体化 ─────────────────────────────────

    def fetch_and_store(self, purge_days: int = 30) -> dict:
        """
        抓取 -> 去重 -> 入库（只存新增） -> 清理过期。

        Returns
        -------
        dict with keys: total_raw, new_added, purged, sources_status, fetch_time, new_row_ids
        """
        items, sources_status = self._run_fetch_all()
        total_raw = sum(s["count"] for s in sources_status.values())
        new_added, new_row_ids = self.db.insert_many(items)
        purged = self.db.purge_old(days=purge_days)

        logger.info(
            "抓取完成: 原始 %d 条, 新增 %d 条, 过期清理 %d 条",
            total_raw, new_added, purged,
        )

        return {
            "total_raw": total_raw,
            "new_added": new_added,
            "purged": purged,
            "db_total": self.db.get_total_count(),
            "sources_status": sources_status,
            "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "new_items": items,
            "new_row_ids": new_row_ids,
        }

    def _run_fetch_all(self) -> tuple[list[dict], dict[str, dict]]:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, self.fetch_all()).result()
        return asyncio.run(self.fetch_all())
