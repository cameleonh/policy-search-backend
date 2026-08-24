"""Tests for the ingest scheduler's slot arithmetic."""

from __future__ import annotations

from datetime import datetime, timedelta

from scripts.ingest_scheduler import _parse_slots, _seconds_until_next


def test_parse_slots_sorted_and_normalized() -> None:
    assert _parse_slots("19:00,11:00") == [timedelta(hours=11), timedelta(hours=19)]
    assert _parse_slots(" 11:00 , 19:00 ") == [timedelta(hours=11), timedelta(hours=19)]
    assert _parse_slots("9:30") == [timedelta(hours=9, minutes=30)]


def test_next_slot_same_day() -> None:
    slots = [timedelta(hours=11), timedelta(hours=19)]
    now = datetime(2026, 8, 24, 8, 0)
    assert _seconds_until_next(slots, now) == 3 * 3600


def test_next_slot_after_all_today_wraps_to_tomorrow() -> None:
    slots = [timedelta(hours=11), timedelta(hours=19)]
    now = datetime(2026, 8, 24, 20, 0)
    expected = (datetime(2026, 8, 25, 11, 0) - now).total_seconds()
    assert _seconds_until_next(slots, now) == expected


def test_next_slot_between_slots() -> None:
    slots = [timedelta(hours=11), timedelta(hours=19)]
    now = datetime(2026, 8, 24, 12, 0)
    assert _seconds_until_next(slots, now) == 7 * 3600
