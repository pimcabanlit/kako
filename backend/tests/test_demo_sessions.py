"""The demo household's scripted sessions: the files in the repo, and each mistake one can hold."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from kako.agents.recorded import read_recording
from kako.demo.files import read_demo
from kako.demo.sessions import RECORDED_DIR, DemoSessionError, read_sessions

PEOPLE = frozenset(p.key for p in read_demo().people)


def test_the_repos_sessions_each_have_their_recording() -> None:
    sessions = read_sessions(people=PEOPLE)
    assert [s.name for s in sessions][:1] == ["session-2"]
    two = sessions[0]
    assert (two.title, two.on) == ("Session 2", date(2026, 9, 15))
    assert two.known_at.isoformat() == "2026-09-15T09:00:00+08:00"
    assert [(t.speaker, t.seed) for t in two.turns] == [("mara", "s2:t1")]
    for session in sessions:
        assert session.recording.parent == RECORDED_DIR
        recorded = read_recording(session.recording)
        for turn in session.turns:
            assert any(key.startswith(f"{turn.seed}/") for key in recorded), turn.seed


GOOD = (
    'title = "S"\non = 2026-09-15\nknown_at = 2026-09-15T09:00:00+08:00\n'
    'recording = "s.json"\n'
    '[[turn]]\nspeaker = "mara"\nseed = "s9:t1"\nmessage = "Hi"\n'
)


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("tone = 1\n" + GOOD, "unknown fields"),
        (GOOD + "tone = 1\n", "exactly speaker, seed and message"),  # a field of the turn
        (GOOD.replace('title = "S"', 'title = " "'), "title must be a non-empty string"),
        (GOOD.replace("on = 2026-09-15\n", "on = 2026-09-15T00:00:00\n"), "on must be a date"),
        (GOOD.replace("+08:00", ""), "known_at must be a time with its zone"),
        (GOOD.replace('"s.json"', '"../secrets.json"'), "recording must be a file name"),
        (GOOD.replace('"s.json"', '"s.txt"'), "recording must be a file name"),
        (GOOD.partition("[[turn]]")[0], "at least one"),
        (GOOD.replace('"mara"', '"lola"'), "'lola' isn't a person"),
        (GOOD.replace('"s9:t1"', '"S9 T1"'), "seed 'S9 T1'"),
        (GOOD.replace('"Hi"', '"  "'), "message must be a non-empty string"),
        (GOOD + '[[turn]]\nspeaker = "jun"\nseed = "s9:t2"\n', "exactly speaker, seed and message"),
        ("title = [", "s.toml"),
    ],
)
def test_a_broken_session_names_the_file_and_the_field(
    tmp_path: Path, text: str, error: str
) -> None:
    (tmp_path / "s.toml").write_text(text, encoding="utf-8")
    with pytest.raises(DemoSessionError, match=error):
        read_sessions(tmp_path, people=PEOPLE)


def test_two_turns_cant_share_a_seed(tmp_path: Path) -> None:
    (tmp_path / "a.toml").write_text(GOOD, encoding="utf-8")
    (tmp_path / "b.toml").write_text(GOOD, encoding="utf-8")
    with pytest.raises(DemoSessionError, match="two turns share a seed"):
        read_sessions(tmp_path, people=PEOPLE)
    (tmp_path / "b.toml").write_text(GOOD.replace("s9:t1", "s9:t2"), encoding="utf-8")
    sessions = read_sessions(tmp_path, people=PEOPLE, recorded=tmp_path / "rec")
    assert [s.name for s in sessions] == ["a", "b"]
    assert sessions[0].recording == tmp_path / "rec" / "s.json"
