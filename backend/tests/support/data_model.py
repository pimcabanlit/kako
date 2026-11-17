"""Reads the tables out of docs/data-model.md, so tests can hold the schema to the document.

Each table is a `### `name`` heading followed by a Markdown table whose header is
`| Column | Type | Notes |`. A type reads like `UUID PK, FK` or `NUMERIC(9,6), null`: the SQL type,
then `PK` and `FK` markers, then `null` when the column may be empty (data-model.md, Conventions).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

DATA_MODEL = Path(__file__).resolve().parents[3] / "docs" / "data-model.md"

_HEADING = re.compile(r"^### `([a-z_]+)`\s*$")
_TYPE_NAMES = {
    "UUID": "uuid",
    "TEXT": "text",
    "BIGINT": "bigint",
    "INT": "integer",
    "DATE": "date",
    "TIMESTAMPTZ": "timestamp with time zone",
    "JSONB": "jsonb",
    "BOOLEAN": "boolean",
    "UUID[]": "uuid[]",
    "TEXT[]": "text[]",
}
_NUMERIC = re.compile(r"^NUMERIC\((\d+),\s*(\d+)\)$")


@dataclass(frozen=True)
class DocColumn:
    name: str
    sql_type: str  # normalised the way Postgres's format_type() writes it, e.g. "numeric(9,6)"
    nullable: bool
    primary_key: bool
    foreign_key: bool
    notes: str


def normalise_type(sql_type: str) -> str:
    """One spelling for a type, whether it comes from the doc, SQLAlchemy or Postgres."""
    compact = re.sub(r"\s*,\s*", ",", sql_type.strip())
    upper = compact.upper()
    if upper in _TYPE_NAMES:
        return _TYPE_NAMES[upper]
    if match := _NUMERIC.match(upper):
        return f"numeric({match[1]},{match[2]})"
    return compact.lower()


def _parse_type(cell: str) -> tuple[str, bool, bool, bool]:
    parts = [part.strip() for part in cell.split(",")]
    # NUMERIC(9,6) contains a comma of its own: glue it back together.
    if parts[0].startswith("NUMERIC(") and not parts[0].endswith(")"):
        parts = [f"{parts[0]},{parts[1]}", *parts[2:]]
    words = parts[0].split()
    base, markers = words[0], set(words[1:])
    markers |= {part for part in parts[1:] if part in ("PK", "FK")}
    nullable = "null" in parts[1:]
    unknown = markers - {"PK", "FK"} or set(parts[1:]) - {"PK", "FK", "null"}
    if unknown:
        raise ValueError(f"can't read the type {cell!r}")
    return normalise_type(base), nullable, "PK" in markers, "FK" in markers


@cache
def doc_tables() -> dict[str, dict[str, DocColumn]]:
    """Every documented table, with its columns in order."""
    tables: dict[str, dict[str, DocColumn]] = {}
    current: str | None = None
    in_columns = False
    for line in DATA_MODEL.read_text(encoding="utf-8").splitlines():
        if heading := _HEADING.match(line):
            current, in_columns = heading[1], False
            continue
        if current is None:
            continue
        if line.startswith("| Column | Type | Notes |"):
            if current in tables:
                raise ValueError(f"{current} has two column tables")
            tables[current] = {}
            in_columns = True
            continue
        if not in_columns:
            continue
        if not line.startswith("|"):
            in_columns = False
            current = None
            continue
        if set(line) <= set("|- "):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        name_cell, type_cell, notes = cells[0], cells[1], "|".join(cells[2:])
        name = name_cell.strip("`")
        if not re.fullmatch(r"[a-z_]+", name):
            raise ValueError(f"{current}: can't read the column name {name_cell!r}")
        sql_type, nullable, pk, fk = _parse_type(type_cell)
        tables[current][name] = DocColumn(name, sql_type, nullable, pk, fk, notes)
    return tables
