"""Built-in classroom layouts consumed by Presenton's existing layout renderer."""
from __future__ import annotations


def _text(name: str, x: float, y: float, w: float, h: float, size: int,
          limit: int, *, bold: bool = False, color: str = "#26374D") -> dict:
    font = {"family": "Noto Sans CJK SC", "size": size, "color": color,
            "bold": bold, "line_height": 1.3}
    return {"type": "text", "position": {"x": x, "y": y},
            "size": {"width": w, "height": h}, "font": font,
            "alignment": {"horizontal": "left", "vertical": "top"},
            "runs": [{"text": name, "font": font}], "decorative": False,
            "name": name, "min_length": 1, "max_length": limit}


def _rect(x: float, y: float, w: float, h: float, color: str) -> dict:
    return {"type": "vector", "shape": "polygon",
            "points": [{"x": x, "y": y}, {"x": x+w, "y": y},
                       {"x": x+w, "y": y+h}, {"x": x, "y": y+h}],
            "closed": True, "fill": {"color": color}, "decorative": True}


def classroom_layouts() -> dict:
    def page(key: str, description: str, elements: list[dict], *, cover: bool = False) -> dict:
        title = _text("title", 76, 66 if not cover else 146, 1110, 114,
                      40 if not cover else 64, 64 if not cover else 25,
                      bold=True, color="#184D78")
        return {"id": key, "description": description,
                "components": [{"id": "page", "description": description,
                                "position": {"x": 0, "y": 0}, "elements": [
                    _rect(0, 0, 1280, 720, "#F7F9FC"),
                    _rect(0, 0, 16, 720, "#245B85"),
                    _rect(76, 185 if not cover else 298, 100, 5, "#E59A46"),
                    title, *elements]}]}
    layouts = [
        page("lesson_cover", "课程封面或章节引入。仅用于课程开始或章节分隔，不生成目录、不编造页码。", [
            _text("subtitle", 80, 346, 1040, 190, 34, 110),
            _text("course_information", 80, 606, 1040, 50, 24, 48, color="#60738A"),
        ], cover=True),
        page("lesson_explanation", "概念说明与小结。单栏大字号。公式应单独选择公式讲解版式，无统计图表。", [
            _text("body", 80, 224, 1110, 420, 32, 260),
        ]),
        page("lesson_equation", "适用于至多两行的独立公式与简短代入计算。多行代码、伪代码请使用代码讲解版式。保留数字与单位。", [
            _text("explanation_without_formulas", 80, 224, 1110, 126, 32, 110),
            _rect(68, 370, 1124, 150, "#EAF0F7"),
            _text("equation", 94, 390, 1060, 112, 38, 120),
            _text("interpretation", 80, 558, 1110, 94, 30, 85),
        ]),
        page("lesson_comparison", "适用于两个概念或方法的对照。两栏各讲一个明确内容，禁止虚构数据或指标。", [
            _rect(68, 214, 550, 440, "#EAF0F7"), _rect(642, 214, 550, 440, "#FFF2DF"),
            _text("left_heading", 94, 236, 494, 68, 34, 15, bold=True),
            _text("left_body", 94, 326, 494, 304, 30, 135),
            _text("right_heading", 668, 236, 494, 68, 34, 15, bold=True),
            _text("right_body", 668, 326, 494, 304, 30, 135),
        ]),
        page("lesson_question", "完整题干、实验任务或讨论问题。正文保留全部已知条件，底部给出学生操作要求；参考答案仅放教师备注。", [
            _text("question", 80, 228, 1100, 276, 34, 185),
            _rect(68, 534, 1124, 120, "#EAF0F7"),
            _text("student_directions", 94, 554, 1060, 90, 28, 90),
        ]),
        page("lesson_code", "代码或算法伪代码讲解。正文区支持至多10行代码，保留原有缩进和步骤；顶部用一句话说明代码作用。代码过长时分成几个逻辑部分展示。", [
            _text("explanation", 80, 218, 1110, 78, 28, 80),
            _rect(68, 312, 1124, 344, "#EAF0F7"),
            _text("code", 94, 326, 1060, 318, 24, 650),
        ]),
    ]
    cells = []
    widths = [280, 530, 290]
    lefts = [80, 360, 890]
    for row in range(5):
        y = 224 + row * 82
        cells.append(_rect(68, y - 6, 1124, 80, "#245B85" if row == 0 else ("#EAF0F7" if row % 2 else "#FFFFFF")))
        for col in range(3):
            cells.append(_text(f"{'header' if row == 0 else 'row_'+str(row)}_column_{col+1}",
                lefts[col] + 10, y + 6, widths[col] - 28, 66, 28, 14 if row == 0 else [16, 26, 18][col],
                bold=row == 0, color="#FFFFFF" if row == 0 else "#26374D"))
            cells[-1]["min_length"] = 0
    layouts.append(page("lesson_table", "知识梳理或数据表格。三列，至多四行数据，单元格文字可编辑；不足四行时留空，超过四行须分页，禁止补造数据。", cells))
    return {"layouts": layouts}
