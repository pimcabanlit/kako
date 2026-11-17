"""Upload the demo household's documents (statements and reference) to Meko's knowledge base.

Each file is uploaded once: Meko knows a file by its content, so running this again uploads nothing
new. It then waits, a bounded number of times, until Meko has indexed each one.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Final

from kako.demo.files import DemoHousehold
from kako.meko.adapter import Document, Meko
from kako.meko.client import MekoError

AGENT: Final = "kako:seed"


class DemoUploadError(MekoError):
    """A demo document that Meko couldn't index."""


async def upload_demo_documents(
    meko: Meko,
    demo: DemoHousehold,
    conversation_id: str,
    *,
    checks: int = 30,
    pause: float = 1.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[Document]:
    """Upload every demo document, then wait until each is searchable. At most `checks` status
    checks per document, `pause` seconds apart."""
    uploaded = [
        await meko.upload_document(conversation_id, path.name, path.read_bytes(), agent_id=AGENT)
        for path in demo.documents
    ]
    done: list[Document] = []
    for document in uploaded:
        for check in range(checks):
            status = await meko.document_status(conversation_id, document.key, agent_id=AGENT)
            if status.state == "failed":
                raise DemoUploadError(f"Meko couldn't index {document.filename}: {status.message}")
            if status.state == "completed":
                done.append(
                    replace(
                        status,
                        filename=document.filename,
                        already_uploaded=document.already_uploaded,
                    )
                )
                break
            if check < checks - 1:
                await sleep(pause)
        else:
            raise DemoUploadError(f"{document.filename} wasn't indexed after {checks} checks")
    return done
