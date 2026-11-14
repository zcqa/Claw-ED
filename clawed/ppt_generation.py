"""Presenton owns presentation planning, content and multi-region layout."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from clawed.presenton import Engine, engine_lock
from clawed.workbench import event


def read_state(output: Path) -> dict:
    path = output / "ppt_state.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def write_state(output: Path, state: dict):
    path = output / "ppt_state.json"
    temp = output / "ppt_state.tmp"
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def presentation_pages(deck: dict) -> list[dict]:
    """Read actual generated text; never use a second curriculum as its source."""
    def strings(value, key=""):
        if key in {"__speaker_note__", "page_number", "slide_number", "section_number", "item_number", "badge_number"} or key.lower().endswith(("_url", "_prompt")):
            return []
        if isinstance(value, str):
            return [value] if value.strip() and key.lower() not in {"image", "icon", "image_query", "icon_query"} and not value.startswith(("/app_data/", "/static/", "<svg")) else []
        if isinstance(value, dict):
            return [text for k, v in value.items() for text in strings(v, k)]
        if isinstance(value, list):
            return [text for v in value for text in strings(v, key)]
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return [str(value)]
        return []

    def title(value):
        if not isinstance(value, dict):
            return ""
        for k, v in value.items():
            if isinstance(v, str) and any(w in k.lower() for w in ("title", "heading")) and v.strip():
                return v
        return next((found for v in value.values() if (found := title(v))), "")

    pages = []
    for slide in sorted(deck.get("slides", []), key=lambda row: row["index"]):
        content = slide.get("content", {})
        text = strings(content)
        heading = title(content) or (text[0] if text else f"第{slide['index']+1}页")
        # Remove only the heading occurrence, preserving deliberate repetition.
        if heading in text:
            text.remove(heading)
        pages.append({"title": heading, "content": "\n".join(text),
            "teacher_notes": slide.get("speaker_note") or content.get("__speaker_note__", ""),
            "chapter_id": ""})
    return pages


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
        raise ValueError("第 " + "、".join(bad) + " 页文字超出画布，页面数据已保留，可在课件预览中调整后重新生成。")


async def generate_presentation(task: Any, brief: dict, config: Any, output: Path) -> Path:
    from clawed.compile_workbench import course_filename
    from clawed.ppt_design import classroom_layouts
    template = task.payload.get("ppt_template") or {}
    fingerprint = hashlib.sha256(json.dumps({"brief": brief, "template": template or {"builtin": classroom_layouts()},
        "version": "presenton-first-v1", "provider": config.provider.value,
        "model": getattr(config, config.provider.value + "_model"),
        "thinking": config.deepseek_thinking, "effort": config.deepseek_reasoning_effort,
        "endpoint": config.deepseek_base_url}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    state = read_state(output)
    if state.get("fingerprint") != fingerprint:
        state = {"fingerprint": fingerprint, "attempt": 0, "phase": "planning",
                 "template_name": template.get("name", "课堂清晰版"), "template_version": template.get("version")}
        if task.payload.get("reuse_task_id"):
            previous = read_state(Path(config.output_dir).expanduser().resolve() / task.payload["reuse_task_id"])
            if previous.get("fingerprint") == fingerprint and previous.get("phase") == "complete":
                state.update({key: previous[key] for key in ("presentation_id", "deck", "plan") if key in previous})
                state["generation_complete"] = True
        write_state(output, state)
    async with engine_lock, Engine() as engine:
        await engine.configure(config)
        template_id = template.get("spec", {}).get("engine_id") if template else await engine.default_template()
        if not state.get("generation_complete"):
            if state.pop("failed", False) or state.pop("cancelled", False):
                # First inspect an existing request: a lost response may have
                # occurred after the engine completed it successfully.
                remote = await engine.json("GET", "/api/v1/async-tasks/status/" + state["engine_task_id"]) if state.get("engine_task_id") else {}
                if remote.get("status") == "error":
                    state.pop("engine_task_id", None)
                    state["attempt"] += 1
            operation = state.get("engine_task_id") or "clawed-" + hashlib.sha256(f"{task.id}:{fingerprint}:{state['attempt']}".encode()).hexdigest()
            state.update(engine_task_id=operation, phase="submitting")
            write_state(output, state)
            event(task.id, "ppt_plan", "Presenton 正在根据任务规划课件大纲、页面与版式")
            try:
                submitted = await engine.json("POST", "/api/v1/clawed/generate/" + operation, json={
                    "content": json.dumps(brief, ensure_ascii=False), "template": template_id,
                    "language": "简体中文", "tone": "educational", "verbosity": "standard",
                    "include_title_slide": True, "include_table_of_contents": False,
                    "web_search": False, "export_as": "pptx",
                    "instructions": (
                        "以学生或听众实际观看的PPT为主要产物。根据任务目的、受众、资料、时长和要求，自主编排大纲、页数与讲解节奏。"
                        "不套用统一的教案栏目，不强制加入互动、检测、情景任务或作业；用户明确禁止的环节在正文和备注中都不能出现。"
                        "homework_allowed=false时不安排任何课后任务；true只是许可，仍服从用户文字要求。"
                        "充分使用所选模板的标题、正文、多栏、图文、表格、流程和重复组件，让版式服务内容；不必逐页套用模板，不为填框编造内容。"
                        "保持适当信息密度，既不一段一句拆成大量空白页，也不堆满小字。完整呈现必要知识、题目条件与关键步骤，不用省略号截断内容。"
                        "章节和页数根据实际内容决定，不要求每章或每个要点恰好一页。"
                        "课程资料为事实依据，保留关键名称、数字、定义和计算结果。未知的时效性数据不编造，说明以正式资料为准。"
                        "教师讲解提示和学生练习参考答案写入__speaker_note__，练习题目页不提前公布答案。讲解例题的解答可正常展示。"
                        "使用简体中文教学指令；公式、单位、代码和外语教学所需文字保留。模板要求只约束视觉与组织建议，用户任务要求优先。"
                        "图表仅用于资料已有的数据；不能虚构统计数字来装饰页面。"
                        f"本次约{brief['duration_minutes']}分钟，请按可实际讲解的内容量安排页面，不把建议时长理解成固定页数。"
                    )})
                state["presentation_id"] = submitted["data"]["presentation_id"]
                write_state(output, state)
                def progress(status):
                    data = status.get("data") or {}
                    count = data.get("created_slides", 0)
                    total = count + data.get("remaining_slides", 0)
                    state.update(phase="generating", completed=count, total=total)
                    write_state(output, state)
                    if count != progress.last:
                        event(task.id, "ppt_generate", f"Presenton 已生成 {count}/{total} 页" if total else "Presenton 正在编排内容与选择版式")
                        progress.last = count
                progress.last = None
                await engine.wait(operation, progress)
                state["generation_complete"] = True
                write_state(output, state)
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
        event(task.id, "ppt_export", "正在导出 Presenton 课件，保留完整多区域版式")
        await engine.json("POST", "/api/v1/clawed/presentations/" + state["presentation_id"] + "/prepare-export")
        state["deck"] = await engine.json("GET", "/api/v1/ppt/presentation/" + state["presentation_id"])
        state["plan"] = {"slides": presentation_pages(state["deck"])}
        if state["plan"]["slides"]:
            state["deck"]["title"] = state["plan"]["slides"][0]["title"]
        write_state(output, state)
        exported = await engine.json("POST", "/api/v1/ppt/presentation/" + state["presentation_id"] + "/export", json={"export_as": "pptx"})
        path = output / course_filename(task.payload["topic"], "教学课件.pptx")
        path.write_bytes((await engine.request("GET", exported["path"])).content)
        check_export(path, output, state)
        count = len(state["deck"]["slides"])
        state.update(phase="complete", file=str(path), completed=count, total=count)
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
        for name in ("master.json", "plan.json", "content_state.json", "资料来源.json"):
            if (source / name).is_file():
                shutil.copy2(source / name, output / name)
        state["plan"] = {"slides": presentation_pages(state["deck"])}
        master_path = output / "master.json"
        if master_path.is_file():
            material = json.loads(master_path.read_text(encoding="utf-8"))
            if material.get("schema_version") == "ppt-first-v1":
                material["slides"] = state["plan"]["slides"]
                master_path.write_text(json.dumps(material, ensure_ascii=False, indent=2), encoding="utf-8")
        check_export(path, output, state)
        state.update(phase="complete", file=str(path))
        write_state(output, state)
    event(task.id, "complete", "修改后的课件已导出，请查看并审核")
    return {"status": "complete", "files": [str(path)], "required_outputs": {"slides": str(path)},
            "title": task.payload["topic"], "text": f"已修改第 {index+1} 页，原课件保留在原任务中。", "warnings": [], "errors": []}
