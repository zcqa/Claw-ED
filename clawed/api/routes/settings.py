"""Settings and health check API routes."""

from __future__ import annotations

import contextlib
import json
import os
from typing import Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from clawed import __version__
from clawed.api.deps import get_db, require_auth
from clawed.config import (
    get_api_key,
    mask_api_key,
    set_api_key,
    test_llm_connection,
)
from clawed.models import AppConfig, LLMProvider

router = APIRouter(tags=["settings"])


class SaveSettingsRequest(BaseModel):
    provider: LLMProvider
    api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-6"
    openai_model: str = "gpt-4o"
    ollama_model: str = "llama3.2"
    ollama_base_url: str = "http://localhost:11434"
    # Optional fields preserve saved values for older API clients.
    deepseek_model: str | None = Field(default=None, min_length=1)
    deepseek_base_url: str | None = None
    deepseek_thinking: bool | None = None
    deepseek_reasoning_effort: Literal["low", "high", "max"] | None = None
    deepseek_reasoning_tokens: int | None = Field(default=None, ge=0, le=131072)
    deepseek_timeout: float | None = Field(default=None, ge=10, le=1800)
    deepseek_vision_model: str | None = None
    default_grade: str = ""
    default_subject: str = ""
    include_homework: bool = True
    export_format: str = "markdown"


class PersonaFormRequest(BaseModel):
    name: str
    subject_area: str = ""
    grade_levels: str = ""
    teaching_style: str = "direct_instruction"
    preferred_lesson_format: str = ""


class OnboardingStepRequest(BaseModel):
    teacher_id: str
    step: int


@router.get("/health")
async def health_check() -> dict[str, Any]:
    """Lightweight liveness check — no DB or LLM calls."""
    return {
        "status": "ok",
        "version": __version__,
    }


@router.get("/health/diagnostics", dependencies=[Depends(require_auth)])
async def health_diagnostics() -> dict[str, Any]:
    """Full diagnostics endpoint with DB stats and LLM connection test."""
    cfg = AppConfig.load()
    db = get_db()
    teacher = db.get_default_teacher()
    stats = db.get_stats()

    connection = await test_llm_connection(cfg)

    return {
        "status": "ok",
        "llm_provider": cfg.provider.value,
        "llm_model": getattr(cfg, f"{cfg.provider.value}_model", ""),
        "llm_connected": connection.get("connected", False),
        "persona_loaded": teacher is not None and teacher.get("persona_json") is not None,
        "units_generated": stats["units"],
        "lessons_generated": stats["lessons"],
        "db_size_mb": round(db.db_size_mb(), 2),
        "version": __version__,
    }


@router.get("/settings", dependencies=[Depends(require_auth)])
async def get_settings() -> dict[str, Any]:
    """Get current settings (API keys masked)."""
    cfg = AppConfig.load()
    anthropic_key = get_api_key("anthropic")
    openai_key = get_api_key("openai")

    return {
        "provider": cfg.provider.value,
        "anthropic_model": cfg.anthropic_model,
        "openai_model": cfg.openai_model,
        "ollama_model": cfg.ollama_model,
        "ollama_base_url": cfg.ollama_base_url,
        "deepseek_model": cfg.deepseek_model,
        "deepseek_base_url": cfg.deepseek_base_url,
        "deepseek_thinking": cfg.deepseek_thinking,
        "deepseek_reasoning_effort": cfg.deepseek_reasoning_effort,
        "deepseek_reasoning_tokens": cfg.deepseek_reasoning_tokens,
        "deepseek_timeout": cfg.deepseek_timeout,
        "deepseek_vision_model": cfg.deepseek_vision_model,
        "deepseek_key_masked": mask_api_key(get_api_key("deepseek")),
        "has_deepseek_key": bool(get_api_key("deepseek")),
        "anthropic_key_masked": mask_api_key(anthropic_key),
        "openai_key_masked": mask_api_key(openai_key),
        "has_anthropic_key": bool(anthropic_key),
        "has_openai_key": bool(openai_key),
        "include_homework": cfg.include_homework,
        "export_format": cfg.export_format,
    }


def _validate_ollama_url(raw: str) -> tuple[str | None, str | None]:
    """Return (normalized_url, error). None error means valid.

    v4.11.2026 SSRF protection. The previous version accepted any URL the
    caller supplied and fed it into httpx for test-connection. An authed
    user could aim it at internal endpoints like http://169.254.169.254
    (cloud metadata), http://10.x.y.z (internal LAN), or
    http://[::1]:<port> (loopback to another local service) and read the
    response via error messages.

    This validator enforces:
    - scheme must be http or https
    - hostname must not be empty
    - hostname must resolve to a loopback address OR be explicitly
      allowlisted via the EDUAGENT_OLLAMA_ALLOW_HOSTS env var
    """
    import ipaddress
    from urllib.parse import urlparse

    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        return None, "ollama_base_url must use http:// or https://"
    host = (parsed.hostname or "").lower()
    if not host:
        return None, "ollama_base_url is missing a host"

    allow_env = os.environ.get("EDUAGENT_OLLAMA_ALLOW_HOSTS", "")
    extra_allowed = {h.strip().lower() for h in allow_env.split(",") if h.strip()}

    # Loopback names are always allowed.
    if host in {"localhost", "127.0.0.1", "::1"} or host in extra_allowed:
        pass
    else:
        # Try parsing as an IP and require it to be loopback.
        try:
            ip = ipaddress.ip_address(host)
            if not ip.is_loopback:
                return None, (
                    "ollama_base_url must be a loopback address "
                    "or be listed in EDUAGENT_OLLAMA_ALLOW_HOSTS."
                )
        except ValueError:
            return None, (
                "ollama_base_url must target localhost or an explicitly "
                "allow-listed host (EDUAGENT_OLLAMA_ALLOW_HOSTS)."
            )

    normalized = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    return normalized, None


def _validate_deepseek_url(raw: str) -> tuple[str | None, str | None]:
    """Only official or explicitly allowlisted endpoints may be set over the web."""
    from urllib.parse import urlsplit

    from clawed.deepseek import normalize_base_url

    try:
        normalized = normalize_base_url(raw)
        parsed = urlsplit(normalized)
        # Accessing port also rejects malformed URLs before persisting them.
        port = parsed.port
    except ValueError as exc:
        return None, str(exc)
    allowed = {"api.deepseek.com"} | {
        host.strip().lower() for host in os.environ.get("EDUAGENT_DEEPSEEK_ALLOW_HOSTS", "").split(",")
        if host.strip()
    }
    if parsed.hostname not in allowed:
        return None, "DeepSeek host must be api.deepseek.com or listed in EDUAGENT_DEEPSEEK_ALLOW_HOSTS"
    if parsed.hostname == "api.deepseek.com" and port not in {None, 443}:
        return None, "The official DeepSeek endpoint must use port 443"
    return normalized, None


@router.post("/settings", dependencies=[Depends(require_auth)])
async def save_settings(req: SaveSettingsRequest) -> Any:
    """Save settings and optionally update API key."""
    cfg = AppConfig.load()
    cfg.provider = LLMProvider(req.provider)
    cfg.anthropic_model = req.anthropic_model
    cfg.openai_model = req.openai_model
    cfg.ollama_model = req.ollama_model

    for field in (
        "deepseek_model", "deepseek_thinking", "deepseek_reasoning_effort",
        "deepseek_reasoning_tokens", "deepseek_timeout", "deepseek_vision_model",
    ):
        value = getattr(req, field)
        if value is not None:
            setattr(cfg, field, value.strip() if isinstance(value, str) else value)
    if not cfg.deepseek_model:
        return JSONResponse({"error": "DeepSeek model cannot be empty"}, status_code=400)
    if req.deepseek_base_url is not None or cfg.provider == LLMProvider.DEEPSEEK:
        deepseek_url, deepseek_error = _validate_deepseek_url(req.deepseek_base_url or cfg.deepseek_base_url)
        if deepseek_error or deepseek_url is None:
            return JSONResponse({"error": deepseek_error or "Invalid DeepSeek URL"}, status_code=400)
        cfg.deepseek_base_url = deepseek_url

    # Validate changed Ollama URLs, or an active Ollama endpoint. An unchanged
    # inactive cloud URL must not prevent configuring another provider.
    if cfg.provider == LLMProvider.OLLAMA or req.ollama_base_url != cfg.ollama_base_url:
        normalized_url, err = _validate_ollama_url(req.ollama_base_url)
        if err or normalized_url is None:
            return JSONResponse({"error": err or "Invalid URL"}, status_code=400)
        cfg.ollama_base_url = normalized_url

    cfg.include_homework = req.include_homework
    cfg.export_format = req.export_format
    cfg.save()

    if req.api_key and req.api_key.strip():
        set_api_key(req.provider.value, req.api_key.strip())

    return {"status": "saved"}


@router.get("/settings/test-connection", dependencies=[Depends(require_auth)])
async def test_connection() -> dict[str, Any]:
    """Test the current LLM connection."""
    cfg = AppConfig.load()
    if cfg.provider == LLMProvider.DEEPSEEK:
        _, error = _validate_deepseek_url(cfg.deepseek_base_url)
        if error:
            return {"connected": False, "provider": "deepseek", "model": cfg.deepseek_model, "error": error}
    result = await test_llm_connection(cfg)
    return result


@router.get("/settings/deepseek-models", dependencies=[Depends(require_auth)])
async def deepseek_models() -> Any:
    """Read the saved endpoint's real catalog without exposing credentials."""
    from clawed.deepseek import list_models

    cfg = AppConfig.load()
    _, error = _validate_deepseek_url(cfg.deepseek_base_url)
    if error:
        return JSONResponse({"error": error}, status_code=400)
    try:
        return {"models": await list_models(cfg)}
    except (OSError, RuntimeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.post("/settings/clear-content", dependencies=[Depends(require_auth)])
async def clear_content() -> dict[str, Any]:
    """Clear all generated content (danger zone)."""
    db = get_db()
    db.clear_all_generated()
    return {"status": "cleared"}


@router.post("/settings/reset", dependencies=[Depends(require_auth)])
async def reset_all() -> dict[str, Any]:
    """Full reset — clear everything and restart onboarding."""
    db = get_db()
    db.reset_all()
    return {"status": "reset"}


@router.post("/onboarding/persona-form", dependencies=[Depends(require_auth)])
async def create_persona_from_form(req: PersonaFormRequest) -> dict[str, Any]:
    """Create a persona from the quick form (no file upload needed)."""
    from clawed.models import TeacherPersona, TeachingStyle

    style_map = {
        "direct_instruction": TeachingStyle.DIRECT_INSTRUCTION,
        "socratic": TeachingStyle.SOCRATIC,
        "inquiry_based": TeachingStyle.INQUIRY_BASED,
        "project_based": TeachingStyle.PROJECT_BASED,
    }

    persona = TeacherPersona(
        name=req.name,
        teaching_style=style_map.get(req.teaching_style, TeachingStyle.DIRECT_INSTRUCTION),
        subject_area=req.subject_area,
        grade_levels=[g.strip() for g in req.grade_levels.split(",") if g.strip()],
        preferred_lesson_format=req.preferred_lesson_format or "I Do / We Do / You Do",
    )

    db = get_db()
    persona_json = persona.model_dump_json()
    teacher_id = db.upsert_teacher(persona.name, persona_json)

    return {"teacher_id": teacher_id, "persona": persona.model_dump()}


@router.post("/onboarding/step", dependencies=[Depends(require_auth)])
async def update_onboarding_step(req: OnboardingStepRequest) -> dict[str, Any]:
    """Update onboarding progress for a teacher."""
    db = get_db()
    db.upsert_onboarding(req.teacher_id, req.step)
    return {"status": "ok", "step": req.step}


@router.get("/onboarding/state", dependencies=[Depends(require_auth)])
async def get_onboarding_state() -> dict[str, Any]:
    """Get current onboarding state."""
    db = get_db()
    teacher = db.get_default_teacher()
    if not teacher:
        return {"has_persona": False, "step_completed": 0, "teacher_id": None}

    onboarding = db.get_onboarding(teacher["id"])
    persona_data = None
    if teacher.get("persona_json"):
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            persona_data = json.loads(teacher["persona_json"])

    return {
        "has_persona": persona_data is not None,
        "step_completed": onboarding["step_completed"] if onboarding else 0,
        "teacher_id": teacher["id"],
        "persona": persona_data,
    }
