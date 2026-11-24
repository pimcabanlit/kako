"""The fact rules, the engine, the planning rules and dreaming's claims and classification stay
pure: no database, network, model, clock or randomness. docs/architecture.md: "the engine and
fact rules never import the database, Meko or the model SDK"; REVIEW.md rule 6: no system clock
for household dates, no unseeded randomness.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "kako"
PURE_PACKAGES = ("facts", "engine", "planning", "decisions")
# Pure modules in packages that aren't, and the one pure module of `kako.agents` they may use (the
# way the agents write values: pesos, days).
PURE_MODULES = (
    "dreaming/claims.py",
    "dreaming/classify.py",
    "dreaming/candidates.py",
    "agents/present.py",
    "upkeep/sentences.py",
    "upkeep/plan.py",
    "upkeep/records.py",
    "dreaming/patterns.py",
)
ALLOWED = ("kako.agents.present",)

BANNED_MODULES = (
    "sqlalchemy",
    "asyncpg",
    "httpx",
    "openai",
    "azure",
    "random",
    "secrets",
    "time",
    "os",
    "subprocess",
    "socket",
    "kako.db",
    "kako.meko",
    "kako.agents",
    "kako.api",
    "kako.settings",
)
BANNED_CALLS = ("now", "today", "utcnow", "uuid4", "getenv")


def _files() -> list[Path]:
    packages = [p for package in PURE_PACKAGES for p in (SRC / package).rglob("*.py")]
    return sorted([*packages, *(SRC / m for m in PURE_MODULES)])


def test_there_is_something_to_check() -> None:
    assert _files()


@pytest.mark.parametrize("path", _files(), ids=lambda p: str(p.relative_to(SRC)))
def test_no_impure_imports_or_calls(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            if name in ALLOWED:
                continue
            for banned in BANNED_MODULES:
                imports_it = name == banned or name.startswith(banned + ".")
                assert not imports_it, f"{path.name}:{node.lineno} imports {name}"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in BANNED_CALLS, (
                f"{path.name}:{node.lineno} calls .{node.func.attr}()"
            )
