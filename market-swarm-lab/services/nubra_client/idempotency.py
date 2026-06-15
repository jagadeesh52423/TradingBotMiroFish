import hashlib


def client_tag(signal_id: str, ticker: str, trading_date: str, intent: str) -> str:
    raw = f"{signal_id}|{ticker}|{trading_date}|{intent}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"msl-{digest}"
