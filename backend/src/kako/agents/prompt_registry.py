"""Every agent prompt, with the version that was used: one place to load them.

Kako's prompts are Markdown files in `kako/agents/prompts/`: the shared rules (`common`), one per
role (`orchestrator`, the four specialists, the single-agent baseline `single`) and dreaming's. The
repo is their record: a change to one is a reviewed PR, and a recording replays only against the
text it was made with (`chat.ChatRequest.digest`).

Each prompt comes with a `PromptVersion`: its name, where it came from and the SHA-256 of its text
as loaded (before code fills in `{glossary}`). Every model call logs the versions of the prompts in
its system message (`llm_call.prompts`), and every turn kept in Meko names them
(`kako_prompts`), so a recommendation can be traced to the exact prompts that produced it.
docs/architecture.md, "Prompt versions".
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import Any, Final, Literal, get_args

PromptName = Literal[
    "common", "orchestrator", "budget", "debt", "savings", "goals", "single", "dreaming"
]
PROMPT_NAMES: Final[tuple[PromptName, ...]] = get_args(PromptName)
PromptSource = Literal["repo"]


@dataclass(frozen=True)
class PromptVersion:
    """Which text of a prompt a call used: its name, its source and the SHA-256 of the text."""

    name: PromptName
    sha256: str
    source: PromptSource = "repo"

    def as_json(self) -> dict[str, Any]:
        return {"source": self.source, "sha256": self.sha256}


@dataclass(frozen=True)
class Prompt:
    text: str
    version: PromptVersion


@dataclass(frozen=True)
class SystemPrompt:
    """A system message's text and the versions of the prompts it was built from, in order."""

    text: str
    prompts: tuple[PromptVersion, ...] = ()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@cache
def load_prompt(name: PromptName) -> Prompt:
    """One prompt from the repo, stripped, with its version."""
    if name not in PROMPT_NAMES:
        raise ValueError(f"no prompt named {name!r}")
    raw = (files("kako.agents") / "prompts" / f"{name}.md").read_text(encoding="utf-8")
    text = raw.strip()
    return Prompt(text, PromptVersion(name, text_sha256(text)))


def versions_json(versions: Iterable[PromptVersion]) -> dict[str, dict[str, Any]]:
    """The versions by prompt name, names sorted, as `llm_call.prompts` and `kako_prompts` keep
    them: the same set reads the same whatever order the agents ran in."""
    by_name: Mapping[str, PromptVersion] = {v.name: v for v in versions}
    return {name: by_name[name].as_json() for name in sorted(by_name)}
