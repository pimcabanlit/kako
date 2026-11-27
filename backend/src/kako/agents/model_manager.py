"""The model manager: the only module that imports a model SDK (REVIEW.md rule 10).

Two providers, chosen by `KAKO_MODEL_PROVIDER` (docs/architecture.md, "Models"):

- `anthropic` (the default): Claude on Anthropic's own API, with the Anthropic SDK and Kako's own
  key (`KAKO_ANTHROPIC_API_KEY`), passed explicitly with the API's URL, so the SDK reads no
  credential or URL of its own from the environment. Thinking is always on; effort is set per tier.
- `foundry`: OpenAI models as Azure AI Foundry deployments, with the OpenAI SDK on Foundry's v1
  endpoint (`<endpoint>/openai/v1/`), signed in with Microsoft Entra ID: a bearer token for the
  Cognitive Services scope, never an API key.

Model and deployment names come from settings only. Two parts:

- `check_models`: settings, sign-in and one tiny call per model (`kako check-models`).
- `ModelManager.chat`: every agent's model call. It picks the model for the call's tier, refuses a
  call past the turn's token budget or the day's spend cap, retries a failed attempt that may pass
  next time (at most `KAKO_MODEL_MAX_RETRIES`), and logs every attempt in `llm_call` with its cost.
  Its backend is `ClaudeChat` or `FoundryChat` (live), `RecordingBackend` (live, saving each reply)
  or `ReplayBackend` (recorded replies, no network): see `kako.agents.recorded`.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final, Protocol

import anthropic
import httpx2
from azure.core.credentials import TokenCredential
from azure.core.exceptions import ClientAuthenticationError
from azure.identity import (
    AzureCliCredential,
    ClientSecretCredential,
    get_bearer_token_provider,
)
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    OpenAI,
    OpenAIError,
    RateLimitError,
)

from kako.agents.chat import (
    Block,
    CallAgent,
    ChatReply,
    ChatRequest,
    Message,
    ModelError,
    Tier,
    ToolCall,
    ToolSpec,
)
from kako.agents.prompt_registry import PromptVersion
from kako.agents.recorded import ChatBackend, RecordingBackend, ReplayBackend
from kako.agents.spend import LlmCallRecord, LlmLog, Outcome, cost_usd
from kako.agents.turn import MemoryStepLog, StepLog, TurnContext
from kako.health import safe_error
from kako.settings import Settings

COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"
CHECK_PROMPT = "Reply with the single word OK."
# Claude's thinking-block controls (beta): a thinking block whose conversation prefix has changed
# is dropped, not refused. The tool loop offers only the final tool at its limit, which changes the
# request's tools, and Claude binds each thinking block to the tools it was written with.
CLAUDE_BETAS: Final = ("thinking-binding-controls-2026-08-01",)
CLAUDE_THINKING: Final[dict[str, Any]] = {
    "type": "adaptive",
    "block_binding": {"prefix_mismatch_behavior": "drop_block"},
}
CLAUDE_CACHE: Final[dict[str, Any]] = {"type": "ephemeral"}  # the 5-minute prompt cache


class SpendRefused(ModelError):
    """Refused before sending: the turn's token budget or the day's spend cap would be passed."""


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
    claude_factory: Callable[[Settings], ClaudeCheckBackend] | None = None,
) -> list[CheckLine]:
    """Settings, sign-in, then one tiny call per model, on the provider settings name. Prints
    nothing secret. At most one call per distinct model name, each with at most one retry."""
    if settings.model_provider == "anthropic":
        return _check_claude(settings, claude_factory or ClaudeBackend)
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

    lines.extend(_check_calls(settings, backend_factory(settings, source)))
    return lines


def _check_calls(settings: Settings, backend: ModelBackend) -> list[CheckLine]:
    """One tiny call per distinct model name, each line saying what it answered."""
    lines: list[CheckLine] = []
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


# ---------------------------------------------------------------------------------------------
# Claude: the Messages API on Anthropic's own API.
# ---------------------------------------------------------------------------------------------


class ClaudeCheckBackend(ModelBackend, Protocol):
    def sign_in(self, model: str) -> str:
        """Check the key against one model, at no cost; returns the model's display name."""
        ...


def claude_models_problem(settings: Settings) -> str | None:
    """Why the tiers' model names can't be Claude models, or None. A name left over from Foundry
    (such as gpt-5.4) is refused before any call, with the way out."""
    wrong = [
        f"{setting}={name}"
        for setting, name in (
            ("KAKO_MODEL_STRONG", settings.model_strong),
            ("KAKO_MODEL_FAST", settings.model_fast),
        )
        if name and not name.startswith("claude-")
    ]
    if not wrong:
        return None
    return (
        f"{', '.join(wrong)} isn't a Claude model: set a claude-* model, or "
        "KAKO_MODEL_PROVIDER=foundry for Azure AI Foundry"
    )


def _claude_key(settings: Settings) -> str:
    key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else ""
    if not key:
        raise ModelError("KAKO_ANTHROPIC_API_KEY is not set")
    return key


def _claude_error(exc: anthropic.AnthropicError) -> ModelError:
    """An SDK error as a `ModelError`, most specific first: which may pass next time, and which
    may have reached the model before failing (so it is charged at its worst case)."""
    if isinstance(exc, anthropic.APITimeoutError | anthropic.APIConnectionError):
        return ModelError(safe_error(exc), retryable=True, maybe_billed=True)
    if isinstance(exc, anthropic.RateLimitError | anthropic.InternalServerError):
        return ModelError(safe_error(exc), retryable=True, retry_after=_retry_after(exc))
    return ModelError(safe_error(exc))


class ClaudeBackend:
    """`kako check-models` on Claude: the key checked on a model (free), then a tiny call."""

    def __init__(self, settings: Settings, *, http_client: httpx2.Client | None = None) -> None:
        self._settings = settings
        self._client = anthropic.Anthropic(
            api_key=_claude_key(settings),
            base_url=settings.anthropic_base_url,
            max_retries=1,  # bounded: at most two attempts per call
            timeout=30.0,
            http_client=http_client,
            open_telemetry=False,
        )

    def sign_in(self, model: str) -> str:
        try:
            info = self._client.models.retrieve(model)
        except anthropic.AnthropicError as exc:
            raise _claude_error(exc) from exc
        return str(info.display_name or info.id)

    def complete(self, deployment: str, prompt: str, max_output_tokens: int) -> ModelReply:
        started = time.perf_counter()
        try:
            # The same thinking and beta as an agent's call, so a model or account that refuses
            # them fails here first, with nothing spent on a turn.
            params: dict[str, Any] = {
                "model": deployment,
                "max_tokens": max_output_tokens,
                "messages": [{"role": "user", "content": prompt}],
                "thinking": CLAUDE_THINKING,
                "output_config": {"effort": "low"},
                "betas": list(CLAUDE_BETAS),
            }
            response = self._client.beta.messages.create(**params)
        except anthropic.AnthropicError as exc:
            raise _claude_error(exc) from exc
        latency_ms = round((time.perf_counter() - started) * 1000)
        text = "".join(b.text for b in response.content if b.type == "text")
        usage = response.usage
        return ModelReply(
            deployment=deployment,
            text=text.strip(),
            input_tokens=usage.input_tokens
            + (usage.cache_creation_input_tokens or 0)
            + (usage.cache_read_input_tokens or 0),
            output_tokens=usage.output_tokens,
            latency_ms=latency_ms,
        )


def _check_claude(
    settings: Settings, factory: Callable[[Settings], ClaudeCheckBackend]
) -> list[CheckLine]:
    missing = [
        name
        for name, value in (
            ("KAKO_ANTHROPIC_API_KEY", settings.anthropic_api_key),
            ("KAKO_MODEL_STRONG", settings.model_strong),
            ("KAKO_MODEL_FAST", settings.model_fast),
        )
        if not value
    ]
    problem = f"missing {', '.join(missing)}" if missing else claude_models_problem(settings)
    lines = [
        CheckLine(
            ok=problem is None,
            label="Settings",
            detail=problem
            or f"Claude at {settings.anthropic_base_url}; strong={settings.model_strong}, "
            f"fast={settings.model_fast}",
        )
    ]
    if problem is not None:
        return lines
    try:
        backend = factory(settings)
        name = backend.sign_in(settings.model_strong or "")
    except Exception as exc:  # noqa: BLE001 - every sign-in failure becomes a FAIL line
        detail = str(exc) if isinstance(exc, ModelError) else safe_error(exc)
        lines.append(CheckLine(False, "Sign-in", f"KAKO_ANTHROPIC_API_KEY: {detail}"))
        return lines
    lines.append(CheckLine(True, "Sign-in", f"API key accepted ({name} is available)"))
    lines.extend(_check_calls(settings, backend))
    return lines


# ---------------------------------------------------------------------------------------------
# Agents' calls: Chat Completions with tools, behind budgets, retries and the call log.
# ---------------------------------------------------------------------------------------------


def _message_json(message: Message) -> dict[str, Any]:
    out: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        out["tool_calls"] = [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
            for c in message.tool_calls
        ]
    if message.tool_call_id is not None:
        out["tool_call_id"] = message.tool_call_id
    return out


def _tool_json(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
            "strict": tool.strict,
        },
    }


def _retry_after(exc: APIStatusError | anthropic.APIStatusError) -> float | None:
    """Seconds the service asked us to wait, from `retry-after-ms` or `retry-after`."""
    headers = exc.response.headers
    for name, scale in (("retry-after-ms", 1000.0), ("retry-after", 1.0)):
        value = headers.get(name)
        if value is not None:
            try:
                return max(float(value) / scale, 0.0)
            except ValueError:
                continue  # an HTTP date: fall back to our own backoff
    return None


class FoundryChat:
    """`ChatBackend` on Azure AI Foundry's v1 endpoint, with an Entra ID token. The SDK's own
    retries are off: the model manager retries, so every attempt is logged."""

    def __init__(
        self,
        settings: Settings,
        credential: TokenCredential | None = None,
        *,
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        if not settings.foundry_endpoint:
            raise ModelError("KAKO_FOUNDRY_ENDPOINT is not set")
        sync_token: Callable[[], str] = get_bearer_token_provider(
            credential or credential_for(settings), COGNITIVE_SERVICES_SCOPE
        )

        async def token() -> str:
            return await asyncio.to_thread(sync_token)

        self._settings = settings
        self._client = AsyncOpenAI(
            base_url=settings.foundry_endpoint.rstrip("/") + "/openai/v1/",
            api_key=token,
            max_retries=0,
            timeout=settings.model_timeout_seconds,
            http_client=http_client,
        )

    @property
    def replays(self) -> bool:
        return False

    async def chat(self, request: ChatRequest, *, deployment: str, key: str) -> ChatReply:
        del key  # only recordings name calls
        options: dict[str, Any] = {}
        if request.tools:
            options["tools"] = [_tool_json(t) for t in request.tools]
            options["tool_choice"] = request.tool_choice
        effort = self._settings.reasoning_effort(request.tier)
        if effort is not None:
            options["reasoning_effort"] = effort
        started = time.perf_counter()
        try:
            response = await self._client.chat.completions.create(
                model=deployment,
                messages=[_message_json(m) for m in request.messages],  # type: ignore[misc]
                max_completion_tokens=request.max_output_tokens,
                **options,
            )
        except (RateLimitError, InternalServerError) as exc:
            raise ModelError(
                safe_error(exc), retryable=True, retry_after=_retry_after(exc)
            ) from exc
        except (APITimeoutError, APIConnectionError) as exc:
            raise ModelError(safe_error(exc), retryable=True, maybe_billed=True) from exc
        except (OpenAIError, ClientAuthenticationError) as exc:
            raise ModelError(safe_error(exc)) from exc
        latency_ms = round((time.perf_counter() - started) * 1000)
        if not response.choices:
            raise ModelError(f"{deployment} answered with no choices")
        choice = response.choices[0]
        calls = tuple(
            ToolCall(id=c.id, name=c.function.name, arguments=c.function.arguments)
            for c in (choice.message.tool_calls or ())
            if c.type == "function"
        )
        usage = response.usage
        details = usage.prompt_tokens_details if usage else None
        return ChatReply(
            deployment=deployment,
            text=(choice.message.content or "").strip(),
            tool_calls=calls,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            cached_tokens=(details.cached_tokens or 0) if details else 0,
            finish_reason=str(choice.finish_reason),
            latency_ms=latency_ms,
        )


# Claude's stop reasons in the words `ChatReply.finish_reason` has used since Foundry.
_CLAUDE_FINISH: Final = {"end_turn": "stop", "tool_use": "tool_calls", "max_tokens": "length"}


def _claude_tool(tool: ToolSpec) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.parameters,
        "strict": tool.strict,
    }


def _claude_assistant(message: Message) -> list[Block]:
    """An assistant message's content blocks: as Claude wrote them when the reply came from this
    loop (thinking blocks included, unchanged), otherwise its words and tool calls."""
    if message.blocks:
        return [dict(b) for b in message.blocks]
    content: list[Block] = []
    if message.content:
        content.append({"type": "text", "text": message.content})
    for call in message.tool_calls:
        try:
            arguments = json.loads(call.arguments or "{}")
        except json.JSONDecodeError:
            arguments = {}
        content.append(
            {
                "type": "tool_use",
                "id": call.id,
                "name": call.name,
                "input": arguments if isinstance(arguments, dict) else {},
            }
        )
    return content


def claude_messages(messages: tuple[Message, ...]) -> tuple[list[Block], list[dict[str, Any]]]:
    """The system prompt as blocks, and the rest as Claude's turns: tool results go in a user
    turn, and turns of the same role are joined, tool results first, as the API requires. The
    system prompt carries a cache breakpoint, so every call of a turn reads it from the cache."""
    system: list[Block] = []
    turns: list[dict[str, Any]] = []

    def add(role: str, blocks: list[Block]) -> None:
        if not blocks:
            return
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"].extend(blocks)
        else:
            turns.append({"role": role, "content": blocks})

    for index, message in enumerate(messages):
        if message.role == "system":
            if index != 0:
                raise ModelError("a system message must come first")
            if message.content:
                system.append({"type": "text", "text": message.content})
        elif message.role == "assistant":
            add("assistant", _claude_assistant(message))
        elif message.role == "tool":
            add(
                "user",
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": message.tool_call_id or "",
                        "content": message.content or "",
                    }
                ],
            )
        elif message.content:
            add("user", [{"type": "text", "text": message.content}])
    if system:
        system[-1]["cache_control"] = dict(CLAUDE_CACHE)
    return system, turns


def _claude_block(block: Any) -> Block | None:
    """One content block of a reply as the plain value to send back, or None for a kind Kako
    never asks for."""
    if block.type == "thinking":
        return {"type": "thinking", "thinking": block.thinking, "signature": block.signature}
    if block.type == "redacted_thinking":
        return {"type": "redacted_thinking", "data": block.data}
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    return None


class ClaudeChat:
    """`ChatBackend` on Claude's Messages API, with Kako's own key. The SDK's own retries are off:
    the model manager retries, so every attempt is logged.

    Each request: the system prompt with a cache breakpoint, and automatic caching of the turns
    after it; adaptive thinking (always on) at the tier's effort, its blocks sent back unchanged;
    tool choice `auto`, since forced tool use is refused by Claude's current models (the tool loop
    sends an empty reply back once and refuses a tool not on offer, so `required` stays enforced in
    code); strict tools, so arguments match their schema. No server-side refusal fallback: a call
    is answered by the model it names, or comes back refused (`finish_reason` "refusal")."""

    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        problem = claude_models_problem(settings)
        if problem is not None:
            raise ModelError(problem)
        self._settings = settings
        self._client = anthropic.AsyncAnthropic(
            api_key=_claude_key(settings),
            base_url=settings.anthropic_base_url,
            max_retries=0,
            timeout=settings.model_timeout_seconds,
            http_client=http_client,
            open_telemetry=False,
        )

    @property
    def replays(self) -> bool:
        return False

    async def chat(self, request: ChatRequest, *, deployment: str, key: str) -> ChatReply:
        del key  # only recordings name calls
        system, turns = claude_messages(request.messages)
        params: dict[str, Any] = {
            "model": deployment,
            "max_tokens": request.max_output_tokens,
            "messages": turns,
            "thinking": CLAUDE_THINKING,
            "output_config": {"effort": self._settings.claude_effort(request.tier)},
            "cache_control": CLAUDE_CACHE,
            "betas": list(CLAUDE_BETAS),
        }
        if system:
            params["system"] = system
        if request.tools and request.tool_choice != "none":
            params["tools"] = [_claude_tool(t) for t in request.tools]
            params["tool_choice"] = {"type": "auto"}
        started = time.perf_counter()
        try:
            response = await self._client.beta.messages.create(**params)
        except anthropic.AnthropicError as exc:
            raise _claude_error(exc) from exc
        latency_ms = round((time.perf_counter() - started) * 1000)
        blocks = tuple(b for b in (_claude_block(c) for c in response.content) if b is not None)
        calls = tuple(
            ToolCall(id=b["id"], name=b["name"], arguments=json.dumps(b["input"]))
            for b in blocks
            if b["type"] == "tool_use"
        )
        text = "".join(b["text"] for b in blocks if b["type"] == "text")
        usage = response.usage
        written = usage.cache_creation_input_tokens or 0
        cached = usage.cache_read_input_tokens or 0
        stop = str(response.stop_reason)
        return ChatReply(
            deployment=str(response.model or deployment),
            text=text.strip(),
            tool_calls=calls,
            input_tokens=usage.input_tokens + written + cached,
            output_tokens=usage.output_tokens,
            cached_tokens=cached,
            cache_write_tokens=written,
            finish_reason=_CLAUDE_FINISH.get(stop, stop),
            latency_ms=latency_ms,
            blocks=blocks,
        )


def chat_backend(settings: Settings) -> ChatBackend:
    """The backend `KAKO_MODEL_MODE` and `KAKO_MODEL_PROVIDER` ask for."""

    def live() -> ChatBackend:
        if settings.model_provider == "anthropic":
            return ClaudeChat(settings)
        return FoundryChat(settings)

    if settings.model_mode == "live":
        return live()
    if settings.recorded_responses is None:
        raise ModelError(f"KAKO_MODEL_MODE={settings.model_mode} needs KAKO_RECORDED_RESPONSES")
    if settings.model_mode == "replay":
        return ReplayBackend(settings.recorded_responses, strict=settings.replay_strict)
    return RecordingBackend(live(), settings.recorded_responses)


def utc_day_start(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


class ModelManager:
    """Every agent's model call goes through `chat`. Bounded three ways: the turn's token budget,
    the day's spend cap, and at most `model_max_retries` retries per call."""

    def __init__(
        self,
        settings: Settings,
        backend: ChatBackend,
        log: LlmLog,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._settings = settings
        self._backend = backend
        self._log = log
        self._sleep = sleep
        self._now = now
        self._cost_in_flight = Decimal(0)  # worst cases of this manager's calls still running

    @property
    def replays(self) -> bool:
        return self._backend.replays

    @property
    def settings(self) -> Settings:
        return self._settings

    def turn(
        self,
        meko_turn_seed: str,
        *,
        session_id: uuid.UUID | None = None,
        steps: StepLog | None = None,
    ) -> TurnContext:
        """A new turn with the budget from settings."""
        return TurnContext(
            meko_turn_seed=meko_turn_seed,
            token_budget=self._settings.turn_token_budget,
            steps=steps or MemoryStepLog(),
            session_id=session_id,
        )

    def _deployment(self, tier: Tier) -> str:
        name = self._settings.deployments.get(tier)
        if name:
            return name
        if self.replays:
            return f"({tier})"  # the recorded reply names the real one
        setting = "KAKO_MODEL_STRONG" if tier == "strong" else "KAKO_MODEL_FAST"
        raise ModelError(f"{setting} is not set")

    async def _record(
        self,
        turn: TurnContext,
        agent: CallAgent,
        deployment: str,
        outcome: Outcome,
        reply: ChatReply | None = None,
        latency_ms: int = 0,
        prices: tuple[Decimal, Decimal, Decimal] | None = None,
        write_price: Decimal | None = None,
        charge: tuple[int, Decimal] | None = None,
        prompts: tuple[PromptVersion, ...] = (),
    ) -> Decimal:
        """Log one attempt; a reply is priced at the tier's prices (a replay too, for the
        metrics; the daily cap counts real calls only). `charge` is the worst case (tokens,
        US$) of a failed attempt that may have been billed, logged as output tokens."""
        cost = charge[1] if charge is not None else Decimal(0)
        if reply is not None and prices is not None:
            cost = cost_usd(
                prices,
                reply.input_tokens,
                reply.cached_tokens,
                reply.output_tokens,
                cache_write_tokens=reply.cache_write_tokens,
                cache_write_price=write_price,
            )
        await self._log.write(
            LlmCallRecord(
                session_id=turn.session_id,
                meko_turn_seed=turn.meko_turn_seed,
                agent=agent,
                deployment=reply.deployment if reply is not None else deployment,
                input_tokens=reply.input_tokens if reply else 0,
                output_tokens=reply.output_tokens if reply else (charge[0] if charge else 0),
                cached_tokens=reply.cached_tokens if reply else 0,
                latency_ms=reply.latency_ms if reply else latency_ms,
                cost_usd=cost,
                outcome=outcome,
                recorded_replay=self.replays,
                prompts=prompts,
                created_at=self._now(),
            )
        )
        return cost

    def _worst_cost(self, request: ChatRequest) -> Decimal:
        """The most a call could cost: its whole input uncached (or written to the cache, which
        costs more on Claude), its whole output cap used."""
        price_in, _, price_out = self._settings.prices(request.tier)
        if self._settings.model_provider == "anthropic":
            price_in = max(price_in, self._settings.cache_write_price(request.tier))
        return cost_usd(
            (price_in, price_in, price_out),
            request.estimated_input_tokens(),
            0,
            request.max_output_tokens,
        )

    async def _reserve(
        self, request: ChatRequest, turn: TurnContext, agent: CallAgent, deployment: str
    ) -> tuple[int, Decimal]:
        """Check the call against the turn's budget and the day's cap, and reserve its worst
        case on both before sending, so calls running in parallel can't each pass a check that
        only one of them fits. Returns what was reserved; `_release` gives it back. A refusal
        is logged and raises `SpendRefused`."""
        worst_tokens = request.estimated_input_tokens() + request.max_output_tokens
        if worst_tokens > turn.tokens_left():
            await self._record(turn, agent, deployment, "budget_exceeded", prompts=request.prompts)
            raise SpendRefused(
                f"the turn's token budget ({turn.token_budget:,}) has {turn.tokens_left():,} "
                f"tokens left; this call could use {worst_tokens:,} (KAKO_TURN_TOKEN_BUDGET)"
            )
        turn.tokens_reserved += worst_tokens  # before any await: no other call slips in
        if self.replays:
            return worst_tokens, Decimal(0)  # a replay spends nothing
        worst_cost = self._worst_cost(request)
        try:
            spent = await self._log.spent_since(utc_day_start(self._now()))
        except BaseException:
            turn.tokens_reserved -= worst_tokens
            raise
        # From here to the reservation there is no await: the check and the reservation are one
        # step for every call in this process.
        cap = self._settings.daily_spend_cap_usd
        if spent + self._cost_in_flight + worst_cost > cap:
            turn.tokens_reserved -= worst_tokens
            await self._record(turn, agent, deployment, "budget_exceeded", prompts=request.prompts)
            raise SpendRefused(
                f"today's model spend is US${spent:.4f} of the US${cap} cap, with "
                f"US${self._cost_in_flight:.4f} in calls still running, and this call could "
                f"cost up to US${worst_cost:.4f} (KAKO_DAILY_SPEND_CAP_USD)"
            )
        self._cost_in_flight += worst_cost
        return worst_tokens, worst_cost

    def _release(self, turn: TurnContext, tokens: int, cost: Decimal) -> None:
        turn.tokens_reserved -= tokens
        self._cost_in_flight -= cost

    async def chat(
        self, request: ChatRequest, *, turn: TurnContext, agent: CallAgent, key: str
    ) -> ChatReply:
        """One model call: checked against the budgets, retried when it may pass next time,
        every attempt logged. Raises `SpendRefused` before sending, `ModelError` after the last
        failed attempt."""
        deployment = self._deployment(request.tier)
        prices = self._settings.prices(request.tier)
        write_price = self._settings.cache_write_price(request.tier)
        attempts = 1 + self._settings.model_max_retries
        for attempt in range(1, attempts + 1):
            tokens, cost = await self._reserve(request, turn, agent, deployment)
            started = time.perf_counter()
            try:
                reply = await self._backend.chat(request, deployment=deployment, key=key)
            except ModelError as exc:
                billed = exc.maybe_billed and not self.replays
                # A request that may have reached the model is charged at its worst case. The
                # row is written before the reservation is released, so the cap always sees one.
                try:
                    await self._record(
                        turn,
                        agent,
                        deployment,
                        "error",
                        latency_ms=round((time.perf_counter() - started) * 1000),
                        charge=(tokens, self._worst_cost(request)) if billed else None,
                        prompts=request.prompts,
                    )
                finally:
                    self._release(turn, tokens, cost)
                if billed:
                    turn.tokens_used += tokens
                if not exc.retryable or attempt == attempts:
                    raise
                await self._sleep(min(exc.retry_after or 2.0 ** (attempt - 1), 20.0))
                continue
            except BaseException:
                self._release(turn, tokens, cost)
                raise
            try:
                await self._record(
                    turn,
                    agent,
                    deployment,
                    "ok",
                    reply,
                    prices=prices,
                    write_price=write_price,
                    prompts=request.prompts,
                )
            finally:
                self._release(turn, tokens, cost)
                turn.tokens_used += reply.total_tokens
            return reply
        raise AssertionError("unreachable: the loop returns or raises")  # pragma: no cover
