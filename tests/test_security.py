"""安全工具测试：URL 校验、鉴权"""

import os
from unittest.mock import patch

from utils.url_security import validate_url, is_private_ip


class TestURLSecurity:
    def test_allow_https(self):
        ok, _ = validate_url("https://example.com")
        assert ok

    def test_allow_http(self):
        ok, _ = validate_url("http://example.com")
        assert ok

    def test_block_localhost(self):
        ok, err = validate_url("http://localhost")
        assert not ok
        assert "localhost" in err

    def test_block_127(self):
        ok, err = validate_url("http://127.0.0.1")
        assert not ok

    def test_block_private_10(self):
        ok, err = validate_url("http://10.0.0.1")
        assert not ok

    def test_block_192_168(self):
        ok, err = validate_url("http://192.168.1.1")
        assert not ok

    def test_block_172_16(self):
        ok, err = validate_url("http://172.16.0.1")
        assert not ok

    def test_block_metadata(self):
        ok, err = validate_url("http://169.254.169.254/latest/meta-data/")
        assert not ok

    def test_block_file_scheme(self):
        ok, err = validate_url("file:///etc/passwd")
        assert not ok
        assert "协议" in err

    def test_block_gopher(self):
        ok, err = validate_url("gopher://internal:25/")
        assert not ok

    def test_auto_prepend_https(self):
        ok, _ = validate_url("example.com")
        assert ok

    def test_private_ip_helper(self):
        assert is_private_ip("127.0.0.1")
        assert is_private_ip("10.0.0.1")
        assert is_private_ip("192.168.0.1")
        assert is_private_ip("172.16.0.1")
        assert not is_private_ip("8.8.8.8")
        assert not is_private_ip("1.1.1.1")


class TestAuthDecorator:
    """测试动态 Token 读取与鉴权逻辑"""

    def _run_auth_test(self, admin_token_env, flask_env="", auth_header=None, query_string=None):
        """Helper: 在指定环境变量下测试 require_auth"""
        from flask import Flask
        from utils.auth import require_auth

        app = Flask(__name__)
        called = []

        @app.route("/test")
        @require_auth
        def test_route():
            called.append(True)
            return "ok"

        env = {}
        if admin_token_env:
            env["ADMIN_TOKEN"] = admin_token_env
        if flask_env:
            env["FLASK_ENV"] = flask_env

        with patch.dict(os.environ, env, clear=False):
            with app.test_client() as client:
                headers = {}
                if auth_header is not None:
                    headers["Authorization"] = auth_header
                kwargs = {}
                if headers:
                    kwargs["headers"] = headers
                if query_string:
                    kwargs["query_string"] = query_string
                resp = client.get("/test", **kwargs)

        return resp, called

    def test_dev_no_token_allows(self):
        """开发模式 + 未配置 Token: 放行"""
        resp, called = self._run_auth_test("", "development")
        assert resp.status_code == 200
        assert called

    def test_prod_no_token_blocks(self):
        """生产模式 + 未配置 Token: 拒绝 (503)"""
        resp, called = self._run_auth_test("", "production")
        assert resp.status_code == 503
        assert not called

    def test_bearer_token_correct(self):
        """正确的 Bearer Token: 放行"""
        resp, called = self._run_auth_test(
            "mysecret123", auth_header="Bearer mysecret123"
        )
        assert resp.status_code == 200
        assert called

    def test_bearer_token_wrong(self):
        """错误的 Bearer Token: 拒绝 (401)"""
        resp, called = self._run_auth_test(
            "mysecret123", auth_header="Bearer wrong"
        )
        assert resp.status_code == 401
        assert not called

    def test_no_auth_header(self):
        """缺少 Authorization 头: 拒绝 (401)"""
        resp, called = self._run_auth_test("mysecret123")
        assert resp.status_code == 401
        assert not called

    def test_query_string_token_rejected(self):
        """Query string Token 不再支持: 拒绝 (401)"""
        resp, called = self._run_auth_test(
            "mysecret123", query_string={"token": "mysecret123"}
        )
        assert resp.status_code == 401
        assert not called

    def test_dynamic_token_update(self):
        """运行时修改 ADMIN_TOKEN 环境变量后立即生效"""
        from flask import Flask
        from utils.auth import require_auth

        app = Flask(__name__)

        @app.route("/test")
        @require_auth
        def test_route():
            return "ok"

        # First call with old token
        with patch.dict(os.environ, {"ADMIN_TOKEN": "old_token"}, clear=False):
            with app.test_client() as client:
                resp = client.get("/test", headers={"Authorization": "Bearer old_token"})
                assert resp.status_code == 200

        # Second call with changed token
        with patch.dict(os.environ, {"ADMIN_TOKEN": "new_token"}, clear=False):
            with app.test_client() as client:
                resp = client.get("/test", headers={"Authorization": "Bearer new_token"})
                assert resp.status_code == 200


class TestSSRFRedirectValidation:
    """测试 SSRF 重定向逐跳校验逻辑"""

    def test_normal_redirect_allowed(self):
        """正常外部 URL 重定向应放行"""
        from unittest.mock import MagicMock
        import httpx
        from utils.url_security import safe_http_get

        # 模拟：第一次 302 → 第二次 200
        mock_resp_302 = MagicMock(spec=httpx.Response)
        mock_resp_302.status_code = 302
        mock_resp_302.headers = {"location": "https://example.com/final"}

        mock_resp_200 = MagicMock(spec=httpx.Response)
        mock_resp_200.status_code = 200

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = [mock_resp_302, mock_resp_200]

        with patch("utils.url_security.httpx.Client", return_value=mock_client):
            result = safe_http_get("https://example.com/start")

        assert result is not None
        assert result.status_code == 200
        assert mock_client.get.call_count == 2

    def test_redirect_to_internal_blocked(self):
        """重定向到内网地址应被拦截"""
        from unittest.mock import MagicMock
        import httpx
        from utils.url_security import safe_http_get

        mock_resp_302 = MagicMock(spec=httpx.Response)
        mock_resp_302.status_code = 302
        mock_resp_302.headers = {"location": "http://127.0.0.1:8080/secret"}

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp_302

        with patch("utils.url_security.httpx.Client", return_value=mock_client):
            result = safe_http_get("https://example.com/start")

        assert result is None

    def test_redirect_loop_limited(self):
        """超过 MAX_REDIRECTS 次重定向应返回 None"""
        from unittest.mock import MagicMock
        import httpx
        from utils.url_security import safe_http_get, MAX_REDIRECTS

        mock_resp_302 = MagicMock(spec=httpx.Response)
        mock_resp_302.status_code = 302
        mock_resp_302.headers = {"location": "https://example.com/loop"}

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp_302

        with patch("utils.url_security.httpx.Client", return_value=mock_client):
            result = safe_http_get("https://example.com/start")

        assert result is None
        assert mock_client.get.call_count == MAX_REDIRECTS + 1

    def test_no_redirect_returns_directly(self):
        """无重定向时直接返回响应"""
        from unittest.mock import MagicMock
        import httpx
        from utils.url_security import safe_http_get

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        with patch("utils.url_security.httpx.Client", return_value=mock_client):
            result = safe_http_get("https://example.com/page")

        assert result is not None
        assert result.status_code == 200
        assert mock_client.get.call_count == 1
