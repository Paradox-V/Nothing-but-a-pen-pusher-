# coding=utf-8
"""
时间工具模块

提供统一的时间处理函数，所有时区相关操作都使用 DEFAULT_TIMEZONE 常量。
"""

from datetime import datetime

import pytz

# 默认时区常量
DEFAULT_TIMEZONE = "Asia/Shanghai"


def get_configured_time(timezone: str = DEFAULT_TIMEZONE) -> datetime:
    """
    获取配置时区的当前时间

    Args:
        timezone: 时区名称，如 'Asia/Shanghai', 'America/Los_Angeles'

    Returns:
        带时区信息的当前时间
    """
    try:
        tz = pytz.timezone(timezone)
    except pytz.UnknownTimeZoneError:
        print(f"[警告] 未知时区 '{timezone}'，使用默认时区 {DEFAULT_TIMEZONE}")
        tz = pytz.timezone(DEFAULT_TIMEZONE)
    return datetime.now(tz)


def format_iso_time_friendly(
    iso_time: str,
    timezone: str = DEFAULT_TIMEZONE,
    include_date: bool = True,
) -> str:
    """
    将 ISO 格式时间转换为用户时区的友好显示格式

    Args:
        iso_time: ISO 格式时间字符串，如 '2025-12-29T00:20:00' 或 '2025-12-29T00:20:00+00:00'
        timezone: 目标时区名称
        include_date: 是否包含日期部分

    Returns:
        友好格式的时间字符串，如 '12-29 08:20' 或 '08:20'
    """
    if not iso_time:
        return ""

    try:
        dt = None

        # 尝试解析带时区的格式
        if "+" in iso_time or iso_time.endswith("Z"):
            iso_time = iso_time.replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(iso_time)
            except ValueError:
                pass

        # 尝试解析不带时区的格式（假设为 UTC）
        if dt is None:
            try:
                if "T" in iso_time:
                    dt = datetime.fromisoformat(iso_time.replace("T", " ").split(".")[0])
                else:
                    dt = datetime.fromisoformat(iso_time.split(".")[0])
                dt = pytz.UTC.localize(dt)
            except ValueError:
                pass

        if dt is None:
            if "T" in iso_time:
                parts = iso_time.split("T")
                if len(parts) == 2:
                    date_part = parts[0][5:]  # MM-DD
                    time_part = parts[1][:5]  # HH:MM
                    return f"{date_part} {time_part}" if include_date else time_part
            return iso_time

        # 转换到目标时区
        try:
            target_tz = pytz.timezone(timezone)
        except pytz.UnknownTimeZoneError:
            target_tz = pytz.timezone(DEFAULT_TIMEZONE)

        dt_local = dt.astimezone(target_tz)

        if include_date:
            return dt_local.strftime("%m-%d %H:%M")
        else:
            return dt_local.strftime("%H:%M")

    except Exception:
        if "T" in iso_time:
            parts = iso_time.split("T")
            if len(parts) == 2:
                date_part = parts[0][5:]
                time_part = parts[1][:5]
                return f"{date_part} {time_part}" if include_date else time_part
        return iso_time


def is_within_days(
    iso_time: str,
    max_days: int,
    timezone: str = DEFAULT_TIMEZONE,
) -> bool:
    """
    检查 ISO 格式时间是否在指定天数内

    Args:
        iso_time: ISO 格式时间字符串
        max_days: 最大天数
        timezone: 时区名称

    Returns:
        True 如果时间在指定天数内，False 如果超过指定天数
        如果无法解析时间，返回 True
    """
    if not iso_time:
        return True
    if max_days <= 0:
        return True

    try:
        dt = None

        if "+" in iso_time or iso_time.endswith("Z"):
            iso_time_normalized = iso_time.replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(iso_time_normalized)
            except ValueError:
                pass

        if dt is None:
            try:
                if "T" in iso_time:
                    dt = datetime.fromisoformat(iso_time.replace("T", " ").split(".")[0])
                else:
                    dt = datetime.fromisoformat(iso_time.split(".")[0])
                dt = pytz.UTC.localize(dt)
            except ValueError:
                pass

        if dt is None:
            return True

        now = get_configured_time(timezone)
        diff = now - dt
        days_diff = diff.total_seconds() / (24 * 60 * 60)

        return days_diff <= max_days

    except Exception:
        return True
