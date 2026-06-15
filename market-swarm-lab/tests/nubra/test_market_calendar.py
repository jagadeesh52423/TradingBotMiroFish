from datetime import datetime
from zoneinfo import ZoneInfo
from services.nubra_client.market_calendar import is_market_open

IST = ZoneInfo("Asia/Kolkata")


def test_open_midday_weekday():
    assert is_market_open(datetime(2026, 6, 16, 11, 0, tzinfo=IST)) is True  # Tue


def test_closed_before_open():
    assert is_market_open(datetime(2026, 6, 16, 9, 0, tzinfo=IST)) is False


def test_closed_after_close():
    assert is_market_open(datetime(2026, 6, 16, 15, 31, tzinfo=IST)) is False


def test_closed_weekend():
    assert is_market_open(datetime(2026, 6, 14, 11, 0, tzinfo=IST)) is False  # Sun


def test_closed_holiday_republic_day():
    assert is_market_open(datetime(2026, 1, 26, 11, 0, tzinfo=IST)) is False


def test_non_ist_input_is_converted():
    utc = ZoneInfo("UTC")
    # 05:45 UTC == 11:15 IST -> open
    assert is_market_open(datetime(2026, 6, 16, 5, 45, tzinfo=utc)) is True
