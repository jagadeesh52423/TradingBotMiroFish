from decimal import Decimal
from services.nubra_client.units import rupees_to_paise, paise_to_rupees, round_to_tick


def test_rupees_to_paise_rounds_half_up():
    assert rupees_to_paise("1344.00") == 134400
    assert rupees_to_paise(1344) == 134400
    assert rupees_to_paise("25.255") == 2526  # half-up


def test_paise_to_rupees():
    assert paise_to_rupees(134400) == Decimal("1344.00")


def test_round_to_tick_nse_5paise():
    # NSE common tick 0.05; 1344.02 -> 1344.00, 1344.03 -> 1344.05
    assert round_to_tick("1344.02", "0.05") == Decimal("1344.00")
    assert round_to_tick("1344.03", "0.05") == Decimal("1344.05")


def test_round_to_tick_then_paise_is_exact():
    r = round_to_tick("1344.03", "0.05")
    assert rupees_to_paise(r) == 134405
