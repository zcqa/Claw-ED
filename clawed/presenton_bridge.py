"""Private engine-side bridge for previews, immutable templates and cancellation.

Loaded inside the pinned Presenton container; generation remains upstream code.
"""
from __future__ import annotations

import asyncio
import copy
from contextlib import asynccontextmanager
from datetime import datetime
import hashlib
import json
from pathlib import Path
import uuid
import zipfile
import re

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from api.v1.ppt.endpoints import presentation as upstream
from enums.async_task_status import AsyncTaskStatus
from models.sql.async_task import AsyncTaskModel
from models.sql.presentation import PresentationModel
from models.sql.slide import SlideModel
from models.sql.template_v2 import TemplateV2
from models.generate_presentation_request import GeneratePresentationRequest
from services.database import get_async_session
from services.export_task_service import EXPORT_TASK_SERVICE
import clawed_ppt_limits
from clawed_ppt_limits import TEMPLATE_MAX_SLIDES, template_limits

router = APIRouter(prefix="/api/v1/clawed", tags=["Claw-ED private bridge"])
_running: dict[str, asyncio.Task] = {}
_preview_lock = asyncio.Lock()


@router.get("/status")
async def status(session: AsyncSession = Depends(get_async_session)):
    pending = (await session.execute(select(AsyncTaskModel).where(
        AsyncTaskModel.status == AsyncTaskStatus.PENDING))).scalars().all()
    return {"version": 1, "active": max(len(_running), len(pending)),
            "template_limits": template_limits(),
            "limits_sha256": hashlib.sha256(Path(clawed_ppt_limits.__file__).read_bytes()).hexdigest(),
            "bridge_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


@router.post("/generate/{operation_id}")
async def generate(operation_id: str, background: BackgroundTasks, body: GeneratePresentationRequest,
                   session: AsyncSession = Depends(get_async_session)):
    if not operation_id.startswith("clawed-") or len(operation_id) != 71:
        raise HTTPException(400, "Invalid operation identifier")
    row = await session.get(AsyncTaskModel, operation_id)
    if row:
        return row
    (pid,) = await upstream.check_if_api_request_is_valid(body, session)
    row = AsyncTaskModel(id=operation_id, type="presentation.generate", status=AsyncTaskStatus.PENDING,
                         message="Queued by Claw-ED", data={"presentation_id": str(pid), "created_slides": 0,
                         "remaining_slides": len(body.slides_markdown or [])})
    session.add(row)
    await session.commit()
    background.add_task(upstream._run_generate_presentation_task, body, pid, operation_id, None, None)
    return row


@router.post("/default-template")
async def default_template(layouts: dict = Body(...), session: AsyncSession = Depends(get_async_session)):
    from templates.v2.models.layouts import SlideLayouts
    validated = SlideLayouts.model_validate(layouts).model_dump(mode="json", exclude_none=True)
    # Content-addressed revisions keep queued and historical tasks immutable.
    digest = hashlib.sha256(json.dumps(validated, sort_keys=True).encode()).hexdigest()[:16]
    key = "clawed-classroom-" + digest
    item = await session.get(TemplateV2, key)
    if not item:
        item = TemplateV2(id=key, name="课堂清晰版", description="中文课堂投影版式",
                         layouts=validated, raw_layouts={"layouts": []},
                         merged_components={"components": []}, assets={"fonts": {}}, is_default=False)
        session.add(item)
        await session.commit()
    return {"id": key}


@router.post("/templates/{template_id}/snapshot")
async def snapshot(template_id: str, session: AsyncSession = Depends(get_async_session)):
    item = await session.get(TemplateV2, template_id)
    if not item:
        raise HTTPException(404, "Template not found")
    fields = {name: copy.deepcopy(getattr(item, name)) for name in
              ("name", "description", "raw_layouts", "layouts", "merged_components", "theme", "assets")}
    clone = TemplateV2(id=str(uuid.uuid4()), **fields, is_default=False)
    session.add(clone)
    await session.commit()
    return {"id": clone.id}


@router.post("/tasks/{task_id}/cancel")
async def cancel(task_id: str, session: AsyncSession = Depends(get_async_session)):
    row = await session.get(AsyncTaskModel, task_id)
    if not row:
        raise HTTPException(404, "Task not found")
    pid = str((row.data or {}).get("presentation_id", ""))
    task = _running.get(pid)
    if task and not task.done():
        task.cancel()
    if row.status == AsyncTaskStatus.PENDING:
        row.status = AsyncTaskStatus.ERROR
        row.message = "已取消，可从工作台恢复"
        row.error = {"status_code": 409, "detail": "Cancelled by workbench"}
        row.updated_at = datetime.now()
        session.add(row)
        await session.commit()
    return {"cancelled": bool(task), "status": row.status}


@router.post("/slides/{slide_id}/edit")
async def edit_content(slide_id: uuid.UUID, prompt: str = Body(..., embed=True),
                       session: AsyncSession = Depends(get_async_session)):
    from utils.llm_calls.edit_slide import get_edited_slide_content
    from utils.schema_utils import get_schema_validation_errors

    slide = await session.get(SlideModel, slide_id)
    presentation = await session.get(PresentationModel, slide.presentation) if slide else None
    if not presentation:
        raise HTTPException(404, "Slide not found")
    layouts = upstream._get_presentation_stream_layout(presentation)
    layout = layouts.slides[layouts.get_slide_layout_index(slide.layout)]
    content = await get_edited_slide_content(
        prompt, slide, "简体中文", layout, presentation.tone, presentation.verbosity,
        "保持本页结构与全部版式，只修改用户要求的内容和备注。严格遵守字段容量。"
        "所有正文使用纯文本和 Unicode 数学符号，不使用 Markdown、HTML 或 LaTeX 标记；"
        "使用单个换行，禁止空白段落。教师备注用中文。保持已有图片地址，不新增图片。")
    errors = get_schema_validation_errors(layout.json_schema,
        {k: v for k, v in content.items() if k != "__speaker_note__"}, strict=False)
    if errors:
        raise HTTPException(400, "修改内容超出原页面容量，请缩小修改范围或精简内容后重试。")
    # Rehydrate from the original template; never retain accumulated rich-text
    # styling from an earlier edit, or let the model change geometry/font size.
    slide.content = content
    slide.ui = upstream._template_slide_ui(presentation.layout, slide.layout)
    upstream._hydrate_template_slide_ui(slide, presentation.layout)
    slide.speaker_note = content.get("__speaker_note__", "")
    slide.id = uuid.uuid4()
    session.add(slide)
    await session.commit()
    return slide


def compact_paragraphs(value):
    if isinstance(value, str):
        return re.sub(r"\n[ \t]*\n+", "\n", value)
    if isinstance(value, dict):
        result = {key: compact_paragraphs(item) for key, item in value.items()}
        equation = result.get("equation")
        if isinstance(equation, str) and re.search(r"\\[a-zA-Z]+", equation) and "<latex>" not in equation:
            result["equation"] = "<latex>" + equation + "</latex>"
        return result
    if isinstance(value, list):
        return [compact_paragraphs(item) for item in value]
    return value


@router.post("/presentations/{presentation_id}/prepare-export")
async def prepare_export(presentation_id: uuid.UUID,
                         session: AsyncSession = Depends(get_async_session)):
    presentation = await session.get(PresentationModel, presentation_id)
    if not presentation:
        raise HTTPException(404, "Presentation not found")
    slides = (await session.execute(select(SlideModel).where(
        SlideModel.presentation == presentation_id))).scalars().all()
    for slide in slides:
        # Empty Markdown paragraphs consume extra projected lines. Compact
        # whitespace without truncating or rewriting any teaching content.
        slide.content = compact_paragraphs(slide.content)
        slide.ui = upstream._template_slide_ui(presentation.layout, slide.layout)
        upstream._hydrate_template_slide_ui(slide, presentation.layout)
        session.add(slide)
    await session.commit()
    return {"slides": len(slides)}


@router.get("/presentations/{presentation_id}/preview/{index}")
async def preview(presentation_id: uuid.UUID, index: int,
                  session: AsyncSession = Depends(get_async_session)):
    presentation = await session.get(PresentationModel, presentation_id)
    slide = (await session.execute(select(SlideModel).where(
        SlideModel.presentation == presentation_id, SlideModel.index == index))).scalars().first()
    if not presentation or not slide:
        raise HTTPException(404, "Slide not found")
    ui = copy.deepcopy(slide.ui)
    if not ui:
        raise HTTPException(400, "Slide has no structured layout")
    ui = upstream._apply_template_content_to_ui(ui, slide.content)
    digest = hashlib.sha256(json.dumps(ui, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    folder = Path("/app_data/exports/clawed-previews") / str(presentation_id)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{index}-{digest[:16]}.png"
    async with _preview_lock:
        if not target.is_file():
            # Use the same DOM and font rendering as PPTX export, including math.
            from utils.export_utils import _build_presentation_export_url
            url, fastapi_url = _build_presentation_export_url(presentation_id)
            result = await EXPORT_TASK_SERVICE.export_from_url(url, "clawed-preview", "png", fastapi_url)
            rows = list((await session.execute(select(SlideModel).where(
                SlideModel.presentation == presentation_id).order_by(SlideModel.index))).scalars().all())
            with zipfile.ZipFile(result.path) as archive:
                names = [n for n in archive.namelist() if n.lower().endswith(".png")]
                names.sort(key=lambda n: [int(v) if v.isdigit() else v for v in re.split(r"(\d+)", n)])
                if len(names) != len(rows):
                    raise HTTPException(500, "Preview page count differs from presentation")
                for row, name in zip(rows, names):
                    row_ui = upstream._apply_template_content_to_ui(copy.deepcopy(row.ui), row.content)
                    stamp = hashlib.sha256(json.dumps(row_ui, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
                    (folder / f"{row.index}-{stamp}.png").write_bytes(archive.read(name))
    return FileResponse(target, media_type="image/png")


def install_complete_template_previews():
    from templates import fonts_and_slides_preview as previews

    def page_count(path):
        with zipfile.ZipFile(path) as archive:
            root = previews.ET.fromstring(archive.read("ppt/presentation.xml"))
            count = len(root.findall("p:sldIdLst/p:sldId", previews.PPT_NS))
        if not 1 <= count <= TEMPLATE_MAX_SLIDES:
            raise HTTPException(400, f"模板须为 1–{TEMPLATE_MAX_SLIDES} 页，实际为 {count} 页；原文件保留，不自动裁页。")
        return count

    def preserve_original(pptx_path, max_slides, temp_dir, logger):
        count = page_count(pptx_path)
        if count > max_slides:
            raise HTTPException(400, f"原文件 {count} 页超过本次预览范围 {max_slides} 页，已停止处理，不自动裁页。")
        return pptx_path

    original_render = previews.render_pptx_slides_to_images

    async def complete_preview(modified_pptx_path, font_paths_for_install, max_slides, logger,
                               font_stylesheet_urls=None, preview_fonts=None):
        expected = page_count(modified_pptx_path)
        if max_slides is not None and max_slides < expected:
            raise HTTPException(400, f"预览范围 {max_slides} 页小于原文件 {expected} 页，已停止处理，不省略页面。")
        try:
            paths = await original_render(modified_pptx_path, font_paths_for_install, max_slides, logger,
                                          font_stylesheet_urls, preview_fonts)
        except HTTPException as exc:
            if "PPTX-to-JSON returned no slides" in str(exc.detail):
                raise HTTPException(400, f"原文件有 {expected} 页，但转换器返回了 0 页；模板尚未提取，原文件已保留。") from exc
            raise
        if len(paths) != expected:
            raise HTTPException(400, f"原文件 {expected} 页，但仅生成 {len(paths)} 页预览；已停止提取，原文件保留。")
        return paths

    previews.MAX_TEMPLATE_PREVIEW_SLIDES = TEMPLATE_MAX_SLIDES
    previews._trim_pptx_to_max_slides = preserve_original
    previews.render_pptx_slides_to_images = complete_preview


def install(app):
    install_complete_template_previews()
    from utils.llm_calls import generate_slide_content as content_calls
    # This export version mishandles long mixed bold/inline-math runs. Keep
    # editable classroom prose plain, with math isolated in its own region.
    content_calls.SLIDE_CONTENT_SYSTEM_PROMPT = re.sub(
        r"# Math Expression Rules\n.*?(?=\{markdown_emphasis_rules\})",
        "# Classroom Text Rules\n"
        "- Use plain text, Unicode math symbols and single line breaks in prose.\n"
        "- Do not use Markdown emphasis, HTML, blank paragraphs or inline LaTeX in prose.\n"
        "- Only a field named equation may contain a standalone <latex> expression.\n"
        "- Preserve all numerical values, units and student question conditions.\n\n",
        content_calls.SLIDE_CONTENT_SYSTEM_PROMPT, flags=re.S,
    ).replace("{markdown_emphasis_rules}", "- Do not add bold or italic markup in content strings.")
    original = upstream.generate_presentation_handler

    async def tracked(*args, **kwargs):
        pid = str(kwargs.get("presentation_id") or args[1])
        _running[pid] = asyncio.current_task()
        try:
            return await original(*args, **kwargs)
        finally:
            _running.pop(pid, None)

    upstream.generate_presentation_handler = tracked
    app.include_router(router)

    async def recover_interrupted():
        # A container restart loses in-memory coroutines, never keep polling
        # their persisted "pending" rows as if they were still running.
        async for session in get_async_session():
            rows = (await session.execute(select(AsyncTaskModel).where(
                AsyncTaskModel.status == AsyncTaskStatus.PENDING))).scalars().all()
            for row in rows:
                row.status = AsyncTaskStatus.ERROR
                row.message = "课件服务重启，任务已中断，可恢复后继续"
                row.error = {"status_code": 409, "detail": row.message}
                row.updated_at = datetime.now()
                session.add(row)
            await session.commit()
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application) as state:
            await recover_interrupted()
            yield state

    app.router.lifespan_context = lifespan
