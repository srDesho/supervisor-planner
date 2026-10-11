"""
Unit tests for the in-memory ConversationService (get/set/clear/expiration).
"""
from datetime import timezone

from app.services.conversation_service import ConversationService, _STORE


def _clear_store():
    _STORE.clear()


def test_get_returns_none_when_absent():
    _clear_store()
    svc = ConversationService()
    assert svc.get("70000001") is None


def test_set_then_get_roundtrip():
    _clear_store()
    svc = ConversationService()
    svc.set("70000001", "AWAITING_CONFIRMATION", payload={"draft": {"modalidad": "OFICINA"}})

    entry = svc.get("70000001")
    assert entry is not None
    assert entry["state"] == "AWAITING_CONFIRMATION"
    assert entry["payload"]["draft"]["modalidad"] == "OFICINA"


def test_clear_removes_entry():
    _clear_store()
    svc = ConversationService()
    svc.set("70000001", "AWAITING_CONFIRMATION")
    svc.clear("70000001")

    assert svc.get("70000001") is None


def test_expired_entry_is_cleared_on_get():
    _clear_store()
    svc = ConversationService()
    svc.set("70000001", "AWAITING_CONFIRMATION", ttl_minutes=-1)  # already expired

    assert svc.get("70000001") is None
    assert "70000001" not in _STORE


def test_clear_expired_sweeps_all_expired_entries():
    _clear_store()
    svc = ConversationService()
    svc.set("70000001", "AWAITING_CONFIRMATION", ttl_minutes=-1)
    svc.set("70000002", "AWAITING_CONFIRMATION", ttl_minutes=30)

    cleared = svc.clear_expired()

    assert cleared == 1
    assert "70000001" not in _STORE
    assert "70000002" in _STORE
