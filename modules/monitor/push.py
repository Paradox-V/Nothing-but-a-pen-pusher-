"""推送渠道实现

支持：企业微信、钉钉、飞书、PushPlus、Server酱、Bark、
      Telegram Bot、Discord Webhook、ntfy、通用 Webhook
"""

import hashlib
import hmac
import base64
import time
import urllib.parse
import re

import httpx


def send_push(content: str, channel: dict) -> tuple[bool, str]:
    """发送推送消息到指定渠道。

    Args:
        content: Markdown 格式的推送内容
        channel: {"type": "wecom"|"dingtalk"|..., "url": "...", "secret": "..."}

    Returns:
        (success: bool, error: str)
    """
    channel_type = channel.get("type", "")
    handler = _CHANNELS.get(channel_type)
    if not handler:
        return False, f"不支持的渠道类型: {channel_type}"

    try:
        return handler(content, channel)
    except Exception as e:
        return False, str(e)


# ── 内部工具 ──────────────────────────────────────────────────────────

def _extract_title(content: str, fallback: str = "信源汇总监控报告") -> str:
    """从 Markdown 内容提取第一行作为标题。"""
    for line in content.strip().splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line[:100]
    return fallback


def _strip_markdown(content: str) -> str:
    """简单去除 Markdown 标记，用于不支持 Markdown 的渠道。"""
    text = re.sub(r"^#{1,6}\s+", "", content, flags=re.MULTILINE)
    text = re.sub(r"\*{1,2}(.*?)\*{1,2}", r"\1", text)
    text = re.sub(r"`{1,3}(.*?)`{1,3}", r"\1", text)
    return text


# ── 企业微信 ──────────────────────────────────────────────────────────

def _send_wecom(content: str, channel: dict) -> tuple[bool, str]:
    url = channel.get("url", "")
    if not url:
        return False, "缺少 webhook URL"

    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    resp = httpx.post(url, json=payload, timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        if data.get("errcode") == 0:
            return True, ""
        return False, data.get("errmsg", "unknown error")
    return False, f"HTTP {resp.status_code}"


# ── 钉钉 ──────────────────────────────────────────────────────────────

def _send_dingtalk(content: str, channel: dict) -> tuple[bool, str]:
    url = channel.get("url", "")
    secret = channel.get("secret", "")
    if not url:
        return False, "缺少 webhook URL"

    if secret:
        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(
            secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        url = f"{url}&timestamp={timestamp}&sign={sign}"

    payload = {
        "msgtype": "markdown",
        "markdown": {"title": _extract_title(content), "text": content},
    }
    resp = httpx.post(url, json=payload, timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        if data.get("errcode") == 0:
            return True, ""
        return False, data.get("errmsg", "unknown error")
    return False, f"HTTP {resp.status_code}"


# ── 飞书 / Lark ───────────────────────────────────────────────────────

def _send_feishu(content: str, channel: dict) -> tuple[bool, str]:
    url = channel.get("url", "")
    if not url:
        return False, "缺少 webhook URL"

    # 飞书自定义机器人支持富文本卡片
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": _extract_title(content)},
            },
            "elements": [
                {"tag": "markdown", "content": content},
            ],
        },
    }
    resp = httpx.post(url, json=payload, timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        if data.get("code") in (0, None) and data.get("msg") == "success" or data.get("StatusCode") == 0:
            return True, ""
        return False, data.get("msg", str(data))
    return False, f"HTTP {resp.status_code}"


# ── PushPlus ──────────────────────────────────────────────────────────

def _send_pushplus(content: str, channel: dict) -> tuple[bool, str]:
    token = channel.get("secret", "") or channel.get("url", "")
    if not token:
        return False, "缺少 PushPlus Token（填在 Secret 或 URL 字段）"

    payload = {
        "token": token,
        "title": _extract_title(content),
        "content": content,
        "template": "markdown",
    }
    resp = httpx.post("https://www.pushplus.plus/send", json=payload, timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        if data.get("code") == 200:
            return True, ""
        return False, data.get("msg", "unknown error")
    return False, f"HTTP {resp.status_code}"


# ── Server酱 (ServerChan) ────────────────────────────────────────────

def _send_serverchan(content: str, channel: dict) -> tuple[bool, str]:
    sendkey = channel.get("secret", "") or channel.get("url", "")
    if not sendkey:
        return False, "缺少 Server酱 SendKey（填在 Secret 或 URL 字段）"

    payload = {
        "title": _extract_title(content),
        "desp": content,
    }
    resp = httpx.post(f"https://sctapi.ftqq.com/{sendkey}.send", json=payload, timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        if data.get("code") == 0:
            return True, ""
        return False, data.get("message", "unknown error")
    return False, f"HTTP {resp.status_code}"


# ── Bark (iOS) ────────────────────────────────────────────────────────

def _send_bark(content: str, channel: dict) -> tuple[bool, str]:
    url = channel.get("url", "")
    if not url:
        return False, "缺少 Bark URL（如 https://api.day.app/yourkey）"

    # 去掉末尾斜杠
    url = url.rstrip("/")

    payload = {
        "title": _extract_title(content),
        "body": _strip_markdown(content),
        "group": "pen-pusher",
    }
    resp = httpx.post(url, json=payload, timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        if data.get("code") == 200:
            return True, ""
        return False, data.get("message", "unknown error")
    return False, f"HTTP {resp.status_code}"


# ── Telegram Bot ──────────────────────────────────────────────────────

def _send_telegram(content: str, channel: dict) -> tuple[bool, str]:
    url = channel.get("url", "")
    secret = channel.get("secret", "")  # chat_id
    if not url:
        return False, "缺少 Telegram Bot Token URL"
    if not secret:
        return False, "缺少 Chat ID（填在 Secret 字段）"

    # url 字段填 bot token，自动拼接 API 地址
    token = url.rstrip("/")
    if "api.telegram.org" not in token:
        api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    else:
        api_url = token

    payload = {
        "chat_id": secret,
        "text": content,
        "parse_mode": "Markdown",
    }
    resp = httpx.post(api_url, json=payload, timeout=15)
    if resp.status_code == 200:
        data = resp.json()
        if data.get("ok"):
            return True, ""
        return False, data.get("description", "unknown error")
    return False, f"HTTP {resp.status_code}"


# ── Discord Webhook ──────────────────────────────────────────────────

def _send_discord(content: str, channel: dict) -> tuple[bool, str]:
    url = channel.get("url", "")
    if not url:
        return False, "缺少 Discord Webhook URL"

    # Discord 消息最大 2000 字符
    text = content[:2000] if len(content) > 2000 else content

    payload = {
        "content": text,
        "username": "信源汇总",
    }
    resp = httpx.post(url, json=payload, timeout=10)
    # Discord 成功返回 204 No Content
    if resp.status_code in (200, 204):
        return True, ""
    return False, f"HTTP {resp.status_code}"


# ── ntfy ──────────────────────────────────────────────────────────────

def _send_ntfy(content: str, channel: dict) -> tuple[bool, str]:
    url = channel.get("url", "")
    if not url:
        return False, "缺少 ntfy URL（如 https://ntfy.sh/your-topic）"

    text = _strip_markdown(content)

    headers = {
        "Title": _extract_title(content),
        "Priority": "default",
    }
    resp = httpx.post(url, content=text.encode("utf-8"), headers=headers, timeout=10)
    if resp.status_code in (200, 204):
        return True, ""
    return False, f"HTTP {resp.status_code}"


# ── WCF / wcfLink (个人微信) ────────────────────────────────────────

def _send_wcf(content: str, channel: dict) -> tuple[bool, str]:
    """通过 wcfLink HTTP API 发送文本消息到个人微信。

    支持两种格式：
    - 新格式（推荐）：channel 直接带 account_id + to_user_id，url 为空时读 config
    - 旧格式（兼容）：url + secret=account_id::to_user_id
    """
    account_id = channel.get("account_id", "")
    to_user_id = channel.get("to_user_id", "")
    context_token = channel.get("context_token", "")
    url = channel.get("url", "")
    secret = channel.get("secret", "")

    # 旧格式兼容：url + secret=account_id::to_user_id
    if not account_id or not to_user_id:
        if not secret:
            return False, "缺少账号信息（Secret 填 account_id::to_user_id）"
        parts = secret.split("::", 1)
        if len(parts) == 2:
            account_id, to_user_id = parts[0].strip(), parts[1].strip()
        else:
            account_id = ""
            to_user_id = secret.strip()

    # URL：新格式未给 url 时默认读 config.wcf.url
    if not url:
        from utils.config import load_config
        config = load_config()
        url = config.get("wcf", {}).get("url", "")
    if not url:
        return False, "缺少 wcfLink 地址（config.yaml wcf.url 或渠道 URL）"

    url = url.rstrip("/")
    text = _strip_markdown(content)

    payload = {"account_id": account_id, "to_user_id": to_user_id, "text": text}
    if context_token:
        payload["context_token"] = context_token
    resp = httpx.post(f"{url}/api/messages/send-text", json=payload, timeout=10)
    if resp.status_code == 200:
        return True, ""
    return False, f"HTTP {resp.status_code}: {resp.text[:200]}"


# ── 通用 Webhook ──────────────────────────────────────────────────────

def _send_generic(content: str, channel: dict) -> tuple[bool, str]:
    url = channel.get("url", "")
    if not url:
        return False, "缺少 webhook URL"

    payload = {
        "title": _extract_title(content),
        "content": content,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    resp = httpx.post(url, json=payload, timeout=10)
    if resp.status_code == 200:
        return True, ""
    return False, f"HTTP {resp.status_code}"


# ── 渠道注册表 ────────────────────────────────────────────────────────

_CHANNELS = {
    "wecom":      _send_wecom,
    "dingtalk":   _send_dingtalk,
    "feishu":     _send_feishu,
    "pushplus":   _send_pushplus,
    "serverchan": _send_serverchan,
    "bark":       _send_bark,
    "telegram":   _send_telegram,
    "discord":    _send_discord,
    "ntfy":       _send_ntfy,
    "wcf":        _send_wcf,
    "generic":    _send_generic,
}
