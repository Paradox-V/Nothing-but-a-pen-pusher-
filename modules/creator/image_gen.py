"""
文案创作模块 - 豆包 Seedream API 配图

移植自 ms-DYP 的 image_generator.py，简化版：
- 使用 REST API（不需要 OpenAI SDK）
- 图片直接返回 URL（不上传 OSS）
- 支持文章智能分段配图
"""

import logging
import re
from typing import Any

import requests

logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_MODEL = "doubao-seedream-5-0-260128"
DEFAULT_SIZE = "2560x1440"  # 16:9
DEFAULT_TIMEOUT = 180
MAX_IMAGES = 5


def _load_config() -> dict:
    """从 config.yaml 加载配图配置"""
    try:
        from utils.config import load_config
        cfg = load_config()
        return cfg.get("creator", {}).get("image", {})
    except Exception:
        return {}


def generate_images(article: str, n: int = 1) -> list[str]:
    """
    根据文章内容智能分段生成 n 张配图。

    Args:
        article: 完整文章内容
        n: 图片数量（1-5）

    Returns:
        图片 URL 列表
    """
    n = max(1, min(MAX_IMAGES, n))

    cfg = _load_config()
    base_url = cfg.get("base_url", DEFAULT_BASE_URL).rstrip("/")
    api_key = cfg.get("api_key", "")
    model = cfg.get("model", DEFAULT_MODEL)
    size = cfg.get("size", DEFAULT_SIZE)
    timeout = cfg.get("timeout", DEFAULT_TIMEOUT)

    if not api_key:
        logger.warning("未配置豆包 API key，跳过配图")
        return []

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # 智能分段
    segments = _split_article(article, n)
    urls = []

    for i, segment in enumerate(segments):
        prompt = _build_prompt(segment)
        logger.info("生成配图 %d/%d: %s...", i + 1, n, prompt[:50])

        try:
            resp = requests.post(
                f"{base_url}/images/generations",
                headers=headers,
                json={
                    "model": model,
                    "prompt": prompt,
                    "response_format": "url",
                    "size": size,
                    "stream": False,
                    "watermark": False,
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("data", []):
                url = item.get("url", "")
                if url:
                    urls.append(url)

        except Exception as e:
            logger.error("配图 %d 生成失败: %s", i + 1, e)

    return urls


def _split_article(content: str, n: int) -> list[dict]:
    """将文章分割为 n 个片段"""
    # 清理文本
    clean = re.sub(r"<[^>]+>", "", content)
    clean = re.sub(r"\s+", " ", clean).strip()

    # 提取标题
    title_match = re.match(r"^([^。！？\n]{5,50})", clean)
    article_title = title_match.group(1).strip() if title_match else "文章"

    # 按段落分割
    paragraphs = re.split(r"\n\s*\n|\n", clean)
    paragraphs = [p.strip() for p in paragraphs if len(p.strip()) >= 30]

    segments = []

    if len(paragraphs) >= n:
        selected = paragraphs[:n]
    else:
        # 段落不足，按字数均分
        chunk_size = max(200, len(clean) // n)
        selected = []
        for i in range(n):
            start = i * chunk_size
            end = min(start + chunk_size, len(clean))
            chunk = clean[start:end].strip()
            if chunk:
                selected.append(chunk)
            else:
                selected.append(article_title)

    for i, para in enumerate(selected[:n]):
        first_sentence = _extract_first_sentence(para)
        segments.append({
            "index": i,
            "article_title": article_title,
            "content": para[:400],
            "first_sentence": first_sentence,
            "position": _position_desc(i, n),
        })

    return segments


def _extract_first_sentence(text: str) -> str:
    match = re.match(r"^([^。！？]+[。！？])", text)
    if match:
        return match.group(1)
    return text[:50] + ("..." if len(text) > 50 else "")


def _position_desc(index: int, total: int) -> str:
    if total == 1:
        return "封面配图"
    if index == 0:
        return "文章开篇配图"
    if index == total - 1:
        return "文章结尾配图"
    return f"文章第{['一', '二', '三', '四', '五'][index]}部分配图"


def _build_prompt(segment: dict) -> str:
    """为每个片段构建差异化 prompt"""
    position = segment["position"]
    first_sentence = segment["first_sentence"]
    content = segment["content"]
    article_title = segment["article_title"]

    if "封面" in position or "开篇" in position:
        return (
            f"为文章《{article_title}》创作{position}。\n\n"
            f"【核心内容】{first_sentence}\n\n"
            f"【详细内容】{content}\n\n"
            "【配图要求】\n"
            "1. 封面/开篇配图，需有视觉冲击力\n"
            "2. 画面构图大气、层次分明\n"
            "3. 色彩鲜明，现代简约风格\n"
            "4. 画面元素紧密呼应文章主题\n"
            "5. 不要在图中添加任何文字"
        )
    elif "结尾" in position:
        return (
            f"为文章《{article_title}》创作{position}。\n\n"
            f"【核心内容】{first_sentence}\n\n"
            f"【详细内容】{content}\n\n"
            "【配图要求】\n"
            "1. 结尾配图，有总结升华感\n"
            "2. 色调温暖或沉稳\n"
            "3. 画面简洁有力，点明主旨\n"
            "4. 不要在图中添加任何文字"
        )
    else:
        return (
            f"为文章《{article_title}》创作{position}。\n\n"
            f"【核心内容】{first_sentence}\n\n"
            f"【详细内容】{content}\n\n"
            "【配图要求】\n"
            "1. 文章中间配图，配合上下文\n"
            "2. 画面内容与段落主题紧密相关\n"
            "3. 风格与前后配图保持一致\n"
            "4. 色调和谐，不突兀\n"
            "5. 不要在图中添加任何文字"
        )
