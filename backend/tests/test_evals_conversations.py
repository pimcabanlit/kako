"""The conversation test set's file and its checks on an answer, in memory."""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from kako.agents.answers import Option, TurnAnswer
from kako.agents.ask import Asked, StoredProposal
from kako.evals.conversations import (
    ConversationSetError,
    Turn,
    read_conversations,
    reply_checks,
)
from kako.evals.questions import architecture_of, session_title


def _asked(reply: str, *, options: int = 0, proposed: tuple[str, ...] = ()) -> Asked:
    offered = tuple(Option(f"{'AB'[n]}: one", "a summary", "", (), (), ()) for n in range(options))
    answer = TurnAnswer(reply, offered, None, ())
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
    ],
)
def test_a_broken_file_is_refused(tmp_path: Path, text: str, error: str) -> None:
    path = tmp_path / "conversations.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConversationSetError, match=error):
        read_conversations(path)
