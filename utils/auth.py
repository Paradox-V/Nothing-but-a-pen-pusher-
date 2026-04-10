"""统一鉴权工具

通过 ADMIN_TOKEN 环境变量配置管理员令牌。
请求方式：Header  Authorization: Bearer <token>

开发模式 (FLASK_ENV=development):
  - 未配置 ADMIN_TOKEN 时放行并打印警告
生产模式 (默认):
  - 未配置 ADMIN_TOKEN 时拒绝所有写请求
"""
import os
import logging
from functools import wraps

from flask import request, jsonify

logger = logging.getLogger(__name__)


def _is_dev_mode():
    """判断是否为开发模式"""
    return os.environ.get("FLASK_ENV") == "development"


def require_auth(f):
    """写接口鉴权装饰器。

    - 每次请求动态读取 ADMIN_TOKEN（支持运行时更新）
    - 仅接受 Authorization: Bearer <token> 头
    - 开发模式未配置 Token 时放行并警告
    - 生产模式未配置 Token 时拒绝请求
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        token = os.environ.get("ADMIN_TOKEN", "")

        if not token:
            if _is_dev_mode():
                logger.warning("ADMIN_TOKEN 未配置，写接口不受保护（仅限开发环境）")
                return f(*args, **kwargs)
            else:
                logger.error("ADMIN_TOKEN 未配置，生产环境拒绝写请求")
                return jsonify({"error": "服务未配置管理员令牌，请联系管理员"}), 503

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            client_token = auth_header[7:]
        else:
            client_token = None

        if not client_token or client_token != token:
            logger.warning("鉴权失败: %s %s (来源: %s)",
                           request.method, request.path, request.remote_addr)
            return jsonify({"error": "未授权访问，请提供有效的 Token"}), 401

        return f(*args, **kwargs)
    return decorated
