"""The fixed list of decision option tags (V-15, docs/data-model.md `decision_option.tags`).

The orchestrator tags an option when it proposes it; code refuses a tag that isn't here, and a
database check holds the same list (`kako.db.enums` reads it from here). Dreaming counts the options
the household chose by tag. A new tag is added here, to the check (a migration) and to the data
model in one change.
"""

from __future__ import annotations

from typing import Final

# The two sides of `preference.debt_vs_flexibility`.
DECISION_TAGS: Final = ("favours_flexibility", "favours_speed")
