"""The private Presenton connection and versioned PPT template library."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse
import uuid
import zipfile

import httpx
from lxml import etree

from clawed.models import AppConfig
from clawed.ppt_limits import TEMPLATE_MAX_SLIDES, TEMPLATE_MAX_FILE_MB, TEMPLATE_MAX_UNPACKED_MB, template_limits
from clawed.workbench import connect, workspace

engine_lock = asyncio.Lock()


def now() -> str:
    return datetime.now(UTC).isoformat()


def engine_url() -> str:
    value = os.getenv("CLAWED_PPT_URL", "http://127.0.0.1:5002").rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("PPT 引擎地址必须使用本机回环地址。")
    return value


class Engine:
    async def __aenter__(self):
        self.client = httpx.AsyncClient(base_url=engine_url(), timeout=httpx.Timeout(240, connect=8), trust_env=False)
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()

    async def request(self, method: str, path: str, **kwargs):
        # Engine file URLs must never send credentials or make arbitrary network requests.
        if not path.startswith("/") or path.startswith("//") or ".." in path.split("/"):
            raise ValueError("PPT 引擎返回了无效资源地址。")
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise ValueError("无法连接 PPT 引擎，请启动 Docker 和本机课件服务后恢复任务。") from exc
        if not response.is_success:
            try:
                detail = str(response.json().get("detail", ""))
            except ValueError:
                detail = ""
            if "must be a string" in detail or "Invalid JSON slide element" in detail:
                raise ValueError("此 PPT 含引擎尚不支持的文字或图形对象，请在 PowerPoint 中另存为新的 PPTX 后重试。原文件已保留。")
            if "mathematical expression" in detail:
                raise ValueError("部分公式超出模板内容区，无法导出。请减少该页内容或选择容量更大的版式后重试。")
            raise ValueError(f"PPT 引擎操作未完成（{response.status_code}）：{detail[:220] or '请检查引擎状态并重试。'}")
        return response

    async def json(self, method: str, path: str, **kwargs):
        return (await self.request(method, path, **kwargs)).json()

    async def configure(self, cfg: AppConfig | None = None):
        from clawed.presenton_runtime import settings
        # Nginx becomes reachable before the engine's Python service during
        # container startup. Wait only for this explicit, transient condition.
        for attempt in range(30):
            try:
                ready = await self.client.get("/api/v1/clawed/status", timeout=8)
            except httpx.RequestError as exc:
                raise ValueError("无法连接 PPT 引擎，请启动 Docker 和本机课件服务后恢复任务。") from exc
            if ready.status_code not in {502, 503}:
                break
            await asyncio.sleep(2)
        if not ready.is_success:
            raise ValueError("课件服务尚未就绪，请等待启动完成后恢复任务；首次使用请先运行课件服务启动命令。")
        if ready.json().get("template_limits") != template_limits():
            raise ValueError("课件服务的模板处理配置尚未更新，请运行 python -m clawed.presenton_runtime start 后恢复任务。")
        await self.json("PUT", "/api/v1/admin/provider-settings", json=settings(cfg))

    async def default_template(self) -> str:
        from clawed.ppt_design import classroom_layouts
        return (await self.json("POST", "/api/v1/clawed/default-template", json=classroom_layouts()))["id"]

    async def wait(self, task_id: str, progress=None, timeout: float = 1800):
        deadline = asyncio.get_running_loop().time() + timeout
        last = None
        while asyncio.get_running_loop().time() < deadline:
            status = await self.json("GET", "/api/v1/async-tasks/status/" + task_id)
            if status["status"] == "completed":
                return status.get("data") or {}
            if status["status"] == "error":
                error = status.get("error") or {}
                detail = error.get("detail", "生成未完成") if isinstance(error, dict) else str(error)
                if "mathematical expression" in detail:
                    detail = "部分公式超出模板内容区，请调整页面内容或更换版式后重试。"
                elif "Cancelled" in detail:
                    detail = "课件任务已取消，可以恢复后继续。"
                raise ValueError("PPT 生成未完成：" + detail[:300])
            data = status.get("data") or {}
            marker = (data.get("created_slides"), data.get("created_layouts"), status.get("message"))
            if progress and marker != last:
                progress(status)
                last = marker
            await asyncio.sleep(2)
        raise ValueError("PPT 引擎处理时间较长，进度已保留。稍后恢复任务会先检查原任务。")


def database() -> None:
    with connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS ppt_templates (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL,
            spec_json TEXT NOT NULL DEFAULT '{}', version INTEGER NOT NULL DEFAULT 0,
            deleted INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '',
            progress_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")


def template_root(tid: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", tid):
        raise ValueError("模板编号无效。")
    return workspace() / "ppt_templates" / tid


def get_template(tid: str) -> dict | None:
    database()
    with connect() as conn:
        row = conn.execute("SELECT * FROM ppt_templates WHERE id=?", (tid,)).fetchone()
    if not row:
        return None
    item = dict(row)
    item["spec"] = json.loads(item.pop("spec_json"))
    item["progress"] = json.loads(item.pop("progress_json"))
    return item


def list_templates(trash: bool = False) -> list[dict]:
    database()
    with connect() as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM ppt_templates WHERE deleted=? ORDER BY created_at DESC", (int(trash),))]
    items = [get_template(tid) for tid in ids]
    for item in items:
        item["spec"] = {"page_count": item["spec"].get("page_count", 0),
                        "preview_count": len((item["spec"].get("upload") or {}).get("slide_image_urls", [])),
                        "analyzed_page_count": len(item["spec"].get("layouts", [])), "layouts": [], "selected": []}
    return items


def upload_template(data: bytes, name: str) -> dict:
    if len(data) > TEMPLATE_MAX_FILE_MB * 1024 * 1024:
        raise ValueError(f"PPT 模板不能超过 {TEMPLATE_MAX_FILE_MB} MB。")
    import io
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if sum(v.file_size for v in z.infolist()) > TEMPLATE_MAX_UNPACKED_MB * 1024 * 1024:
                raise ValueError("PPT 解压后过大，请减少页面或图片后上传。")
            doc = etree.fromstring(z.read("ppt/presentation.xml"), etree.XMLParser(resolve_entities=False))
            ns = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main"}
            size = doc.find("p:sldSz", ns)
            count = len(doc.findall("p:sldIdLst/p:sldId", ns))
            if size is None or int(size.get("cx", 0)) < int(size.get("cy", 0)):
                raise ValueError("当前课件引擎适用于横版 PPT。此文件为竖版，直接转换会导致内容超出画布，请先另存为横版课件。")
            if not 1 <= count <= TEMPLATE_MAX_SLIDES:
                raise ValueError(f"模板支持 1–{TEMPLATE_MAX_SLIDES} 页，实际为 {count} 页。请选取代表页另存为副本；系统不会自动裁页。")
    except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError) as exc:
        raise ValueError("无法读取 PPTX 文件，请在 PowerPoint 中另存为 PPTX 后重试。") from exc
    tid = uuid.uuid4().hex
    root = template_root(tid)
    root.mkdir(parents=True)
    (root / "source.pptx").write_bytes(data)
    database()
    spec = {"source_name": name, "source_sha256": hashlib.sha256(data).hexdigest(),
            "page_count": count, "instruction": "", "layouts": [], "selected": []}
    with connect() as conn:
        conn.execute("INSERT INTO ppt_templates(id,name,status,spec_json,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                     (tid, Path(name).stem[:160], "uploaded", json.dumps(spec, ensure_ascii=False), now(), now()))
    return get_template(tid)


def update_progress(tid: str, value: dict):
    with connect() as conn:
        conn.execute("UPDATE ppt_templates SET progress_json=?,updated_at=? WHERE id=?",
                     (json.dumps(value, ensure_ascii=False), now(), tid))


def check_template_coverage(spec: dict, *, require_layouts: bool = False):
    expected = spec["page_count"]
    count = len((spec.get("upload") or {}).get("slide_image_urls", []))
    if count != expected:
        raise ValueError(f"原文件 {expected} 页，但预览仅 {count} 页，请重新提取完整文件；原文件已保留。")
    if require_layouts and len(spec.get("layouts", [])) != expected:
        raise ValueError(f"原文件 {expected} 页，但仅提取 {len(spec.get('layouts', []))} 页，请重新提取，不能保存不完整模板。")


async def analyze_template(tid: str):
    item = get_template(tid)
    if not item or item["deleted"]:
        raise ValueError("模板不存在。")
    spec = item["spec"]
    if not 1 <= spec["page_count"] <= TEMPLATE_MAX_SLIDES:
        raise ValueError(f"模板最多支持 {TEMPLATE_MAX_SLIDES} 页，请选取代表页另存为副本后上传；原文件保留。")
    async with engine_lock, Engine() as engine:
        await engine.configure()
        update_progress(tid, {"message": f"正在读取全部 {spec['page_count']} 页并生成预览，不自动裁页"})
        if spec.get("upload") and len(spec["upload"].get("slide_image_urls", [])) != spec["page_count"]:
            # Discard an old truncated preview and its analysis reference, not
            # immutable historical template versions or the uploaded original.
            spec.pop("upload", None)
            spec.pop("analysis_task_id", None)
            with connect() as conn:
                conn.execute("UPDATE ppt_templates SET spec_json=? WHERE id=?", (json.dumps(spec, ensure_ascii=False), tid))
        if not spec.get("upload"):
            path = template_root(tid) / "source.pptx"
            with path.open("rb") as source:
                spec["upload"] = await engine.json("POST", "/api/v1/ppt/template/fonts-upload-and-slides-preview",
                    files={"pptx_file": (spec["source_name"], source, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
                    timeout=httpx.Timeout(900, connect=8))
            check_template_coverage(spec)
            # Keep successful previews if starting the model task is interrupted.
            with connect() as conn:
                conn.execute("UPDATE ppt_templates SET spec_json=? WHERE id=?", (json.dumps(spec, ensure_ascii=False), tid))
        check_template_coverage(spec)
        task_id = spec.get("analysis_task_id")
        if task_id:
            state = await engine.json("GET", "/api/v1/async-tasks/status/" + task_id)
            if state["status"] == "error":
                state = await engine.json("POST", "/api/v1/ppt/template/async/" + task_id + "/retry")
                task_id = state["id"]
        else:
            uploaded = spec["upload"]
            state = await engine.json("POST", "/api/v1/ppt/template/async", json={
                "pptx_url": uploaded["modified_pptx_url"], "slide_image_urls": uploaded["slide_image_urls"],
                "fonts": uploaded.get("fonts", {}), "name": item["name"],
                "description": "根据上传文件理解各部分用途，提取可复用版式。课程原文、题目、答案、学科和主题应随新课程替换。"})
            task_id = state["id"]
        spec["analysis_task_id"] = task_id
        with connect() as conn:
            conn.execute("UPDATE ppt_templates SET spec_json=? WHERE id=?", (json.dumps(spec, ensure_ascii=False), tid))
        def progress(state):
            data = state.get("data") or {}
            update_progress(tid, {"message": "正在理解页面并提取版式", "completed": data.get("created_layouts", 0),
                                  "total": spec["page_count"]})
        result = await engine.wait(task_id, progress)
        remote = await engine.json("GET", "/api/v1/ppt/template/" + result["template_v2_id"])
        spec.update(engine_id=remote["id"], layouts=remote["layouts"]["layouts"], fonts=remote.get("fonts", {}))
        check_template_coverage(spec, require_layouts=True)
        spec["selected"] = [layout["id"] for layout in spec["layouts"]]
        version = item["version"] + 1
        (template_root(tid) / f"version-{version}.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        with connect() as conn:
            conn.execute("UPDATE ppt_templates SET status='review',spec_json=?,version=?,error='',progress_json=?,updated_at=? WHERE id=?",
                (json.dumps(spec, ensure_ascii=False), version, '{"message":"提取完成，请确认需要复用的页面"}', now(), tid))


async def save_template(tid: str, version: int, selected: list[str], instruction: str, name: str):
    item = get_template(tid)
    if not item or item["deleted"] or item["status"] == "analyzing" or item["version"] != version:
        raise ValueError("模板状态已变化，请刷新后重试。")
    spec = item["spec"]
    check_template_coverage(spec, require_layouts=True)
    layouts = [v for v in spec.get("layouts", []) if v["id"] in selected]
    if not layouts:
        raise ValueError("请至少保留一种页面版式。")
    async with engine_lock, Engine() as engine:
        clone = await engine.json("POST", "/api/v1/clawed/templates/" + spec["engine_id"] + "/snapshot")
        await engine.json("PATCH", "/api/v1/ppt/template/" + clone["id"], json={
            "name": name.strip() or item["name"], "layouts": {"layouts": layouts}, "merged_components": {"components": []}})
    spec.update(engine_id=clone["id"], selected=selected, instruction=instruction)
    new_version = version + 1
    (template_root(tid) / f"version-{new_version}.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    with connect() as conn:
        changed = conn.execute("UPDATE ppt_templates SET name=?,status='ready',spec_json=?,version=?,updated_at=? WHERE id=? AND version=? AND deleted=0",
            (name.strip() or item["name"], json.dumps(spec, ensure_ascii=False), new_version, now(), tid, version)).rowcount
        if not changed:
            raise ValueError("模板已被修改，请刷新后重试。")
    return get_template(tid)


def freeze_template(tid: str) -> dict:
    item = get_template(tid)
    if not item or item["deleted"] or item["status"] != "ready":
        raise ValueError("PPT 模板已删除或尚未确认，请重新选择。")
    check_template_coverage(item["spec"], require_layouts=True)
    return {"id": tid, "name": item["name"], "version": item["version"], "spec": item["spec"]}
