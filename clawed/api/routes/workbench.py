"""Authenticated APIs supporting the Chinese React workbench."""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from clawed.api.deps import authentication_required, get_api_token, limiter, require_auth
from clawed.config import get_api_key, mask_api_key, set_api_key, test_llm_connection
from clawed.models import AppConfig, LLMProvider
from clawed.task_queue import TaskQueue
from clawed.workbench import connect, events, material_get, material_list, source_path, workspace, visibility, set_visibility

router = APIRouter(prefix="/workbench", tags=["workbench"])
auth = [Depends(require_auth)]


class LoginRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)


@router.post("/session")
@limiter.limit("10/minute")
async def login(request: Request, body: LoginRequest) -> JSONResponse:
    if not authentication_required():
        return JSONResponse({"status": "ok", "auth_required": False})
    if not secrets.compare_digest(body.token.strip().encode(), get_api_token().encode()):
        raise HTTPException(401, "访问令牌不正确，请检查后重试。")
    response = JSONResponse({"status": "ok"})
    response.set_cookie("clawed_token", get_api_token(), httponly=True, samesite="strict",
                        secure=request.url.scheme == "https", max_age=86400)
    return response


@router.delete("/session", dependencies=auth)
async def logout() -> JSONResponse:
    response = JSONResponse({"status": "ok"})
    response.delete_cookie("clawed_token")
    return response


@router.get("/overview", dependencies=auth)
async def overview() -> dict[str, Any]:
    cfg = AppConfig.load()
    queue = TaskQueue()
    try:
        hidden = visibility()
        all_jobs = queue.list_tasks(limit=-1)
        jobs = [item for item in all_jobs if not hidden.get(item.id, {}).get("record_deleted")]
    finally:
        queue.close()
    with connect() as conn:
        workers = conn.execute("SELECT count(*) FROM workers WHERE heartbeat>?", (time.time() - 30,)).fetchone()[0]
    return {
        "auth_required": authentication_required(),
        "provider": cfg.provider.value, "model": getattr(cfg, f"{cfg.provider.value}_model"),
        "has_key": bool(get_api_key(cfg.provider.value)) or cfg.provider == LLMProvider.OLLAMA,
        "worker_online": bool(workers), "materials": len(material_list()),
        "jobs": len(jobs), "completed": sum(item.status.value == "done" for item in jobs),
        "active": sum(item.status.value in {"queued", "running", "cancel_requested"} for item in jobs),
        "files": sum(len((item.result or {}).get("files", [])) for item in all_jobs
                     if not hidden.get(item.id, {}).get("results_deleted")),
        "teacher_name": cfg.teacher_profile.name or "老师",
    }


@router.get("/materials", dependencies=auth)
async def materials(trash: bool = False) -> list[dict[str, Any]]:
    return material_list(trash=trash)


class MaterialVisibilityRequest(BaseModel):
    deleted: bool


@router.post('/materials/{material_id}/visibility', dependencies=auth)
async def material_visibility(material_id: str, body: MaterialVisibilityRequest):
    if not material_get(material_id): raise HTTPException(404,'资料不存在。')
    with connect() as conn:
        conn.execute('INSERT INTO material_visibility(material_id,deleted) VALUES(?,?) '
            'ON CONFLICT(material_id) DO UPDATE SET deleted=excluded.deleted',(material_id,int(body.deleted)))
    return {'status':'deleted' if body.deleted else 'restored'}


@router.post("/materials", dependencies=auth)
@limiter.limit("10/minute")
async def upload(request: Request, files: list[UploadFile] = File(...)) -> dict[str, Any]:
    from clawed.ingestor import ingest_path

    if not 1 <= len(files) <= 20:
        raise HTTPException(400, "每次可上传 1–20 份资料。")
    supported = {"pdf", "docx", "pptx", "txt", "md"}
    results = []
    for upload_file in files:
        name = (upload_file.filename or "未命名资料").replace("\\", "/").rsplit("/", 1)[-1][:200]
        kind = Path(name).suffix.lower().lstrip(".")
        if kind not in supported:
            raise HTTPException(400, f"不支持 {name}，请上传 PDF、DOCX、PPTX、TXT 或 Markdown。")
        item_id = uuid.uuid4().hex
        root = workspace() / "materials" / item_id
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"source.{kind}"
        size = 0
        try:
            with path.open("wb") as target:
                while chunk := await upload_file.read(1024 * 1024):
                    size += len(chunk)
                    if size > 50 * 1024 * 1024:
                        raise HTTPException(413, f"{name} 超过 50 MB，请拆分资料。")
                    target.write(chunk)
            with connect() as conn:
                conn.execute("INSERT INTO materials VALUES(?,?,?,?,?,?,?,?)", (
                    item_id, name, kind, size, "", "processing", "", datetime.now(UTC).isoformat(),
                ))
            try:
                documents = await asyncio.to_thread(ingest_path, path)
                text = "\n\n".join(document.content for document in documents).strip()
                if not text:
                    raise ValueError("未提取到文字；扫描 PDF 请先使用 OCR 转为可检索文本。")
                with connect() as conn:
                    conn.execute("UPDATE materials SET text=?,status='ready' WHERE id=?", (text, item_id))
            except Exception as exc:
                message = str(exc) if isinstance(exc, ValueError) else "解析失败，请检查文件格式或重新导出文件。"
                with connect() as conn:
                    conn.execute("UPDATE materials SET status='failed',error=? WHERE id=?", (message, item_id))
            result = material_get(item_id)
            if result:
                results.append({key: value for key, value in result.items() if key != "text"})
        except HTTPException:
            path.unlink(missing_ok=True)
            raise
        finally:
            await upload_file.close()
    return {"materials": results}


@router.get("/materials/{material_id}", dependencies=auth)
async def material_detail(material_id: str) -> dict[str, Any]:
    item = material_get(material_id)
    if not item:
        raise HTTPException(404, "资料不存在。")
    return {**item, "text": item["text"][:16000], "characters": len(item["text"])}


@router.get("/materials/{material_id}/file", dependencies=auth)
async def material_download(material_id: str) -> FileResponse:
    item = material_get(material_id)
    if not item or not source_path(item).is_file():
        raise HTTPException(404, "原始文件不存在。")
    return FileResponse(source_path(item), filename=item["name"])


@router.get("/jobs/{task_id}", dependencies=auth)
async def job_detail(task_id: str) -> dict[str, Any]:
    queue = TaskQueue()
    try:
        task = queue.get_status(task_id)
        if not task:
            raise HTTPException(404, "任务不存在。")
        result = {**task.model_dump(), "steps": queue.steps(task_id), "events": events(task_id)}
        result["visibility"] = visibility().get(task_id, {})
        root = Path(AppConfig.load().output_dir).expanduser().resolve() / task_id
        master = root / "master.json"
        result["content"] = json.loads(master.read_text(encoding="utf-8")) if master.is_file() else None
        template_file = root / "template_content.json"
        if template_file.is_file():
            documents = json.loads(template_file.read_text(encoding="utf-8")).get("documents", {})
            for doc in documents.values():
                for field in doc.get('template',{}).get('spec',{}).get('fields',[]):
                    if field.get('kind')=='rows' and field.get('label') in doc['display']:
                        labels={column['key']:column['label'] for column in field.get('columns',[])}
                        value=doc['display'][field['label']]
                        if isinstance(value,list):
                            doc['display'][field['label']]=[{labels.get(k,k):v for k,v in row.items()} if isinstance(row,dict) else row for row in value]
            contents = {"教师教案" if role == "teacher" else "学生讲义": doc["display"] for role, doc in documents.items()}
            result["content"] = {"模板教学方案": contents, **({"默认产物教学方案": result["content"]} if result["content"] else {})}
        result["materials"] = [
            {"id": item["id"], "name": item["name"]}
            for mid in task.payload.get("material_ids", []) if (item := material_get(mid)) is not None
        ]
        return result
    finally:
        queue.close()


@router.get("/results", dependencies=auth)
async def results(trash: bool = False) -> list[dict[str, Any]]:
    queue = TaskQueue()
    try:
        states = visibility()
        items = []
        for task in queue.list_tasks(limit=-1):
            state = states.get(task.id, {})
            if trash:
                include = state.get("record_deleted") or state.get("results_deleted")
            else:
                include = (task.result or {}).get("files") and not state.get("results_deleted")
            if include:
                items.append({**task.model_dump(), "visibility": state})
        return items
    finally:
        queue.close()


class ManageRequest(BaseModel):
    target: str = Field(pattern="^(record|results|both)$")
    restore: bool = False


@router.post("/jobs/{task_id}/manage", dependencies=auth)
async def manage_job(task_id: str, body: ManageRequest) -> dict[str, str]:
    queue = TaskQueue()
    try:
        task = queue.get_status(task_id)
        if not task:
            raise HTTPException(404, "任务不存在。")
        if not body.restore and task.status.value in {"queued", "running", "cancel_requested"}:
            raise HTTPException(409, "请先取消任务，等待任务停止后再删除。")
        set_visibility(task_id,
            record=(not body.restore) if body.target in {"record", "both"} else None,
            results=(not body.restore) if body.target in {"results", "both"} else None)
        return {"status": "restored" if body.restore else "deleted"}
    finally:
        queue.close()


class ReexportRequest(BaseModel):
    teacher_template_id: str | None = Field(default=None, max_length=32)
    student_template_id: str | None = Field(default=None, max_length=32)


@router.post("/jobs/{task_id}/reexport", dependencies=auth)
async def reexport_job(task_id: str, body: ReexportRequest | None = None) -> dict[str, str]:
    from clawed.task_queue import TaskType
    queue = TaskQueue()
    try:
        task = queue.get_status(task_id)
        if not task or not task.payload.get("workbench"):
            raise HTTPException(400, "此任务没有工作台教学方案，无法重新导出。")
        if task.status.value in {"queued", "running", "cancel_requested"}:
            raise HTTPException(409, "请等待任务结束后重新导出。")
        path = Path(AppConfig.load().output_dir).expanduser().resolve() / task.id / "master.json"
        if not path.is_file() and not path.with_name("template_content.json").is_file():
            raise HTTPException(404, "教学方案不存在，请重新生成。")
        payload = {**task.payload, "reuse_task_id": task.id}
        if body:
            from clawed.word_templates import freeze_template
            snapshots = dict(payload.get("word_templates", {}))
            for role in ("teacher", "student"):
                tid = getattr(body, role + "_template_id")
                if tid is not None and role in payload["outputs"]:
                    payload[role + "_template_id"] = tid
                    try:
                        if tid:
                            snapshots[role] = freeze_template(tid, role)
                        else:
                            snapshots.pop(role, None)
                    except ValueError as exc:
                        raise HTTPException(400, str(exc)) from exc
            payload["word_templates"] = snapshots
        return {"id": queue.submit(TaskType.LESSON_BUNDLE, payload), "status": "queued"}
    finally:
        queue.close()


@router.get("/settings", dependencies=auth)
async def settings() -> dict[str, Any]:
    cfg = AppConfig.load()
    key = get_api_key(cfg.provider.value)
    return {
        "provider": cfg.provider.value, "model": getattr(cfg, f"{cfg.provider.value}_model"),
        "models": {provider.value: getattr(cfg, f"{provider.value}_model") for provider in LLMProvider},
        "has_key": bool(key), "key_masked": mask_api_key(key),
        "provider_keys": {provider.value: mask_api_key(get_api_key(provider.value)) for provider in LLMProvider},
        "deepseek_base_url": cfg.deepseek_base_url, "deepseek_thinking": cfg.deepseek_thinking,
        "deepseek_reasoning_effort": cfg.deepseek_reasoning_effort,
        "deepseek_reasoning_tokens": cfg.deepseek_reasoning_tokens, "deepseek_timeout": cfg.deepseek_timeout,
        "deepseek_vision_model": cfg.deepseek_vision_model, "teacher_name": cfg.teacher_profile.name,
    }


class SettingsRequest(BaseModel):
    provider: LLMProvider
    model: str = Field(min_length=1, max_length=200)
    api_key: str = Field(default="", max_length=1024)
    teacher_name: str = Field(default="", max_length=100)
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_thinking: bool = False
    deepseek_reasoning_effort: str = "high"
    deepseek_reasoning_tokens: int = Field(default=8192, ge=0, le=131072)
    deepseek_timeout: float = Field(default=300, ge=10, le=1800)
    deepseek_vision_model: str = Field(default="", max_length=200)


@router.put("/settings", dependencies=auth)
async def save_settings(body: SettingsRequest) -> dict[str, str]:
    from pydantic import ValidationError

    from clawed.api.routes.settings import _validate_deepseek_url

    cfg = AppConfig.load()
    updates: dict[str, Any] = {"provider": body.provider, f"{body.provider.value}_model": body.model.strip()}
    if not body.model.strip():
        raise HTTPException(400, "模型名称不能为空。")
    if body.provider == LLMProvider.DEEPSEEK:
        normalized, error = _validate_deepseek_url(body.deepseek_base_url)
        if error:
            raise HTTPException(400, error)
        updates.update({key: value for key, value in body.model_dump().items() if key.startswith("deepseek_")})
        updates["deepseek_base_url"] = normalized
    try:
        cfg = AppConfig.model_validate({**cfg.model_dump(), **updates})
    except ValidationError as exc:
        raise HTTPException(400, "模型设置格式不正确，请检查推理强度、超时和地址。") from exc
    cfg.teacher_profile.name = body.teacher_name.strip()
    if body.api_key.strip():
        set_api_key(body.provider.value, body.api_key.strip())
    cfg.save()
    return {"status": "saved"}


@router.post("/connection", dependencies=auth)
async def connection() -> dict[str, Any]:
    cfg = AppConfig.load()
    if cfg.provider == LLMProvider.DEEPSEEK:
        from clawed.api.routes.settings import _validate_deepseek_url
        _, error = _validate_deepseek_url(cfg.deepseek_base_url)
        if error:
            raise HTTPException(400, error)
    if cfg.provider in {LLMProvider.GOOGLE, LLMProvider.OPENROUTER}:
        from clawed.llm import LLMClient
        model = getattr(cfg, f"{cfg.provider.value}_model")
        if not get_api_key(cfg.provider.value):
            return {"connected": False, "model": model, "error": "请先配置 API Key。"}
        try:
            text = await LLMClient(cfg).generate("Reply only OK.", max_tokens=64)
            return {"connected": bool(text.strip()), "model": model, "error": "模型未返回有效内容。"}
        except Exception as exc:
            return {"connected": False, "model": model, "error": str(exc)}
    return await test_llm_connection(cfg)
