"""Kako's settings, read from the environment (or a gitignored `.env` file).

Every name, URL, budget and cap the backend uses lives here, so nothing is written into logic.
Secrets are `SecretStr`: they never appear in a repr, a log line or an API response.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode, urlsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from kako.agents.chat import ReasoningEffort, Tier

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class Settings(BaseSettings):
    """Backend settings. Field names map to `KAKO_*` variables unless an alias says otherwise."""

    model_config = SettingsConfigDict(
        env_prefix="KAKO_",
        # The repo root's .env first, then backend/.env; later files win.
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: SecretStr | None = Field(
        default=None,
        description="Postgres, as postgresql+asyncpg://user:password@host:port/db",
    )
    meko_mcp_url: str = Field(
        default="http://127.0.0.1:7777/mcp",
        # The same variable Claude Code's Meko toolkit reads, so there is one place to set it.
        validation_alias=AliasChoices("MEKO_MCP_URL", "KAKO_MEKO_MCP_URL"),
    )
    meko_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("MEKO_API_KEY", "KAKO_MEKO_API_KEY"),
    )
    meko_datapack_id: str | None = Field(
        default=None, description="The datapack every Meko call names; unset uses the default one"
    )
    # Meko Cloud's Free tier caps some tools for the account's lifetime (docs/architecture.md, Cost
    # plan). This environment may make at most this many calls to each capped tool on Meko Cloud,
    # counted in `meko_call`; 0 refuses them all. Local Meko has no allowances and no ceiling.
    meko_cloud_ceiling: int = Field(default=0, ge=0, le=10_000)
    # The most tool calls one adapter session sends, wherever Meko is: no loop runs unbounded.
    meko_session_max_calls: int = Field(default=50, ge=1, le=1_000)
    # The account's Langfuse project in Meko Cloud's Observe page (docs/meko-setup.md); not secret.
    meko_langfuse_project_id: str | None = None
    health_timeout_seconds: float = Field(default=3.0, gt=0, le=30)

    # Azure AI Foundry. Deployment names live here and nowhere else (REVIEW.md rule 10).
    foundry_endpoint: str | None = Field(
        default=None,
        description="The Foundry resource's endpoint, https://<resource>.openai.azure.com",
    )
    model_strong: str | None = Field(
        default=None, description="Deployment for the orchestrator and dreaming"
    )
    model_fast: str | None = Field(default=None, description="Deployment for the specialists")
    # Kako's own app registration. KAKO_-prefixed, so it can't be confused with another
    # project's AZURE_* variables in a shared environment. Without them, sign-in falls back to
    # the Azure CLI's `az login`, so no secret is needed where the CLI is signed in.
    azure_tenant_id: str | None = None
    azure_client_id: str | None = None
    azure_client_secret: SecretStr | None = None
    # Room for a reasoning model's hidden reasoning plus a one-word answer: GPT-5 models count
    # reasoning tokens against this cap, and 64 can leave nothing for the answer.
    check_models_max_tokens: int = Field(default=256, ge=16, le=1024)

    # How the model manager reaches a model (docs/architecture.md, "Demo mode"): `live` calls
    # Foundry, `record` calls Foundry and saves each reply to `recorded_responses`, `replay` answers
    # from that file with no network and no Azure settings.
    model_mode: Literal["live", "record", "replay"] = "live"
    recorded_responses: Path | None = Field(
        default=None, description="The recording file `record` writes and `replay` reads"
    )
    # Replay refuses a recorded reply whose request has changed since it was recorded.
    replay_strict: bool = True
    # Spend controls (REVIEW.md rule 10). A planning turn's model calls together may use at most
    # this many tokens (input and output, hidden reasoning included).
    turn_token_budget: int = Field(default=200_000, ge=1_000, le=2_000_000)
    # US dollars of real model calls per UTC day, summed from `llm_call`. Replays cost nothing.
    daily_spend_cap_usd: Decimal = Field(default=Decimal(3), ge=0, le=50)
    # Retries after a failed attempt that may pass next time (rate limit, timeout, server error).
    model_max_retries: int = Field(default=2, ge=0, le=3)
    model_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    reasoning_effort_strong: ReasoningEffort | None = "low"
    reasoning_effort_fast: ReasoningEffort | None = "low"
    # Per-token prices in US$ per million tokens, per tier, for `llm_call.cost_usd`. Defaults are
    # OpenAI's list prices for gpt-5.4 and gpt-5-mini (Nov 2026); check Azure's pricing page for
    # the deployment type in use (docs/azure-setup.md). Never 0: a free price turns the cap off.
    price_strong_input: Decimal = Field(default=Decimal("2.50"), gt=0)
    price_strong_cached: Decimal = Field(default=Decimal("0.25"), gt=0)
    price_strong_output: Decimal = Field(default=Decimal("15.00"), gt=0)
    price_fast_input: Decimal = Field(default=Decimal("0.25"), gt=0)
    price_fast_cached: Decimal = Field(default=Decimal("0.025"), gt=0)
    price_fast_output: Decimal = Field(default=Decimal("2.00"), gt=0)

    @field_validator("meko_mcp_url")
    @classmethod
    def _meko_url_safe(cls, value: str) -> str:
        """Plain http only to this machine: anywhere else the API key would travel in clear text."""
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("must be an http:// or https:// URL")
        if parts.scheme == "http" and parts.hostname not in LOCAL_HOSTS:
            raise ValueError("must use https:// unless it points at this machine (local Meko)")
        return value

    @field_validator(
        "model_strong",
        "model_fast",
        "meko_datapack_id",
        "meko_langfuse_project_id",
        "recorded_responses",
        "reasoning_effort_strong",
        "reasoning_effort_fast",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("foundry_endpoint", mode="before")
    @classmethod
    def _resource_endpoint(cls, value: object) -> object:
        """Keep the scheme and host only, so the resource endpoint and the project endpoint
        (`.../api/projects/<name>`) shown in the Foundry portal both work. HTTPS only: the
        bearer token must never travel in clear text."""
        if not isinstance(value, str) or not value.strip():
            return None
        parts = urlsplit(value.strip())
        if parts.scheme != "https" or not parts.hostname:
            raise ValueError("must be an https:// URL, such as https://<resource>.openai.azure.com")
        return f"https://{parts.netloc}"

    def prices(self, tier: Tier) -> tuple[Decimal, Decimal, Decimal]:
        """US$ per million tokens for a tier: input, cached input, output."""
        if tier == "strong":
            return self.price_strong_input, self.price_strong_cached, self.price_strong_output
        return self.price_fast_input, self.price_fast_cached, self.price_fast_output

    def reasoning_effort(self, tier: Tier) -> ReasoningEffort | None:
        return self.reasoning_effort_strong if tier == "strong" else self.reasoning_effort_fast

    @property
    def deployments(self) -> dict[str, str]:
        """Each tier's deployment name, for the tiers that are set."""
        tiers = {"strong": self.model_strong, "fast": self.model_fast}
        return {tier: name for tier, name in tiers.items() if name}

    @field_validator("database_url", mode="before")
    @classmethod
    def _asyncpg_driver(cls, value: object) -> object:
        """Accept the plain `postgresql://` form most providers hand out, and use asyncpg."""
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        if isinstance(value, str):
            if not value.strip():
                return None
            for prefix in ("postgresql://", "postgres://"):
                if value.startswith(prefix):
                    return "postgresql+asyncpg://" + value.removeprefix(prefix)
        return value

    @property
    def meko_target(self) -> Literal["local", "cloud"]:
        """`local` when the Meko URL points at this machine; anything else counts as Meko Cloud."""
        host = urlsplit(self.meko_mcp_url).hostname or ""
        return "local" if host in LOCAL_HOSTS else "cloud"

    def meko_trace_url(self, conversation_id: str) -> str | None:
        """Meko Cloud's trace page for a conversation, or None (local Meko, or no project id)."""
        if self.meko_target != "cloud" or self.meko_langfuse_project_id is None:
            return None
        query = urlencode({"project": self.meko_langfuse_project_id, "session": conversation_id})
        return f"https://cloud.mekodata.ai/observe-hub?{query}"


@lru_cache
def get_settings() -> Settings:
    """The process-wide settings, read once."""
    return Settings()
