"""The table models follow docs/data-model.md exactly: tables, columns, types, nulls and keys.

The integration test (tests/integration/test_schema.py) holds the migrated database to the same
document, so the doc, the models and the database can't drift apart.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Table
from sqlalchemy.dialects import postgresql

import kako.db.models  # noqa: F401 - registers every table
from kako.db.base import Base
from kako.db.enums import DECISION_TAGS, ENUMS
from tests.support.data_model import doc_tables, normalise_type

TABLES = Base.metadata.tables


def test_the_same_tables() -> None:
    assert sorted(TABLES) == sorted(doc_tables())
    assert len(TABLES) == 30


@pytest.mark.parametrize("name", sorted(doc_tables()))
def test_columns_match_the_doc(name: str) -> None:
    table: Table = TABLES[name]
    documented = doc_tables()[name]
    assert list(table.columns.keys()) == list(documented), "same columns, in the doc's order"
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    for column in table.columns:
        doc = documented[column.name]
        where = f"{name}.{column.name}"
        assert normalise_type(column.type.compile(dialect=dialect)) == doc.sql_type, where
        assert column.nullable == doc.nullable, where
        assert column.primary_key == doc.primary_key, where
        assert bool(column.foreign_keys) == doc.foreign_key, where


@pytest.mark.parametrize(("table", "column"), sorted(ENUMS))
def test_every_enum_value_is_in_the_doc(table: str, column: str) -> None:
    notes = doc_tables()[table][column].notes
    missing = [value for value in ENUMS[(table, column)] if f"`{value}`" not in notes]
    assert not missing, f"{table}.{column}: the doc doesn't name {missing}"


def test_every_enum_column_has_its_check() -> None:
    for (table, column), _values in ENUMS.items():
        names = {c.name for c in TABLES[table].constraints if c.name}
        assert f"ck_{table}_{column}" in names or column in names, f"{table}.{column}"


def test_decision_tags_are_in_the_doc() -> None:
    notes = doc_tables()["decision_option"]["tags"].notes
    assert all(f"`{tag}`" in notes for tag in DECISION_TAGS)


def test_money_is_never_a_float() -> None:
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    for table in TABLES.values():
        for column in table.columns:
            compiled = column.type.compile(dialect=dialect).upper()
            for floating in ("FLOAT", "REAL", "DOUBLE"):
                assert floating not in compiled, f"{table.name}.{column.name}"
            if column.name.startswith("value_money") or column.name in ("allocation",):
                assert compiled == "BIGINT", f"{table.name}.{column.name}"
