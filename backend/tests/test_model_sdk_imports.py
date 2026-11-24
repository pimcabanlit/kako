"""Only the model manager may import a model SDK (REVIEW.md rule 10; Phase 3, task 1, done when: a
lint check fails if any other module imports the SDK).

Two checks: Ruff's banned-import rule (TID251, in pyproject.toml) refuses the import in any other
file, and a scan of every module under `src/kako` finds none today.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
SOURCE = BACKEND / "src" / "kako"
BANNED = ("openai", "azure.identity", "azure.ai")
MANAGER = SOURCE / "agents" / "model_manager.py"


def _ruff(filename: str, code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - a fixed command on test-owned input
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--select",
            "TID251",
            "--stdin-filename",
            filename,
            "-",
        ],
        input=code,
        text=True,
        capture_output=True,
        cwd=BACKEND,
        check=False,
    )


@pytest.mark.parametrize(
    "code",
    [
        "import openai\n",
        "from openai import AsyncOpenAI\n",
        "from azure.identity import ClientSecretCredential\n",
        "import azure.ai.inference\n",
    ],
)
@pytest.mark.parametrize(
    "filename", ["src/kako/agents/orchestrator.py", "src/kako/api/app.py", "tests/test_x.py"]
)
def test_ruff_refuses_a_model_sdk_outside_the_model_manager(filename: str, code: str) -> None:
    result = _ruff(filename, code)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "TID251" in result.stdout


def test_ruff_allows_it_in_the_model_manager() -> None:
    result = _ruff("src/kako/agents/model_manager.py", "import openai\nimport azure.identity\n")
    assert result.returncode == 0, result.stdout + result.stderr


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_no_other_module_imports_a_model_sdk() -> None:
    offenders = {
        str(path.relative_to(BACKEND)): sorted(
            name
            for name in _imports(path)
            if any(name == b or name.startswith(b + ".") for b in BANNED)
        )
        for path in SOURCE.rglob("*.py")
        if path != MANAGER
    }
    assert {k: v for k, v in offenders.items() if v} == {}
    assert "openai" in _imports(MANAGER)  # the scan does see imports
