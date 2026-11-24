"""The model manager and check-models, with a fake credential and a fake Foundry: no network."""

from __future__ import annotations

import json
import time
from collections.abc import Callable

import httpx2
import pytest
from azure.core.credentials import AccessToken

from kako.agents.chat import ChatRequest, Message, ToolCall, ToolSpec
from kako.agents.model_manager import (
    COGNITIVE_SERVICES_SCOPE,
    CheckLine,
    FoundryBackend,
    FoundryChat,
    ModelError,
    ModelReply,
    check_models,
    credential_for,
)
from kako.cli import main
from kako.settings import Settings
from tests.conftest import MakeSettings

ENDPOINT = "https://kako-test.openai.azure.com"


class FakeCredential:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.scopes: list[tuple[str, ...]] = []

    def get_token(self, *scopes: str, **_: object) -> AccessToken:
        self.scopes.append(scopes)
        if self.fail:
            raise RuntimeError("AADSTS7000215: Invalid client secret provided")
        return AccessToken("fake-entra-token", int(time.time()) + 3600)


class FakeBackend:
    def __init__(self, failing: set[str] | None = None, text: str = "OK") -> None:
        self.calls: list[tuple[str, int]] = []
        self.failing = failing or set()
        self.text = text

    def complete(self, deployment: str, prompt: str, max_output_tokens: int) -> ModelReply:
        self.calls.append((deployment, max_output_tokens))
        if deployment in self.failing:
            raise ModelError("NotFoundError: The API deployment for this resource does not exist")
        return ModelReply(deployment, self.text, 14, 2, 120)


@pytest.fixture
def foundry(make_settings: MakeSettings) -> Settings:
    return make_settings(
        foundry_endpoint=ENDPOINT, model_strong="kako-strong", model_fast="kako-fast"
    )


def run(
    settings: Settings, backend: FakeBackend, credential: FakeCredential | None = None
) -> list[CheckLine]:
    return check_models(
        settings,
        credential=credential or FakeCredential(),  # type: ignore[arg-type]
        backend_factory=lambda _s, _c: backend,
    )


def test_missing_settings_stop_before_any_call(make_settings: MakeSettings) -> None:
    backend = FakeBackend()
    lines = run(make_settings(model_fast="kako-fast"), backend)
    assert [str(line) for line in lines] == [
        "[FAIL] Settings: missing KAKO_FOUNDRY_ENDPOINT, KAKO_MODEL_STRONG"
    ]
    assert backend.calls == []


def test_one_call_per_deployment(foundry: Settings) -> None:
    backend, credential = FakeBackend(), FakeCredential()
    lines = run(foundry, backend, credential)
    assert all(line.ok for line in lines), lines
    assert [line.label for line in lines] == [
        "Settings",
        "Sign-in",
        "Model kako-strong (strong)",
        "Model kako-fast (fast)",
    ]
    assert backend.calls == [("kako-strong", 256), ("kako-fast", 256)]
    assert credential.scopes == [(COGNITIVE_SERVICES_SCOPE,)]


def test_an_empty_answer_still_passes_and_says_why(foundry: Settings) -> None:
    lines = run(foundry, FakeBackend(text=""))
    assert all(line.ok for line in lines), lines
    assert "answered with no text (cap reached)" in lines[-1].detail


def test_shared_deployment_is_called_once(make_settings: MakeSettings) -> None:
    settings = make_settings(foundry_endpoint=ENDPOINT, model_strong="mini", model_fast="mini")
    backend = FakeBackend()
    lines = run(settings, backend)
    assert backend.calls == [("mini", 256)]
    assert lines[-1].label == "Model mini (strong, fast)"


def test_sign_in_failure_is_reported_without_secrets(make_settings: MakeSettings) -> None:
    settings = make_settings(
        foundry_endpoint=ENDPOINT,
        model_strong="kako-strong",
        model_fast="kako-fast",
        azure_tenant_id="tenant",
        azure_client_id="client",
        azure_client_secret="super-secret-value",
    )
    backend = FakeBackend()
    lines = run(settings, backend, FakeCredential(fail=True))
    assert not lines[-1].ok
    assert lines[-1].label == "Sign-in"
    assert "Kako's app registration" in lines[-1].detail
    assert "super-secret-value" not in "".join(str(line) for line in lines)
    assert backend.calls == []


def test_a_failing_deployment_fails_only_its_line(foundry: Settings) -> None:
    lines = run(foundry, FakeBackend(failing={"kako-fast"}))
    assert [line.ok for line in lines] == [True, True, True, False]
    assert "does not exist" in lines[-1].detail


def test_cli_exits_1_on_a_fail(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("kako.cli.get_settings", lambda: Settings(_env_file=None))  # type: ignore[call-arg]
    assert main(["check-models"]) == 1
    assert "[FAIL] Settings: missing KAKO_FOUNDRY_ENDPOINT" in capsys.readouterr().out


def test_credential_for_kakos_app(make_settings: MakeSettings) -> None:
    settings = make_settings(azure_tenant_id="t", azure_client_id="c", azure_client_secret="s")
    assert type(credential_for(settings)).__name__ == "ClientSecretCredential"


def test_credential_falls_back_to_azure_cli(make_settings: MakeSettings) -> None:
    assert type(credential_for(make_settings())).__name__ == "AzureCliCredential"


@pytest.mark.parametrize(
    "values",
    [
        {"azure_client_id": "c"},
        {"azure_client_secret": "s"},
        {"azure_client_id": "c", "azure_client_secret": "s"},  # no tenant
    ],
)
def test_incomplete_app_settings_are_refused(
    make_settings: MakeSettings, values: dict[str, str]
) -> None:
    with pytest.raises(ModelError):
        credential_for(make_settings(**values))


def test_another_projects_azure_variables_are_ignored(
    make_settings: MakeSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AZURE_CLIENT_ID and friends belong to whatever else shares the environment."""
    monkeypatch.setenv("AZURE_CLIENT_ID", "someone-elses-app")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "someone-elses-secret")
    monkeypatch.setenv("AZURE_TENANT_ID", "someone-elses-tenant")
    assert type(credential_for(make_settings())).__name__ == "AzureCliCredential"


def test_foundry_backend_request(foundry: Settings) -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "created": 0,
                "model": "kako-fast",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": " OK "},
                    }
                ],
                "usage": {"prompt_tokens": 14, "completion_tokens": 2, "total_tokens": 16},
            },
        )

    backend = FoundryBackend(
        foundry,
        FakeCredential(),  # type: ignore[arg-type]
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )
    reply = backend.complete("kako-fast", "Reply with the single word OK.", 64)

    assert (reply.text, reply.input_tokens, reply.output_tokens) == ("OK", 14, 2)
    (request,) = seen
    assert str(request.url) == f"{ENDPOINT}/openai/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer fake-entra-token"
    assert "api-key" not in request.headers
    body = json.loads(request.content)
    assert body["model"] == "kako-fast"
    assert body["max_completion_tokens"] == 64


def test_foundry_backend_errors_become_model_errors(foundry: Settings) -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(404, json={"error": {"code": "DeploymentNotFound", "message": "no"}})

    backend = FoundryBackend(
        foundry,
        FakeCredential(),  # type: ignore[arg-type]
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )
    with pytest.raises(ModelError, match="NotFoundError"):
        backend.complete("missing", "hi", 16)


def test_foundry_backend_needs_an_endpoint(make_settings: MakeSettings) -> None:
    with pytest.raises(ModelError, match="KAKO_FOUNDRY_ENDPOINT"):
        FoundryBackend(make_settings(), FakeCredential())  # type: ignore[arg-type]


CHAT_RESPONSE = {
    "id": "chatcmpl-2",
    "object": "chat.completion",
    "created": 0,
    "model": "kako-fast",
    "choices": [
        {
            "index": 0,
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "get_figures", "arguments": '{"keys": ["F1"]}'},
                    }
                ],
            },
        }
    ],
    "usage": {
        "prompt_tokens": 1200,
        "completion_tokens": 90,
        "total_tokens": 1290,
        "prompt_tokens_details": {"cached_tokens": 1024},
    },
}


def _chat(foundry: Settings, handler: Callable[[httpx2.Request], httpx2.Response]) -> FoundryChat:
    return FoundryChat(
        foundry,
        FakeCredential(),  # type: ignore[arg-type]
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )


async def test_foundry_chat_sends_tools_and_reads_tool_calls(foundry: Settings) -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=CHAT_RESPONSE)

    tool = ToolSpec("get_figures", "Read figures.", {"type": "object", "properties": {}})
    request = ChatRequest(
        "fast",
        (
            Message("system", "You are the debt specialist."),
            Message("user", "Brief."),
            Message("assistant", None, (ToolCall("call_0", "get_facts", "{}"),)),
            Message("tool", '{"facts": []}', tool_call_id="call_0"),
        ),
        max_output_tokens=800,
        tools=(tool,),
    )
    reply = await _chat(foundry, handler).chat(request, deployment="kako-fast", key="ignored")

    assert reply.tool_calls == (ToolCall("call_1", "get_figures", '{"keys": ["F1"]}'),)
    assert (reply.input_tokens, reply.cached_tokens, reply.output_tokens) == (1200, 1024, 90)
    assert reply.finish_reason == "tool_calls"
    (sent,) = seen
    assert sent.headers["authorization"] == "Bearer fake-entra-token"
    assert "api-key" not in sent.headers
    body = json.loads(sent.content)
    assert body["model"] == "kako-fast"
    assert body["max_completion_tokens"] == 800
    assert body["reasoning_effort"] == "low"
    assert body["tool_choice"] == "auto"
    assert body["tools"][0]["function"]["name"] == "get_figures"
    assert body["tools"][0]["function"]["strict"] is True
    assert body["messages"][2]["tool_calls"][0]["function"]["name"] == "get_facts"
    assert body["messages"][3] == {
        "role": "tool",
        "content": '{"facts": []}',
        "tool_call_id": "call_0",
    }


@pytest.mark.parametrize(
    ("status", "headers", "retryable", "retry_after"),
    [
        (429, {"retry-after": "7"}, True, 7.0),
        (429, {"retry-after-ms": "1500"}, True, 1.5),
        (503, {}, True, None),
        (400, {}, False, None),
        (401, {}, False, None),
    ],
)
async def test_foundry_chat_says_which_errors_may_pass_next_time(
    foundry: Settings,
    status: int,
    headers: dict[str, str],
    retryable: bool,
    retry_after: float | None,
) -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, headers=headers, json={"error": {"message": "no"}})

    request = ChatRequest("fast", (Message("user", "hi"),), max_output_tokens=16)
    with pytest.raises(ModelError) as caught:
        await _chat(foundry, handler).chat(request, deployment="kako-fast", key="k")
    assert caught.value.retryable is retryable
    assert caught.value.retry_after == retry_after


async def test_foundry_chat_sends_no_tools_when_there_are_none(
    make_settings: MakeSettings,
) -> None:
    settings = make_settings(
        foundry_endpoint=ENDPOINT, model_fast="kako-fast", reasoning_effort_fast=None
    )
    seen: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json=CHAT_RESPONSE
            | {
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": " ok "},
                    }
                ]
            },
        )

    request = ChatRequest("fast", (Message("user", "hi"),), max_output_tokens=16)
    reply = await _chat(settings, handler).chat(request, deployment="kako-fast", key="k")
    assert reply.text == "ok"
    assert "tools" not in seen[0]
    assert "reasoning_effort" not in seen[0]
