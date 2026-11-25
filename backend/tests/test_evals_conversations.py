"""The conversation test set's file and its checks on an answer, in memory."""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from kako.agents.answers import Citation, Option, TurnAnswer
from kako.agents.ask import Asked, StoredProposal
from kako.evals.conversations import (
    OPEN_QUESTIONS,
    ConversationSetError,
    Turn,
    read_conversations,
    reply_checks,
)
from kako.evals.questions import architecture_of, session_title


def _asked(
    reply: str,
    *,
    options: int = 0,
    proposed: tuple[str, ...] = (),
    kind: str | None = None,
    sources: tuple[Citation, ...] = (),
) -> Asked:
    offered = tuple(Option(f"{'AB'[n]}: one", "a summary", "", (), (), ()) for n in range(options))
    answer = TurnAnswer(reply, offered, None, (), kind=kind, sources=sources)  # type: ignore[arg-type]
    return Asked(
        answer,
        uuid.uuid4(),
        "c01:t1",
        1,
        0,
        0,
        Decimal(0),
        proposed=tuple(StoredProposal(uuid.uuid4(), "replace_fact", s) for s in proposed),
    )


def _failed(turn: Turn, asked: Asked) -> list[str]:
    return [c.name for c in reply_checks(turn, asked) if not c.passed]


def test_the_set_reads_and_each_turn_has_its_writer() -> None:
    conversations = read_conversations()
    assert [c.id for c in conversations] == ["c01", "c02", "c03"]
    jun = conversations[0]
    assert [t.message for t in jun.turns] == [
        "what if i lose my job",
        "Jun",
        "just give me the simulation",
    ]
    assert {t.by for c in conversations for t in c.turns} == {"jun", "mara"}
    assert jun.seed(2) == "c01:t2"
    # A conversation's session is told apart from the household's, by architecture.
    assert architecture_of(session_title("c01", "specialists")) == "specialists"


def test_the_checks_on_an_answer() -> None:
    jun = read_conversations()[0].turns[0]
    assert _failed(jun, _asked("Your emergency fund covers your runway.")) == []
    assert _failed(jun, _asked("Do you mean Jun's or Mara's?")) == [
        "says one of 'emergency fund', 'runway'",
        "doesn't say \"Jun's or Mara's\"",
    ]
    assert _failed(jun, _asked("Your runway.", proposed=("Jun's salary ends",))) == [
        "files nothing"
    ]
    mara = read_conversations()[1].turns[0]
    assert _failed(mara, _asked("Noted, Mara.", proposed=("Mara's salary: ₱72,000.00",))) == []
    assert _failed(mara, _asked("Noted, Mara.", proposed=("Jun's salary: ₱72,000.00",))) == [
        "files Mara's salary"
    ]
    assert _failed(mara, _asked("Noted, Mara.")) == ["files Mara's salary"]
    go = read_conversations()[2].turns[1]
    assert _failed(go, _asked("B it is: here is what B does.")) == []
    # "B" is a whole word: "Bills" doesn't say it; an option's label does.
    assert _failed(go, _asked("Bills first.")) == ["says one of 'B'"]
    assert _failed(go, _asked("Bills first.", options=2)) == ["0 to 1 options"]
    assert [c.name for c in reply_checks(go, None)] == ["answered"]


def test_the_open_questions_read_and_score_kind_sources_and_labels() -> None:
    questions = read_conversations(OPEN_QUESTIONS)
    assert [c.id for c in questions] == [f"o{n:02}" for n in range(1, 31)]
    assert all(len(c.turns) == 1 and c.turns[0].kinds for c in questions)
    # Every question but small talk is answered, never turned away.
    assert all(
        "Kako can't test" in c.turns[0].lacks
        for c in questions
        if "small_talk" not in c.turns[0].kinds
    )
    raise_ = questions[0].turns[0]
    assert raise_.kinds == ("simulate",)
    assert raise_.sourced
    assert raise_.labels == ("Scenario, nothing saved",)
    doc = Citation("knowledge", "doc:sss", "file:sss", "")
    assert _failed(raise_, _asked("Your surplus would grow.", kind="explain", sources=(doc,))) == [
        "a simulate answer",
        "labelled 'Scenario, nothing saved'",
    ]
    assert _failed(raise_, _asked("Kako can't test that. Your surplus.", kind="simulate")) == [
        "doesn't say \"Kako can't test\"",
        "doesn't say \"can't test that\"",
        "names its sources",
        "labelled 'Scenario, nothing saved'",
    ]
    guide = next(c for c in questions if "From your documents" in c.turns[0].labels).turns[0]
    labelled = [c.name for c in reply_checks(guide, _asked("x", sources=(doc,))) if c.passed]
    assert "labelled 'From your documents'" in labelled


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("version = 2", "version must be 1"),
        ("version = 1", "no \\[\\[conversation\\]\\]"),
        (
            'version = 1\n[[conversation]]\nid = "x1"',
            "must look like c01",
        ),
        (
            'version = 1\n[[conversation]]\nid = "c01"\ntitle = "t"\non = 2026-12-01\n'
            "known_at = 2026-12-01T12:00:00",
            "known_at must be a time with its zone",
        ),
        (
            'version = 1\n[[conversation]]\nid = "c01"\ntitle = "t"\non = 2026-12-01\n'
            "known_at = 2026-12-01T12:00:00+08:00\n[[conversation.turn]]\n"
            'by = "jun"\nmessage = "hi"\nproposes = true',
            "proposes is false",
        ),
        (
            'version = 1\n[[conversation]]\nid = "c01"\ntitle = "t"\non = 2026-12-01\n'
            "known_at = 2026-12-01T12:00:00+08:00\n[[conversation.turn]]\n"
            'by = "jun"\nmessage = "hi"\noptions = [3, 1]',
            "options must be",
        ),
        (
            'version = 1\n[[conversation]]\nid = "c01"\ntitle = "t"\non = 2026-12-01\n'
            "known_at = 2026-12-01T12:00:00+08:00\n[[conversation.turn]]\n"
            'by = "jun"\nmessage = "hi"\nsays = ["x"]',
            "unknown fields",
        ),
        (
            'version = 1\n[[conversation]]\nid = "o01"\ntitle = "t"\non = 2026-12-01\n'
            "known_at = 2026-12-01T12:00:00+08:00\n[[conversation.turn]]\n"
            'by = "jun"\nmessage = "hi"\nkinds = ["guess"]',
            "kinds are among",
        ),
        (
            'version = 1\n[[conversation]]\nid = "o01"\ntitle = "t"\non = 2026-12-01\n'
            "known_at = 2026-12-01T12:00:00+08:00\n[[conversation.turn]]\n"
            'by = "jun"\nmessage = "hi"\nlabels = ["Advice"]',
            "labels are among",
        ),
    ],
)
def test_a_broken_file_is_refused(tmp_path: Path, text: str, error: str) -> None:
    path = tmp_path / "conversations.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConversationSetError, match=error):
        read_conversations(path)
