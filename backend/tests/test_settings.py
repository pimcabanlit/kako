import pytest

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
        ("http://127.0.0.1.example.test/mcp", "cloud"),
    ],
)
def test_meko_target(make_settings: MakeSettings, url: str, target: str) -> None:
    assert make_settings(meko_mcp_url=url).meko_target == target
