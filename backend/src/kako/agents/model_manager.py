"""The model manager: the only module that imports a model SDK (REVIEW.md rule 10).

Models are Azure AI Foundry deployments, reached with the OpenAI SDK on Foundry's v1 endpoint
(`<endpoint>/openai/v1/`) and signed in with Microsoft Entra ID: a bearer token for the Cognitive
Services scope, never an API key. Deployment names come from settings only.

Phase 1 needs one thing from it: `check_models`, one tiny call per deployment. Phase 3 adds the
per-turn budget, the daily cap, `llm_call` logging with cost, and recorded responses for tests and
demo mode, behind the same `ModelBackend` seam that tests use today.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import httpx2
from azure.core.credentials import TokenCredential
from azure.core.exceptions import ClientAuthenticationError
from azure.identity import (
    AzureCliCredential,
    ClientSecretCredential,
    get_bearer_token_provider,
)
from openai import OpenAI, OpenAIError

from kako.health import safe_error
from kako.settings import Settings

COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"
CHECK_PROMPT = "Reply with the single word OK."


class ModelError(Exception):
    """A model call or the sign-in before it failed."""


@dataclass(frozen=True)
class ModelReply:
    deployment: str
    text: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


class ModelBackend(Protocol):
    """Sends one chat request to one deployment. Foundry in live mode; fakes in tests."""

    def complete(self, deployment: str, prompt: str, max_output_tokens: int) -> ModelReply: ...


def sign_in_method(settings: Settings) -> str:
    """Which credential `credential_for` will use, in plain words."""
    if settings.azure_client_id and settings.azure_client_secret:
        return "Kako's app registration (KAKO_AZURE_CLIENT_ID)"
    return "Azure CLI (az login)"


def credential_for(settings: Settings) -> ClientSecretCredential | AzureCliCredential:
    """Kako's app registration when its three settings are set, otherwise `az login`.

    Never `DefaultAzureCredential`: it would also read the AZURE_* variables of whatever else
    shares the environment, and sign Kako in as a different app.
    """
    if settings.azure_client_id and settings.azure_client_secret:
        if not settings.azure_tenant_id:
            raise ModelError("KAKO_AZURE_TENANT_ID is required with KAKO_AZURE_CLIENT_ID")
        return ClientSecretCredential(
            tenant_id=settings.azure_tenant_id,
            client_id=settings.azure_client_id,
            client_secret=settings.azure_client_secret.get_secret_value(),
        )
    if settings.azure_client_id or settings.azure_client_secret:
        raise ModelError("set both KAKO_AZURE_CLIENT_ID and KAKO_AZURE_CLIENT_SECRET, or neither")
    return AzureCliCredential(tenant_id=settings.azure_tenant_id or "")


class FoundryBackend:
    """Chat completions on Azure AI Foundry's v1 endpoint, with an Entra ID token."""

    def __init__(
        self,
        settings: Settings,
        credential: TokenCredential | None = None,
        *,
        http_client: httpx2.Client | None = None,
    ) -> None:
        if not settings.foundry_endpoint:
            raise ModelError("KAKO_FOUNDRY_ENDPOINT is not set")
        token_provider: Callable[[], str] = get_bearer_token_provider(
            credential or credential_for(settings),
            COGNITIVE_SERVICES_SCOPE,
        )
        self._client = OpenAI(
            base_url=settings.foundry_endpoint.rstrip("/") + "/openai/v1/",
            api_key=token_provider,
            max_retries=1,  # bounded: at most two attempts per call
            timeout=30.0,
            http_client=http_client,
        )

    def complete(self, deployment: str, prompt: str, max_output_tokens: int) -> ModelReply:
        started = time.perf_counter()
        try:
            response = self._client.chat.completions.create(
                model=deployment,
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=max_output_tokens,
            )
        except (OpenAIError, ClientAuthenticationError) as exc:
            raise ModelError(safe_error(exc)) from exc
        latency_ms = round((time.perf_counter() - started) * 1000)
        text = (response.choices[0].message.content or "") if response.choices else ""
        usage = response.usage
        return ModelReply(
            deployment=deployment,
            text=text.strip(),
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            latency_ms=latency_ms,
        )


@dataclass(frozen=True)
class CheckLine:
    ok: bool
    label: str
    detail: str

    def __str__(self) -> str:
        return f"[{'PASS' if self.ok else 'FAIL'}] {self.label}: {self.detail}"


def check_models(
    settings: Settings,
    *,
    credential: TokenCredential | None = None,
    backend_factory: Callable[[Settings, TokenCredential | None], ModelBackend] = FoundryBackend,
) -> list[CheckLine]:
    """Settings, sign-in, then one tiny call per deployment. Prints nothing secret.

    At most one call per distinct deployment name, each with at most one retry.
    """
    lines: list[CheckLine] = []
    missing = [
        name
        for name, value in (
            ("KAKO_FOUNDRY_ENDPOINT", settings.foundry_endpoint),
            ("KAKO_MODEL_STRONG", settings.model_strong),
            ("KAKO_MODEL_FAST", settings.model_fast),
        )
        if not value
    ]
    lines.append(
        CheckLine(
            ok=not missing,
            label="Settings",
            detail=f"missing {', '.join(missing)}"
            if missing
            else f"{settings.foundry_endpoint}; strong={settings.model_strong}, "
            f"fast={settings.model_fast}",
        )
    )
    if missing:
        return lines

    try:
        source = credential or credential_for(settings)
        source.get_token(COGNITIVE_SERVICES_SCOPE)
    except Exception as exc:  # noqa: BLE001 - every sign-in failure becomes a FAIL line
        lines.append(CheckLine(False, "Sign-in", f"{sign_in_method(settings)}: {safe_error(exc)}"))
        return lines
    lines.append(CheckLine(True, "Sign-in", f"Entra ID token from {sign_in_method(settings)}"))

    backend = backend_factory(settings, source)
    for deployment in dict.fromkeys(settings.deployments.values()):  # each name once
        tiers = ", ".join(t for t, name in settings.deployments.items() if name == deployment)
        label = f"Model {deployment} ({tiers})"
        try:
            reply = backend.complete(deployment, CHECK_PROMPT, settings.check_models_max_tokens)
        except ModelError as exc:
            lines.append(CheckLine(False, label, str(exc)))
            continue
        # The call worked either way; an empty answer means the cap went to hidden reasoning.
        answer = (
            f"answered {reply.text[:20]!r}" if reply.text else "answered with no text (cap reached)"
        )
        lines.append(
            CheckLine(
                True,
                label,
                f"{answer} in {reply.latency_ms} ms, "
                f"{reply.input_tokens} tokens in, {reply.output_tokens} out",
            )
        )
    return lines
