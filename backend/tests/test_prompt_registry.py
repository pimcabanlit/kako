"""Every agent prompt loads with its version (docs/architecture.md, "Prompt versions")."""

from __future__ import annotations

import hashlib
from importlib.resources import files

import pytest

from kako.agents.chat import ChatRequest, Message
from kako.agents.prompt_registry import (
    PROMPT_NAMES,
    PromptVersion,
    load_prompt,
    text_sha256,
    versions_json,
)


def test_every_prompt_file_has_a_name_and_every_name_a_file() -> None:
    folder = files("kako.agents") / "prompts"
    on_disk = sorted(p.name.removesuffix(".md") for p in folder.iterdir() if p.name.endswith(".md"))
    assert on_disk == sorted(PROMPT_NAMES)


@pytest.mark.parametrize("name", PROMPT_NAMES)
def test_a_prompts_version_is_the_hash_of_its_text_as_loaded(name: str) -> None:
    prompt = load_prompt(name)  # type: ignore[arg-type]
    raw = (files("kako.agents") / "prompts" / f"{name}.md").read_text(encoding="utf-8")
    assert prompt.text == raw.strip()
    assert prompt.version == PromptVersion(
        name,  # type: ignore[arg-type]
        hashlib.sha256(raw.strip().encode()).hexdigest(),
        "repo",
    )


def test_an_unknown_prompt_is_refused() -> None:
    with pytest.raises(ValueError, match="no prompt named 'tax'"):
        load_prompt("tax")  # type: ignore[arg-type]


def test_versions_read_the_same_in_any_order() -> None:
    a = PromptVersion("orchestrator", text_sha256("a"))
    b = PromptVersion("common", text_sha256("b"))
    assert versions_json([a, b]) == versions_json([b, a])
    assert list(versions_json([a, b])) == ["common", "orchestrator"]
    assert versions_json([]) == {}


def test_prompt_versions_stay_out_of_the_request_digest() -> None:
    # The system message's text is in the digest already; the versions only label it, so a
    # recording made before versions were logged still replays.
    plain = ChatRequest("fast", (Message("system", "s"), Message("user", "u")), 100)
    labelled = ChatRequest("fast", plain.messages, 100, prompts=(load_prompt("debt").version,))
    assert labelled.digest() == plain.digest()
