"""DeepSeek transport shared by teaching generation and native tool calls.

Uses the OpenAI-compatible Chat Completions protocol. Native assistant
messages are retained verbatim across tool turns, including reasoning_content.
"""
from __future__ import annotations

import json
from copy import deepcopy
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import httpx

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from clawed.models import AppConfig


def normalize_base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlsplit(value)
    _ = parsed.port  # Reject malformed ports before issuing a request.
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if not parsed.hostname or (parsed.scheme != "https" and not (local and parsed.scheme == "http")):
        raise ValueError("DeepSeek URL must use HTTPS (HTTP is allowed only for localhost)")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("DeepSeek URL must not contain credentials, a query, or a fragment")
    if parsed.path.endswith(("/chat/completions", "/models")):
        raise ValueError("Use the DeepSeek base URL, without /chat/completions or /models")
    return value


def request_headers() -> dict[str, str]:
    from clawed.config import get_api_key

    key = get_api_key("deepseek")
    if not key:
        raise OSError("DeepSeek API key missing. Set DEEPSEEK_API_KEY or run clawed config set-key deepseek")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def timeout(config: AppConfig) -> httpx.Timeout:
    return httpx.Timeout(connect=20.0, read=config.deepseek_timeout, write=30.0, pool=20.0)


def history_key(config: AppConfig) -> str:
    """Keep native histories separate when endpoint, model, or mode changes."""
    return json.dumps({
        "url": normalize_base_url(config.deepseek_base_url),
        "model": config.deepseek_model,
        "thinking": config.deepseek_thinking,
        "effort": config.deepseek_reasoning_effort,
    }, sort_keys=True)


def build_messages(messages: list[dict[str, Any]], system: str = "") -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if system:
        result.append({"role": "system", "content": system})
    for message in messages:
        native = message.get("deepseek_message")
        if isinstance(native, dict):
            result.append(deepcopy(native))
            continue
        role = message["role"]
        item: dict[str, Any] = {"role": role, "content": message.get("content") or ""}
        if role == "tool":
            item["tool_call_id"] = message["tool_call_id"]
        if role == "assistant":
            # Older text-only history did not perform DeepSeek reasoning.
            item["reasoning_content"] = message.get("reasoning_content") or ""
            if message.get("tool_calls"):
                calls = []
                for call in message["tool_calls"]:
                    if "function" in call:
                        calls.append(deepcopy(call))
                    else:
                        calls.append({
                            "id": call["id"], "type": "function",
                            "function": {"name": call["name"],
                                         "arguments": json.dumps(call.get("arguments", {}), ensure_ascii=False)},
                        })
                item["tool_calls"] = calls
        result.append(item)
    return result


def build_request(
    config: AppConfig, messages: list[dict[str, Any]], *, system: str = "",
    temperature: float = 0.7, max_tokens: int = 4096, json_mode: bool = False,
    tools: list[dict[str, Any]] | None = None, stream: bool = False,
    model: str | None = None,
) -> dict[str, Any]:
    prepared = build_messages(messages, system)
    if json_mode:
        prepared.insert(0, {"role": "system", "content": (
            "Return only a valid JSON object matching the requested structure. "
            "For example: {\"result\": \"value\"}. Do not include Markdown fences."
        )})
    budget = max_tokens + (config.deepseek_reasoning_tokens if config.deepseek_thinking else 0)
    body: dict[str, Any] = {
        "model": model or config.deepseek_model, "messages": prepared,
        "max_tokens": min(max(1, budget), 393216), "stream": stream,
        "thinking": {"type": "enabled" if config.deepseek_thinking else "disabled"},
    }
    if config.deepseek_thinking:
        body["reasoning_effort"] = config.deepseek_reasoning_effort
    else:
        body["temperature"] = temperature
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if tools:
        body["tools"] = tools
    return body


def raise_for_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    labels = {
        400: "Invalid request or incompatible model parameters",
        401: "API key is invalid", 402: "Insufficient balance",
        403: "Access denied", 404: "Endpoint or model not found",
        422: "Invalid request parameters", 429: "Rate limit reached; retry later",
        500: "Provider internal error; retry later", 503: "Provider is overloaded; retry later",
    }
    # Do not echo provider bodies: they can contain prompts and credentials.
    detail = labels.get(response.status_code, "Provider request failed")
    if response.status_code in {401, 403}:
        raise OSError(f"DeepSeek ({response.status_code}): {detail}")
    raise RuntimeError(f"DeepSeek ({response.status_code}): {detail}")


def check_finish(reason: str | None) -> None:
    if reason == "length":
        raise RuntimeError("DeepSeek output was truncated; increase the output/reasoning token budget")
    if reason in {"content_filter", "insufficient_system_resource", "aborted"}:
        raise RuntimeError(f"DeepSeek did not complete the response: {reason}")


async def complete(config: AppConfig, body: dict[str, Any]) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=timeout(config)) as client:
            response = await client.post(
                f"{normalize_base_url(config.deepseek_base_url)}/chat/completions",
                headers=request_headers(), json=body,
            )
            raise_for_status(response)
            data = response.json()
    except httpx.TimeoutException as exc:
        raise TimeoutError("DeepSeek request timed out; adjust deepseek_timeout or disable thinking") from exc
    except httpx.ConnectError as exc:
        raise ConnectionError("Could not connect to DeepSeek; check the URL and network") from exc
    choices = data.get("choices")
    if not choices:
        raise RuntimeError("DeepSeek returned no completion choices")
    check_finish(choices[0].get("finish_reason"))
    message: dict[str, Any] = choices[0].get("message") or {}
    if not message.get("tool_calls") and not str(message.get("content") or "").strip():
        raise RuntimeError("DeepSeek returned empty answer content; adjust the prompt or reasoning token budget")
    return message


async def stream_text(config: AppConfig, body: dict[str, Any]) -> AsyncIterator[str]:
    body = {**body, "stream": True}
    content_seen = False
    done = False
    try:
        async with httpx.AsyncClient(timeout=timeout(config)) as client, client.stream(
            "POST", f"{normalize_base_url(config.deepseek_base_url)}/chat/completions",
            headers=request_headers(), json=body,
        ) as response:
            raise_for_status(response)
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    done = True
                    break
                data = json.loads(payload)
                if data.get("error"):
                    raise RuntimeError("DeepSeek returned a streaming API error")
                for choice in data.get("choices") or []:
                    check_finish(choice.get("finish_reason"))
                    text = choice.get("delta", {}).get("content")
                    # Reasoning deltas are protocol data, never user-facing answer text.
                    if text:
                        content_seen = content_seen or bool(text.strip())
                        yield str(text)
    except httpx.TimeoutException as exc:
        raise TimeoutError("DeepSeek stream timed out") from exc
    except httpx.ConnectError as exc:
        raise ConnectionError("Could not connect to DeepSeek") from exc
    if not done:
        raise ConnectionError("DeepSeek stream ended before completion")
    if not content_seen:
        raise RuntimeError("DeepSeek stream returned no answer content")


async def list_models(config: AppConfig) -> list[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                f"{normalize_base_url(config.deepseek_base_url)}/models", headers=request_headers(),
            )
            raise_for_status(response)
            models: list[dict[str, Any]] = response.json().get("data", [])
            return models
    except httpx.HTTPError as exc:
        raise ConnectionError("Could not retrieve the DeepSeek model catalog; check the network") from exc


async def vision_available(config: AppConfig, model: str) -> bool:
    if model in {"deepseek-flash", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp"}:
        return True
    if model in {"deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"}:
        return False
    return any(
        item.get("id") == model and "image" in (item.get("input_modalities") or [])
        for item in await list_models(config)
    )
