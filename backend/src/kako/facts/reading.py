"""Reading numbers out of a text: the one reader the number check (V-10, `agents.numbers`), the
evidence check on proposals (V-09, `facts.evidence`) and the agent test set's scoring share.

Pure: no database, clock or model. It finds peso amounts (₱9,050.00, 9,050 pesos), months ("9
months", "3-month target"), years ("2 years"), percentages (5.1%), dates (Feb 15, 2028; March 3rd,
2028; 15 Feb 2028; 2028-02-15; 15/02/2028; Feb 15; Feb 2028), bare years and any other number
written in digits, and a spelled-out number with a unit ("nine months"). A number run into letters
(`debt1-W1`) is one code, and a number with a multiplier (`150k`) is scaled: neither is ever a
match. What each number may match is the caller's rule.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final, Literal

Kind = Literal["money", "months", "percent", "date", "month", "number", "code", "scaled"]

_MONTHS: Final = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_MON = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?"
    r"|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)
_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"


_UNITS: Final = [
    *("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"),
    *("eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen"),
    *("eighteen", "nineteen"),
]
_TENS: Final = ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_WORDNUM = (
    rf"(?:{'|'.join(_TENS)})(?:[\s-](?:{'|'.join(_UNITS[1:10])}))?|{'|'.join(reversed(_UNITS))}"
)
_ORD = r"(?:st|nd|rd|th)?"
TOKEN: Final = re.compile(
    rf"(?P<iso>\b(?P<iy>\d{{4}})-(?P<im>\d{{1,2}})-(?P<id>\d{{1,2}})\b)"
    rf"|(?P<slash>\b(?P<s1>\d{{1,2}})/(?P<s2>\d{{1,2}})/(?P<s3>\d{{4}}|\d{{2}})\b)"
    rf"|(?P<date>\b(?P<dmon>{_MON})\.?\s+(?P<day>\d{{1,2}}){_ORD}\b(?:,?\s+(?P<dyear>\d{{4}})\b)?)"
    rf"|(?P<first>\b(?:the\s+)?(?P<fday>\d{{1,2}}){_ORD}\s+(?:of\s+)?(?P<fmon>{_MON})\b\.?"
    rf"(?:,?\s+(?P<fyear>\d{{4}})\b)?)"
    rf"|(?P<month>\b(?P<mmon>{_MON})\.?\s+(?P<myear>\d{{4}})\b)"
    rf"|(?P<money>(?:₱|\bPHP\s?|(?<![A-Za-z])P(?=\d))(?P<mnum>{_NUM}))"
    rf"|(?P<pesos>(?P<pnum>{_NUM})\s?pesos?\b)"
    rf"|(?P<percent>(?P<cnum>{_NUM})\s?%)"
    rf"|(?P<months>(?P<onum>{_NUM})[\s-]months?\b)"
    rf"|(?P<years>(?P<ynum>{_NUM})[\s-]years?\b)"
    rf"|(?P<words>\b(?P<wnum>{_WORDNUM})[\s-](?P<wunit>months?|years?|percent|per\s?cent)\b)"
    rf"|(?P<number>{_NUM})",
    re.IGNORECASE,
)
ORDINAL: Final = re.compile(r"(?:st|nd|rd|th)(?![A-Za-z])", re.IGNORECASE)
# A multiplier after a number: the figure is never written that way.
SCALE: Final = re.compile(r"\s?(?:k|m|b|mn|bn|thousand|million|billion)\b", re.IGNORECASE)
# Words with digits that are names of things, not numbers: 13th-month pay.
TERMS: Final = re.compile(r"\b13th[\s-]month\b", re.IGNORECASE)
WORD: Final = re.compile(r"[\w:@./\-]")  # what a ref is made of

MAX_PLACES: Final = 6  # more decimals than this is never a figure
MAX_DIGITS: Final = 18


@dataclass(frozen=True)
class Token:
    """One number read out of a text, with every value it may stand for."""

    start: int
    end: int
    text: str  # as written: a code is its whole word, a scaled number with its multiplier
    kind: Kind
    pools: tuple[str, ...] = ()  # where its value may be: money, months, percent, counts
    value: Decimal | None = None
    places: int = 0
    dates: tuple[date, ...] = ()  # a date: the days it may be
    year_month: tuple[int, int] | None = None  # a month (Feb 2028), or a bare year (month 0)
    day_of: tuple[int, int] | None = None  # a date with no year: (month, day)


def _decimal(text: str) -> tuple[Decimal, int]:
    """The value and how many decimals it was written with."""
    plain = text.replace(",", "")
    return Decimal(plain), len(plain.partition(".")[2])


def _month(name: str) -> int:
    return _MONTHS[name[:3].lower()]


def _day(year: int, month: int, day: int) -> tuple[date, ...]:
    try:
        return (date(year, month, day),)
    except ValueError:
        return ()  # not a real date (Feb 30, 2028): never a match


def _word_value(words: str) -> Decimal:
    parts = re.split(r"[\s-]+", words.lower())
    if parts[0] in _TENS:
        tens = (_TENS.index(parts[0]) + 2) * 10
        return Decimal(tens + (_UNITS.index(parts[1]) if len(parts) > 1 else 0))
    return Decimal(_UNITS.index(parts[0]))


def _strip_names(text: str, names: Iterable[str]) -> str:
    for name in sorted({n for n in names if any(c.isdigit() for c in n)}, key=len, reverse=True):
        pattern = re.compile(rf"(?<!\w){re.escape(name)}(?!\w)")
        text = pattern.sub(lambda m: " " * len(m.group()), text)
    return TERMS.sub(lambda m: " " * len(m.group()), text)


def _whole_word(text: str, start: int, end: int) -> tuple[int, int]:
    while start > 0 and WORD.match(text[start - 1]):
        start -= 1
    while end < len(text) and WORD.match(text[end]):
        end += 1
    while end > start and text[end - 1] in ".:-/":
        end -= 1
    while start < end and text[start] in ".:-/":
        start += 1
    return start, end


def scan(text: str, names: Iterable[str] = ()) -> list[Token]:
    """Each number in the text, in order. Names (people's and things') and fixed terms are left
    out first; a word with two numbers in it (`debt1-W1`) is one code."""
    text = _strip_names(text, names)
    found: list[Token] = []
    word_end = -1
    for m in TOKEN.finditer(text):
        token = _token(text, m)
        if token.kind == "code" and token.start < word_end:
            continue
        if token.kind == "code":
            word_end = token.end
        found.append(token)
    return found


def _token(text: str, m: re.Match[str]) -> Token:
    start, end, written = m.start(), m.end(), m.group().strip()
    if m.group("iso"):
        days = _day(int(m.group("iy")), int(m.group("im")), int(m.group("id")))
        return Token(start, end, written, "date", dates=days)
    if m.group("slash"):
        a, b, y = int(m.group("s1")), int(m.group("s2")), int(m.group("s3"))
        full = y + 2000 if y < 100 else y
        days = tuple(dict.fromkeys(_day(full, b, a) + _day(full, a, b)))  # D/M/Y or M/D/Y
        return Token(start, end, written, "date", dates=days)
    if m.group("date") or m.group("first"):
        mon = _month(m.group("dmon") or m.group("fmon"))
        day = int(m.group("day") or m.group("fday"))
        written_year = m.group("dyear") or m.group("fyear")
        if written_year is None:
            return Token(start, end, written, "date", day_of=(mon, day))
        return Token(start, end, written, "date", dates=_day(int(written_year), mon, day))
    if m.group("month"):
        ym = (int(m.group("myear")), _month(m.group("mmon")))
        return Token(start, end, written, "month", year_month=ym)
    if m.group("words"):
        value = _word_value(m.group("wnum"))
        unit = m.group("wunit").lower()
        if unit.startswith("month"):
            return Token(start, end, written, "months", ("months",), value)
        if unit.startswith("year"):
            return Token(start, end, written, "months", ("years",), value)
        return Token(start, end, written, "percent", ("percent",), value)
    kind: Kind
    pools: tuple[str, ...]
    if m.group("money") or m.group("pesos"):
        kind, raw, pools = "money", m.group("mnum") or m.group("pnum"), ("money",)
    elif m.group("percent"):
        kind, raw, pools = "percent", m.group("cnum"), ("percent",)
    elif m.group("months"):
        kind, raw, pools = "months", m.group("onum"), ("months",)
    elif m.group("years"):
        kind, raw, pools = "months", m.group("ynum"), ("years",)
    else:
        kind, raw, pools = "number", m.group("number"), ("money", "months", "percent", "counts")
    before = text[start - 1] if start > 0 else " "
    after = text[end:]
    scale = SCALE.match(text, end) if kind in ("money", "number") else None
    if kind == "number" and (
        before.isalpha()
        or before == "_"
        or (scale is None and after[:1].isalpha() and not ORDINAL.match(after))
    ):
        ws, we = _whole_word(text, start, end)  # run into letters: a code (`debt1-W1`)
        return Token(ws, we, text[ws:we], "code")
    if scale is not None:
        return Token(start, scale.end(), text[start : scale.end()].strip(), "scaled")
    value, places = _decimal(raw)
    if kind == "number" and places == 0 and "," not in raw and 1900 <= value <= 2100:
        bare = (int(value), 0)  # a bare year: any date in it, or the number itself
        return Token(start, end, written, kind, pools, value, places, year_month=bare)
    return Token(start, end, written, kind, pools, value, places)
