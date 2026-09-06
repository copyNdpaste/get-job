import json
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings


class AIUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AIStatus:
    enabled: bool
    available: bool
    provider: str
    configured_model: str
    active_model: str | None
    models: list[str]
    local_only: bool
    message: str


@dataclass(frozen=True, slots=True)
class AICompletion:
    content: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class LocalAIClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport

    async def status(self, *, model: str | None = None) -> AIStatus:
        configured_model = self._requested_model(model)
        if not self.settings.ai_enabled or self.settings.ai_provider == "disabled":
            return AIStatus(
                enabled=False,
                available=False,
                provider="disabled",
                configured_model=configured_model,
                active_model=None,
                models=[],
                local_only=not self.settings.ai_allow_remote,
                message="AI 기능이 꺼져 있어 규칙 기반 분석만 사용합니다.",
            )
        try:
            async with self._client() as client:
                models = await self._list_models(client)
            active_model = self._select_model(models, configured_model)
            return AIStatus(
                enabled=True,
                available=active_model is not None,
                provider=self.settings.ai_provider,
                configured_model=configured_model,
                active_model=active_model,
                models=models,
                local_only=not self.settings.ai_allow_remote,
                message=(
                    (
                        f"Codex GPT {active_model}에 ChatGPT 계정으로 연결되었습니다."
                        if self.settings.ai_provider == "codex"
                        else f"로컬 AI {active_model}에 연결되었습니다."
                    )
                    if active_model
                    else (
                        f"AI 서버에 {configured_model} 모델이 없습니다. "
                        "GUI에서 사용 가능한 모델을 선택해 주세요."
                        if models
                        else "AI 서버는 응답했지만 사용 가능한 모델이 없습니다."
                    )
                ),
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return AIStatus(
                enabled=True,
                available=False,
                provider=self.settings.ai_provider,
                configured_model=configured_model,
                active_model=None,
                models=[],
                local_only=not self.settings.ai_allow_remote,
                message=(
                    "Codex GPT 브리지가 실행 중이지 않아 규칙 기반 분석을 사용합니다."
                    if self.settings.ai_provider == "codex"
                    else "로컬 AI 서버에 연결할 수 없어 규칙 기반 분석을 사용합니다."
                ),
            )

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
        model: str | None = None,
        max_output_tokens: int | None = None,
    ) -> AICompletion:
        if max_output_tokens is not None and not 128 <= max_output_tokens <= 8192:
            raise ValueError("max_output_tokens must be between 128 and 8192")
        if not self.settings.ai_enabled or self.settings.ai_provider == "disabled":
            raise AIUnavailableError("AI 기능이 비활성화되어 있습니다.")
        try:
            async with self._client() as client:
                models = await self._list_models(client)
                selected_model = self._select_model(models, self._requested_model(model))
                if not selected_model:
                    raise AIUnavailableError(
                        "선택한 모델을 로컬 AI 서버에서 찾을 수 없습니다. "
                        "모델 목록을 새로고침해 주세요."
                    )
                if self.settings.ai_provider == "ollama":
                    body: dict[str, Any] = {
                        "model": selected_model,
                        "messages": messages,
                        "stream": False,
                        "think": False,
                        "options": {"temperature": 0.2},
                    }
                    if json_mode:
                        body["format"] = "json"
                    if max_output_tokens is not None:
                        body["options"]["num_predict"] = max_output_tokens
                    response = await client.post(
                        self._endpoint("/api/chat"),
                        json=body,
                    )
                    response.raise_for_status()
                    payload = response.json()
                    content = str(payload.get("message", {}).get("content", "")).strip()
                else:
                    body: dict[str, Any] = {
                        "model": selected_model,
                        "messages": messages,
                        "temperature": 0.2,
                    }
                    if json_mode:
                        body["response_format"] = {"type": "json_object"}
                    if max_output_tokens is not None:
                        token_field = (
                            "max_completion_tokens"
                            if selected_model.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4"))
                            else "max_tokens"
                        )
                        body[token_field] = max_output_tokens
                        if token_field == "max_completion_tokens":
                            body.pop("temperature", None)
                    response = await client.post(
                        self._endpoint("/chat/completions", openai=True), json=body
                    )
                    response.raise_for_status()
                    payload = response.json()
                    content = str(payload["choices"][0]["message"]["content"]).strip()
        except AIUnavailableError:
            raise
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            provider_name = "Codex GPT" if self.settings.ai_provider == "codex" else "로컬 AI"
            raise AIUnavailableError(
                f"{provider_name} 요청을 완료하지 못했습니다. 연결 상태를 확인해 주세요."
            ) from exc
        if not content:
            raise AIUnavailableError("AI 모델이 빈 응답을 반환했습니다.")
        usage = payload.get("usage") or {}
        if not isinstance(usage, dict):
            usage = {}

        def token_count(value: object) -> int | None:
            return value if type(value) is int and value >= 0 else None

        return AICompletion(
            content=content, model=selected_model,
            input_tokens=token_count(usage.get("prompt_tokens", payload.get("prompt_eval_count"))),
            output_tokens=token_count(usage.get("completion_tokens", payload.get("eval_count"))),
        )

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
    ) -> tuple[dict[str, Any], str]:
        completion = await self.complete(messages, json_mode=True, model=model)
        content = completion.content.strip()
        if content.startswith("```"):
            content = (
                content.removeprefix("```json")
                .removeprefix("```")
                .removesuffix("```")
                .strip()
            )
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            start, end = content.find("{"), content.rfind("}")
            if start < 0 or end <= start:
                raise AIUnavailableError("AI 모델이 JSON 형식을 지키지 않았습니다.") from None
            try:
                parsed = json.loads(content[start : end + 1])
            except json.JSONDecodeError as exc:
                raise AIUnavailableError("AI 모델의 JSON 응답을 해석할 수 없습니다.") from exc
        if not isinstance(parsed, dict):
            raise AIUnavailableError("AI 모델의 응답이 JSON 객체가 아닙니다.")
        return parsed, completion.model

    def _client(self) -> httpx.AsyncClient:
        headers = {"Content-Type": "application/json"}
        if self.settings.ai_provider == "codex":
            headers["X-Job-Radar-Bridge"] = "codex-gpt-consent"
        if self.settings.ai_provider == "openai-compatible" and self.settings.ai_api_key:
            headers["Authorization"] = f"Bearer {self.settings.ai_api_key.get_secret_value()}"
        timeout = httpx.Timeout(
            connect=2.0,
            read=self.settings.ai_timeout_seconds,
            write=10.0,
            pool=2.0,
        )
        return httpx.AsyncClient(headers=headers, timeout=timeout, transport=self.transport)

    async def _list_models(self, client: httpx.AsyncClient) -> list[str]:
        if self.settings.ai_provider == "ollama":
            response = await client.get(self._endpoint("/api/tags"))
            response.raise_for_status()
            rows = response.json().get("models", [])
            return [
                str(row.get("name") or row.get("model"))
                for row in rows
                if isinstance(row, dict) and (row.get("name") or row.get("model"))
            ]
        response = await client.get(self._endpoint("/models", openai=True))
        response.raise_for_status()
        rows = response.json().get("data", [])
        return [
            str(row["id"])
            for row in rows
            if isinstance(row, dict) and row.get("id")
        ]

    def _requested_model(self, model: str | None) -> str:
        return (model or self.settings.ai_model).strip() or self.settings.ai_model

    def _select_model(self, models: list[str], requested_model: str) -> str | None:
        if not models:
            return None
        if requested_model == "auto":
            return models[0]
        return requested_model if requested_model in models else None

    def _endpoint(self, path: str, *, openai: bool = False) -> str:
        base = self.settings.ai_base_url.rstrip("/")
        if openai and not base.endswith("/v1"):
            base = f"{base}/v1"
        return f"{base}{path}"
