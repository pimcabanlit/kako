from kako.health import redact, safe_error


def test_url_password_is_blanked() -> None:
    text = redact("could not connect to postgresql+asyncpg://kako:hunter2@db:5432/kako")
    assert "hunter2" not in text
    assert "postgresql+asyncpg://kako:***@db:5432/kako" in text


def test_bearer_token_is_blanked() -> None:
    assert redact("Authorization: Bearer mk_abc.def") == "Authorization: Bearer ***"


def test_url_without_password_is_kept() -> None:
    assert redact("http://127.0.0.1:7777/mcp") == "http://127.0.0.1:7777/mcp"


def test_safe_error_keeps_type_and_first_line_only() -> None:
    error = ValueError("first line with postgres://u:pw@h/db\nsecond line with more detail")
    assert safe_error(error) == "ValueError: first line with postgres://u:***@h/db"


def test_safe_error_is_short() -> None:
    assert len(safe_error(RuntimeError("x" * 1000))) == 200


def test_safe_error_without_message() -> None:
    assert safe_error(TimeoutError()) == "TimeoutError"
