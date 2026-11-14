"""PPT templates and slide previews inside the existing teaching workbench."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from clawed.api.deps import require_auth
from clawed.models import AppConfig
from clawed.ppt_limits import TEMPLATE_MAX_SLIDES, TEMPLATE_MAX_FILE_MB, template_limits
from clawed.presenton import Engine, analyze_template, database, get_template, list_templates, now, save_template, template_root, upload_template
from clawed.ppt_generation import read_state
from clawed.task_queue import TaskQueue, TaskType
from clawed.workbench import connect, visibility

router = APIRouter(prefix="/workbench/ppt", tags=["PPT"], dependencies=[Depends(require_auth)])


@router.get("/status")
async def engine_status():
    try:
        async with Engine() as engine:
            data = await engine.json("GET", "/api/v1/clawed/status", timeout=8)
        return {"ready": True, "message": "课件引擎已连接", **data}
    except ValueError as exc:
        return {"ready": False, "message": str(exc)}


@router.get("/templates")
async def templates(trash: bool = False):
    return list_templates(trash)


@router.get("/limits")
async def limits():
    return template_limits()


@router.post("/templates")
async def upload(file: UploadFile = File(...)):
    try:
        if not (file.filename or "").lower().endswith(".pptx"):
            raise ValueError("模板请使用 PPTX 格式，旧版 PPT 请先在 PowerPoint 中另存为 PPTX。")
        data = await file.read(TEMPLATE_MAX_FILE_MB * 1024 * 1024 + 1)
        return await asyncio.to_thread(upload_template, data, file.filename)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        await file.close()


@router.get("/templates/{tid}")
async def detail(tid: str):
    item = get_template(tid)
    if not item:
        raise HTTPException(404, "模板不存在。")
    return item


@router.post("/templates/{tid}/analyze")
async def analyze(tid: str, background: BackgroundTasks):
    item = get_template(tid)
    if not item or item["deleted"]:
        raise HTTPException(404, "模板不存在。")
    with connect() as conn:
        changed = conn.execute("UPDATE ppt_templates SET status='analyzing',error='',updated_at=? WHERE id=? AND status!='analyzing' AND deleted=0", (now(), tid)).rowcount
    if not changed:
        raise HTTPException(409, "模板正在提取，请等待完成。")
    async def perform():
        try:
            await analyze_template(tid)
        except (Exception, asyncio.CancelledError) as exc:
            message = str(exc)[:500] or "提取中断，已保留进度，可重新提取。"
            with connect() as conn:
                conn.execute("UPDATE ppt_templates SET status='review',error=?,updated_at=? WHERE id=?", (message, now(), tid))
            if isinstance(exc, asyncio.CancelledError):
                raise
    background.add_task(perform)
    return {"status": "analyzing"}


class SaveRequest(BaseModel):
    version: int
    name: str = Field(min_length=1, max_length=160)
    selected: list[str] = Field(min_length=1, max_length=TEMPLATE_MAX_SLIDES)
    instruction: str = Field(default="", max_length=5000)


@router.put("/templates/{tid}")
async def save(tid: str, body: SaveRequest):
    try:
        return await save_template(tid, body.version, body.selected, body.instruction, body.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class VisibilityRequest(BaseModel):
    deleted: bool


@router.post("/templates/{tid}/visibility")
async def manage(tid: str, body: VisibilityRequest):
    database()
    with connect() as conn:
        changed = conn.execute("UPDATE ppt_templates SET deleted=?,updated_at=? WHERE id=? AND status!='analyzing'", (int(body.deleted), now(), tid)).rowcount
    if not changed:
        raise HTTPException(409, "模板正在提取或不存在，请完成后再删除或恢复。")
    return {"status": "deleted" if body.deleted else "restored"}


@router.get("/templates/{tid}/source")
async def original(tid: str):
    item = get_template(tid)
    if not item:
        raise HTTPException(404, "模板不存在。")
    return FileResponse(template_root(tid) / "source.pptx", filename=item["spec"]["source_name"])


@router.get("/templates/{tid}/preview/{index}")
async def template_preview(tid: str, index: int):
    item = get_template(tid)
    urls = ((item or {}).get("spec", {}).get("upload") or {}).get("slide_image_urls", [])
    if not 0 <= index < len(urls):
        raise HTTPException(404, "页面预览尚未生成。")
    target = template_root(tid) / f"preview-{index}.png"
    if not target.is_file():
        async with Engine() as engine:
            target.write_bytes((await engine.request("GET", urls[index])).content)
    return FileResponse(target, media_type="image/png")


def job_state(task_id: str):
    queue = TaskQueue()
    try:
        task = queue.get_status(task_id)
    finally:
        queue.close()
    if not task or visibility().get(task_id, {}).get("results_deleted"):
        raise HTTPException(404, "课件不存在或已移至回收站。")
    output = Path(AppConfig.load().output_dir).expanduser().resolve() / task_id
    return task, output, read_state(output)


@router.get("/jobs/{task_id}")
async def deck(task_id: str):
    task, output, state = job_state(task_id)
    if not state:
        return {"available": False, "legacy": True, "message": "此任务使用旧版课件导出，可重新导出以使用新版预览和编辑。"}
    slides = sorted(state.get("deck", {}).get("slides", []), key=lambda s: s["index"])
    plans = state.get("plan", {}).get("slides", [])
    chapter_titles = {}
    if (output / "plan.json").is_file():
        chapter_titles = {c["id"]: c["title"] for c in json.loads((output / "plan.json").read_text(encoding="utf-8")).get("chapters", [])}
    return {"available": bool(slides) and state.get("phase") in {"complete", "review"}, "phase": state.get("phase"), "total": state.get("total", len(plans)),
            "completed": state.get("completed", 0), "template_name": state.get("template_name", "课堂清晰版"),
            "slides": [{"index": s["index"], "chapter_id": plans[i].get("chapter_id", "") if i < len(plans) else "",
                        "chapter_title": chapter_titles.get(plans[i].get("chapter_id", ""), "") if i < len(plans) else "",
                        "title": ((s.get("content", {}).get("page") or {}).get("title")
                        or (plans[i].get("title") if i < len(plans) else f"第 {i+1} 页")),
                        "notes": s.get("speaker_note", ""), "content": s.get("content", {})} for i, s in enumerate(slides)]}


@router.get("/jobs/{task_id}/preview/{index}")
async def slide_preview(task_id: str, index: int):
    task, output, state = job_state(task_id)
    slides = state.get("deck", {}).get("slides", [])
    if not state.get("presentation_id") or not any(s["index"] == index for s in slides):
        raise HTTPException(404, "课件页面尚未生成。")
    slide = next(s for s in slides if s["index"] == index)
    stamp = hashlib.sha256(json.dumps(slide, sort_keys=True).encode()).hexdigest()[:12]
    target = output / f"ppt-preview-{index}-{stamp}.png"
    if not target.is_file():
        async with Engine() as engine:
            response = await engine.request("GET", f"/api/v1/clawed/presentations/{state['presentation_id']}/preview/{index}")
            target.write_bytes(response.content)
    return FileResponse(target, media_type="image/png")


class EditRequest(BaseModel):
    index: int = Field(ge=0, le=59)
    prompt: str = Field(min_length=1, max_length=3000)


@router.post("/jobs/{task_id}/edit")
async def edit(task_id: str, body: EditRequest):
    task, output, state = job_state(task_id)
    if task.status.value in {"queued", "running", "cancel_requested"}:
        raise HTTPException(409, "请等待当前任务结束后修改。")
    if not state.get("deck") or body.index >= len(state["deck"].get("slides", [])):
        raise HTTPException(400, "请选择已生成的课件页面。")
    queue = TaskQueue()
    try:
        payload = {**task.payload, "outputs": ["slides"], "reuse_task_id": task_id,
                   "ppt_edit": {"source_task_id": task_id, **body.model_dump()}}
        return {"id": queue.submit(TaskType.LESSON_BUNDLE, payload), "status": "queued"}
    finally:
        queue.close()
