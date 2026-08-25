"""Tests for operational ID boundary helpers."""

from app.services.operational.ids import format_shift_id, parse_shift_id


def test_parse_shift_id_synthetic():
    assert parse_shift_id("shift-42") == 42


def test_parse_shift_id_raw_int():
    assert parse_shift_id(7) == 7
    assert parse_shift_id("7") == 7


def test_parse_shift_id_none_and_invalid():
    assert parse_shift_id(None) is None
    assert parse_shift_id("") is None
    assert parse_shift_id("shift-morning") is None


def test_format_shift_id():
    assert format_shift_id(3) == "shift-3"
