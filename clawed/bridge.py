"""Bridge module for TS CLI -> Python provider routing.

Called via subprocess from the TypeScript CLI when the active provider
is not Anthropic (i.e. openai, google, ollama).  Reads a JSON request
on stdin, calls the appropriate LLM through the existing Python engine,
and writes a JSON response to stdout.

Protocol (stdin JSON):
  {
    "messages": [{"role": "user", "content": "..."}],
    "system":   "optional system prompt",
    "tools":    [{"type": "function", "function": {"name": "...", ...}}],
    "provider": "openai",         # from config if omitted
    "model":    "gpt-4o",         # from config if omitted
    "max_tokens": 4096,
    "temperature": 0.7
  }

Protocol (stdout JSON):
  {
    "status":  "success" | "error",
    "content": [
      {"type": "text", "text": "..."},
      {"type": "tool_use", "id": "...", "name": "...", "input": {...}}
    ],
    "model":   "gpt-4o",
    "usage":   {"input_tokens": 123, "output_tokens": 456},
    "stop_reason": "end_turn" | "tool_use",
    "error":   null | "description"
  }

  When no tools are provided, "content" may be a plain string (backward
  compat).  The TS side handles both.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Any

logger = logging.getLogger(__name__)


def _inject_api_keys() -> None:
    """Load API keys from ~/.eduagent/secrets.json into environment.

    The Python LLM clients read from env vars (OPENAI_API_KEY, GOOGLE_API_KEY,
    etc.). The TS CLI stores keys in secrets.json, so we need to bridge them.
    Only sets vars that aren't already in the environment.
    """
    from pathlib import Path

    secrets_path = Path(
        os.environ.get("EDUAGENT_DATA_DIR", str(Path.home() / ".eduagent"))
    ) / "secrets.json"

    if not secrets_path.exists():
        return

    try:
        secrets = json.loads(secrets_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    env_map = {
        "openai_api_key": "OPENAI_API_KEY",
        "google_api_key": "GOOGLE_API_KEY",
        "gemini_api_key": "GEMINI_API_KEY",
        "anthropic_api_key": "ANTHROPIC_API_KEY",
        "ollama_api_key": "OLLAMA_API_KEY",
        "deepseek_api_key": "DEEPSEEK_API_KEY",
    }

    for secret_key, env_var in env_map.items():
        if secret_key in secrets and secrets[secret_key] and env_var not in os.environ:
            os.environ[env_var] = secrets[secret_key]


def _build_config(provider: str | None, model: str | None) -> Any:
    """Load AppConfig, optionally overriding provider/model."""
    from clawed.models import AppConfig, LLMProvider

    # Ensure API keys are available
    _inject_api_keys()

    config = AppConfig.load()

    if provider:
        try:
            config.provider = LLMProvider(provider)
        except ValueError as e:
            raise ValueError(f"Unknown provider: {provider}") from e

    if model:
        # Set the right model field based on provider
        if config.provider == LLMProvider.OPENAI:
            config.openai_model = model
        elif config.provider == LLMProvider.GOOGLE:
            config.google_model = model
        elif config.provider == LLMProvider.OLLAMA:
            config.ollama_model = model
        elif config.provider == LLMProvider.ANTHROPIC:
            config.anthropic_model = model
        elif config.provider == LLMProvider.OPENROUTER:
            config.openrouter_model = model
        elif config.provider == LLMProvider.DEEPSEEK:
            config.deepseek_model = model

    return config


def _resolve_model(config: Any, model: str | None) -> str:
    """Determine the actual model name from config and override."""
    if model:
        return model
    from clawed.models import LLMProvider
    _model_fields = {
        LLMProvider.OPENAI: "openai_model",
        LLMProvider.GOOGLE: "google_model",
        LLMProvider.OLLAMA: "ollama_model",
        LLMProvider.ANTHROPIC: "anthropic_model",
        LLMProvider.OPENROUTER: "openrouter_model",
        LLMProvider.DEEPSEEK: "deepseek_model",
    }
    return getattr(config, _model_fields.get(config.provider, ""), "") or ""


def _convert_messages_for_agent(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert TS-side messages (Anthropic content-block format) to the
    internal format expected by agent.py tool-calling functions.

    Handles:
      - Plain text messages (role + string content)
      - User messages with tool_result content blocks
      - Assistant messages with tool_use content blocks
    """
    converted: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(msg.get("deepseek_message"), dict):
            converted.append({"role": "assistant", "deepseek_message": msg["deepseek_message"]})
            continue
        if role == "assistant" and isinstance(content, list):
            reasoning = "".join(
                block.get("thinking", "") for block in content
                if isinstance(block, dict) and block.get("type") == "thinking"
            )
        else:
            reasoning = msg.get("reasoning_content") or ""

        # ── User message with structured content (may contain tool_result) ──
        if role == "user" and isinstance(content, list):
            tool_results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
            if tool_results:
                # Each tool_result becomes a separate "tool" message for
                # the OpenAI-compatible format that agent.py uses internally.
                for tr in tool_results:
                    tr_content = tr.get("content", "")
                    # content can be a string or a list of blocks
                    if isinstance(tr_content, list):
                        tr_content = "\n".join(
                            b.get("text", "") for b in tr_content
                            if isinstance(b, dict) and b.get("type") == "text"
                        )
                    converted.append({
                        "role": "tool",
                        "tool_call_id": tr.get("tool_use_id", ""),
                        "content": str(tr_content),
                    })
            else:
                # Regular user message with text blocks
                text = "\n".join(
                    b.get("text", "") for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
                if text:
                    converted.append({"role": "user", "content": text})
            continue

        # ── Assistant message with structured content (may contain tool_use) ──
        if role == "assistant" and isinstance(content, list):
            tool_uses = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
            if tool_uses:
                tool_calls = []
                for tu in tool_uses:
                    tool_calls.append({
                        "id": tu.get("id", tu.get("name", "")),
                        "name": tu.get("name", ""),
                        "arguments": tu.get("input", {}),
                    })
                converted.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": tool_calls,
                    "reasoning_content": reasoning,
                })
            else:
                text = "\n".join(
                    b.get("text", "") for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
                if text:
                    converted.append({"role": "assistant", "content": text, "reasoning_content": reasoning})
            continue

        # ── Plain string content ──
        if isinstance(content, str) and content:
            converted.append({"role": role, "content": content, **(
                {"reasoning_content": reasoning} if role == "assistant" else {}
            )})

    return converted


async def _handle_chat(request: dict[str, Any]) -> dict[str, Any]:
    """Process a single chat request and return a response dict.

    When ``tools`` are provided in the request, routes through the
    agent.py tool-calling functions instead of the plain LLMClient.
    """
    from clawed.llm import LLMClient

    provider = request.get("provider")
    model = request.get("model")
    messages = request.get("messages", [])
    system = request.get("system", "")
    max_tokens = request.get("max_tokens", 4096)
    temperature = request.get("temperature", 0.7)
    tools = request.get("tools")  # may be None or []

    try:
        config = _build_config(provider, model)
    except ValueError as exc:
        return {
            "status": "error",
            "content": "",
            "model": model or "",
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "error": str(exc),
        }

    used_model = _resolve_model(config, model)

    # ── Tool-calling path ──────────────────────────────────────────────
    if tools:
        try:
            return await _handle_chat_with_tools(
                messages, system, tools, config, used_model,
            )
        except Exception as exc:
            if config.provider.value == "deepseek":
                return {
                    "status": "error", "content": [], "model": used_model,
                    "usage": {"input_tokens": 0, "output_tokens": 0}, "error": str(exc),
                }
            logger.warning(
                "Tool-calling path failed (%s), falling back to text-only", exc,
            )
            # Fall through to the text-only path below

    # ── Text-only path (original behaviour, backward compat) ───────────
    prompt_parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            text_parts = [
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            content = "\n".join(text_parts)
        if role == "user":
            prompt_parts.append(content)
        elif role == "assistant":
            prompt_parts.append(f"[Previous assistant response: {content[:200]}...]")

    prompt = "\n\n".join(prompt_parts) if prompt_parts else ""

    try:
        client = LLMClient(config=config)
        response_text = await client.generate(
            prompt=prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return {
            "status": "success",
            "content": response_text,
            "model": used_model,
            "usage": {
                "input_tokens": len(prompt.split()),
                "output_tokens": len(response_text.split()),
            },
            "error": None,
        }

    except Exception as exc:
        logger.exception("Bridge chat error")
        return {
            "status": "error",
            "content": "",
            "model": used_model,
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "error": f"{type(exc).__name__}: {exc}",
        }


async def _handle_chat_with_tools(
    messages: list[dict[str, Any]],
    system: str,
    tools: list[dict[str, Any]],
    config: Any,
    used_model: str,
) -> dict[str, Any]:
    """Route a tool-capable request through agent.py's native tool functions.

    Passes request-local tool definitions to the selected adapter.
    """
    from clawed.agent import (
        _call_with_native_tools,
        _call_with_ollama_tools,
    )
    from clawed.models import LLMProvider

    agent_messages = _convert_messages_for_agent(messages)
    if config.provider == LLMProvider.OLLAMA:
        response = await _call_with_ollama_tools(agent_messages, system, config, tools)
    else:
        response = await _call_with_native_tools(agent_messages, system, config, tools)

    # ── Build the response in Anthropic content-block format ───────────
    if response["type"] == "text":
        content_blocks: list[dict[str, Any]] = [
            {"type": "text", "text": response.get("content", "")},
        ]
        if response.get("deepseek_message", {}).get("reasoning_content"):
            content_blocks.insert(0, {"type": "thinking", "thinking": response["deepseek_message"]["reasoning_content"]})
        return {
            "status": "success",
            "content": content_blocks,
            "model": used_model,
            "usage": {
                "input_tokens": len(system.split()) + sum(
                    len(str(m.get("content", "")).split()) for m in messages
                ),
                "output_tokens": len(response.get("content", "").split()),
            },
            "stop_reason": "end_turn",
            "deepseek_message": response.get("deepseek_message"),
            "error": None,
        }

    if response["type"] == "tool_calls":
        content_blocks = []
        native = response.get("deepseek_message") or {}
        if native.get("reasoning_content"):
            content_blocks.append({"type": "thinking", "thinking": native["reasoning_content"]})
        if native.get("content"):
            content_blocks.append({"type": "text", "text": native["content"]})
        for tc in response["tool_calls"]:
            content_blocks.append({
                "type": "tool_use",
                "id": tc.get("id", tc.get("name", "")),
                "name": tc["name"],
                "input": tc.get("arguments", {}),
            })
        return {
            "status": "success",
            "content": content_blocks,
            "model": used_model,
            "usage": {
                "input_tokens": len(system.split()) + sum(
                    len(str(m.get("content", "")).split()) for m in messages
                ),
                "output_tokens": 0,
            },
            "stop_reason": "tool_use",
            "deepseek_message": response.get("deepseek_message"),
            "error": None,
        }

    # Unexpected response type -- return empty text
    return {
        "status": "success",
        "content": [{"type": "text", "text": ""}],
        "model": used_model,
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "stop_reason": "end_turn",
        "error": None,
    }


def _run_chat_stdin() -> None:
    """Read request from stdin, process, write response to stdout."""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            _write_error("Empty input on stdin")
            return

        request = json.loads(raw)
    except json.JSONDecodeError as exc:
        _write_error(f"Invalid JSON on stdin: {exc}")
        return

    result = asyncio.run(_handle_chat(request))
    sys.stdout.write(json.dumps(result))
    sys.stdout.flush()


def _run_chat_args(provider: str, model: str) -> None:
    """Interactive single-shot chat from CLI args (for testing)."""
    logger.info("Bridge ready: provider=%s, model=%s", provider, model)
    logger.info("Enter message (Ctrl+D to send):")
    prompt = sys.stdin.read().strip()
    if not prompt:
        _write_error("No prompt provided")
        return

    request = {
        "messages": [{"role": "user", "content": prompt}],
        "provider": provider,
        "model": model,
    }
    result = asyncio.run(_handle_chat(request))
    sys.stdout.write(json.dumps(result))
    sys.stdout.flush()


def _write_error(msg: str) -> None:
    result = {
        "status": "error",
        "content": "",
        "model": "",
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "error": msg,
    }
    sys.stdout.write(json.dumps(result))
    sys.stdout.flush()


def main() -> None:
    """Entry point for `python -m clawed.bridge`."""
    parser = argparse.ArgumentParser(description="Claw-ED Python LLM bridge")
    sub = parser.add_subparsers(dest="command")

    chat_parser = sub.add_parser("chat", help="Process a chat request")
    chat_parser.add_argument("--provider", default=None, help="LLM provider")
    chat_parser.add_argument("--model", default=None, help="Model name")
    chat_parser.add_argument(
        "--stdin", action="store_true", default=True,
        help="Read full JSON request from stdin (default)",
    )

    args = parser.parse_args()

    if args.command == "chat":
        if args.stdin and args.provider is None:
            _run_chat_stdin()
        elif args.provider:
            _run_chat_args(args.provider, args.model or "")
        else:
            _run_chat_stdin()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
