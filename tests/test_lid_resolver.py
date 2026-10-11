"""
Unit tests for app.whatsapp.lid_resolver.resolve_to_phone.
"""
import pytest
import httpx

from app.whatsapp import lid_resolver
from app.whatsapp.lid_resolver import resolve_to_phone


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text

    def json(self):
        return self._json_data


class _FakeAsyncClient:
    """Stand-in for httpx.AsyncClient used as an async context manager."""
    calls = []
    response = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, headers=None):
        _FakeAsyncClient.calls.append(url)
        return _FakeAsyncClient.response


class _BrokenAsyncClient(_FakeAsyncClient):
    async def get(self, url, headers=None):
        raise httpx.ConnectError("connection refused")


@pytest.fixture(autouse=True)
def reset_state():
    lid_resolver.clear_cache()
    _FakeAsyncClient.calls = []
    yield
    lid_resolver.clear_cache()


@pytest.mark.asyncio
async def test_cus_suffix_resolves_without_calling_waha(monkeypatch):
    monkeypatch.setattr(lid_resolver.httpx, "AsyncClient", _FakeAsyncClient)

    phone = await resolve_to_phone("59169105312@c.us")

    assert phone == "69105312"
    assert _FakeAsyncClient.calls == []


@pytest.mark.asyncio
async def test_lid_suffix_resolves_via_waha(monkeypatch):
    _FakeAsyncClient.response = _FakeResponse(status_code=200, json_data={"pn": "59169105312"})
    monkeypatch.setattr(lid_resolver.httpx, "AsyncClient", _FakeAsyncClient)

    phone = await resolve_to_phone("88283556139076@lid")

    assert phone == "69105312"
    assert len(_FakeAsyncClient.calls) == 1


@pytest.mark.asyncio
async def test_lid_suffix_waha_down_returns_none(monkeypatch):
    monkeypatch.setattr(lid_resolver.httpx, "AsyncClient", _BrokenAsyncClient)

    phone = await resolve_to_phone("88283556139076@lid")

    assert phone is None


@pytest.mark.asyncio
async def test_lid_suffix_waha_http_error_returns_none(monkeypatch):
    _FakeAsyncClient.response = _FakeResponse(status_code=404, text="not found")
    monkeypatch.setattr(lid_resolver.httpx, "AsyncClient", _FakeAsyncClient)

    phone = await resolve_to_phone("88283556139076@lid")

    assert phone is None


@pytest.mark.asyncio
async def test_lid_cache_hit_avoids_second_waha_call(monkeypatch):
    _FakeAsyncClient.response = _FakeResponse(status_code=200, json_data={"pn": "59169105312"})
    monkeypatch.setattr(lid_resolver.httpx, "AsyncClient", _FakeAsyncClient)

    first = await resolve_to_phone("88283556139076@lid")
    second = await resolve_to_phone("88283556139076@lid")

    assert first == "69105312"
    assert second == "69105312"
    assert len(_FakeAsyncClient.calls) == 1
