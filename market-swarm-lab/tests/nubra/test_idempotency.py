from services.nubra_client.idempotency import client_tag


def test_deterministic():
    a = client_tag("sig123", "SBIN", "2026-06-16", "BUY")
    b = client_tag("sig123", "SBIN", "2026-06-16", "BUY")
    assert a == b


def test_distinct_on_any_field():
    base = client_tag("sig123", "SBIN", "2026-06-16", "BUY")
    assert client_tag("sig124", "SBIN", "2026-06-16", "BUY") != base
    assert client_tag("sig123", "RELIANCE", "2026-06-16", "BUY") != base
    assert client_tag("sig123", "SBIN", "2026-06-17", "BUY") != base
    assert client_tag("sig123", "SBIN", "2026-06-16", "SELL") != base


def test_prefixed_and_bounded():
    t = client_tag("sig123", "SBIN", "2026-06-16", "BUY")
    assert t.startswith("msl-")
    assert len(t) <= 24
