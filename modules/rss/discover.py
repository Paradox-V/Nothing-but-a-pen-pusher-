# coding=utf-8
"""
RSSHub 站点发现引擎

根据用户输入的网站 URL，通过域名映射表匹配 RSSHub 路由，
调用自建 RSSHub 实例获取预览信息。
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote, urlparse

import httpx

from utils.url_security import validate_url

logger = logging.getLogger(__name__)


class RSSHubDiscover:
    """RSSHub 站点发现引擎。

    config 结构（来自 config.yaml 的 rsshub 段）:
    {
        "base_url": "http://127.0.0.1:1200",
        "sites": {
            "36kr.com": {
                "name": "36氪",
                "routes": [{"path": "/36kr/newsflashes", "name": "快讯"}]
            },
            ...
        }
    }
    """

    def __init__(self, config: dict):
        self.base_url = config.get("base_url", "http://127.0.0.1:1200").rstrip("/")
        self.sites = config.get("sites", {})
        self.timeout = 10

    def discover(self, url: str) -> dict:
        """主入口：输入用户 URL，返回可订阅的路由列表。

        Returns:
            {"success": bool, "site_name": str, "domain": str, "routes": [...]}
        """
        # 0. SSRF 校验
        is_safe, error = validate_url(url)
        if not is_safe:
            return {"success": False, "error": f"URL 校验失败: {error}"}

        # 1. 提取域名
        domain = self._extract_domain(url)
        if not domain:
            return {"success": False, "error": "请输入有效的网站地址"}

        # 2. 匹配映射表
        site_key, site_config = self._match_site(domain)
        if not site_config:
            # 回退：尝试通用 HTML 转换
            return self.generic_discover(url)

        site_name = site_config.get("name", site_key)
        routes_config = site_config.get("routes", [])

        if not routes_config:
            return {
                "success": False,
                "error": "该网站暂无可订阅内容",
            }

        # 3. 并发获取每个路由的预览
        result_routes = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_idx = {
                executor.submit(self._preview_route, route): idx
                for idx, route in enumerate(routes_config)
            }
            ordered = [None] * len(routes_config)
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                ordered[idx] = future.result()

        for idx, route_result in enumerate(ordered):
            if route_result is not None:
                route_result["key"] = str(idx)
                result_routes.append(route_result)

        return {
            "success": True,
            "site_name": site_name,
            "domain": domain,
            "routes": result_routes,
        }

    def _extract_domain(self, url: str) -> str:
        """从 URL 提取域名。

        支持:
            https://www.36kr.com/news → www.36kr.com
            36kr.com → 36kr.com
            www.36kr.com/path → www.36kr.com
        """
        url = url.strip()
        if not url:
            return ""

        # 自动补全协议
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        try:
            parsed = urlparse(url)
            domain = parsed.hostname or ""
            return domain.lower()
        except (ValueError, AttributeError):
            return ""

    def _match_site(self, domain: str) -> tuple:
        """后缀匹配映射表，优先匹配最长的域名。

        要求匹配在 label 边界上：
            www.36kr.com 匹配 36kr.com ✓
            example.com 不匹配 36kr.com ✗
            my36kr.com 不匹配 36kr.com ✗
            pbc.gov.cn 优先匹配 pbc.gov.cn 而非 gov.cn ✓

        Returns:
            (site_key, site_config) 或 (None, None)
        """
        domain_parts = domain.split(".")
        best_key, best_config, best_len = None, None, 0

        for site_key, site_config in self.sites.items():
            site_parts = site_key.split(".")
            if len(domain_parts) >= len(site_parts) > best_len:
                if domain_parts[-len(site_parts):] == site_parts:
                    best_key, best_config, best_len = site_key, site_config, len(site_parts)

        return best_key, best_config

    def _preview_route(self, route: dict) -> dict:
        """调用 RSSHub 获取单条路由预览。

        Args:
            route: {"path": "/36kr/newsflashes", "name": "快讯"}

        Returns:
            成功: {"name": str, "feed_url": str, "sample_items": [...], "item_count": int}
            失败: {"name": str, "error": str, "sample_items": [], "item_count": 0}
        """
        path = route["path"]
        name = route.get("name", path)
        feed_url = f"{self.base_url}{path}"

        try:
            resp = httpx.get(
                f"{feed_url}?format=json",
                timeout=self.timeout,
                headers={"User-Agent": "NewsAggregator/1.0 RSS Reader"},
            )
            resp.raise_for_status()
            data = resp.json()

            items_data = data.get("items", [])
            sample_items = []
            for item in items_data[:3]:
                sample_items.append({
                    "title": item.get("title", ""),
                    "url": item.get("link", item.get("url", "")),
                    "published_at": item.get("pubDate", item.get("date_published", "")),
                })

            return {
                "name": name,
                "feed_url": feed_url,
                "sample_items": sample_items,
                "item_count": len(items_data),
            }

        except httpx.TimeoutException:
            logger.warning("RSSHub 路由 %s 超时", path)
            return {
                "name": name,
                "error": "请求超时",
                "sample_items": [],
                "item_count": 0,
            }
        except (httpx.HTTPStatusError, httpx.RequestError, ValueError) as e:
            return {
                "name": name,
                "error": "获取失败",
                "sample_items": [],
                "item_count": 0,
            }

    # ── 通用 HTML 转换（Direction A：未匹配映射表时的回退） ─────

    # 自动尝试的 CSS 选择器列表：(标签, CSS 选择器)
    _AUTO_SELECTORS = [
        ("文章", "article"),
        ("标题", "h2, h3"),
    ]

    def generic_discover(self, url: str, item_selector: str = None, title_selector: str = None) -> dict:
        """通用 HTML 转换回退：通过 RSSHub transform 路由生成 RSS 源。

        Args:
            url: 目标网站 URL
            item_selector: 可选的自定义 CSS 选择器，为 None 时自动尝试
            title_selector: 可选的标题 CSS 选择器

        Returns:
            与 discover() 相同格式的结果字典
        """
        # SSRF 校验
        is_safe, error = validate_url(url)
        if not is_safe:
            return {"success": False, "error": f"URL 校验失败: {error}"}

        original_url = url.strip()
        if not original_url.startswith(("http://", "https://")):
            original_url = "https://" + original_url

        domain = self._extract_domain(original_url)
        if not domain:
            return {"success": False, "error": "请输入有效的网站地址"}

        encoded_url = quote(original_url, safe="")

        if item_selector:
            # 用户自定义选择器
            results = [
                self._try_html_transform(encoded_url, "自定义", item_selector, title_selector)
            ]
        else:
            # 并行自动尝试多个选择器
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = [
                    executor.submit(
                        self._try_html_transform, encoded_url, label, selector
                    )
                    for label, selector in self._AUTO_SELECTORS
                ]
                results = [f.result() for f in futures]

        # 找出返回条目最多的结果
        valid = [r for r in results if r and r.get("item_count", 0) > 0]
        if not valid:
            return {
                "success": False,
                "error": "未能自动识别页面结构，可尝试手动输入 CSS 选择器",
                "generic_available": True,
                "domain": domain,
            }

        best = max(valid, key=lambda r: r.get("item_count", 0))
        best["key"] = "0"
        site_name = best.pop("_site_name", domain)

        return {
            "success": True,
            "site_name": site_name,
            "domain": domain,
            "routes": [best],
            "generic": True,
        }

    def _try_html_transform(
        self, encoded_url: str, label: str, item_selector: str, title_selector: str = None
    ) -> dict | None:
        """调用 RSSHub HTML transform 路由尝试单个选择器。"""
        route_params = f"item={quote(item_selector, safe='')}"
        if title_selector:
            route_params += f"&title={quote(title_selector, safe='')}"
        feed_url = f"{self.base_url}/rsshub/transform/html/{encoded_url}/{route_params}"

        try:
            resp = httpx.get(
                f"{feed_url}?format=json",
                timeout=self.timeout,
                headers={"User-Agent": "NewsAggregator/1.0 RSS Reader"},
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            items = data.get("items", [])
            if not items:
                return None

            sample_items = [
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", item.get("link", "")),
                    "published_at": item.get("date_published", ""),
                }
                for item in items[:3]
            ]

            return {
                "name": f"自动发现 ({label})",
                "feed_url": feed_url,
                "sample_items": sample_items,
                "item_count": len(items),
                "_site_name": data.get("title", ""),
            }
        except (httpx.HTTPStatusError, httpx.RequestError, ValueError, KeyError):
            return None
