"""URL 安全校验工具

防止 SSRF 攻击：校验 URL scheme、域名、IP 地址。
重定向时逐跳校验，防止通过 302 绕过内网限制。
"""
import ipaddress
import logging
import re
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# 禁止的 scheme
BLOCKED_SCHEMES = {"file", "gopher", "ftp", "ssh", "telnet", "dict", "ldap", "ldaps"}

# 允许的 scheme
ALLOWED_SCHEMES = {"http", "https"}

# 私有/保留 IP 范围
PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),       # Loopback
    ipaddress.ip_network("10.0.0.0/8"),         # Class A private
    ipaddress.ip_network("172.16.0.0/12"),      # Class B private
    ipaddress.ip_network("192.168.0.0/16"),     # Class C private
    ipaddress.ip_network("169.254.0.0/16"),     # Link-local
    ipaddress.ip_network("::1/128"),            # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),           # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),          # IPv6 link-local
]

MAX_REDIRECTS = 5


def is_private_ip(ip_str: str) -> bool:
    """检查 IP 是否属于私有/保留地址范围"""
    try:
        ip = ipaddress.ip_address(ip_str)
        return any(ip in network for network in PRIVATE_NETWORKS)
    except ValueError:
        return False


def resolve_hostname(hostname: str) -> list[str]:
    """DNS 解析域名，返回所有 IP 地址"""
    import socket
    try:
        results = socket.getaddrinfo(hostname, None)
        return list({r[4][0] for r in results})
    except socket.gaierror:
        return []


def validate_url(url: str) -> tuple[bool, str]:
    """校验 URL 是否安全（防 SSRF）。

    返回 (is_safe, error_message)
    """
    if not url or not isinstance(url, str):
        return False, "URL 不能为空"

    url = url.strip()

    # 自动补全 https://
    if not re.match(r'^[a-zA-Z]+://', url):
        url = "https://" + url

    try:
        parsed = urlparse(url)
    except Exception:
        return False, "URL 格式无效"

    # 检查 scheme
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        return False, f"不支持的协议: {parsed.scheme}，仅允许 http/https"

    hostname = parsed.hostname
    if not hostname:
        return False, "URL 缺少主机名"

    # 检查 hostname 是否为 IP
    try:
        ip = ipaddress.ip_address(hostname)
        if is_private_ip(str(ip)):
            return False, f"不允许访问内网地址: {hostname}"
    except ValueError:
        pass  # 不是 IP，继续检查域名

    # 检查特殊域名
    hostname_lower = hostname.lower()
    blocked_hostnames = {
        "localhost", "localhost.localdomain",
        "ip6-localhost", "ip6-loopback",
    }
    if hostname_lower in blocked_hostnames:
        return False, f"不允许访问: {hostname}"

    # DNS 解析后二次校验（防 DNS 重绑定）
    ips = resolve_hostname(hostname)
    for ip_str in ips:
        if is_private_ip(ip_str):
            logger.warning("DNS 解析 %s 得到内网 IP: %s（已拒绝）", hostname, ip_str)
            return False, f"域名 {hostname} 解析到内网地址，不允许访问"

    return True, ""


def safe_http_get(url: str, **kwargs) -> httpx.Response | None:
    """安全的 HTTP GET 请求，自动校验 URL 并逐跳校验重定向。

    返回 Response 或 None（校验失败时）
    """
    is_safe, error = validate_url(url)
    if not is_safe:
        logger.warning("SSRF 防护拦截: %s → %s", url, error)
        return None

    kwargs.setdefault("timeout", 15)
    kwargs["follow_redirects"] = False

    return _follow_with_validation(url, "GET", kwargs)


def safe_http_post(url: str, **kwargs) -> httpx.Response | None:
    """安全的 HTTP POST 请求，自动校验 URL 并逐跳校验重定向。"""
    is_safe, error = validate_url(url)
    if not is_safe:
        logger.warning("SSRF 防护拦截: %s → %s", url, error)
        return None

    kwargs.setdefault("timeout", 15)
    kwargs["follow_redirects"] = False

    return _follow_with_validation(url, "POST", kwargs)


def _follow_with_validation(url: str, method: str, kwargs: dict) -> httpx.Response | None:
    """手动跟随重定向，每跳都做 SSRF 校验。"""
    client_kwargs = {
        "timeout": kwargs.pop("timeout", 15),
        "follow_redirects": False,
    }
    current_url = url

    with httpx.Client(**client_kwargs) as client:
        for hop in range(MAX_REDIRECTS + 1):
            try:
                if method.upper() == "GET":
                    resp = client.get(current_url, **kwargs)
                else:
                    resp = client.post(current_url, **kwargs)
            except httpx.HTTPError as e:
                logger.warning("HTTP 请求失败: %s → %s", current_url, e)
                return None

            if resp.status_code not in (301, 302, 303, 307, 308):
                return resp

            # 跟随重定向前校验目标 URL
            redirect_url = resp.headers.get("location")
            if not redirect_url:
                return resp

            # 处理相对路径重定向
            from urllib.parse import urljoin
            redirect_url = urljoin(current_url, redirect_url)

            is_safe, error = validate_url(redirect_url)
            if not is_safe:
                logger.warning("重定向目标被 SSRF 拦截: %s → %s → %s", current_url, redirect_url, error)
                return None

            logger.debug("重定向 %d: %s → %s", hop + 1, current_url, redirect_url)
            current_url = redirect_url

        logger.warning("重定向次数超过 %d 次上限: %s", MAX_REDIRECTS, url)
        return None
