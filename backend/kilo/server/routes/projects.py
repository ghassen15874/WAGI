import os
import shutil
import tempfile
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ...orchestrator.session_service import (
    cancel_project_execution,
    start_project_runtime,
    terminate_sandbox_processes,
)
from ..db import get_conn
from ..auth.middleware import get_current_user
from ..config import settings

router = APIRouter(prefix="/api/projects", tags=["projects"])


class RenameProjectRequest(BaseModel):
    name: str


class UpdateProjectFileRequest(BaseModel):
    path: str
    content: str


def _remove_file(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def _should_skip_dir(dirname: str) -> bool:
    return dirname in {"node_modules", ".git", "dist", "build", ".next", "__pycache__"}


def _should_skip_file(filename: str) -> bool:
    return filename.endswith((".pyc", ".pyo")) or filename in {".DS_Store"}


def _normalize_project_file_path(path: str) -> str:
    normalized = str(path or "").strip().replace("\\", "/")
    if not normalized:
        return ""
    if normalized.startswith("/"):
        return ""
    parts = [part for part in normalized.split("/") if part]
    if not parts:
        return ""
    if any(part in {".", ".."} for part in parts):
        return ""
    clean = "/".join(parts)
    if clean.startswith((".git/", "node_modules/", ".lovable/")):
        return ""
    return clean

@router.get("")
async def list_projects(user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, created_at, updated_at, status, last_narration, error_message FROM projects WHERE user_id = %s ORDER BY updated_at DESC",
            (user["sub"],)
        ).fetchall()
        return {"projects": [dict(r) for r in rows]}


@router.patch("/{project_id}")
async def rename_project(
    project_id: str,
    req: RenameProjectRequest,
    user: dict = Depends(get_current_user),
):
    name = str(req.name or "").strip()
    if not name:
        raise HTTPException(400, "Project name cannot be empty")
    if len(name) > 255:
        raise HTTPException(400, "Project name must be 255 characters or fewer")

    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM projects WHERE id = %s AND user_id = %s",
            (project_id, user["sub"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Project not found")

        conn.execute(
            "UPDATE projects SET name = %s, updated_at = NOW() WHERE id = %s",
            (name, project_id),
        )
        conn.commit()

    return {"success": True, "project": {"id": project_id, "name": name}}

@router.get("/{project_id}/files")
async def get_project_files(project_id: str, user: dict = Depends(get_current_user)):
    # 1. Verify ownership
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM projects WHERE id = %s AND user_id = %s", (project_id, user["sub"])).fetchone()
        if not row:
            raise HTTPException(404, "Project not found")

    # 2. Read sandbox dir
    base_dir = settings.SANDBOX_BASE_DIR
    sandbox = os.path.join(base_dir, project_id)
    if not os.path.exists(sandbox):
        return {"files": {}}
        
    files = {}
    for root, dirs, fnames in os.walk(sandbox):
        dirs[:] = [d for d in dirs if d != "node_modules" and d != ".git" and not d.startswith(".")]
        for fname in fnames:
            if fname.startswith("."):
                continue
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, sandbox)
            try:
                with open(fpath, encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                if content and len(content) > 0:
                    files[rel] = content
            except Exception:
                pass
                
    return {"files": files}


@router.patch("/{project_id}/files")
async def update_project_file(
    project_id: str,
    req: UpdateProjectFileRequest,
    user: dict = Depends(get_current_user),
):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM projects WHERE id = %s AND user_id = %s",
            (project_id, user["sub"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Project not found")

    safe_rel_path = _normalize_project_file_path(req.path)
    if not safe_rel_path:
        raise HTTPException(400, "Invalid file path")

    content = str(req.content or "")
    if len(content.encode("utf-8")) > 2_000_000:
        raise HTTPException(400, "File content is too large (max 2 MB)")

    sandbox = os.path.join(settings.SANDBOX_BASE_DIR, project_id)
    if not os.path.isdir(sandbox):
        raise HTTPException(404, "Project files not found")

    sandbox_abs = os.path.abspath(sandbox)
    target_abs = os.path.abspath(os.path.join(sandbox_abs, safe_rel_path))
    if not (target_abs == sandbox_abs or target_abs.startswith(sandbox_abs + os.sep)):
        raise HTTPException(400, "Invalid file path")

    os.makedirs(os.path.dirname(target_abs), exist_ok=True)
    try:
        with open(target_abs, "w", encoding="utf-8") as handle:
            handle.write(content)
    except Exception as exc:
        raise HTTPException(500, f"Failed to write file: {exc}") from exc

    with get_conn() as conn:
        conn.execute(
            "UPDATE projects SET updated_at = NOW() WHERE id = %s",
            (project_id,),
        )
        conn.commit()

    return {"success": True, "path": safe_rel_path}


@router.get("/{project_id}/log-tail")
async def get_project_log_tail(
    project_id: str,
    chars: int = Query(default=80000, ge=1000, le=250000),
    user: dict = Depends(get_current_user),
):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM projects WHERE id = %s AND user_id = %s",
            (project_id, user["sub"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Project not found")

    sandbox = os.path.join(settings.SANDBOX_BASE_DIR, project_id)
    log_path = os.path.join(sandbox, ".lovable", "build.log")
    if not os.path.isfile(log_path):
        return {"content": "", "truncated": False}

    try:
        size = os.path.getsize(log_path)
        with open(log_path, "rb") as handle:
            if size > chars:
                handle.seek(size - chars)
            raw = handle.read()
        content = raw.decode("utf-8", errors="ignore")
        return {"content": content, "truncated": size > chars}
    except Exception as exc:
        raise HTTPException(500, f"Failed to read project log: {exc}") from exc


@router.get("/{project_id}/export")
async def export_project_zip(
    project_id: str,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, name FROM projects WHERE id = %s AND user_id = %s",
            (project_id, user["sub"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Project not found")

    sandbox = os.path.join(settings.SANDBOX_BASE_DIR, project_id)
    if not os.path.isdir(sandbox):
        raise HTTPException(404, "Project files not found")

    temp_dir = tempfile.mkdtemp(prefix="project-export-")
    archive_base = os.path.join(temp_dir, project_id)

    staged_root = os.path.join(temp_dir, "project")
    os.makedirs(staged_root, exist_ok=True)

    for root, dirs, files in os.walk(sandbox):
        dirs[:] = [d for d in dirs if not _should_skip_dir(d)]
        rel_root = os.path.relpath(root, sandbox)
        target_root = staged_root if rel_root == "." else os.path.join(staged_root, rel_root)
        os.makedirs(target_root, exist_ok=True)

        for filename in files:
            if _should_skip_file(filename):
                continue
            source_path = os.path.join(root, filename)
            rel_path = os.path.relpath(source_path, sandbox)
            target_path = os.path.join(staged_root, rel_path)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            shutil.copy2(source_path, target_path)

    archive_path = shutil.make_archive(archive_base, "zip", root_dir=staged_root)
    background_tasks.add_task(_remove_file, archive_path)
    background_tasks.add_task(shutil.rmtree, temp_dir, True)

    project_name = str(row["name"] or "project").strip() or "project"
    safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in project_name).strip("-") or "project"
    return FileResponse(
        archive_path,
        media_type="application/zip",
        filename=f"{safe_name}.zip",
    )

@router.delete("/{project_id}")
async def delete_project(project_id: str, user: dict = Depends(get_current_user)):
    # 1. Verify ownership and delete from DB
    base_dir = settings.SANDBOX_BASE_DIR
    sandbox = os.path.join(base_dir, project_id)

    with get_conn() as conn:
        row = conn.execute("SELECT id FROM projects WHERE id = %s AND user_id = %s", (project_id, user["sub"])).fetchone()
        if not row:
            raise HTTPException(404, "Project not found")

    await cancel_project_execution(
        project_id,
        sandbox,
        status_after_cancel="CANCELLED",
        narration="Project deleted by user.",
    )

    with get_conn() as conn:
            
        conn.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        conn.commit()

    # 2. Delete sandbox directory
    if os.path.exists(sandbox):
        try:
            shutil.rmtree(sandbox)
        except Exception as e:
            print(f"Failed to delete sandbox {sandbox}: {e}")
            
    return {"success": True}


@router.post("/{project_id}/run")
async def run_project_runtime(project_id: str, user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, status FROM projects WHERE id = %s AND user_id = %s",
            (project_id, user["sub"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Project not found")

    sandbox = os.path.join(settings.SANDBOX_BASE_DIR, project_id)
    if not os.path.isdir(sandbox):
        raise HTTPException(404, "Project files not found")

    try:
        runtime = await start_project_runtime(
            sandbox,
            backend_port=3001,
            frontend_port=3000,
            stop_existing=True,
        )
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc

    if not runtime.get("backend_ready") or not runtime.get("frontend_ready"):
        detail = (
            "Runtime start failed: services did not become reachable after auto-retries.\n\n"
            f"backend_ready={runtime.get('backend_ready')} frontend_ready={runtime.get('frontend_ready')}\n"
            f"attempts={runtime.get('attempts')}\n\n"
            "Backend log tail:\n"
            f"{runtime.get('server_log_tail') or '(empty)'}\n\n"
            "Frontend log tail:\n"
            f"{runtime.get('preview_log_tail') or '(empty)'}"
        )
        raise HTTPException(status_code=503, detail=detail)

    with get_conn() as conn:
        conn.execute(
            "UPDATE projects SET last_narration=%s, updated_at=NOW() WHERE id=%s",
            ("Runtime started (npm run dev + node --import tsx server/index.ts).", project_id),
        )
        conn.commit()

    return {
        "success": True,
        "project_id": project_id,
        "runtime": runtime,
    }


@router.post("/{project_id}/stop-runtime")
async def stop_project_runtime(project_id: str, user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM projects WHERE id = %s AND user_id = %s",
            (project_id, user["sub"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Project not found")

    sandbox = os.path.join(settings.SANDBOX_BASE_DIR, project_id)
    if not os.path.isdir(sandbox):
        return {"success": True, "stopped": False, "reason": "sandbox-missing"}

    killed = await terminate_sandbox_processes(sandbox)
    with get_conn() as conn:
        conn.execute(
            "UPDATE projects SET last_narration=%s, updated_at=NOW() WHERE id=%s",
            ("Runtime stopped.", project_id),
        )
        conn.commit()

    return {"success": True, "stopped": bool(killed), "killed_pids": killed}
