"""Word template library and extraction review APIs."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from clawed.api.deps import require_auth
from clawed.word_templates import (TemplateSpec, analyze_template, get_template,
    list_templates, root, save_template, structure, upload_template)
from clawed.workbench import connect

router = APIRouter(prefix="/workbench/templates", tags=["word templates"], dependencies=[Depends(require_auth)])


@router.get("")
async def listing(trash: bool = False):
    return list_templates(trash=trash)


@router.post("")
async def upload(file: UploadFile = File(...), role: Literal["teacher", "student"] = Form("teacher"),
                 mode: Literal["auto", "placeholder", "sample"] = Form("auto")):
    try:
        if not (file.filename or "").lower().endswith(".docx"):
            raise ValueError("模板请使用 DOCX 格式，旧版 DOC 请先在 Word 中另存为 DOCX。")
        data = await file.read(20 * 1024 * 1024 + 1)
        if len(data) > 20 * 1024 * 1024:
            raise ValueError("模板不能超过 20 MB。")
        return await asyncio.to_thread(upload_template, data, file.filename, role, mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, "无法读取此 Word 文件，请检查格式及文档结构。") from exc
    finally:
        await file.close()


@router.post("/from-material/{material_id}")
async def from_material(material_id: str):
    from clawed.workbench import material_get, source_path
    item = material_get(material_id)
    if not item or item.get('deleted') or item["kind"] != "docx":
        raise HTTPException(400, "请选择 DOCX 课程资料导入为模板。")
    path = source_path(item)
    if not path.is_file() or path.stat().st_size > 20 * 1024 * 1024:
        raise HTTPException(400, "原文件不存在或超过模板的 20 MB 限制。")
    try:
        return await asyncio.to_thread(upload_template, path.read_bytes(), item["name"], "teacher", "auto")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, "无法将此文件作为 Word 模板，请检查文档格式。") from exc


@router.get("/{template_id}")
async def detail(template_id: str):
    item = get_template(template_id)
    if not item:
        raise HTTPException(404, "模板不存在。")
    from clawed.document_template import document_blocks, coverage
    item["blocks"] = document_blocks(root(template_id) / "source.docx")[0]
    if item["spec"].get("engine") == "document-v2":
        item["spec"]["coverage"] = coverage(TemplateSpec.model_validate(item["spec"]),item["blocks"])
    return item


@router.post("/{template_id}/analyze")
async def analyze(template_id: str, background: BackgroundTasks):
    from datetime import UTC, datetime, timedelta
    item = get_template(template_id)
    if not item or item["deleted"]: raise HTTPException(404,"模板不存在。")
    if item["status"] == "analyzing" and datetime.fromisoformat(item["updated_at"]) > datetime.now(UTC)-timedelta(minutes=15):
        raise HTTPException(409,"文档正在理解中，请等待当前任务完成。")
    with connect() as conn:
        changed=conn.execute("UPDATE word_templates SET status='analyzing',error='',analysis_json=?,updated_at=? WHERE id=? AND updated_at=?",
            ('{"phase":"queued","message":"准备理解全文"}',datetime.now(UTC).isoformat(),template_id,item["updated_at"])).rowcount
        if not changed: raise HTTPException(409,"模板正在变化，请刷新。")
    async def perform():
        try: await analyze_template(template_id)
        except asyncio.CancelledError:
            with connect() as conn:
                conn.execute("UPDATE word_templates SET status='review',error=?,analysis_json=? WHERE id=?",
                    ("服务关闭中断了提取，请重新提取。",'{"phase":"interrupted","message":"提取已中断，可重新开始"}',template_id))
            raise
        except Exception as exc:
            with connect() as conn:
                conn.execute("UPDATE word_templates SET status='review',error=?,analysis_json=? WHERE id=?",
                    (str(exc),json.dumps({"phase":"failed","message":str(exc)},ensure_ascii=False),template_id))
    background.add_task(perform)
    return {"status":"analyzing", "id":template_id}


class SaveRequest(BaseModel):
    spec: TemplateSpec
    version: int


@router.put("/{template_id}")
async def save(template_id: str, body: SaveRequest):
    try:
        return await asyncio.to_thread(save_template, template_id, body.spec, body.version)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, f"模板保存或预览未完成，请检查填写区域与占位符：{type(exc).__name__}") from exc


class VisibilityRequest(BaseModel):
    deleted: bool


@router.post("/{template_id}/visibility")
async def visibility(template_id: str, body: VisibilityRequest):
    item = get_template(template_id)
    if not item:
        raise HTTPException(404, "模板不存在。")
    if item['status']=='analyzing': raise HTTPException(409,"请等待当前文档提取完成后移除。")
    with connect() as conn:
        from datetime import UTC, datetime
        changed=conn.execute("UPDATE word_templates SET deleted=?,updated_at=? WHERE id=? AND status!='analyzing'", (int(body.deleted),datetime.now(UTC).isoformat(),template_id)).rowcount
        if not changed: raise HTTPException(409,'模板正在提取，请完成后再删除或恢复。')
    return {"status": "deleted" if body.deleted else "restored"}


@router.get("/{template_id}/file")
async def download(template_id: str, preview: bool = False):
    item = get_template(template_id)
    if not item:
        raise HTTPException(404, "模板不存在。")
    path = root(template_id) / "source.docx"
    if preview:
        if item["status"] != "ready":
            raise HTTPException(400, "请先确认并保存模板，再下载空白模板预览。")
        path = Path(item["spec"]["file"]).with_name("preview.docx")
    return FileResponse(path, filename=item["name"] + ("_空白模板预览.docx" if preview else "_原文件.docx"))
