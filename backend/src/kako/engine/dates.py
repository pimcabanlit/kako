"""Calendar months: payment k falls k months after the as-of date."""

from __future__ import annotations

import calendar
from datetime import date
from typing import Final

# How far ahead the engine looks: 100 years. A debt still owed then never pays off; a goal that far
# away counts as having no allocation.
HORIZON_MONTHS: Final = 1200


def add_months(start: date, months: int) -> date:
    """The same day `months` later; a day the month doesn't have becomes its last day (Jan 31 +
    1 month is Feb 28, or Feb 29 in a leap year)."""
    index = start.year * 12 + (start.month - 1) + months
    year, month = divmod(index, 12)
    last = calendar.monthrange(year, month + 1)[1]
    return date(year, month + 1, min(start.day, last))


def whole_months_until(start: date, end: date) -> int:
    """How many monthly steps from `start` land on or before `end` (0 when none do)."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    while months > 0 and add_months(start, months) > end:
        months -= 1
    return max(months, 0)
