import os

from fastapi import APIRouter, HTTPException

from ..config import settings

router = APIRouter(prefix="/api/files", tags=["files"])

@router.get("/list")
async def list_files(session_id: str = ""):
    sandbox = os.path.join(settings.SANDBOX_BASE_DIR, session_id) if session_id else settings.SANDBOX_BASE_DIR
    if not os.path.exists(sandbox):
        return {"files": []}
    files = []
    for root, dirs, fnames in os.walk(sandbox):
        dirs[:] = [d for d in dirs 
                   if d not in ("node_modules", ".git", ".lovable")]
        for fname in fnames:
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, sandbox)
            files.append(rel)
    return {"files": sorted(files)}

@router.get("/read")
async def read_file(path: str, session_id: str = ""):
    sandbox = os.path.join(settings.SANDBOX_BASE_DIR, session_id) if session_id else settings.SANDBOX_BASE_DIR
    full_path = os.path.join(sandbox, path.lstrip("/"))
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File not found")
    try:
        with open(full_path, encoding="utf-8", errors="ignore") as f:
            return {"path": path, "content": f.read()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
