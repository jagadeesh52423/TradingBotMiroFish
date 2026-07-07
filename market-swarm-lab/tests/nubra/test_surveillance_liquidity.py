"""ASM/GSM exclusion + turnover-floor guard on catalyst discovery."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

from services.nubra_client.catalyst_discovery import SurveillanceLiquidityGuard, parse_turnover_lacs

_CSV = (
    "SYMBOL, SERIES, DATE1, TURNOVER_LACS\n"
    "RELIANCE, EQ, 04-Jul-2025, 122515.20\n"   # ₹1225 cr
    "TINYCO, EQ, 04-Jul-2025, 120.00\n"        # ₹1.2 cr — below floor
    "BONDX, N2, 04-Jul-2025, 99999.00\n"       # non-EQ series → ignored
    "BADROW, EQ, 04-Jul-2025, -\n"             # unparseable → skipped
)


def test_parse_turnover_eq_only():
    out = parse_turnover_lacs(_CSV)
    assert out == {"RELIANCE": 122515.20, "TINYCO": 120.0}  # N2 + bad row excluded


def _guard():
    return SurveillanceLiquidityGuard(min_turnover_cr=5.0, exclude_surveillance=True)


def test_filter_drops_surveilled_and_illiquid():
    g = _guard()
    with patch.object(g, "_surveillance_symbols", return_value={"ANSALAPI"}), \
         patch.object(g, "_turnover_map", return_value={"RELIANCE": 122515.0, "TINYCO": 120.0, "ANSALAPI": 90000.0}):
        # RELIANCE liquid+clean → kept. TINYCO below ₹5cr → dropped. ANSALAPI surveilled → dropped.
        assert g.filter(["RELIANCE", "TINYCO", "ANSALAPI"], date(2026, 7, 7)) == ["RELIANCE"]


def test_absent_from_bhavcopy_is_illiquid():
    g = _guard()
    with patch.object(g, "_surveillance_symbols", return_value=set()), \
         patch.object(g, "_turnover_map", return_value={"RELIANCE": 122515.0}):
        # UNKNOWN not in the EQ bhavcopy → treated as illiquid → dropped.
        assert g.filter(["RELIANCE", "UNKNOWN"], date(2026, 7, 7)) == ["RELIANCE"]


def test_liquidity_fails_open_when_bhavcopy_empty():
    g = _guard()
    with patch.object(g, "_surveillance_symbols", return_value=set()), \
         patch.object(g, "_turnover_map", return_value={}):  # fetch failed
        # no turnover data → don't empty the universe; keep all (surveillance still applied)
        assert g.filter(["RELIANCE", "TINYCO"], date(2026, 7, 7)) == ["RELIANCE", "TINYCO"]


def test_surveillance_fetch_error_does_not_crash():
    g = _guard()
    with patch.object(g, "_surveillance_symbols", side_effect=RuntimeError("nse down")), \
         patch.object(g, "_turnover_map", return_value={"RELIANCE": 122515.0}):
        assert g.filter(["RELIANCE"], date(2026, 7, 7)) == ["RELIANCE"]  # liquidity still applied
