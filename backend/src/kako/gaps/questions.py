"""Which weak searches Kako asks the household about, and how it asks (docs/architecture.md,
"Self-learning (Context Gaps)").

Pure: no database, Meko or clock. Meko's search log bands each `context_search` by its best score
(high from 0.75, mid from 0.50, low below) and says why one fell short. Only a shortfall of coverage
is a question for the household: the datapack lacks something it could tell Kako. A vague prompt, a
source that failed, an out-of-date source or content still indexing is not theirs to answer. The
question is written by code, never a model, and the search's words in it are data.
"""

from __future__ import annotations

from typing import Final, Protocol


class LoggedSearch(Protocol):
    """What the questions read of a search in Meko's log (`kako.meko.adapter.LoggedSearch`)."""

    @property
    def query(self) -> str: ...
    @property
    def band(self) -> str: ...
    @property
    def reason(self) -> str | None: ...
    @property
    def category(self) -> str | None: ...


# Meko's reasons for a search that fell short for want of content (its Self-learning tab, Analyze).
COVERAGE: Final = frozenset(
    {"weak_match", "partial_match", "nothing_matched", "below_quality_floor"}
)
MAX_QUERY: Final = 500  # characters of a search kept in a question


def worth_asking(search: LoggedSearch) -> bool:
    """A mid or low search that fell short for want of content."""
    if search.band == "high" or not search.query.strip():
        return False
    if search.category is not None:
        return search.category == "coverage"
    return search.reason is None or search.reason in COVERAGE


def reason_of(search: LoggedSearch) -> str:
    """Meko's reason, or the one its band implies."""
    return search.reason or ("partial_match" if search.band == "mid" else "weak_match")


def question(search: LoggedSearch) -> str:
    """The plain question for the household."""
    asked = " ".join(search.query.split())[:MAX_QUERY]
    found = "only part of an answer" if search.band == "mid" else "little to go on"
    return (
        f'Kako looked for "{asked}" in what it knows about your household and found {found}. '
        "Can you tell Kako about it?"
    )
