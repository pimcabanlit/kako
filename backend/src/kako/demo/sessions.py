"""The demo household's scripted sessions (`data/demo-household/sessions/*.toml`), read and checked.

A session names its title, the household's date (`on`), what Kako knew then (`known_at`, so a
database loaded with the whole story answers as it would have then), the recording its turns replay
from (a file in `data/recorded/`), and each turn: who speaks, its seed and the message. Pure: no
database, Meko or clock.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final

from kako.demo.files import DEMO_DIR

SESSIONS_DIR: Final = DEMO_DIR / "sessions"
RECORDED_DIR: Final = DEMO_DIR.parent / "recorded"
SEED: Final = re.compile(r"^[a-z0-9][a-z0-9:_-]{0,39}$")  # as the session API takes it
RECORDING: Final = re.compile(r"^[a-z0-9][a-z0-9_-]*\.json$")  # a file name, never a path


class DemoSessionError(Exception):
    """A session file that isn't as demo mode needs it."""


@dataclass(frozen=True)
class DemoTurn:
    speaker: str  # a person's key in people.csv
    seed: str
    message: str


@dataclass(frozen=True)
class DemoSession:
    name: str  # the file's stem: session-2
    title: str
    on: date
    known_at: datetime
    recording: Path
    turns: tuple[DemoTurn, ...]


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
    unknown = set(raw) - {"title", "on", "known_at", "recording", "turn"}
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
    return DemoSession(
        path.stem,
        title.strip(),
        on,
        known_at,
        recorded / recording,
        tuple(_turn(t, people, fail) for t in turns),
    )


def _turn(raw: Any, people: frozenset[str], fail: Any) -> DemoTurn:
    if not isinstance(raw, dict) or set(raw) != {"speaker", "seed", "message"}:
        raise fail("each [[turn]] has exactly speaker, seed and message")
    speaker, seed, message = raw["speaker"], raw["seed"], raw["message"]
    if speaker not in people:
        raise fail(f"{speaker!r} isn't a person in people.csv")
    if not isinstance(seed, str) or not SEED.match(seed):
        raise fail(f"seed {seed!r} must be lowercase letters, digits, ':', '_' or '-'")
    if not isinstance(message, str) or not message.strip():
        raise fail("message must be a non-empty string")
    return DemoTurn(speaker, seed, message.strip())
