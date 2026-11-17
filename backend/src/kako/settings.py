"""Kako's settings, read from the environment (or a gitignored `.env` file).

Every name, URL, budget and cap the backend uses lives here, so nothing is written into logic.
Secrets are `SecretStr`: they never appear in a repr, a log line or an API response.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    check_models_max_tokens: int = Field(default=64, ge=16, le=256)

    @field_validator("foundry_endpoint", "model_strong", "model_fast", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

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


@lru_cache
def get_settings() -> Settings:
    """The process-wide settings, read once."""
    return Settings()
