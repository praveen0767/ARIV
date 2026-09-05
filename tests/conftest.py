"""tests/conftest.py

Global test fixtures.
Ensures that no test ever makes real external network calls to the Telegram API.
"""

from unittest.mock import MagicMock, patch
import httpx
import pytest


@pytest.fixture(autouse=True)
def mock_telegram_api():
    """
    Globally intercept any httpx calls to api.telegram.org to ensure tests
    remain completely isolated, deterministic, and fast without external network traffic.
    """
    real_post = httpx.AsyncClient.post
    real_get = httpx.AsyncClient.get

    async def fake_post(self, url, *args, **kwargs):
        if "api.telegram.org" in str(url):
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.text = '{"ok": true, "result": {"message_id": 999}}'
            resp.json.return_value = {"ok": True, "result": {"message_id": 999}}
            return resp
        return await real_post(self, url, *args, **kwargs)

    async def fake_get(self, url, *args, **kwargs):
        if "api.telegram.org" in str(url):
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.text = '{"ok": true, "result": {"id": 12345, "is_bot": true}}'
            resp.json.return_value = {"ok": True, "result": {"id": 12345, "is_bot": True}}
            return resp
        return await real_get(self, url, *args, **kwargs)

    with patch.object(httpx.AsyncClient, "post", fake_post), patch.object(
        httpx.AsyncClient, "get", fake_get
    ):
        yield
