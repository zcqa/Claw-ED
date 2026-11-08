"""Chinese classroom exports. Preserve complete text and paginate instead of eliding it."""
from __future__ import annotations

import math
import re
import unicodedata
from pathlib import Path
from typing import Any


def teaching_text(text: str) -> str:
    """Translate known teaching jargon, preserving names, formulas, units and code."""
    labels = {"Do Now": "课堂导入", "exit ticket": "课堂检测", "turn and talk": "交流讨论",
        "guided notes": "学习笔记", "teacher moves": "教师活动", "sentence starters": "作答提示",
        "REMEMBER": "请注意", "Use these sentence starters:": "可参考以下句式："}
    for phrase, translated in {"I Do": "教师示范", "We Do": "师生共练", "You Do": "独立练习"}.items():
        text = re.sub(r"[（(]\s*" + re.escape(phrase) + r"\s*[）)]", f"（{translated}）", text)
    for phrase, translated in sorted(labels.items(), key=lambda row: len(row[0]), reverse=True):
        text = re.sub(r"(?<![A-Za-z])" + re.escape(phrase) + r"(?![A-Za-z])", translated, text, flags=re.I)
    return text


def response_requirement(text: str) -> str:
    return {"TEA": "观点、证据与分析", "RACE": "回应问题、作答、引用证据与解释",
            "CER": "主张、证据与推理"}.get(text.strip().upper(), text)


def course_filename(topic: str, suffix: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", topic).strip(" .")[:90]
    if not name or name.upper() in {"CON", "PRN", "AUX", "NUL"}:
        name = "未命名课程"
    return f"{name}_{suffix}"


def sections(master: Any, teacher: bool = False) -> list[tuple[str, list[str], str]]:
    """Student-visible text and separate teacher notes, shared by Word and slides."""
    result = [("教学目标", [master.objective], "")]
    if master.prerequisite_skills:
        result.append(("先备知识", master.prerequisite_skills, ""))
    result.append(("课堂导入", [master.do_now.stimulus, *master.do_now.questions],
                   "参考答案：\n" + "\n".join(master.do_now.answers)))
    for item in master.vocabulary:
        result.append((f"核心概念 · {item.term}", [item.definition, f"情境例句：{item.context_sentence}"], ""))
    for item in master.direct_instruction:
        result.append((item.heading, [item.content, *[f"要点：{x}" for x in item.key_points]],
                       "\n".join(filter(None, [item.hook, item.teacher_script, item.transition]))))
    for index, item in enumerate(master.guided_notes, 1):
        result.append((f"学习笔记 · {index}", [item.prompt], f"参考答案：{item.answer}"))
    for item in master.primary_sources:
        result.append((f"资料研读 · {item.title}", [item.content_text, f"资料来源：{item.attribution}",
                       *item.scaffolding_questions], ""))
    for item in master.stations:
        source = next((s for s in master.primary_sources if s.id == item.source_ref), None)
        result.append((f"分组活动 · {item.title}", list(filter(None, [
            f"活动时间：{item.timer_minutes} 分钟", source.content_text if source else "",
            item.task, item.student_directions, item.group_roles, item.reporting_template,
        ])), f"参考答案：{item.teacher_answer_key}"))
    if not master.stations and not master.creative_activity and not master.jigsaw:
        activities = [row for row in master.minute_by_minute
                      if any(word in str(row.get("activity", "")) for word in ("小组", "探究", "讨论"))]
        for row in activities:
            result.append((str(row.get("activity", "课堂活动")), [
                f"时间安排：{row.get('time', '')}", str(row.get("teacher_moves", ""))], ""))
    if master.jigsaw:
        item = master.jigsaw
        result.append(("合作学习", [f"专家组：{item.num_expert_groups} 组；专家研讨 {item.expert_phase_minutes} 分钟；组内分享 {item.teaching_phase_minutes} 分钟。",
            item.graphic_organizer, item.share_out_protocol, item.debrief_question], ""))
    if master.creative_activity:
        item = master.creative_activity
        result.append((f"拓展活动 · {item.title}", list(filter(None, [item.scenario, "、".join(item.roles),
            item.student_directions, f"活动成果：{item.deliverable}", item.debrief])), ""))
    if master.independent_work:
        item = master.independent_work
        result.append(("独立练习", list(filter(None, [item.task, item.rubric_snippet])), f"参考示例：{item.exemplar}"))
    if master.formative_checks:
        result.append(("课堂理解检查", master.formative_checks, ""))
    for index, item in enumerate(master.exit_ticket, 1):
        result.append((f"课堂检测 · 第 {index} 题", [item.stimulus, item.question,
            *[f"作答提示：{x}" for x in item.sentence_starters],
            *([f"作答要求：{response_requirement(item.response_framework)}"] if item.response_framework else [])], f"参考答案：{item.answer}"))
    result.append(("课堂小结", [f"本课目标：{master.objective}",
        *[f"{x.term}：{x.definition}" for x in master.vocabulary]], ""))
    if master.homework:
        result.append(("课后作业", [master.homework], ""))
    if teacher:
        if master.materials_needed:
            result.append(("教学准备", master.materials_needed, ""))
        if master.minute_by_minute:
            result.append(("教学时间安排", [" · ".join(str(row.get(k, "")) for k in
                ("time", "activity", "teacher_moves") if row.get(k)) for row in master.minute_by_minute], ""))
        if master.misconceptions:
            result.append(("常见误区", master.misconceptions, ""))
        labels = {"ell": "语言支持", "iep": "个别化支持", "gifted": "拓展提升", "advanced": "拓展提升", "struggling": "基础巩固"}
        result.append(("分层教学", [f"{labels.get(k, '学习支持')}：{'；'.join(v) if isinstance(v, list) else v}" for k, v in
            master.differentiation.model_dump().items() if v], ""))
    return result


async def compile_word(master: Any, images: dict[str, Path], output: Path, *, teacher: bool) -> Path:
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor
    from docx.oxml.ns import qn

    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Microsoft YaHei"
    normal.font.size = Pt(12)
    normal.paragraph_format.space_after = Pt(8)
    normal.paragraph_format.line_spacing = 1.35
    for style in doc.styles:
        if style.type == 1:
            style.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "微软雅黑")
            if style.name in {"Title", "Subtitle"} or style.name.startswith("Heading"):
                style.font.color.rgb = RGBColor(0, 0, 0)
    for section in doc.sections:
        section.top_margin = section.bottom_margin = Inches(.7)
    role = "教师教案" if teacher else "学生讲义"
    doc.add_heading(teaching_text(master.title), 0)
    doc.add_paragraph(f"{role}  ·  {master.subject}  ·  {master.grade_level}  ·  {master.duration_minutes} 分钟")
    if not teacher:
        doc.add_paragraph("姓名：________________    班级：________________    日期：________________")
    for title, paragraphs, notes in sections(master, teacher):
        doc.add_heading(teaching_text(title), 1)
        for text in paragraphs:
            if text:
                doc.add_paragraph(teaching_text(text))
        if teacher and notes:
            p = doc.add_paragraph()
            run = p.add_run(teaching_text("教学提示与参考答案\n" + notes))
            run.font.color.rgb = RGBColor.from_string("305C83")
        if not teacher and any(word in title for word in ("笔记", "检测", "练习", "活动", "导入")):
            doc.add_paragraph("作答区：\n________________________________________________________________\n________________________________________________________________")
        if title in [s.heading for s in master.direct_instruction]:
            spec = next(s.image_spec for s in master.direct_instruction if s.heading == title)
            if spec in images and images[spec].is_file():
                doc.add_picture(str(images[spec]), width=Inches(5.5))
    path = output / role
    path = path.with_suffix(".docx")
    doc.save(path)
    return path


def _width(text: str) -> float:
    return sum(1 if unicodedata.east_asian_width(c) in {"W", "F"} else .55 for c in text)


def _chunks(text: str, limit: int) -> list[str]:
    # Prefer sentence boundaries. A very long sentence continues without losing characters.
    sentences = re.findall(r"[^。！？；\n]+[。！？；]?|\n", text)
    result, current = [], ""
    for sentence in sentences:
        if _width(current + sentence) <= limit:
            current += sentence
            continue
        if current.strip():
            result.append(current.strip())
        current = ""
        for char in sentence:
            if _width(current + char) > limit:
                result.append(current)
                current = ""
            current += char
    if current.strip():
        result.append(current.strip())
    return result


async def compile_slides(master: Any, images: dict[str, Path], output: Path) -> Path:
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.oxml.xmlchemy import OxmlElement

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)

    def textbox(slide: Any, text: str, x: float, y: float, w: float, h: float,
                size: int, color: str = "25364B", bold: bool = False) -> None:
        box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        frame = box.text_frame
        frame.word_wrap = True
        for index, line in enumerate(text.split("\n")):
            p = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
            p.space_after = Pt(10)
            p.line_spacing = 1.2
            run = p.add_run()
            run.text = teaching_text(line)
            run.font.size, run.font.name = Pt(size), "Microsoft YaHei"
            run.font.bold, run.font.color.rgb = bold, RGBColor.from_string(color)
            ea = OxmlElement("a:ea")
            ea.set("typeface", "Microsoft YaHei")
            run._r.get_or_add_rPr().append(ea)

    def page(title: str, text: str, notes: str = "", image: Path | None = None) -> None:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor.from_string("F8FAFD")
        # Long headings receive a dedicated band; never shorten them with ellipses.
        size = 30 if _width(title) <= 24 else 24
        textbox(slide, title, .65, .35, 12, 1.3, size, "265A91", True)
        textbox(slide, text, .75, 1.85, 7.2 if image else 11.8, 4.85, 23)
        if image:
            from PIL import Image
            with Image.open(image) as im:
                iw, ih = im.size
            ratio = min(4.1 / iw, 4.4 / ih)
            slide.shapes.add_picture(str(image), Inches(8.5), Inches(2),
                width=Inches(iw * ratio), height=Inches(ih * ratio))
        textbox(slide, f"{master.subject} · {len(prs.slides)}", .75, 7.03, 11.8, .3, 11, "62748A")
        slide.notes_slide.notes_text_frame.text = teaching_text(notes or title)

    page(master.title, f"{master.grade_level} · {master.duration_minutes} 分钟\n\n{master.subject}")
    for title, paragraphs, notes in sections(master):
        spec = next((s.image_spec for s in master.direct_instruction if s.heading == title), "")
        image = images.get(spec)
        image = image if image and image.is_file() else None
        width = 25 if image else 42
        # Approximate rendered lines with CJK and Latin widths; reserve ample vertical space.
        pages, lines, current = [], 0, []
        for text in paragraphs:
            for paragraph in text.splitlines():
                for chunk in _chunks(paragraph, width * 4):
                    count = max(1, math.ceil(_width(chunk) / width))
                    if current and lines + count + 1 > 7:
                        pages.append("\n\n".join(current))
                        current, lines = [], 0
                    current.append(chunk)
                    lines += count + 1
        if current:
            pages.append("\n\n".join(current))
        for index, text in enumerate(pages):
            heading = title if len(pages) == 1 else f"{title}（{index + 1}/{len(pages)}）"
            page(heading, text, notes, image)
    path = output / "教学课件.pptx"
    prs.save(path)
    return path
