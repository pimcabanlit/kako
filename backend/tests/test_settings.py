from decimal import Decimal

import pytest
from pydantic import ValidationError

from tests.conftest import MakeSettings


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("postgresql://u:p@db:5432/kako", "postgresql+asyncpg://u:p@db:5432/kako"),
        ("postgres://u:p@db/kako", "postgresql+asyncpg://u:p@db/kako"),
        ("postgresql+asyncpg://u@db/kako", "postgresql+asyncpg://u@db/kako"),
    ],
)
def test_database_url_uses_asyncpg(make_settings: MakeSettings, given: str, expected: str) -> None:
    url = make_settings(database_url=given).database_url
    assert url is not None
    assert url.get_secret_value() == expected


def test_blank_database_url_means_not_configured(make_settings: MakeSettings) -> None:
    assert make_settings(database_url="  ").database_url is None


def test_secrets_stay_out_of_repr(make_settings: MakeSettings) -> None:
    settings = make_settings(
        database_url="postgresql://kako:hunter2@db/kako", meko_api_key="mk_secret_value"
    )
    shown = repr(settings) + str(settings.model_dump())
    assert "hunter2" not in shown
    assert "mk_secret_value" not in shown


def test_meko_url_reads_the_toolkit_variable(
    make_settings: MakeSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEKO_MCP_URL", "https://mcp.example.test/mcp")
    assert make_settings().meko_mcp_url == "https://mcp.example.test/mcp"


@pytest.mark.parametrize(
    ("url", "target"),
    [
        ("http://127.0.0.1:7777/mcp", "local"),
        ("http://localhost:7777/mcp", "local"),
        ("http://[::1]:7777/mcp", "local"),
        ("https://mcp.example.test/mcp", "cloud"),
        ("https://127.0.0.1.example.test/mcp", "cloud"),
    ],
)
def test_meko_target(make_settings: MakeSettings, url: str, target: str) -> None:
    assert make_settings(meko_mcp_url=url).meko_target == target


@pytest.mark.parametrize(
    "url",
    [
        "http://mcp.mekodata.ai/mcp",
        "http://127.0.0.1.example.test/mcp",
        "ftp://127.0.0.1/mcp",
        "mcp",
    ],
)
def test_meko_url_refuses_clear_text_off_this_machine(
    make_settings: MakeSettings, url: str
) -> None:
    with pytest.raises(ValueError, match=r"URL|https://"):
        make_settings(meko_mcp_url=url)


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("https://kako-ai.openai.azure.com/", "https://kako-ai.openai.azure.com"),
        (
            "https://kako-ai.services.ai.azure.com/api/projects/kako",
            "https://kako-ai.services.ai.azure.com",
        ),
        ("  ", None),
    ],
    ids=["resource", "project", "blank"],
)
def test_foundry_endpoint_keeps_the_host(
    make_settings: MakeSettings, given: str, expected: str | None
) -> None:
    assert make_settings(foundry_endpoint=given).foundry_endpoint == expected


@pytest.mark.parametrize("given", ["http://kako-ai.openai.azure.com", "kako-ai.openai.azure.com"])
def test_foundry_endpoint_must_be_https(make_settings: MakeSettings, given: str) -> None:
    with pytest.raises(ValueError, match="https://"):
        make_settings(foundry_endpoint=given)


def test_spend_controls_have_safe_defaults(make_settings: MakeSettings) -> None:
    settings = make_settings()
    assert settings.model_mode == "live"
    assert settings.turn_token_budget == 200_000
    assert settings.daily_spend_cap_usd == Decimal(3)
    assert settings.model_max_retries == 2
    assert settings.prices("strong") == (Decimal("2.50"), Decimal("0.25"), Decimal("15.00"))
    assert settings.prices("fast") == (Decimal("0.25"), Decimal("0.025"), Decimal("2.00"))
    assert settings.reasoning_effort("fast") == "low"


@pytest.mark.parametrize(
    "values",
    [
        {"daily_spend_cap_usd": "51"},
        {"daily_spend_cap_usd": "-1"},
        {"turn_token_budget": 10_000_000},
        {"model_max_retries": 4},
        {"model_mode": "free"},
        {"price_fast_output": "-0.1"},
        {"reasoning_effort_fast": "max"},
    ],
)
def test_spend_controls_refuse_out_of_bounds_values(
    make_settings: MakeSettings, values: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        make_settings(**values)


def test_spend_controls_read_the_environment(
    make_settings: MakeSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KAKO_DAILY_SPEND_CAP_USD", "1.5")
    monkeypatch.setenv("KAKO_MODEL_MODE", "replay")
    monkeypatch.setenv("KAKO_RECORDED_RESPONSES", "data/demo-household/recorded/session-2.json")
    settings = make_settings()
    assert settings.daily_spend_cap_usd == Decimal("1.5")
    assert settings.model_mode == "replay"
    assert str(settings.recorded_responses).endswith("session-2.json")


def test_blank_recording_and_effort_mean_unset(make_settings: MakeSettings) -> None:
    settings = make_settings(recorded_responses=" ", reasoning_effort_strong="")
    assert settings.recorded_responses is None
    assert settings.reasoning_effort("strong") is None
