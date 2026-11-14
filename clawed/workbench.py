"""Persistent materials and Chinese teaching bundles for the web workbench."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from collections.abc import Iterator

from clawed.models import AppConfig
from clawed.paths import data_dir

def workspace() -> Path:
    root = data_dir() / "workbench"
    root.mkdir(parents=True, exist_ok=True)
    return root


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(workspace() / "workbench.db", timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS materials (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
            size INTEGER NOT NULL, text TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL, error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS job_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
            phase TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS workers (id TEXT PRIMARY KEY, heartbeat REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS job_visibility (
            task_id TEXT PRIMARY KEY, record_deleted INTEGER NOT NULL DEFAULT 0,
            results_deleted INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS material_visibility (
            material_id TEXT PRIMARY KEY, deleted INTEGER NOT NULL DEFAULT 0
        );
    """)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def material_list(trash: bool = False) -> list[dict[str, Any]]:
    with connect() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT m.id,m.name,m.kind,m.size,length(m.text) AS characters,m.status,m.error,m.created_at "
            "FROM materials m LEFT JOIN material_visibility v ON v.material_id=m.id "
            "WHERE COALESCE(v.deleted,0)=? ORDER BY m.created_at DESC", (int(trash),)
        )]


def material_get(material_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT m.*,COALESCE(v.deleted,0) AS deleted FROM materials m "
            "LEFT JOIN material_visibility v ON v.material_id=m.id WHERE m.id=?", (material_id,)).fetchone()
        return dict(row) if row else None


def source_path(material: dict[str, Any]) -> Path:
    # Both values originate in our database, never a client-supplied path.
    return workspace() / "materials" / material["id"] / f"source.{material['kind']}"


def event(task_id: str, phase: str, message: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO job_events(task_id,phase,message,created_at) VALUES(?,?,?,?)",
            (task_id, phase, message, datetime.now(UTC).isoformat()),
        )


def events(task_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT phase,message,created_at FROM job_events WHERE task_id=? ORDER BY id", (task_id,),
        )]


def visibility() -> dict[str, dict[str, Any]]:
    with connect() as conn:
        return {row['task_id']: dict(row) for row in conn.execute('SELECT * FROM job_visibility')}


def set_visibility(task_id: str, *, record: bool | None = None, results: bool | None = None) -> None:
    with connect() as conn:
        conn.execute('INSERT OR IGNORE INTO job_visibility(task_id) VALUES(?)', (task_id,))
        for column, value in (("record_deleted", record), ("results_deleted", results)):
            if value is not None:
                conn.execute(f'UPDATE job_visibility SET {column}=? WHERE task_id=?', (int(value), task_id))


async def generate_bundle(task: Any, config: AppConfig) -> dict[str, Any]:
    """Generate task-specific chapters and render the requested materials."""
    from clawed.teaching_content import generate_bundle as generate_adaptive_bundle
    return await generate_adaptive_bundle(task, config)
