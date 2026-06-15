from datetime import datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
NSE_OPEN = time(9, 15)
NSE_CLOSE = time(15, 30)

# Minimal 2026 NSE trading-holiday list. Extend as needed; rich holiday feed is deferred.
NSE_HOLIDAYS = {
    "2026-01-26",  # Republic Day
    "2026-03-06",  # Holi (verify)
    "2026-08-15",  # Independence Day
    "2026-10-02",  # Gandhi Jayanti
}


def is_market_open(now: datetime | None = None) -> bool:
    now = (now or datetime.now(IST))
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    now = now.astimezone(IST)
    if now.weekday() >= 5:
        return False
    if now.strftime("%Y-%m-%d") in NSE_HOLIDAYS:
        return False
    return NSE_OPEN <= now.time() <= NSE_CLOSE
