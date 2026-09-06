import asyncio
import json

import httpx
import pytest

from app.config import Settings
from app.local_ai import LocalAIClient


@pytest.mark.parametrize(
    "provider,model,token_key",
    [
        ("openai-compatible", "gpt-5.6-luna", "max_completion_tokens"),
        ("openai-compatible", "small-local", "max_tokens"),
        ("ollama", "small-local", "num_predict"),
    ],
)
def test_analysis_output_limits_and_provider_usage(provider, model, token_key):
    def handler(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": model}]})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": model}]})
        body = json.loads(request.content)
        if provider == "ollama":
            assert body["options"][token_key] == 1200
            return httpx.Response(
                200, json={"message": {"content": "{}"}, "prompt_eval_count": 12, "eval_count": 8}
            )
        assert body[token_key] == 1200
        if token_key == "max_completion_tokens":
            assert "temperature" not in body
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8},
            },
        )

    client = LocalAIClient(
        Settings(
            _env_file=None,
            ai_provider=provider,
            ai_base_url="http://localhost:1234",
            ai_model=model,
        ),
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(
        client.complete([{"role": "user", "content": "synthetic"}], max_output_tokens=1200)
    )
    assert result.input_tokens == 12 and result.output_tokens == 8


def test_ollama_status_uses_installed_local_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "qwen-local:8b"}]})

    client = LocalAIClient(
        Settings(
            ai_provider="ollama",
            ai_base_url="http://localhost:11434",
            ai_model="auto",
        ),
        transport=httpx.MockTransport(handler),
    )

    status = asyncio.run(client.status())

    assert status.available is True
    assert status.active_model == "qwen-local:8b"
    assert status.local_only is True


def test_ollama_json_completion_never_uses_remote_endpoint() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "local-model"}]})
        body = json.loads(request.content)
        assert request.url.path == "/api/chat"
        assert body["model"] == "local-model"
        assert body["format"] == "json"
        return httpx.Response(
            200,
            json={"message": {"content": '{"summary":"로컬 분석"}'}},
        )

    client = LocalAIClient(
        Settings(
            ai_provider="ollama",
            ai_base_url="http://127.0.0.1:11434",
            ai_model="auto",
        ),
        transport=httpx.MockTransport(handler),
    )

    payload, model = asyncio.run(client.complete_json([{"role": "user", "content": "analyze"}]))

    assert payload == {"summary": "로컬 분석"}
    assert model == "local-model"
    assert {request.url.host for request in requests} == {"127.0.0.1"}


def test_openai_compatible_completion_uses_gui_selected_local_model() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/models":
            return httpx.Response(
                200,
                json={"data": [{"id": "gpt5.6"}, {"id": "local-coder"}]},
            )
        body = json.loads(request.content)
        assert request.url.path == "/v1/chat/completions"
        assert body["model"] == "local-coder"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "로컬 모델 분석"}}]},
        )

    client = LocalAIClient(
        Settings(ai_base_url="http://localhost:1234"),
        transport=httpx.MockTransport(handler),
    )

    status = asyncio.run(client.status(model="local-coder"))
    completion = asyncio.run(
        client.complete(
            [{"role": "user", "content": "analyze"}],
            model="local-coder",
        )
    )

    assert status.configured_model == "local-coder"
    assert status.active_model == "local-coder"
    assert completion.model == "local-coder"
    assert completion.content == "로컬 모델 분석"
    assert {request.url.host for request in requests} == {"localhost"}


def test_codex_provider_uses_consent_bridge_header_and_selected_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Job-Radar-Bridge"] == "codex-gpt-consent"
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "gpt-5.6-sol"}]})
        body = json.loads(request.content)
        assert request.url.path == "/v1/chat/completions"
        assert body["model"] == "gpt-5.6-sol"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Codex GPT 분석"}}]},
        )

    client = LocalAIClient(
        Settings(
            ai_provider="codex",
            ai_base_url="http://codex-bridge:48765",
            ai_model="gpt-5.6-sol",
            ai_allow_remote=True,
        ),
        transport=httpx.MockTransport(handler),
    )

    status = asyncio.run(client.status())
    completion = asyncio.run(client.complete([{"role": "user", "content": "analyze"}]))

    assert status.available is True
    assert status.local_only is False
    assert "ChatGPT 계정" in status.message
    assert completion.content == "Codex GPT 분석"
