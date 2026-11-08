"""Serve the built React application alongside the existing FastAPI routes."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles


def mount_workbench(app: FastAPI) -> None:
    root = Path(__file__).parent / "workbench_dist"
    if not (root / "index.html").is_file():
        return
    app.mount("/app/assets", StaticFiles(directory=str(root / "assets")), name="workbench-assets")

    @app.get("/", include_in_schema=False)
    async def workbench_home() -> RedirectResponse:
        return RedirectResponse("/app")

    @app.get("/app", include_in_schema=False)
    @app.get("/app/{page:path}", include_in_schema=False)
    async def workbench_page(page: str = "") -> FileResponse:
        return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})
