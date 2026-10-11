"""
Unit tests for app.utils.phone.normalize_phone.
"""
from app.utils.phone import normalize_phone


def test_full_number_with_country_code():
    assert normalize_phone("59169105312") == "69105312"


def test_full_number_with_whatsapp_suffix():
    assert normalize_phone("59169105312@c.us") == "69105312"


def test_number_with_plus_spaces_and_dashes():
    assert normalize_phone("+591 691-05312") == "69105312"


def test_already_local_number():
    assert normalize_phone("69105312") == "69105312"


def test_number_with_internal_spaces():
    assert normalize_phone("691 05 312") == "69105312"


def test_too_short_returns_empty():
    assert normalize_phone("123") == ""


def test_empty_input_returns_empty():
    assert normalize_phone("") == ""
