"""
Unit tests for MastersService cache staleness and lazy refresh (tests/test_masters_refresh.py).
"""
import time
from unittest.mock import patch
import pytest

from app.sheets.masters import MastersService
from app.sheets.client import GoogleSheetsError


def test_empty_cache_is_stale():
    svc = MastersService()
    assert svc._is_cache_stale() is True


def test_populated_cache_fresh_is_not_stale():
    svc = MastersService()
    svc._cache = {"SCZ": [{"RUTA": "R01"}]}
    svc._last_refresh = time.time()
    assert svc._is_cache_stale() is False


def test_populated_cache_expired_is_stale():
    svc = MastersService()
    svc._cache = {"SCZ": [{"RUTA": "R01"}]}
    # 1 hour ago (TTL is 1800s / 30 min)
    svc._last_refresh = time.time() - 3600
    assert svc._is_cache_stale() is True


def test_get_master_triggers_refresh_when_empty():
    svc = MastersService()
    sample_rows = [{"RUTA": "R01", "VENDEDOR": "Juan"}]

    def fake_refresh():
        svc.update_cache("SCZ", sample_rows)
        svc._last_refresh = time.time()

    with patch.object(svc, "refresh", side_effect=fake_refresh) as mock_refresh:
        res = svc.get_master_for_sede("SCZ")
        mock_refresh.assert_called_once()
        assert res == sample_rows


def test_ensure_loaded_returns_false_on_error():
    svc = MastersService()
    with patch.object(svc, "refresh", side_effect=GoogleSheetsError("Failed connecting to Sheets")):
        result = svc.ensure_loaded()
        assert result is False


def test_ensure_loaded_returns_true_on_success():
    svc = MastersService()

    def fake_refresh():
        svc.update_cache("SCZ", [{"RUTA": "R01"}])
        svc._last_refresh = time.time()

    with patch.object(svc, "refresh", side_effect=fake_refresh) as mock_refresh:
        result = svc.ensure_loaded()
        assert result is True
        mock_refresh.assert_called_once()
