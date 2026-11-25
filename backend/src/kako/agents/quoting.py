"""People's and models' words in a prompt: escaped, cut, and wrapped as data (REVIEW.md rule 5).

Every prompt Kako builds writes such words through these three, so none can start a heading, a
figure line or a `<data>` block of its own. `agents.brief` re-exports them.
"""

from __future__ import annotations

from typing import Final

NAME_CHARS: Final = 80  # the most of one name or label
QUOTE_CHARS: Final = 400  # the most of one memory, excerpt or reason


def escape(text: str) -> str:
    """Angle brackets and ampersands as entities: the text can't open or close a tag."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def plain(text: str, limit: int = NAME_CHARS) -> str:
    """A name or a short label from people or a model: one line, escaped, at most `limit`
    characters. It can't start a line of its own or open or close a `<data>` block."""
    body = " ".join(text.split())
    if len(body) > limit:
        body = body[: limit - 1] + "…"
    return escape(body)


def data(text: str, *, limit: int = QUOTE_CHARS, **attributes: str) -> str:
    """People's or a model's words, wrapped so they read as data, never as instructions, and cut
    at `limit` characters."""
    attrs = "".join(f' {k}="{escape(v).replace(chr(34), "&quot;")}"' for k, v in attributes.items())
    return f"<data{attrs}>{plain(text, limit)}</data>"
