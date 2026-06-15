from decimal import Decimal, ROUND_HALF_UP


def _d(v) -> Decimal:
    return v if isinstance(v, Decimal) else Decimal(str(v))


def rupees_to_paise(rupees) -> int:
    return int((_d(rupees) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def paise_to_rupees(paise: int) -> Decimal:
    return (Decimal(int(paise)) / 100).quantize(Decimal("0.01"))


def round_to_tick(rupees, tick) -> Decimal:
    r, t = _d(rupees), _d(tick)
    steps = (r / t).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return (steps * t).quantize(Decimal("0.01"))
