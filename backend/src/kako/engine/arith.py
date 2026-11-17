"""Money and ratio arithmetic: integer centavos, half-up rounding, six-decimal ratios."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Context, Decimal

# Wide enough that no product or quotient of centavos and rates is ever rounded by the context.
_EXACT = Context(prec=60)
_RATIO_PLACES = Decimal("0.000001")


def round_half_up(amount: Decimal) -> int:
    """To the whole centavo, a half rounding away from zero (0.5 → 1)."""
    return int(amount.to_integral_value(rounding=ROUND_HALF_UP, context=_EXACT))


def interest(balance: int, monthly_rate: Decimal) -> int:
    """One month's interest on a balance in centavos, to the centavo."""
    return round_half_up(_EXACT.multiply(Decimal(balance), monthly_rate))


def monthly_from_annual(annual_rate: Decimal) -> Decimal:
    """An annual rate as a monthly one (annual ÷ 12), unrounded, so interest is rounded once."""
    return _EXACT.divide(annual_rate, Decimal(12))


def ceil_div(numerator: int, denominator: int) -> int:
    """⌈numerator ÷ denominator⌉ for whole numbers, the denominator positive."""
    if denominator <= 0:
        raise ValueError("ceil_div needs a positive denominator")
    return -(-numerator // denominator)


def ratio(numerator: int, denominator: int) -> Decimal:
    """numerator ÷ denominator to six decimals, half up. The denominator is never zero."""
    if denominator == 0:
        raise ValueError("ratio needs a denominator other than zero")
    quotient = _EXACT.divide(Decimal(numerator), Decimal(denominator))
    return quotient.quantize(_RATIO_PLACES, rounding=ROUND_HALF_UP, context=_EXACT)
