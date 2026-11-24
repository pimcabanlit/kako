"""The demo household's scripted sessions (`data/demo-household/sessions/*.toml`), read and checked.

A session names its title, the household's date (`on`), what Kako knew then (`known_at`, so a
database loaded with the whole story answers as it would have then), the recording its turns replay
from (a file in `data/recorded/`), and each turn: who speaks, its seed and the message, and
optionally what Kako knew at that turn (a later `known_at`) and an `approve` step after it: an adult
approves what the turn proposed, at a time in the story.

A session whose approval writes rows of `changes.csv` names them in `writes`: demo mode loads the
story without them, the session writes them through its own proposals, and code checks that what
it wrote is what those rows say (`check_writes`). Pure: no database, Meko or clock.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final

from kako.demo.files import DEMO_DIR, DemoHousehold

SESSIONS_DIR: Final = DEMO_DIR / "sessions"
RECORDED_DIR: Final = DEMO_DIR.parent / "recorded"
SEED: Final = re.compile(r"^[a-z0-9][a-z0-9:_-]{0,39}$")  # as the session API takes it
RECORDING: Final = re.compile(r"^[a-z0-9][a-z0-9_-]*\.json$")  # a file name, never a path


class DemoSessionError(Exception):
    """A session file that isn't as demo mode needs it."""


@dataclass(frozen=True)
class Approval:
    """After a turn: `by` (an adult's key) approves everything the turn proposed, `at` then."""

    by: str
    at: datetime


@dataclass(frozen=True)
class DemoTurn:
    speaker: str  # a person's key in people.csv
    seed: str
    message: str
    known_at: datetime | None = None  # None: the session's
    approve: Approval | None = None


@dataclass(frozen=True)
class DemoSession:
    name: str  # the file's stem: session-2
    title: str
    on: date
    known_at: datetime
    recording: Path
    turns: tuple[DemoTurn, ...]
    writes: tuple[int, ...] = ()  # changes.csv rows its approvals write (their seq)

    def known_at_of(self, turn: DemoTurn) -> datetime:
        return turn.known_at or self.known_at


def read_sessions(
    folder: Path = SESSIONS_DIR, *, people: frozenset[str], recorded: Path = RECORDED_DIR
) -> tuple[DemoSession, ...]:
    """Every session in the folder, in name order. `people`: the speakers that may appear."""
    sessions = tuple(_session(path, people, recorded) for path in sorted(folder.glob("*.toml")))
    seeds = [t.seed for s in sessions for t in s.turns]
    if len(set(seeds)) != len(seeds):
        raise DemoSessionError("two turns share a seed")
    return sessions


def _session(path: Path, people: frozenset[str], recorded: Path) -> DemoSession:
    def fail(what: str) -> DemoSessionError:
        return DemoSessionError(f"{path.name}: {what}")

    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise fail(str(exc)) from None
    unknown = set(raw) - {"title", "on", "known_at", "recording", "turn", "writes"}
    if unknown:
        raise fail(f"unknown fields {sorted(unknown)}")
    title, on, known_at, recording = (raw.get(k) for k in ("title", "on", "known_at", "recording"))
    if not isinstance(title, str) or not title.strip():
        raise fail("title must be a non-empty string")
    if not isinstance(on, date) or isinstance(on, datetime):
        raise fail("on must be a date")
    if not isinstance(known_at, datetime) or known_at.tzinfo is None:
        raise fail("known_at must be a time with its zone")
    if not isinstance(recording, str) or not RECORDING.match(recording):
        raise fail("recording must be a file name in data/recorded/, such as session-2.json")
    turns = raw.get("turn")
    if not isinstance(turns, list) or not turns:
        raise fail("a session has at least one [[turn]]")
    writes = raw.get("writes", [])
    if (
        not isinstance(writes, list)
        or not all(isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in writes)
        or len(set(writes)) != len(writes)
    ):
        raise fail("writes is a list of changes.csv seq numbers, each once")
    read = tuple(_turn(t, people, fail) for t in turns)
    if writes and not any(t.approve for t in read):
        raise fail("a session that writes changes approves them in a turn (approve)")
    last = known_at
    for turn in read:  # the story moves forward: each turn knows at least what came before
        if turn.known_at is not None and turn.known_at < last:
            raise fail(f"turn {turn.seed}: known_at is before what the session knew already")
        last = turn.known_at or last
        if turn.approve is not None:
            if turn.approve.at < last:
                raise fail(f"turn {turn.seed}: approve.at is before the turn")
            last = turn.approve.at
    return DemoSession(
        path.stem, title.strip(), on, known_at, recorded / recording, read, tuple(writes)
    )


def _turn(raw: Any, people: frozenset[str], fail: Any) -> DemoTurn:
    if (
        not isinstance(raw, dict)
        or not {"speaker", "seed", "message"} <= set(raw)
        or not set(raw) <= {"speaker", "seed", "message", "known_at", "approve"}
    ):
        raise fail("each [[turn]] has speaker, seed and message, and may have known_at and approve")
    speaker, seed, message = raw["speaker"], raw["seed"], raw["message"]
    if speaker not in people:
        raise fail(f"{speaker!r} isn't a person in people.csv")
    if not isinstance(seed, str) or not SEED.match(seed):
        raise fail(f"seed {seed!r} must be lowercase letters, digits, ':', '_' or '-'")
    if not isinstance(message, str) or not message.strip():
        raise fail("message must be a non-empty string")
    known_at = raw.get("known_at")
    if known_at is not None and (not isinstance(known_at, datetime) or known_at.tzinfo is None):
        raise fail(f"turn {seed}: known_at must be a time with its zone")
    approve = raw.get("approve")
    approval = None
    if approve is not None:
        if not isinstance(approve, dict) or set(approve) != {"by", "at"}:
            raise fail(f"turn {seed}: approve is {{ by = <person>, at = <time with its zone> }}")
        by, at = approve["by"], approve["at"]
        if by not in people:
            raise fail(f"turn {seed}: approve.by {by!r} isn't a person in people.csv")
        if not isinstance(at, datetime) or at.tzinfo is None:
            raise fail(f"turn {seed}: approve.at must be a time with its zone")
        approval = Approval(by, at)
    return DemoTurn(speaker, seed, message.strip(), known_at, approval)


def check_writes(sessions: tuple[DemoSession, ...], demo: DemoHousehold) -> None:
    """Each row a session writes is a change of the story, recorded at its approval, and written by
    one session only; a life event's facts go with it."""
    changes = {c.seq: c for c in demo.changes}
    adults = {p.key for p in demo.people if p.role == "adult"}
    seen: set[int] = set()
    for session in sessions:
        approvals = [t.approve for t in session.turns if t.approve is not None]
        if any(a.by not in adults for a in approvals):
            raise DemoSessionError(f"{session.name}: approve.by must be an adult")
        times = {a.at for a in approvals}
        for seq in session.writes:
            change = changes.get(seq)
            if change is None:
                raise DemoSessionError(f"{session.name}: writes {seq}, which isn't in changes.csv")
            if seq in seen:
                raise DemoSessionError(f"{session.name}: another session writes change {seq}")
            seen.add(seq)
            if change.recorded_at not in times:
                raise DemoSessionError(
                    f"{session.name}: change {seq} is recorded at "
                    f"{change.recorded_at.isoformat()}, not at one of the session's approvals"
                )
            if change.kind not in ("life_event", "new_fact", "replace_fact"):
                raise DemoSessionError(
                    f"{session.name}: change {seq} is a {change.kind}, which a turn doesn't propose"
                )
        events = {changes[n].life_event for n in session.writes if changes[n].kind == "life_event"}
        for change in demo.changes:
            joins = change.kind != "life_event" and change.life_event in events
            if joins and change.seq not in session.writes:
                raise DemoSessionError(
                    f"{session.name}: change {change.seq} belongs to a life event it writes, so "
                    "it writes that change too"
                )
