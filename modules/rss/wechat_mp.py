"""微信公众号 RSS 转化工具

三级 Fallback 策略：
  Level 1 — RSSHub 官方路由（提取 __biz）
  Level 2 — 外部 WeRSS 服务（配置 wechat_mp.werss_url）
  Level 3 — 自定义服务（配置 wechat_mp.service_url）
"""

import logging
import re
from urllib.parse import urlparse, parse_qs

import httpx

logger = logging.getLogger(__name__)


class WechatMPConverter:
    """微信公众号 URL/名称 → RSS Feed URL 转化器。"""

    def __init__(self, rsshub_base_url: str = "http://127.0.0.1:1200",
                 wechat_mp_config: dict | None = None):
        self.rsshub_base_url = rsshub_base_url.rstrip("/")
        self.config = wechat_mp_config or {}

    def is_wechat_mp_url(self, url: str) -> bool:
        """判断是否为微信公众号链接（使用域名精确匹配，防止子字符串欺骗）。"""
        try:
            from urllib.parse import urlparse
            hostname = urlparse(url).hostname or ""
            return hostname == "mp.weixin.qq.com" or hostname.endswith(".mp.weixin.qq.com")
        except Exception:
            return False

    def extract_biz(self, url: str) -> str | None:
        """从公众号主页 URL 中提取 __biz 参数。"""
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        biz = params.get("__biz")
        if biz:
            return biz[0]
        # 尝试从 fragment 中匹配
        match = re.search(r"__biz=([^&]+)", url)
        return match.group(1) if match else None

    def to_rss_url(self, url_or_name: str) -> dict:
        """将微信公众号 URL 或名称转化为 RSS Feed URL。

        Returns:
            {
                "success": bool,
                "feed_url": str,
                "name": str,
                "method": str,  # rsshub | werss | custom
                "error": str    # 失败时
            }
        """
        method = self.config.get("method", "rsshub")

        # Level 1: RSSHub
        if method in ("rsshub", "auto"):
            result = self._try_rsshub(url_or_name)
            if result.get("success"):
                return result
            if method == "rsshub":
                return result

        # Level 2: WeRSS
        werss_url = self.config.get("werss_url", "")
        if werss_url and method in ("werss", "auto"):
            result = self._try_werss(url_or_name, werss_url)
            if result.get("success"):
                return result
            if method == "werss":
                return result

        # Level 3: 自定义服务
        service_url = self.config.get("service_url", "")
        if service_url and method in ("custom", "auto"):
            return self._try_custom(url_or_name, service_url)

        return {
            "success": False,
            "error": "未找到可用的微信公众号 RSS 转化服务，"
                     "请在 config.yaml 中配置 wechat_mp 段",
        }

    def _try_rsshub(self, url_or_name: str) -> dict:
        """尝试通过 RSSHub 路由生成 RSS URL。"""
        biz = None
        name = url_or_name

        if self.is_wechat_mp_url(url_or_name):
            biz = self.extract_biz(url_or_name)
            name = "微信公众号"
        elif not url_or_name.startswith("http"):
            # 当作公众号名称 — RSSHub 不直接支持名称搜索，返回失败
            return {"success": False, "error": "RSSHub 不支持通过公众号名称查找，请提供公众号主页链接"}

        if not biz:
            return {"success": False, "error": "无法从链接中提取 __biz 参数，请确认链接为公众号主页地址"}

        feed_url = f"{self.rsshub_base_url}/wechat/mp/id/{biz}"

        # 验证 Feed 可访问性
        try:
            resp = httpx.get(feed_url, timeout=8, follow_redirects=True)
            if resp.status_code == 200:
                # 尝试从 RSS/Atom 内容中提取标题
                name = self._extract_feed_title(resp.text) or name
                return {
                    "success": True,
                    "feed_url": feed_url,
                    "name": name,
                    "method": "rsshub",
                }
        except Exception as e:
            logger.debug("RSSHub 验证失败: %s", e)

        # 即使无法验证，仍返回生成的 URL（用户可自行判断）
        return {
            "success": True,
            "feed_url": feed_url,
            "name": name,
            "method": "rsshub",
            "warning": "无法连接 RSSHub 验证，请确认 RSSHub 服务是否运行",
        }

    def _try_werss(self, url_or_name: str, werss_base: str) -> dict:
        """尝试通过 WeRSS 服务生成 RSS URL。"""
        werss_base = werss_base.rstrip("/")
        try:
            # WeRSS 支持通过公众号名称搜索
            if not url_or_name.startswith("http"):
                # 名称搜索
                resp = httpx.get(
                    f"{werss_base}/feeds",
                    params={"name": url_or_name},
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("items"):
                        item = data["items"][0]
                        mp_id = item.get("id") or item.get("mp_id", "")
                        if mp_id:
                            feed_url = f"{werss_base}/feeds/{mp_id}.rss"
                            return {
                                "success": True,
                                "feed_url": feed_url,
                                "name": item.get("name", url_or_name),
                                "method": "werss",
                            }
        except Exception as e:
            logger.debug("WeRSS 失败: %s", e)
        return {"success": False, "error": "WeRSS 服务不可用或未找到该公众号"}

    def _try_custom(self, url_or_name: str, service_url: str) -> dict:
        """尝试通过自定义服务转化。"""
        try:
            resp = httpx.post(
                service_url,
                json={"url": url_or_name, "name": url_or_name},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("feed_url"):
                    return {
                        "success": True,
                        "feed_url": data["feed_url"],
                        "name": data.get("name", url_or_name),
                        "method": "custom",
                    }
        except Exception as e:
            logger.debug("自定义服务失败: %s", e)
        return {"success": False, "error": "自定义 RSS 转化服务不可用"}

    @staticmethod
    def _extract_feed_title(xml_text: str) -> str | None:
        """从 RSS/Atom XML 中提取 title，优先使用 stdlib XML 解析。"""
        # 尝试用 feedparser（更健壮）
        try:
            import feedparser
            parsed = feedparser.parse(xml_text)
            title = parsed.feed.get("title", "").strip()
            if title:
                return title
        except Exception:
            pass

        # Fallback: 用 defusedxml 解析（防止 XXE 攻击）
        try:
            import defusedxml.ElementTree as ET
            root = ET.fromstring(xml_text)
            # RSS 2.0: channel/title
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for path in ("./channel/title", "./atom:title"):
                try:
                    elem = root.find(path, ns)
                    if elem is not None and elem.text:
                        return elem.text.strip()
                except Exception:
                    pass
        except Exception:
            pass

        return None
