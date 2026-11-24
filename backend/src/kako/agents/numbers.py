"""The number check (rule V-10, docs/architecture.md step 7): every number in a text the agents
write must be one the engine produced, a fact Kako holds, or one the household said.

Code reads each number out of the text: peso amounts (₱9,050.00, 9,050 pesos), months
("9 months", "3-month target"), percentages (5.1%), dates (Feb 15, 2028; Feb 2028), years and
any other number written in digits. Each must match, at the precision it is written, one of:

- a figure of the turn's run, or of one of the turn's what-ifs (the asks together included);
- a fact in the turn's snapshot (money, a rate as a percentage, a whole number, a date);
- an allocation in one of the turn's what-ifs (a hypothetical fact, `scenario_override`);
- a number in the household's own message, or the household's date.

A negative figure matches its amount ("₱5,050.00 more than the surplus" for -₱5,050.00).
Written at a lower precision a value is rounded half up to it ("2.1 months", "₱12,460").
A number run into letters (`W1`, `150k`) is never a figure, so it fails: agents write numbers as
the tools show them and never write refs. Spelled-out numbers ("two options") aren't checked.

The texts: the reply, each option's label and summary, the resolution's reason and each
specialist's summary. A text that fails is sent back once with the numbers named
(`regenerated`); if it fails again it is shown with those numbers flagged (`fail`), never silently.
Every check is a `number_check` row.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from kako.agents.checks import Kind, Number, Subject, TextCheck
from kako.agents.tools import TurnState
from kako.engine.figures import Figure

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
TOKEN: Final = re.compile(
    rf"(?P<date>\b(?P<dmon>{_MON})\.?\s+(?P<day>\d{{1,2}}),?\s+(?P<dyear>\d{{4}})\b)"
    rf"|(?P<month>\b(?P<mmon>{_MON})\.?\s+(?P<myear>\d{{4}})\b)"
    rf"|(?P<money>(?:₱|\bPHP\s?|(?<![A-Za-z])P(?=\d))(?P<mnum>{_NUM}))"
    rf"|(?P<pesos>(?P<pnum>{_NUM})\s?pesos?\b)"
    rf"|(?P<percent>(?P<cnum>{_NUM})\s?%)"
    rf"|(?P<months>(?P<onum>{_NUM})[\s-]months?\b)"
    rf"|(?P<number>{_NUM})",
    re.IGNORECASE,
)
ORDINAL: Final = re.compile(r"(?:st|nd|rd|th)(?![A-Za-z])", re.IGNORECASE)
# Words with digits that are names of things, not numbers: 13th-month pay.
TERMS: Final = re.compile(r"\b13th[\s-]month\b", re.IGNORECASE)
WORD: Final = re.compile(r"[\w:@.\-]")  # what a ref is made of
SHOWN_UNMATCHED: Final = 12  # the most unmatched numbers named back to the model


# --- What a number may be ------------------------------------------------------------------------


@dataclass
class Pool:
    """Every value a number may match, by kind, with what it is (the first source wins)."""

    money: dict[Decimal, str] = field(default_factory=dict)  # pesos, not negative
    months: dict[Decimal, str] = field(default_factory=dict)
    percent: dict[Decimal, str] = field(default_factory=dict)
    counts: dict[Decimal, str] = field(default_factory=dict)
    dates: dict[date, str] = field(default_factory=dict)
    what_ifs: frozenset[str] = frozenset()  # the turn's what-if refs, for refs in a summary

    def add_figure(self, figure: Figure, ref: str) -> None:
        value = figure.value
        if value is None:
            return
        if isinstance(value, date):
            self.dates.setdefault(value, ref)
        elif figure.unit == "centavos":
            self.money.setdefault(abs(Decimal(value)) / 100, ref)
        elif figure.unit == "months":
            self.months.setdefault(Decimal(value), ref)
        elif figure.unit == "ratio":
            if figure.key.endswith("_months"):
                self.months.setdefault(Decimal(value), ref)
            else:
                self.percent.setdefault(abs(Decimal(value)) * 100, ref)
        else:
            self.counts.setdefault(Decimal(value), ref)

    def add_number(self, kind: Kind, value: Decimal | date, ref: str) -> None:
        if isinstance(value, date):
            self.dates.setdefault(value, ref)
            return
        target = {
            "money": self.money,
            "months": self.months,
            "percent": self.percent,
        }.get(kind, self.counts)
        target.setdefault(abs(value), ref)


def pool_of(state: TurnState) -> Pool:
    """Everything a number in this turn may match: the turn's run first, then each what-if in the
    order it ran, the snapshot's facts, the what-ifs' allocations, the household's own words."""
    pool = Pool()
    refs = state.refs
    for figure in state.run.figures:
        pool.add_figure(figure, f"figure:{refs.figure(figure)}")
    for ref, what_if in state.what_ifs.items():
        for figure in what_if.run.figures:
            pool.add_figure(figure, f"figure:{ref}:{refs.figure(figure)}")
    for fact in state.snapshot.facts:
        name = f"fact:{refs.fact(fact)}"
        if fact.value_money is not None:
            pool.money.setdefault(Decimal(fact.value_money) / 100, name)
        if fact.value_rate is not None:
            pool.percent.setdefault(fact.value_rate * 100, name)
        if fact.value_int is not None:
            pool.counts.setdefault(Decimal(fact.value_int), name)
            pool.months.setdefault(Decimal(fact.value_int), name)
        if fact.value_date is not None:
            pool.dates.setdefault(fact.value_date, name)
    for ref, what_if in state.what_ifs.items():
        for a in what_if.allocations:
            pool.money.setdefault(Decimal(a.centavos) / 100, f"allocation:{ref}:{a.entity_ref}")
    for number, value in _values(_scan(state.message, ())):
        pool.add_number(number.kind, value, "said")
        if number.kind == "number" and isinstance(value, Decimal):
            pool.money.setdefault(value, "said")  # "4000 extra" is pesos too
    pool.dates.setdefault(state.snapshot.on, "date:today")
    pool.what_ifs = frozenset(state.what_ifs)
    return pool


# --- Reading numbers out of a text ------------------------------------------------------------


def _decimal(text: str) -> tuple[Decimal, int]:
    """The value and how many decimals it was written with."""
    plain = text.replace(",", "")
    return Decimal(plain), len(plain.partition(".")[2])


def _month(name: str) -> int:
    return _MONTHS[name[:3].lower()]


def _scan(text: str, names: Iterable[str]) -> list[tuple[re.Match[str], Kind]]:
    """Each number in the text and its kind. Names and fixed terms are left out first."""
    for name in sorted({n for n in names if any(c.isdigit() for c in n)}, key=len, reverse=True):
        text = text.replace(name, " " * len(name))
    text = TERMS.sub(lambda m: " " * len(m.group()), text)
    found: list[tuple[re.Match[str], Kind]] = []
    for m in TOKEN.finditer(text):
        kind: Kind
        if m.group("date"):
            kind = "date"
        elif m.group("month"):
            kind = "month"
        elif m.group("money") or m.group("pesos"):
            kind = "money"
        elif m.group("percent"):
            kind = "percent"
        elif m.group("months"):
            kind = "months"
        else:
            before = text[m.start() - 1] if m.start() > 0 else " "
            after = text[m.end() :]
            run_in = before.isalpha() or before == "_"
            if after[:1].isalpha() and not ORDINAL.match(after):
                run_in = True
            kind = "code" if run_in else "number"
        found.append((m, kind))
    return found


def _values(found: list[tuple[re.Match[str], Kind]]) -> list[tuple[Number, Decimal | date]]:
    out: list[tuple[Number, Decimal | date]] = []
    for m, kind in found:
        number = Number(m.group().strip(), kind, None)
        value: Decimal | date
        try:
            if kind == "date":
                value = date(int(m.group("dyear")), _month(m.group("dmon")), int(m.group("day")))
            elif kind == "month":
                value = date(int(m.group("myear")), _month(m.group("mmon")), 1)
            else:
                raw = (
                    m.group("mnum")
                    or m.group("pnum")
                    or m.group("cnum")
                    or m.group("onum")
                    or m.group("number")
                )
                value = _decimal(raw)[0]
        except ValueError:
            continue  # not a real date (Feb 30, 2028): checked as the numbers in it
        out.append((number, value))
    return out


def _round(value: Decimal, places: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _find(candidates: dict[Decimal, str], value: Decimal, places: int) -> str | None:
    exact = candidates.get(value)
    if exact is not None:
        return exact
    return next((ref for c, ref in candidates.items() if _round(c, places) == value), None)


def _match(m: re.Match[str], kind: Kind, pool: Pool) -> str | None:
    if kind == "code":
        return None
    if kind == "date":
        try:
            day = date(int(m.group("dyear")), _month(m.group("dmon")), int(m.group("day")))
        except ValueError:
            return None
        return pool.dates.get(day)
    if kind == "month":
        year, month = int(m.group("myear")), _month(m.group("mmon"))
        return next(
            (ref for d, ref in pool.dates.items() if (d.year, d.month) == (year, month)), None
        )
    raw = m.group("mnum") or m.group("pnum") or m.group("cnum") or m.group("onum")
    if raw is not None:
        value, places = _decimal(raw)
        pools = {"money": pool.money, "percent": pool.percent, "months": pool.months}
        return _find(pools[kind], value, places)
    value, places = _decimal(m.group("number"))
    for candidates in (pool.money, pool.months, pool.percent, pool.counts):
        found = _find(candidates, value, places)
        if found is not None:
            return found
    if places == 0 and "," not in m.group("number") and 1900 <= value <= 2100:
        return next((ref for d, ref in pool.dates.items() if d.year == value), None)
    return None


REF_KINDS: Final = ("figure", "fact")


def _ref(word: str, pool: Pool) -> bool:
    """A ref of this turn: a what-if (`debt1-W1`) or a figure or fact ref."""
    return word in pool.what_ifs or word.partition(":")[0] in REF_KINDS


def check_text(
    subject: Subject,
    label: str,
    text: str,
    pool: Pool,
    names: Iterable[str] = (),
    *,
    refs_allowed: bool = False,
) -> TextCheck:
    """Every number in `text`, each with what it matched. With `refs_allowed` (a specialist's
    summary, which only the orchestrator reads) a ref of this turn is a ref, not a number."""
    numbers = []
    word_end = -1  # a word with two numbers in it (`debt1-W1`) is one code
    for m, kind in _scan(text, names):
        if kind == "code" and m.start() < word_end:
            continue
        shown, word_end = _shown(m, kind)
        match = _match(m, kind, pool)
        if kind == "code" and refs_allowed and _ref(shown, pool):
            match = "ref"
        numbers.append(Number(shown, kind, match))
    return TextCheck(subject, label, text, tuple(numbers))


def _shown(m: re.Match[str], kind: Kind) -> tuple[str, int]:
    """The number as written, and where it ends; for one run into letters, the whole word it is
    in (`debt1-W1`), so the model is told what to take out."""
    if kind != "code":
        return m.group().strip(), m.end()
    start, end = m.start(), m.end()
    while start > 0 and WORD.match(m.string[start - 1]):
        start -= 1
    while end < len(m.string) and WORD.match(m.string[end]):
        end += 1
    return m.string[start:end].strip(".:-"), end


def names_of(state: TurnState) -> tuple[str, ...]:
    """The household's own names (people and things), left out of the check."""
    return (*(name for name, _ in state.inputs.people), *(e.name for e in state.entities))


def check_texts(
    state: TurnState, texts: Sequence[tuple[Subject, str, str]], *, refs_allowed: bool = False
) -> tuple[TextCheck, ...]:
    pool = pool_of(state)
    names = names_of(state)
    return tuple(
        check_text(s, label, text, pool, names, refs_allowed=refs_allowed)
        for s, label, text in texts
    )


def mismatch(checks: Sequence[TextCheck]) -> str:
    """What the model is told when a text fails: each number that matched nothing, and where."""

    def listed(refs: bool) -> str:
        named = list(
            dict.fromkeys(
                f"{n.text!r} in {c.label}"
                for c in checks
                for n in c.unmatched
                if (n.kind == "code") == refs
            )
        )
        more = len(named) - SHOWN_UNMATCHED
        return "; ".join(named[:SHOWN_UNMATCHED]) + (f"; and {more} more" if more > 0 else "")

    parts = []
    numbers = listed(refs=False)
    if numbers:
        parts.append(
            f"the number check found numbers that match no figure, fact or what-if of this turn: "
            f"{numbers}. Write only figures exactly as a tool or the brief shows them (such as "
            "₱9,050.00 or 9 months), or leave the number out; never work one out"
        )
    refs = listed(refs=True)
    if refs:
        parts.append(
            f"the text has refs or codes in it: {refs}. The reader sees plain words: take each "
            "one out and say what it shows, keeping the figures themselves as the tools show them"
        )
    return ". Also, ".join(parts)
