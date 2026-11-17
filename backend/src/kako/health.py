"""The health report's shapes, shared by the probes and the `/api/v1/health` route."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field


class ServiceStatus(BaseModel):
    """One dependency: reachable or not, and a short plain-words detail."""

    ok: bool
    detail: str
    latency_ms: int | None = None
    version: str | None = Field(default=None, description="The server's version, when known")


class MekoStatus(ServiceStatus):
    target: Literal["local", "cloud"]


class HealthReport(BaseModel):
    status: Literal["ok", "degraded"]
    postgres: ServiceStatus
    meko: MekoStatus


# A password inside a URL (scheme://user:password@host) and a bearer token.
_URL_PASSWORD = re.compile(r"(?P<head>[a-z][a-z0-9+.-]*://[^\s:/@]+:)[^\s@]+@", re.IGNORECASE)
_BEARER = re.compile(r"(?P<head>bearer\s+)\S+", re.IGNORECASE)


def redact(text: str) -> str:
    """Blank out URL passwords and bearer tokens."""
    text = _URL_PASSWORD.sub(r"\g<head>***@", text)
    return _BEARER.sub(r"\g<head>***", text)


def safe_error(exc: BaseException) -> str:
    """A short description of a failure, safe to show and to log.

    Only the exception's type and the first line of its message are kept, with URL passwords and
    bearer tokens blanked out, cut to 200 characters.
    """
    lines = str(exc).strip().splitlines()
    message = redact(lines[0]) if lines else ""
    text = f"{type(exc).__name__}: {message}" if message else type(exc).__name__
    return text[:200]
