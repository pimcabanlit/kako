"""The conversation: what the orchestrator reads of the session so far (docs/architecture.md,
"The conversation").

Pure. A chat model follows a conversation best as the conversation itself, so the session's earlier
turns go to the orchestrator (and the single-agent baseline) as chat messages, after the system
prompt and before the turn's own message: each turn's message from the household (wrapped as data,
with who wrote it) and Kako's reply as the household saw it, with the options it offered and the
changes it filed. Tool calls and their results are never carried from one turn to the next: the
engine works every figure out again on the turn's snapshot, and the brief comes fresh each turn.
The conversation comes first and the brief last, so the next turn's request starts with this one's
(the provider's prompt cache serves it again).

**Compaction is code's, not a model's.** The conversation is kept word for word while it fits
`KAKO_HISTORY_TOKEN_BUDGET` (about 12,000 tokens). Past that, the oldest turns become one line each
(`digest_line`): the household's own words, cut; the options' labels; what was filed for a yes;
what Kako asked. No summary is written by a model, so none can drop or invent a number, and a
recorded turn replays the same way. The last `KEEP_VERBATIM` turns always stay word for word.
Turns move into the digest in blocks of `BLOCK`, so the start of the request stays the same for
several turns. Past `DIGEST_TOKENS`, the oldest digest lines are left out too, again in blocks, and
a line says which: the orchestrator reads any turn in full with `read_turns`.

The session's state (who is writing, what it is about, what Kako asked, the options on the table,
the changes filed) is written by `agents.brief` from the same kept turns, so every agent has it.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from kako.agents.chat import MESSAGE_OVERHEAD, Message, estimate_text_tokens
from kako.agents.kept import KeptTurn, PastSession
from kako.agents.present import day
from kako.agents.quoting import data, escape, plain

KEEP_VERBATIM: Final = 8  # the newest turns always kept word for word
BLOCK: Final = 10  # turns move into the digest, and out of it, this many at a time
DIGEST_TOKENS: Final = 3_000  # the most the digest of older turns takes
MESSAGE_CHARS: Final = 2_000  # the most of a household message kept word for word
REPLY_CHARS: Final = 4_000  # the most of a reply kept word for word
DIGEST_MESSAGE_CHARS: Final = 240  # the most of a household message a digest line keeps
ASKS_CHARS: Final = 300
TOPIC_CHARS: Final = 120
QUERY_CHARS: Final = 500  # the most of the brief's Meko search
SHORT_MESSAGE_WORDS: Final = 6  # a message this short is searched with the one before it
RECAP_CHARS: Final = 900
RECAP_MESSAGES: Final = 4  # the household messages a recap quotes: the first ones and the last


def who(turn: KeptTurn) -> str:
    return plain(turn.said_by) if turn.said_by else "The household"


def _block(text: str, limit: int) -> str:
    """Kako's own words from an earlier turn: lines kept, cut at `limit` characters, escaped so
    nothing in them opens or closes a `<data>` block."""
    body = text.strip()
    if len(body) > limit:
        body = body[: limit - 1] + "…"
    return escape(body)


def user_text(turn: KeptTurn) -> str:
    """An earlier turn's message, as the orchestrator reads it."""
    return f"{who(turn)} wrote (turn {turn.number}): " + data(
        turn.message, limit=MESSAGE_CHARS, source="household"
    )


def reply_text(turn: KeptTurn) -> str:
    """Kako's reply to an earlier turn, as the household saw it: the reply, the options with the
    moves behind them, the changes filed for a yes."""
    parts = [_block(turn.reply, REPLY_CHARS) or "(no reply text)"]
    if turn.options:
        lines = ["Options offered:"]
        for option in turn.options:
            moves = "; ".join(plain(a, 120) for a in option.allocations) or "no moves"
            mark = " (recommended)" if option.recommended else ""
            lines.append(
                f"- {plain(option.label)}{mark}: {_block(option.summary, 600)} "
                f"[what-if {plain(option.what_if, 40)}: {moves}]"
            )
        parts.append("\n".join(lines))
    if turn.changes:
        parts.append(
            "Filed for a yes: " + "; ".join(plain(c.shown, 200) for c in turn.changes) + "."
        )
    if turn.replan:
        parts.append("(Code also showed the household what changed and why.)")
    return "\n\n".join(parts)


def turn_messages(turn: KeptTurn) -> tuple[Message, Message]:
    return Message("user", user_text(turn)), Message("assistant", reply_text(turn))


def full_text(turn: KeptTurn) -> str:
    """One earlier turn in full, for `read_turns`."""
    return f"{user_text(turn)}\nKako replied:\n{reply_text(turn)}"


def digest_line(turn: KeptTurn) -> str:
    """An older turn in one line, by code: the household's words (cut), the options' labels, what
    was filed and what Kako asked. Kako's figures are left out: they were right then."""
    line = f"- Turn {turn.number}, {who(turn)}: " + data(
        turn.message, limit=DIGEST_MESSAGE_CHARS, source="household"
    )
    if turn.options:
        labels = ", ".join(
            plain(o.label) + (" (recommended)" if o.recommended else "") for o in turn.options
        )
        line += f" Kako offered {labels}."
    if turn.changes:
        line += " Filed for a yes: " + "; ".join(plain(c.shown, 120) for c in turn.changes) + "."
    if turn.asks:
        line += " Kako asked: " + data(turn.asks, limit=ASKS_CHARS, source="kako")
    return line


def _tokens(texts: Sequence[str]) -> int:
    return sum(estimate_text_tokens(t) + MESSAGE_OVERHEAD for t in texts)


@dataclass(frozen=True)
class History:
    """The conversation as the orchestrator reads it, and which turns went where."""

    messages: tuple[Message, ...]
    verbatim: tuple[int, ...]  # turn numbers kept word for word
    digest: tuple[int, ...]  # turn numbers kept as one line each
    left_out: tuple[int, ...]  # turn numbers left out (read them with read_turns)
    tokens: int  # the estimate, high
    budget: int

    def as_json(self) -> dict[str, object]:
        return {
            "verbatim": list(self.verbatim),
            "digest": list(self.digest),
            "left_out": list(self.left_out),
            "tokens": self.tokens,
            "budget": self.budget,
        }


def _span(numbers: Sequence[int]) -> str:
    return f"turn {numbers[0]}" if len(numbers) == 1 else f"turns {numbers[0]} to {numbers[-1]}"


def history(
    turns: Sequence[KeptTurn],
    budget: int,
    *,
    digest_budget: int = DIGEST_TOKENS,
    keep: int = KEEP_VERBATIM,
    block: int = BLOCK,
) -> History:
    """The session's earlier turns, oldest first, as chat messages within `budget` (word for word)
    and `digest_budget` (the older turns' lines). Deterministic: the same turns give the same
    messages, and a turn moves only forward (word for word, then a line, then left out)."""
    pairs = [turn_messages(t) for t in turns]
    costs = [_tokens([u.content or "", a.content or ""]) for u, a in pairs]
    n = len(turns)
    start = 0  # the first turn kept word for word
    while sum(costs[start:]) > budget and n - start > keep:
        start = min(start + block, n - keep)
    lines = [digest_line(t) for t in turns[:start]]
    first = 0  # the first turn kept as a line
    while first < start and _tokens(lines[first:]) > digest_budget:
        first = min(first + block, start)
    messages: list[Message] = []
    if start:
        head = [
            "Earlier in this session, shortened by code: one line a turn, the household's words "
            "cut and Kako's figures left out (they were right then). Read any turn in full with "
            "read_turns."
        ]
        if first:
            head.append(f"- ({_span(range(1, first + 1))} left out)")
        head += lines[first:]
        messages.append(Message("user", "\n".join(head)))
    for user, assistant in pairs[start:]:
        messages += [user, assistant]
    return History(
        tuple(messages),
        tuple(t.number for t in turns[start:]),
        tuple(t.number for t in turns[first:start]),
        tuple(t.number for t in turns[:first]),
        _tokens([m.content or "" for m in messages]),
        budget,
    )


def new_message(writer: str | None, message: str, number: int, limit: int) -> str:
    """This turn's message, as the orchestrator reads it after the brief."""
    name = plain(writer) if writer else "The household"
    return f"## The new message (turn {number})\n{name} writes: " + data(
        message, limit=limit, source="household"
    )


def search_query(message: str, turns: Sequence[KeptTurn]) -> str:
    """What the brief's one Meko search looks for: the message, after what the conversation is
    about (the orchestrator's last topic) and, for a short message such as "Jun", the household's
    message before it, so the search finds what the answer is about. Built by code."""
    parts: list[str] = []
    topic = next((t.topic for t in reversed(turns) if t.topic), None)
    if topic:
        parts.append(topic.strip()[:TOPIC_CHARS])
    if turns and len(message.split()) < SHORT_MESSAGE_WORDS:
        parts.append(turns[-1].message.strip()[:DIGEST_MESSAGE_CHARS])
    parts.append(message.strip())
    query = " — ".join(" ".join(p.split()) for p in parts if p)
    return query[:QUERY_CHARS]


def recap(past: PastSession, statuses: Mapping[uuid.UUID, str]) -> str:
    """An earlier session in a few lines, by code, for the brief of a later session: what it was
    about, who wrote what (the first messages and the last, cut), the options Kako offered last,
    the changes it filed with where they stand now, what it decided, and what Kako last asked.
    Kako's figures are left out (they were right then); the household's words are theirs."""
    turns = past.turns
    parts: list[str] = []
    topics = list(dict.fromkeys(t.topic.strip() for t in turns if t.topic and t.topic.strip()))
    if topics:
        parts.append("About: " + "; ".join(topics[-3:]) + ".")
    quoted = turns if len(turns) <= RECAP_MESSAGES else (*turns[: RECAP_MESSAGES - 1], turns[-1])
    for turn in quoted:
        name = turn.said_by or "The household"
        message = " ".join(turn.message.split())
        if len(message) > 160:
            message = message[:159] + "…"
        parts.append(f'Turn {turn.number}, {name}: "{message}"')
    offered = next((t for t in reversed(turns) if t.options), None)
    if offered is not None:
        labels = ", ".join(
            o.label + (" (recommended)" if o.recommended else "") for o in offered.options
        )
        parts.append(f"Kako offered at turn {offered.number}: {labels}.")
    changes = [c for t in turns for c in t.changes]
    if changes:
        parts.append(
            "Filed for a yes: "
            + "; ".join(
                c.shown + (f" ({statuses[c.proposal_id]})" if c.proposal_id in statuses else "")
                if c.proposal_id is not None
                else c.shown
                for c in changes[:4]
            )
            + (f"; and {len(changes) - 4} more" if len(changes) > 4 else "")
            + "."
        )
    if past.decisions:
        parts.append("Decided: " + "; ".join(past.decisions) + ".")
    if turns and turns[-1].asks:
        parts.append(f"Kako's last question: {turns[-1].asks.strip()}")
    text = " ".join(parts) or "No turns were kept."
    return text if len(text) <= RECAP_CHARS else text[: RECAP_CHARS - 1] + "…"


def recap_line(past: PastSession, statuses: Mapping[uuid.UUID, str]) -> str:
    """A past session as the brief lists it: its ref, title, date and recap."""
    count = len(past.turns)
    writers = list(dict.fromkeys(t.said_by for t in past.turns if t.said_by))
    by = f", {' and '.join(plain(w) for w in writers)}" if writers else ""
    return (
        f"- {past.ref}: {plain(past.title)}, {day(past.on)} ({count} turn"
        f"{'s' if count != 1 else ''}{by}"
        f"{'' if past.ended else ', not ended'}): "
        + data(recap(past, statuses), limit=RECAP_CHARS, source="kako-recap")
    )
