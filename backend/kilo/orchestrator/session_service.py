"""Session lifecycle helpers for generation runs."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import signal
import urllib.error
import urllib.request
from typing import AsyncIterator

from fastapi import HTTPException

from ..server.auth.encryption import decrypt_key
from ..server.config import settings
from ..server.db import get_conn

ACTIVE_GENERATIONS: dict[str, asyncio.Task] = {}


def _local_generation_active(project_id: str) -> bool:
    task = ACTIVE_GENERATIONS.get(project_id)
    return bool(task and not task.done())


def collect_project_files(sandbox: str) -> dict[str, str]:
    files: dict[str, str] = {}
    for root, dirs, fnames in os.walk(sandbox):
        dirs[:] = [d for d in dirs if d not in ("node_modules", ".git") and not d.startswith(".")]
        for fname in fnames:
            if fname.startswith("."):
                continue
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, sandbox)
            try:
                with open(fpath, encoding="utf-8", errors="ignore") as handle:
                    content = handle.read()
                    if content:
                        files[rel] = content
            except Exception:
                continue
    return files


def resume_iteration_from_log(log_path: str) -> int:
    if not os.path.exists(log_path):
        return 0

    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as handle:
            content = handle.read()[-200_000:]
    except Exception:
        return 0

    completed_matches = re.findall(r"Iteration\s+(\d+)\s+complete", content)
    if completed_matches:
        return max(0, int(completed_matches[-1]))

    started_matches = re.findall(r"Iteration\s+(\d+)/(\d+)", content)
    if started_matches:
        last_started = int(started_matches[-1][0])
        return max(0, last_started - 1)

    return 0


def hydrate_user_provider_keys(user_id: str) -> dict[str, str]:
    grouped: dict[str, list[str]] = {}
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT provider, encrypted_key
            FROM api_keys
            WHERE user_id = %s
            ORDER BY created_at ASC, id ASC
            """,
            (user_id,),
        ).fetchall()

    for row in rows:
        provider = str(row["provider"]).lower()
        key = decrypt_key(row["encrypted_key"])
        if key.strip():
            grouped.setdefault(provider, []).append(key.strip())

    return {provider: ",".join(keys) for provider, keys in grouped.items()}


def validate_registry_selection(provider_id: str, model_id: str, *, require_registered_model: bool = True) -> None:
    with get_conn() as conn:
        provider_row = conn.execute(
            "SELECT id, enabled FROM provider_registry WHERE id = %s",
            (provider_id,),
        ).fetchone()
        if not provider_row:
            raise HTTPException(400, f"Unknown provider: {provider_id}")
        if not provider_row["enabled"]:
            raise HTTPException(403, f"Provider '{provider_id}' is disabled by admin")

        if provider_id == "auto":
            return

        if require_registered_model and model_id:
            model_row = conn.execute(
                "SELECT id, provider_id, model_id, enabled FROM model_registry WHERE provider_id = %s AND model_id = %s",
                (provider_id, model_id),
            ).fetchone()
            if not model_row:
                raise HTTPException(400, f"Unknown model: {model_id}")
            if not model_row["enabled"]:
                raise HTTPException(403, f"Model '{model_id}' is disabled by admin")


def _collect_sandbox_processes(sandbox: str) -> list[int]:
    sandbox_real = os.path.realpath(sandbox)
    if not sandbox_real or not os.path.exists(sandbox_real):
        return []

    current_pid = os.getpid()
    pids: list[int] = []

    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue

        pid = int(entry)
        if pid == current_pid:
            continue

        proc_dir = os.path.join("/proc", entry)
        cwd_path = os.path.join(proc_dir, "cwd")
        cmdline_path = os.path.join(proc_dir, "cmdline")

        try:
            proc_cwd = os.path.realpath(os.readlink(cwd_path))
        except Exception:
            proc_cwd = ""

        try:
            with open(cmdline_path, "rb") as handle:
                cmdline = handle.read().decode("utf-8", errors="ignore").replace("\x00", " ")
        except Exception:
            cmdline = ""

        if (proc_cwd and proc_cwd.startswith(sandbox_real)) or (cmdline and sandbox_real in cmdline):
            pids.append(pid)

    return pids


async def terminate_sandbox_processes(sandbox: str) -> list[int]:
    pids = _collect_sandbox_processes(sandbox)
    if not pids:
        return []

    for pid in pids:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGTERM)

    await asyncio.sleep(0.5)

    remaining = _collect_sandbox_processes(sandbox)
    for pid in remaining:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGKILL)

    return pids


def _runtime_log_paths(sandbox: str) -> tuple[str, str]:
    lovable_dir = os.path.join(sandbox, ".lovable")
    os.makedirs(lovable_dir, exist_ok=True)
    return (
        os.path.join(lovable_dir, "runtime_server.log"),
        os.path.join(lovable_dir, "runtime_preview.log"),
    )


def _read_log_tail(path: str, *, max_chars: int = 4000) -> str:
    if not path or not os.path.isfile(path):
        return ""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            if size > max_chars:
                handle.seek(size - max_chars)
            raw = handle.read()
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _looks_like_frontend_bus_error(log_text: str) -> bool:
    lowered = str(log_text or "").lower()
    return "bus error" in lowered or "sigbus" in lowered


def _pin_rollup_wasm_for_runtime(sandbox: str) -> bool:
    package_json_path = os.path.join(sandbox, "package.json")
    if not os.path.isfile(package_json_path):
        return False

    try:
        with open(package_json_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return False

    dev_deps = payload.setdefault("devDependencies", {})
    target_value = "npm:@rollup/wasm-node@4.52.4"
    if dev_deps.get("rollup") == target_value:
        return False

    dev_deps["rollup"] = target_value
    try:
        with open(package_json_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
    except Exception:
        return False
    return True


async def _reinstall_runtime_after_rollup_wasm_fallback(sandbox: str, install_log: str) -> bool:
    install_cmd = (
        "sh -c '"
        "rm -rf node_modules/rollup node_modules/@rollup/rollup-* node_modules/.vite 2>/dev/null || true; "
        "npm install --legacy-peer-deps --no-audit --no-fund' "
        f"> '{install_log}' 2>&1"
    )
    proc = await asyncio.create_subprocess_shell(install_cmd, cwd=sandbox)
    try:
        await asyncio.wait_for(proc.wait(), timeout=300)
    except asyncio.TimeoutError:
        with contextlib.suppress(Exception):
            proc.kill()
        return False
    return proc.returncode == 0


def _collect_platform_sandbox_processes(exclude_sandbox: str | None = None) -> list[int]:
    base_real = os.path.realpath(settings.SANDBOX_BASE_DIR)
    exclude_real = os.path.realpath(exclude_sandbox) if exclude_sandbox else ""
    if not base_real or not os.path.exists(base_real):
        return []

    current_pid = os.getpid()
    pids: list[int] = []

    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue

        pid = int(entry)
        if pid == current_pid:
            continue

        proc_dir = os.path.join("/proc", entry)
        cwd_path = os.path.join(proc_dir, "cwd")
        cmdline_path = os.path.join(proc_dir, "cmdline")

        try:
            proc_cwd = os.path.realpath(os.readlink(cwd_path))
        except Exception:
            proc_cwd = ""

        try:
            with open(cmdline_path, "rb") as handle:
                cmdline = handle.read().decode("utf-8", errors="ignore").replace("\x00", " ")
        except Exception:
            cmdline = ""

        if not ((proc_cwd and proc_cwd.startswith(base_real)) or (cmdline and base_real in cmdline)):
            continue
        if exclude_real and ((proc_cwd and proc_cwd.startswith(exclude_real)) or (cmdline and exclude_real in cmdline)):
            continue
        pids.append(pid)

    return pids


async def terminate_all_sandbox_processes(exclude_sandbox: str | None = None) -> list[int]:
    pids = _collect_platform_sandbox_processes(exclude_sandbox=exclude_sandbox)
    if not pids:
        return []

    for pid in pids:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGTERM)

    await asyncio.sleep(0.5)

    remaining = _collect_platform_sandbox_processes(exclude_sandbox=exclude_sandbox)
    for pid in remaining:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGKILL)

    return pids


def _runtime_needs_install(sandbox: str) -> bool:
    node_modules_dir = os.path.join(sandbox, "node_modules")
    if not os.path.isdir(node_modules_dir):
        return True

    required_bins = (
        os.path.join(node_modules_dir, ".bin", "vite"),
        os.path.join(node_modules_dir, ".bin", "tsx"),
    )
    return any(not os.path.exists(path) for path in required_bins)


async def _ensure_runtime_dependencies(sandbox: str, install_log: str) -> None:
    if not _runtime_needs_install(sandbox):
        return

    install_cmd = (
        "sh -c 'npm install --no-audit --no-fund' "
        f"> '{install_log}' 2>&1"
    )
    proc = await asyncio.create_subprocess_shell(install_cmd, cwd=sandbox)
    try:
        await asyncio.wait_for(proc.wait(), timeout=300)
    except asyncio.TimeoutError as exc:
        with contextlib.suppress(Exception):
            proc.kill()
        raise RuntimeError("npm install timed out while preparing runtime.") from exc

    if proc.returncode != 0:
        raise RuntimeError("npm install failed while preparing runtime.")


def _http_ping(url: str, timeout: float = 2.0) -> bool:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(getattr(response, "status", 0) or 0) < 500
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False
    except Exception:
        return False


def _http_ping_any(urls: list[str], timeout: float = 2.0) -> bool:
    for url in urls:
        if _http_ping(url, timeout=timeout):
            return True
    return False


async def start_project_runtime(
    sandbox: str,
    *,
    backend_port: int = 3001,
    frontend_port: int = 3000,
    stop_existing: bool = True,
) -> dict:
    server_log, preview_log = _runtime_log_paths(sandbox)
    install_log = os.path.join(sandbox, ".lovable", "runtime_install.log")
    for log_path in (server_log, preview_log):
        with contextlib.suppress(Exception):
            with open(log_path, "w", encoding="utf-8"):
                pass
    with contextlib.suppress(Exception):
        with open(install_log, "w", encoding="utf-8"):
            pass

    await _ensure_runtime_dependencies(sandbox, install_log)

    backend_probe_urls = [
        f"http://127.0.0.1:{backend_port}/api/health",
        f"http://localhost:{backend_port}/api/health",
    ]
    frontend_probe_urls = [
        f"http://127.0.0.1:{frontend_port}/",
        f"http://localhost:{frontend_port}/",
    ]
    max_attempts = 3
    last_backend_ready = False
    last_frontend_ready = False
    last_server_tail = ""
    last_preview_tail = ""

    for attempt in range(1, max_attempts + 1):
        if stop_existing or attempt > 1:
            await terminate_sandbox_processes(sandbox)
            await terminate_all_sandbox_processes(exclude_sandbox=sandbox)
        for log_path in (server_log, preview_log):
            with contextlib.suppress(Exception):
                with open(log_path, "w", encoding="utf-8"):
                    pass

        backend_cmd = (
            "nohup sh -c '"
            f"PORT={backend_port} node --import tsx server/index.ts || "
            f"PORT={backend_port} npm run server || "
            f"PORT={backend_port} npx tsx server/index.ts || "
            f"PORT={backend_port} ./node_modules/.bin/tsx server/index.ts"
            f"' > '{server_log}' 2>&1 < /dev/null &"
        )
        preview_cmd = (
            "nohup sh -c '"
            f"npm run dev || "
            f"./node_modules/.bin/vite --host 127.0.0.1 --port {frontend_port} --strictPort || "
            f"npx vite --host 127.0.0.1 --port {frontend_port} --strictPort || "
            f"npm run preview -- --host 127.0.0.1 --port {frontend_port} --strictPort"
            f"' > '{preview_log}' 2>&1 < /dev/null &"
        )

        backend_proc = await asyncio.create_subprocess_shell(backend_cmd, cwd=sandbox)
        await backend_proc.wait()
        preview_proc = await asyncio.create_subprocess_shell(preview_cmd, cwd=sandbox)
        await preview_proc.wait()

        backend_ready = False
        frontend_ready = False
        for _ in range(40):
            if not backend_ready:
                backend_ready = _http_ping_any(backend_probe_urls, timeout=1.5)
            if not frontend_ready:
                frontend_ready = _http_ping_any(frontend_probe_urls, timeout=1.5)
            if backend_ready and frontend_ready:
                break
            await asyncio.sleep(1.0)

        last_backend_ready = bool(backend_ready)
        last_frontend_ready = bool(frontend_ready)
        last_server_tail = _read_log_tail(server_log)
        last_preview_tail = _read_log_tail(preview_log)

        if last_backend_ready and last_frontend_ready:
            return {
                "backend_port": int(backend_port),
                "frontend_port": int(frontend_port),
                "backend_url": f"http://localhost:{backend_port}",
                "frontend_url": f"http://localhost:{frontend_port}",
                "backend_ready": True,
                "frontend_ready": True,
                "attempts": attempt,
                "server_log": server_log,
                "preview_log": preview_log,
                "install_log": install_log,
                "server_log_tail": last_server_tail,
                "preview_log_tail": last_preview_tail,
            }

        # Frontend Rollup native binary can crash with SIGBUS on some hosts.
        # Auto-switch to WASM Rollup and retry startup before returning failure.
        if not last_frontend_ready and _looks_like_frontend_bus_error(last_preview_tail):
            patched = _pin_rollup_wasm_for_runtime(sandbox)
            if patched:
                await _reinstall_runtime_after_rollup_wasm_fallback(sandbox, install_log)
                continue

    return {
        "backend_port": int(backend_port),
        "frontend_port": int(frontend_port),
        "backend_url": f"http://localhost:{backend_port}",
        "frontend_url": f"http://localhost:{frontend_port}",
        "backend_ready": last_backend_ready,
        "frontend_ready": last_frontend_ready,
        "attempts": max_attempts,
        "server_log": server_log,
        "preview_log": preview_log,
        "install_log": install_log,
        "server_log_tail": last_server_tail,
        "preview_log_tail": last_preview_tail,
    }


async def cancel_project_execution(
    project_id: str,
    sandbox: str,
    *,
    status_after_cancel: str | None = "CANCELLED",
    narration: str = "Build stopped.",
) -> bool:
    task = ACTIVE_GENERATIONS.pop(project_id, None)
    had_running_task = bool(task and not task.done())

    if task and not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
            await asyncio.wait_for(task, timeout=5)

    killed_pids = await terminate_sandbox_processes(sandbox)

    if status_after_cancel:
        with contextlib.suppress(Exception):
            with get_conn() as conn:
                conn.execute(
                    "UPDATE projects SET status=%s, last_narration=%s, updated_at=NOW() WHERE id=%s",
                    (status_after_cancel, narration, project_id),
                )
                conn.commit()

    return had_running_task or bool(killed_pids)


async def cancel_other_user_generations(user_id: str, keep_project_id: str) -> int:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id
            FROM projects
            WHERE user_id = %s
              AND status = 'GENERATING'
              AND id <> %s
            """,
            (user_id, keep_project_id),
        ).fetchall()

    cancelled = 0
    for row in rows:
        project_id = str(row["id"])
        sandbox = os.path.join(settings.SANDBOX_BASE_DIR, project_id)
        stopped = await cancel_project_execution(
            project_id,
            sandbox,
            status_after_cancel="CANCELLED",
            narration="Stopped automatically because a newer build started.",
        )
        if stopped:
            cancelled += 1

    return cancelled


async def run_agent_background(agent, prompt: str, session_id: str, sandbox: str, *, resume: bool = False) -> None:
    log_path = os.path.join(sandbox, ".lovable", "build.log")

    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        if resume:
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write("\n▶ Resuming build from saved state...\n")
        else:
            with open(log_path, "w", encoding="utf-8"):
                pass
    except Exception as exc:
        print(f"Failed to init log file: {exc}")

    try:
        with get_conn() as conn:
            conn.execute("UPDATE projects SET status='GENERATING' WHERE id=%s", (session_id,))
            conn.commit()
    except Exception as exc:
        print(f"Background DB Error (Initial): {exc}")

    try:
        with open(log_path, "a", encoding="utf-8") as handle:
            async for chunk in agent.run(prompt):
                if not chunk:
                    continue
                handle.write(chunk)
                handle.flush()

                if any(emoji in chunk for emoji in ("⚙️", "🤖", "🛠️", "🎨", "✓")):
                    try:
                        with get_conn() as conn:
                            narration = (
                                chunk.strip()
                                .replace("⚙️", "")
                                .replace("🤖", "")
                                .replace("🛠️", "")
                                .replace("🎨", "")
                                .replace("✓", "")
                                .strip()
                            )
                            if narration:
                                conn.execute(
                                    "UPDATE projects SET last_narration=%s WHERE id=%s",
                                    (narration, session_id),
                                )
                                conn.commit()
                    except Exception:
                        pass

        github_repo_url = ""
        try:
            from ..server.github.service import deploy_to_github

            deployment = await deploy_to_github(session_id, sandbox)
            if deployment and deployment.get("repo_url"):
                github_repo_url = str(deployment["repo_url"])
                with open(log_path, "a", encoding="utf-8") as handle:
                    handle.write("\n✅ Project deployed to GitHub\n")
                    handle.write(f"🔗 {github_repo_url}\n")
                    handle.flush()
        except Exception as deploy_error:
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(f"\n⚠️ GitHub deployment skipped: {deploy_error}\n")
                handle.flush()

        try:
            with get_conn() as conn:
                narration = "Project deployed to GitHub." if github_repo_url else "Build completed."
                conn.execute(
                    "UPDATE projects SET status='COMPLETED', last_narration=%s WHERE id=%s",
                    (narration, session_id),
                )
                conn.commit()
        except Exception:
            pass
    except asyncio.CancelledError:
        try:
            with get_conn() as conn:
                conn.execute(
                    "UPDATE projects SET status='CANCELLED', error_message='', last_narration=%s WHERE id=%s",
                    ("Build cancelled.", session_id),
                )
                conn.commit()
        except Exception:
            pass

        try:
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write("\n🛑 Build cancelled by user.\n---LOG_CHUNK---\n")
                handle.flush()
        except Exception:
            pass

        raise
    except Exception as exc:
        print(f"Background Agent Error: {exc}")
        try:
            with get_conn() as conn:
                conn.execute("UPDATE projects SET status='FAILED', error_message=%s WHERE id=%s", (str(exc), session_id))
                conn.commit()
        except Exception:
            pass

        try:
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(f"\n❌ FATAL ERROR: {exc}\n")
                handle.flush()
        except Exception:
            pass
    finally:
        ACTIVE_GENERATIONS.pop(session_id, None)
        final_status = ""
        with contextlib.suppress(Exception):
            with get_conn() as conn:
                row = conn.execute(
                    "SELECT status FROM projects WHERE id=%s",
                    (session_id,),
                ).fetchone()
                if row:
                    final_status = str(row["status"] or "").upper()

        # Keep the runtime alive regardless of final status, so users can see the app (even if incomplete/failed)
        # as requested: "dont close until user get out from chat".
        keep_runtime_alive = True
        if not keep_runtime_alive:
            await terminate_sandbox_processes(sandbox)


def start_generation_task(agent, prompt: str, session_id: str, sandbox: str, *, resume: bool = False) -> asyncio.Task:
    task = asyncio.create_task(run_agent_background(agent, prompt, session_id, sandbox, resume=resume))
    ACTIVE_GENERATIONS[session_id] = task
    return task


async def iter_project_logs(project_id: str, sandbox: str, log_path: str, *, from_end: bool = False, byte_offset: int = 0) -> AsyncIterator[str]:
    wait_started = asyncio.get_running_loop().time()
    if not os.path.exists(log_path):
        yield "data: " + json.dumps({"type": "info", "content": "Waiting for engine..."}) + "\n\n"
        while not os.path.exists(log_path):
            try:
                with get_conn() as conn:
                    row = conn.execute(
                        "SELECT status, error_message FROM projects WHERE id=%s",
                        (project_id,),
                    ).fetchone()
                    if not row:
                        if _local_generation_active(project_id):
                            await asyncio.sleep(0.5)
                            continue
                        yield "data: " + json.dumps({"type": "info", "content": "Project was removed."}) + "\n\n"
                        yield "data: " + json.dumps({"type": "done"}) + "\n\n"
                        return
                    if row["status"] in ("COMPLETED", "FAILED"):
                        if row["status"] == "FAILED":
                            message = row["error_message"] or "Generation failed before logs became available."
                            yield "data: " + json.dumps({"type": "error", "message": message}) + "\n\n"
                        yield "data: " + json.dumps({"type": "files", "files": collect_project_files(sandbox), "session_id": project_id}) + "\n\n"
                        yield "data: " + json.dumps({"type": "done"}) + "\n\n"
                        return
                    if row["status"] == "CANCELLED":
                        yield "data: " + json.dumps({"type": "info", "content": "Build cancelled."}) + "\n\n"
                        yield "data: " + json.dumps({"type": "files", "files": collect_project_files(sandbox), "session_id": project_id}) + "\n\n"
                        yield "data: " + json.dumps({"type": "done"}) + "\n\n"
                        return
            except Exception:
                pass

            if asyncio.get_running_loop().time() - wait_started > 15:
                message = "Build log did not initialize. The worker may have stopped. Please retry."
                try:
                    with get_conn() as conn:
                        conn.execute(
                            "UPDATE projects SET status='FAILED', error_message=%s WHERE id=%s AND status='GENERATING'",
                            (message, project_id),
                        )
                        conn.commit()
                except Exception:
                    pass
                yield "data: " + json.dumps({"type": "error", "message": message}) + "\n\n"
                yield "data: " + json.dumps({"type": "done"}) + "\n\n"
                return
            await asyncio.sleep(0.5)

    with open(log_path, "r", encoding="utf-8") as handle:
        # Seek to reconnect position (Last-Event-ID byte offset) or end if from_end
        if byte_offset > 0:
            handle.seek(byte_offset)
        elif from_end:
            handle.seek(0, os.SEEK_END)
        while True:
            chunk = handle.read()
            if chunk:
                pos = handle.tell()
                # Emit SSE with 'id' so the browser can resume from this byte offset on reconnect
                yield f"id: {pos}\ndata: {json.dumps({'type': 'token', 'content': chunk})}\n\n"
                continue

            status = "IDLE"
            try:
                with get_conn() as conn:
                    row = conn.execute("SELECT status FROM projects WHERE id=%s", (project_id,)).fetchone()
                    if row:
                        status = row["status"]
                    elif _local_generation_active(project_id):
                        status = "GENERATING"
                    else:
                        status = "DELETED"
            except Exception:
                pass

            if status in ("COMPLETED", "FAILED", "CANCELLED", "DELETED"):
                files = collect_project_files(sandbox)
                yield "data: " + json.dumps({"type": "files", "files": files, "session_id": project_id}) + "\n\n"
                yield "data: " + json.dumps({"type": "done"}) + "\n\n"
                break

            await asyncio.sleep(0.5)
