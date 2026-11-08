"""Authenticated job ledger shared by the dashboard and CLI worker."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from clawed.api.deps import require_auth
from clawed.models import AppConfig
from clawed.task_queue import TaskQueue, TaskType

router = APIRouter(tags=["jobs"], dependencies=[Depends(require_auth)])


class BundleJobRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    subject: str = Field(min_length=1, max_length=100)
    grade: str = Field(min_length=1, max_length=20)
    course_id: str = Field(default="", max_length=100)
    unit_id: str = Field(default="", max_length=100)
    lesson_id: str = Field(default="", max_length=100)
    workbench: bool = False
    content: str = Field(default="", max_length=50000)
    requirements: str = Field(default="", max_length=6000)
    duration_minutes: int = Field(default=45, ge=15, le=240)
    material_ids: list[str] = Field(default_factory=list, max_length=20)
    outputs: list[Literal["teacher", "student", "slides"]] = Field(default_factory=lambda: ["teacher", "student", "slides"])
    include_images: bool = False
    include_homework: bool = True


@router.get("/jobs")
async def list_jobs() -> list[dict[str, Any]]:
    from clawed.workbench import visibility
    queue = TaskQueue()
    try:
        hidden = visibility()
        return [{**task.model_dump(), "steps": queue.steps(task.id)} for task in queue.list_tasks(limit=-1)
                if not hidden.get(task.id, {}).get("record_deleted")]
    finally:
        queue.close()


@router.post("/jobs")
async def submit_job(req: BundleJobRequest) -> dict[str, str]:
    if req.workbench:
        from clawed.config import get_api_key
        from clawed.workbench import material_get

        cfg = AppConfig.load()
        if cfg.provider.value != "ollama" and not get_api_key(cfg.provider.value):
            raise HTTPException(400, "请先在模型设置中配置所选供应商的 API Key。")
        if not req.outputs:
            raise HTTPException(400, "请至少选择一种输出文件。")
        for material_id in req.material_ids:
            item = material_get(material_id)
            if not item or item["status"] != "ready":
                raise HTTPException(400, "所选资料尚未解析完成或不存在。")
        req.outputs = list(dict.fromkeys(req.outputs))
    queue = TaskQueue()
    try:
        return {"id": queue.submit(TaskType.LESSON_BUNDLE, req.model_dump()), "status": "queued"}
    finally:
        queue.close()


@router.post("/jobs/recover")
async def recover_jobs() -> dict[str, int]:
    queue = TaskQueue()
    try:
        return {"recovered": queue.recover_interrupted()}
    finally:
        queue.close()


@router.get("/jobs/{task_id}/files/{index}")
async def download_artifact(task_id: str, index: int) -> FileResponse:
    from clawed.workbench import visibility
    if visibility().get(task_id, {}).get("results_deleted"):
        raise HTTPException(404, "成果已移至回收站，请先恢复。")
    queue = TaskQueue()
    try:
        task = queue.get_status(task_id)
        files = (task.result or {}).get("files", []) if task else []
        if index < 0 or index >= len(files):
            raise HTTPException(404, "Artifact not found")
        path = Path(files[index]).resolve()
        root = Path(AppConfig.load().output_dir).expanduser().resolve() / task_id
        if not path.is_relative_to(root) or not path.is_file():
            raise HTTPException(404, "Artifact is unavailable")
        return FileResponse(path, filename=path.name)
    finally:
        queue.close()


@router.post("/jobs/{task_id}/{action}")
async def control_job(task_id: str, action: str) -> dict[str, str]:
    from clawed.workbench import visibility
    queue = TaskQueue()
    try:
        if action not in ("cancel", "resume"):
            raise HTTPException(404, "Unknown job action")
        if action == "resume" and visibility().get(task_id, {}).get("record_deleted"):
            raise HTTPException(409, "请先从回收站恢复任务记录。")
        changed = queue.cancel(task_id) if action == "cancel" else queue.resume(task_id)
        if not changed:
            raise HTTPException(409, "Job is missing or cannot transition from its current status")
        return {"id": task_id, "action": action}
    finally:
        queue.close()
