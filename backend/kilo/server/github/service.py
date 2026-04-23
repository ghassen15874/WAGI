import asyncio
import os
import re
import subprocess
import time
from typing import Any
from urllib.parse import quote

import aiohttp
from jose import jwt

from ..config import settings
from ..db import get_conn

GITHUB_API_BASE = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"


class GitHubDeployError(RuntimeError):
    pass


def github_oauth_is_configured() -> bool:
    return bool(settings.GITHUB_CLIENT_ID and settings.GITHUB_CLIENT_SECRET)


def github_app_is_configured() -> bool:
    return bool(settings.GITHUB_APP_ID and settings.GITHUB_PRIVATE_KEY)


def github_is_configured() -> bool:
    return github_oauth_is_configured()


def _normalized_private_key() -> str:
    return (settings.GITHUB_PRIVATE_KEY or "").replace("\\n", "\n").strip()


def create_github_app_jwt() -> str:
    if not github_app_is_configured():
        raise GitHubDeployError("GitHub App integration is not configured on the backend.")

    payload = {
        "iat": int(time.time()) - 60,
        "exp": int(time.time()) + 540,
        "iss": settings.GITHUB_APP_ID,
    }
    return jwt.encode(payload, _normalized_private_key(), algorithm="RS256")


async def _github_request(
    method: str,
    path: str,
    *,
    token: str = "",
    json_body: dict[str, Any] | None = None,
    acceptable_statuses: tuple[int, ...] = (200,),
) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        "User-Agent": "wagi-platform-github",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = path if path.startswith("https://") else f"{GITHUB_API_BASE}{path}"
    async with aiohttp.ClientSession() as session:
        async with session.request(method, url, headers=headers, json=json_body) as response:
            try:
                data = await response.json(content_type=None)
            except Exception:
                data = await response.text()

            if response.status not in acceptable_statuses:
                if isinstance(data, dict):
                    message = data.get("message") or str(data)
                else:
                    message = str(data)
                raise GitHubDeployError(message.strip() or f"GitHub request failed with status {response.status}")

            return data


async def fetch_github_profile(access_token: str) -> dict[str, Any]:
    data = await _github_request("GET", "/user", token=access_token, acceptable_statuses=(200,))
    if not isinstance(data, dict):
        raise GitHubDeployError("GitHub user profile response was invalid.")
    return data


async def fetch_github_primary_email(access_token: str) -> str:
    data = await _github_request("GET", "/user/emails", token=access_token, acceptable_statuses=(200,))
    if not isinstance(data, list):
        return ""

    primary = next((item for item in data if item.get("primary")), None)
    verified = next((item for item in data if item.get("verified")), None)
    chosen = primary or verified or (data[0] if data else {})
    return str(chosen.get("email", "") or "")


async def discover_installation_id(
    access_token: str,
    github_username: str,
    github_id: str,
) -> int | None:
    try:
        data = await _github_request("GET", "/user/installations", token=access_token, acceptable_statuses=(200,))
        installations = data.get("installations", []) if isinstance(data, dict) else []
        for installation in installations:
            account = installation.get("account", {}) or {}
            if (
                str(account.get("id", "")) == str(github_id)
                or str(account.get("login", "")).lower() == github_username.lower()
            ):
                return int(installation["id"])
        if len(installations) == 1:
            return int(installations[0]["id"])
    except Exception:
        pass

    if not github_app_is_configured():
        return None

    try:
        app_jwt = create_github_app_jwt()
        installations = await _github_request("GET", "/app/installations", token=app_jwt, acceptable_statuses=(200,))
        if isinstance(installations, list):
            for installation in installations:
                account = installation.get("account", {}) or {}
                if (
                    str(account.get("id", "")) == str(github_id)
                    or str(account.get("login", "")).lower() == github_username.lower()
                ):
                    return int(installation["id"])
    except Exception:
        return None

    return None


async def get_installation_token(installation_id: int) -> str:
    app_jwt = create_github_app_jwt()
    data = await _github_request(
        "POST",
        f"/app/installations/{installation_id}/access_tokens",
        token=app_jwt,
        json_body={},
        acceptable_statuses=(201,),
    )
    token = str(data.get("token", "") or "")
    if not token:
        raise GitHubDeployError("GitHub installation token was missing from the response.")
    return token


def _slugify_repo_name(project_name: str, project_id: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (project_name or "").lower()).strip("-")
    if not base:
        base = "ai-generated-project"
    return f"{base[:48]}-{project_id[:8]}".strip("-")


async def _create_repository_with_user_token(
    *,
    access_token: str,
    username: str,
    project_name: str,
    project_id: str,
    existing_repo_name: str = "",
) -> tuple[str, str]:
    repo_name = existing_repo_name or _slugify_repo_name(project_name, project_id)
    payload = {
        "name": repo_name,
        "private": True,
        "description": f"AI generated project for {project_name or project_id}",
        "auto_init": False,
    }

    try:
        data = await _github_request(
            "POST",
            "/user/repos",
            token=access_token,
            json_body=payload,
            acceptable_statuses=(201,),
        )
        return repo_name, str(data.get("html_url", "") or f"https://github.com/{username}/{repo_name}")
    except GitHubDeployError as exc:
        message = str(exc).lower()
        if "name already exists" not in message and "already exists on this account" not in message:
            raise

    data = await _github_request(
        "GET",
        f"/repos/{username}/{repo_name}",
        token=access_token,
        acceptable_statuses=(200,),
    )
    return repo_name, str(data.get("html_url", "") or f"https://github.com/{username}/{repo_name}")


def _run_command(command: list[str], cwd: str) -> None:
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        stdout = completed.stdout.strip()
        message = stderr or stdout or f"Command failed: {' '.join(command)}"
        raise GitHubDeployError(message)


def _push_repository(
    project_path: str,
    *,
    github_username: str,
    repo_name: str,
    auth_token: str,
    commit_email: str,
    token_mode: str,
) -> None:
    if not os.path.isdir(project_path):
        raise GitHubDeployError("Project directory does not exist.")

    auth_user = "x-access-token" if token_mode == "installation" else (github_username or "oauth2")
    remote_url = (
        f"https://{quote(auth_user, safe='')}:{quote(auth_token, safe='')}"
        f"@github.com/{github_username}/{repo_name}.git"
    )

    _run_command(["git", "init"], project_path)
    _run_command(["git", "config", "user.name", github_username or "AI Builder"], project_path)
    _run_command(["git", "config", "user.email", commit_email or "github-actions@users.noreply.github.com"], project_path)
    _run_command(["git", "add", "."], project_path)

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=project_path,
        text=True,
        capture_output=True,
        check=False,
    )
    has_changes = bool(status.stdout.strip())

    head_exists = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=project_path,
        text=True,
        capture_output=True,
        check=False,
    ).returncode == 0

    if has_changes or not head_exists:
        commit_command = ["git", "commit", "-m", "AI generated project"]
        if not head_exists:
            commit_command.insert(2, "--allow-empty")
        _run_command(commit_command, project_path)

    _run_command(["git", "branch", "-M", "main"], project_path)

    existing_remote = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=project_path,
        text=True,
        capture_output=True,
        check=False,
    )
    if existing_remote.returncode == 0:
        _run_command(["git", "remote", "remove", "origin"], project_path)

    _run_command(["git", "remote", "add", "origin", remote_url], project_path)
    _run_command(["git", "push", "-u", "origin", "main"], project_path)


async def deploy_to_github(
    project_id: str,
    project_path: str,
    *,
    access_token: str = "",
) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT
                p.id AS project_id,
                p.name AS project_name,
                p.github_repo_name,
                p.github_repo_url,
                u.id AS user_id,
                u.email,
                u.github_id,
                u.github_username,
                u.github_connected,
                u.github_installation_id
            FROM projects p
            JOIN users u ON u.id = p.user_id
            WHERE p.id = %s
            """,
            (project_id,),
        ).fetchone()

    if not row:
        raise GitHubDeployError("Project not found for GitHub deployment.")

    project = dict(row)
    if not project.get("github_connected"):
        return None

    github_username = str(project.get("github_username", "") or "")
    if not github_username:
        raise GitHubDeployError("GitHub account is linked, but the GitHub username is missing.")

    installation_id = project.get("github_installation_id")
    if not installation_id and access_token:
        installation_id = await discover_installation_id(
            access_token,
            github_username,
            str(project.get("github_id", "") or ""),
        )
        if installation_id:
            with get_conn() as conn:
                conn.execute(
                    "UPDATE users SET github_installation_id=%s, updated_at=NOW() WHERE id=%s",
                    (installation_id, project["user_id"]),
                )
                conn.commit()

    repo_name = str(project.get("github_repo_name", "") or "")
    repo_url = str(project.get("github_repo_url", "") or "")

    if not repo_name:
        if not access_token:
            return None
        repo_name, repo_url = await _create_repository_with_user_token(
            access_token=access_token,
            username=github_username,
            project_name=str(project.get("project_name", "") or ""),
            project_id=project_id,
        )

    auth_token = ""
    token_mode = "installation"
    if installation_id:
        try:
            auth_token = await get_installation_token(int(installation_id))
        except Exception:
            if access_token:
                auth_token = access_token
                token_mode = "user"
            else:
                raise
    elif access_token:
        auth_token = access_token
        token_mode = "user"

    if not auth_token:
        return None

    if not repo_url:
        repo_url = f"https://github.com/{github_username}/{repo_name}"

    try:
        await asyncio.to_thread(
            _push_repository,
            project_path,
            github_username=github_username,
            repo_name=repo_name,
            auth_token=auth_token,
            commit_email=str(project.get("email", "") or ""),
            token_mode=token_mode,
        )
    except Exception as exc:
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE projects
                SET github_repo_name=%s,
                    github_repo_url=%s,
                    github_deploy_status='FAILED',
                    github_deploy_error=%s,
                    updated_at=NOW()
                WHERE id=%s
                """,
                (repo_name, repo_url, str(exc)[:4000], project_id),
            )
            conn.commit()
        raise

    with get_conn() as conn:
        conn.execute(
            """
            UPDATE projects
            SET github_repo_name=%s,
                github_repo_url=%s,
                github_deploy_status='DEPLOYED',
                github_deploy_error='',
                updated_at=NOW()
            WHERE id=%s
            """,
            (repo_name, repo_url, project_id),
        )
        conn.commit()

    return {
        "repo_name": repo_name,
        "repo_url": repo_url,
        "token_mode": token_mode,
    }
