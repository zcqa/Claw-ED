"""Template-aware classroom slide planning and recoverable engine operations."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from clawed.presenton import Engine, engine_lock
from clawed.workbench import event


class SlidePlan(BaseModel):
    title: str = Field(min_length=1, max_length=70)
    purpose: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=2200)
    teacher_notes: str = Field(default="", max_length=3000)


class DeckPlan(BaseModel):
    slides: list[SlidePlan] = Field(min_length=3, max_length=45)


def read_state(output: Path) -> dict:
    path = output / "ppt_state.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def write_state(output: Path, state: dict):
    path = output / "ppt_state.json"
    temp = output / "ppt_state.tmp"
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def layout_brief(layouts: list[dict]) -> list[dict]:
    def fields(value):
        result = []
        if isinstance(value, dict):
            if value.get("decorative") is False and value.get("name"):
                result.append({k: value[k] for k in ("name", "max_length", "min_length", "max_items") if k in value})
            for child in value.values():
                result.extend(fields(child))
        elif isinstance(value, list):
            for child in value:
                result.extend(fields(child))
        return result
    return [{"id": v["id"], "purpose": v.get("description", ""), "fields": fields(v)} for v in layouts]


def check_export(path: Path, output: Path, state: dict, expected: int | None = None):
    from pptx import Presentation
    presentation = Presentation(path)
    if expected is not None and len(presentation.slides) != expected:
        raise ValueError("导出页数与课件计划不一致，请恢复任务重新导出。")
    bad = []
    tolerance = 45720  # 0.05 inch: ignore rounding at the slide boundary.
    for index, slide in enumerate(presentation.slides):
        if any(shape.has_text_frame and shape.text.strip() and (
            shape.left < -tolerance or shape.top < -tolerance
            or shape.left + shape.width > presentation.slide_width + tolerance
            or shape.top + shape.height > presentation.slide_height + tolerance
        ) for shape in slide.shapes):
            bad.append(str(index + 1))
    if bad:
        state["phase"] = "review"
        write_state(output, state)
        raise ValueError("第 " + "、".join(bad) + " 页文字超出画布，请在课件预览中精简对应页面后重新生成。Word 已保留。")


async def compile_slides(task: Any, master: Any, config: Any, output: Path) -> Path:
    from clawed.llm import LLMClient
    from clawed.ppt_design import classroom_layouts
    from clawed.compile_workbench import course_filename

    template = task.payload.get("ppt_template") or {}
    spec = template.get("spec", {})
    layouts = [v for v in spec.get("layouts", []) if v["id"] in spec.get("selected", [])] if template else classroom_layouts()["layouts"]
    fingerprint = hashlib.sha256(json.dumps({"master": master.model_dump(), "template": template,
        "design": layouts, "version": 2, "provider": config.provider.value,
        "model": getattr(config, config.provider.value + "_model")}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    state = read_state(output)
    if state.get("fingerprint") != fingerprint:
        state = {"fingerprint": fingerprint, "attempt": 0, "template_name": template.get("name", "课堂清晰版"),
                 "template_version": template.get("version"), "phase": "planning"}
        if task.payload.get("reuse_task_id"):
            previous = read_state(Path(config.output_dir).expanduser().resolve() / task.payload["reuse_task_id"])
            if previous.get("fingerprint") == fingerprint and previous.get("plan"):
                state["plan"] = previous["plan"]
                if previous.get("phase") == "complete":
                    state["presentation_id"] = previous.get("presentation_id")
                    state["deck"] = previous.get("deck")
        write_state(output, state)
    if not state.get("plan"):
        event(task.id, "ppt_plan", "正在结合课程内容与课件模板编排每一页")
        desired = max(8, min(28, round(master.duration_minutes / 2.5)))
        prompt = (
            "请将以下教学方案编排为能直接用于课堂投影的中文课件。先理解所选模板提供的页面功能与容量，"
            "再结合课程资料安排各页；不必逐项照搬教案栏目，也不要逐个文本框机械填充。\n"
            f"建议约 {desired} 页，可根据实际讲解、例题和活动调整。\n"
            "每页只处理一个清晰问题。所有学生必须看到的定义、公式、题目条件、活动步骤必须完整出现在页面内容中。"
            "页数是建议，不是限制；例题题目、例题解析、课堂检测必须分为不同页面。"
            "例题解析页必须给出完整代入运算与结果，不能只把例题解答放教师备注。"
            "单页正文建议120–180字、至多4段、至多1块主要公式，超过就拆页；不要用空行堆积高度。"
            "题目与解析分开展示。教师讲解、提示和参考答案放在 teacher_notes；解析页可展示完整解题过程。"
            "例题不得只列题名，计算必须给出完整的代入式和正确结果。保持与教学方案的数字、单位、结论一致。"
            "不能为填满模板编造数据、引文或多余文字。表格超过一页容量时拆分。"
            "复杂公式独立成块，避免与长段落混排；简单公式可用 Unicode 数学符号。"
            "content 用普通 Markdown 编排学生可见内容，teacher_notes 单独填写。中文默认简体，专业符号、单位和必要代码保留。\n"
            "不要出现 I Do、We Do、You Do、REMEMBER 等英文教学指令。不要引用不存在的‘下方公式’、教材题号或任务卡。\n"
            f"用户教学要求：{task.payload.get('requirements', '')}\n"
            f"课后作业：{'按教学方案安排' if task.payload.get('include_homework') else '不安排，不生成作业页或作业要求'}。\n"
            f"模板组织要求：{spec.get('instruction', '')}\n"
            f"模板实际页面及容量：{json.dumps(layout_brief(layouts), ensure_ascii=False)}\n"
            f"课程教学方案：{master.model_dump_json()}\n"
            "严格返回符合下列 JSON Schema 的对象，根字段必须为 slides，不返回完成说明或摘要。\n"
            f"{json.dumps(DeckPlan.model_json_schema(), ensure_ascii=False)}"
        )
        plan = await LLMClient(config).safe_generate_json(prompt, DeckPlan, max_retries=1, max_tokens=22000,
            system="你是严谨的中文课程设计教师。输出符合给定结构的课件计划，保持课程事实与题目条件，按实际模板组织内容。")
        state["plan"] = plan.model_dump()
        state["phase"] = "generating"
        write_state(output, state)
    plan = DeckPlan.model_validate(state["plan"])
    async with engine_lock, Engine() as engine:
        await engine.configure(config)
        template_id = spec.get("engine_id") if template else await engine.default_template()
        # An interrupted export can be retried without another model call.
        pid = state.get("presentation_id")
        deck = None
        if pid:
            try:
                deck = await engine.json("GET", "/api/v1/ppt/presentation/" + pid)
            except ValueError:
                deck = None
        if deck and len(deck.get("slides", [])) == len(plan.slides):
            state["deck"] = deck
        else:
            if state.pop("failed", False) or state.pop("cancelled", False):
                state.pop("engine_task_id", None)
                state["attempt"] += 1
            if not state.get("engine_task_id"):
                operation = "clawed-" + hashlib.sha256(f"{task.id}:{fingerprint}:{state['attempt']}".encode()).hexdigest()
                state["engine_task_id"] = operation
                state["phase"] = "submitting"
                write_state(output, state)
            operation = state["engine_task_id"]
            markdown = [f"# {s.title}\n\n{s.content}\n\n【仅教师备注，不显示在学生页面】\n{s.teacher_notes}" for s in plan.slides]
            try:
                submitted = await engine.json("POST", "/api/v1/clawed/generate/" + operation, json={
                    "content": task.payload["topic"], "slides_markdown": markdown, "template": template_id,
                    "language": "简体中文", "tone": "educational", "include_title_slide": False,
                    "include_table_of_contents": False, "web_search": False, "export_as": "pptx",
                    "instructions": "面向课堂投影，中文大字号。完整保留数字、单位、公式和题目条件；禁止目录、虚构页码、虚构图表和省略号截断。"
                    "仅教师备注放入 __speaker_note__，不得出现在学生页面。复杂公式独立占区，正文不混排多个数学表达式。"
                    "不要增加计划之外的题目、作业或结论，不引用本页没有的公式或图。用中文替换英文教学指令。"
                    + ("允许按计划安排课后作业。" if task.payload.get("include_homework") else "不安排课后作业，不生成作业栏目或作业要求。")
                    + "用户要求：" + task.payload.get("requirements", "") + "模板要求：" + spec.get("instruction", "")})
                state["presentation_id"] = submitted["data"]["presentation_id"]
                write_state(output, state)
                def progress(status):
                    data = status.get("data") or {}
                    count = data.get("created_slides", 0)
                    state.update(phase="generating", completed=count, total=len(plan.slides))
                    write_state(output, state)
                    if count != progress.last:
                        event(task.id, "ppt_generate", f"课件页面已生成 {count}/{len(plan.slides)} 页")
                        progress.last = count
                progress.last = None
                await engine.wait(operation, progress)
                state["deck"] = await engine.json("GET", "/api/v1/ppt/presentation/" + state["presentation_id"])
            except asyncio.CancelledError:
                state["cancelled"] = True
                write_state(output, state)
                try:
                    await asyncio.shield(asyncio.wait_for(engine.json("POST", "/api/v1/clawed/tasks/" + operation + "/cancel"), 8))
                except Exception:
                    pass
                raise
            except Exception:
                state["failed"] = True
                write_state(output, state)
                raise
        state["phase"] = "exporting"
        write_state(output, state)
        event(task.id, "ppt_export", "正在导出并检查完整课件")
        await engine.json("POST", "/api/v1/clawed/presentations/" + state["presentation_id"] + "/prepare-export")
        state["deck"] = await engine.json("GET", "/api/v1/ppt/presentation/" + state["presentation_id"])
        write_state(output, state)
        exported = await engine.json("POST", "/api/v1/ppt/presentation/" + state["presentation_id"] + "/export", json={"export_as": "pptx"})
        data = (await engine.request("GET", exported["path"])).content
        path = output / course_filename(task.payload["topic"], "教学课件.pptx")
        path.write_bytes(data)
        check_export(path, output, state, len(plan.slides))
        state.update(phase="complete", file=str(path), completed=len(plan.slides), total=len(plan.slides))
        write_state(output, state)
        return path


async def edit_deck(task: Any, config: Any) -> dict:
    from clawed.compile_workbench import course_filename
    import shutil
    source_id = task.payload["ppt_edit"]["source_task_id"]
    source = Path(config.output_dir).expanduser().resolve() / source_id
    output = Path(config.output_dir).expanduser().resolve() / task.id
    output.mkdir(parents=True, exist_ok=True)
    state = read_state(output)
    if not state:
        state = read_state(source)
        if not state.get("presentation_id"):
            raise ValueError("原课件缺少可编辑的页面数据，请重新生成课件。")
        state = {**state, "source_presentation_id": state["presentation_id"], "presentation_id": None,
                 "phase": "editing", "edit_complete": False}
        write_state(output, state)
    async with engine_lock, Engine() as engine:
        await engine.configure(config)
        if not state.get("presentation_id"):
            cloned = await engine.json("POST", "/api/v1/ppt/presentation/" + state["source_presentation_id"] + "/duplicate")
            state["presentation_id"] = cloned["id"]
            write_state(output, state)
        deck = await engine.json("GET", "/api/v1/ppt/presentation/" + state["presentation_id"])
        index = task.payload["ppt_edit"]["index"]
        slides = sorted(deck["slides"], key=lambda s: s["index"])
        if not 0 <= index < len(slides):
            raise ValueError("所选页面不存在，请刷新课件后重试。")
        if not state.get("edit_complete"):
            event(task.id, "ppt_edit", f"正在修改第 {index+1} 页，保留原任务的课件")
            await engine.json("POST", "/api/v1/clawed/slides/" + slides[index]["id"] + "/edit", json={
                "prompt": "保持中文、课程事实、公式和单位准确，文字完整且适合投影。" + task.payload["ppt_edit"]["prompt"]})
            state["edit_complete"] = True
            write_state(output, state)
        await engine.json("POST", "/api/v1/clawed/presentations/" + state["presentation_id"] + "/prepare-export")
        state["deck"] = await engine.json("GET", "/api/v1/ppt/presentation/" + state["presentation_id"])
        exported = await engine.json("POST", "/api/v1/ppt/presentation/" + state["presentation_id"] + "/export", json={"export_as": "pptx"})
        path = output / course_filename(task.payload["topic"], "教学课件.pptx")
        path.write_bytes((await engine.request("GET", exported["path"])).content)
        for name in ("master.json", "资料来源.json"):
            if (source / name).is_file():
                shutil.copy2(source / name, output / name)
        check_export(path, output, state)
        state.update(phase="complete", file=str(path))
        write_state(output, state)
    event(task.id, "complete", "修改后的课件已导出，请查看并审核")
    return {"status": "complete", "files": [str(path)], "required_outputs": {"slides": str(path)},
            "title": task.payload["topic"], "text": f"已修改第 {index+1} 页，原课件保留在原任务中。", "warnings": [], "errors": []}
