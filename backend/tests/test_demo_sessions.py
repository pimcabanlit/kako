"""The demo household's scripted sessions: the files in the repo, and each mistake one can hold."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from kako.agents.recorded import read_recording
from kako.demo.files import read_demo
from kako.demo.sessions import (
    RECORDED_DIR,
    Approval,
    DemoSessionError,
    check_writes,
    read_sessions,
)

PEOPLE = frozenset(p.key for p in read_demo().people)
MANILA = timezone(timedelta(hours=8))


def test_the_repos_sessions_each_have_their_recording() -> None:
    sessions = read_sessions(people=PEOPLE)
    check_writes(sessions, read_demo())
    assert [s.name for s in sessions] == ["session-2", "session-4"]
    two, four = sessions
    assert (two.title, two.on) == ("Session 2", date(2026, 9, 15))
    assert two.known_at.isoformat() == "2026-09-15T09:00:00+08:00"
    assert [(t.speaker, t.seed) for t in two.turns] == [("mara", "s2:t1")]
    assert (four.title, four.on, four.writes) == ("Session 4", date(2026, 11, 20), (10, 11))
    told, asked = four.turns
    assert told.approve == Approval("mara", datetime(2026, 11, 20, 20, tzinfo=MANILA))
    assert four.known_at_of(told) == datetime(2026, 11, 20, 19, tzinfo=MANILA)
    assert four.known_at_of(asked) == datetime(2026, 11, 20, 20, 5, tzinfo=MANILA)
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
        (GOOD + "tone = 1\n", "may have known_at and approve"),  # a field of the turn
        (GOOD.replace('title = "S"', 'title = " "'), "title must be a non-empty string"),
        (GOOD.replace("on = 2026-09-15\n", "on = 2026-09-15T00:00:00\n"), "on must be a date"),
        (GOOD.replace("+08:00", ""), "known_at must be a time with its zone"),
        (GOOD.replace('"s.json"', '"../secrets.json"'), "recording must be a file name"),
        (GOOD.replace('"s.json"', '"s.txt"'), "recording must be a file name"),
        (GOOD.partition("[[turn]]")[0], "at least one"),
        (GOOD.replace('"mara"', '"lola"'), "'lola' isn't a person"),
        (GOOD.replace('"s9:t1"', '"S9 T1"'), "seed 'S9 T1'"),
        (GOOD.replace('"Hi"', '"  "'), "message must be a non-empty string"),
        (GOOD + '[[turn]]\nspeaker = "jun"\nseed = "s9:t2"\n', "has speaker, seed and message"),
        ("writes = [10, 10]\n" + GOOD, "writes is a list of changes.csv seq numbers, each once"),
        ("writes = [0]\n" + GOOD, "writes is a list"),
        ("writes = [10]\n" + GOOD, "approves them in a turn"),
        (GOOD + "known_at = 2026-09-15T08:00:00+08:00\n", "before what the session knew"),
        (GOOD + "known_at = 2026-09-15T10:00:00\n", "known_at must be a time with its zone"),
        (GOOD + 'approve = { by = "mara" }\n', "approve is { by"),
        (GOOD + 'approve = { by = "lola", at = 2026-09-15T10:00:00+08:00 }\n', "approve.by 'lola'"),
        (GOOD + 'approve = { by = "mara", at = 2026-09-15T10:00:00 }\n', "approve.at must be"),
        (GOOD + 'approve = { by = "mara", at = 2026-09-15T08:00:00+08:00 }\n', "before the turn"),
        (
            GOOD
            + 'approve = { by = "mara", at = 2026-09-15T10:00:00+08:00 }\n'
            + '[[turn]]\nspeaker = "jun"\nseed = "s9:t2"\nmessage = "So?"\n'
            + "known_at = 2026-09-15T09:30:00+08:00\n",
            "s9:t2: known_at is before",
        ),
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


def test_what_a_session_writes_is_checked_against_the_story() -> None:
    demo = read_demo()
    four = next(s for s in read_sessions(people=PEOPLE) if s.name == "session-4")
    lia = replace(four.turns[0], approve=Approval("lia", four.turns[0].approve.at))  # type: ignore[union-attr]
    later = replace(
        four.turns[0], approve=Approval("mara", datetime(2026, 11, 20, 21, tzinfo=MANILA))
    )
    cases = [
        (replace(four, writes=(10, 11, 99)), "writes 99, which isn't in changes.csv"),
        (replace(four, writes=(10,)), "change 11 belongs to a life event it writes"),
        (replace(four, writes=(3,)), "change 3 is recorded at"),
        (replace(four, turns=(lia, four.turns[1])), "approve.by must be an adult"),
        (replace(four, turns=(later, four.turns[1])), "not at one of the session's approvals"),
    ]
    for session, error in cases:
        with pytest.raises(DemoSessionError, match=error):
            check_writes((session,), demo)
    with pytest.raises(DemoSessionError, match="another session writes change 10"):
        check_writes((four, replace(four, name="again")), demo)
