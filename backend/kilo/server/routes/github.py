import logging
import os
from datetime import timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from ..auth.jwt import create_access_token, verify_token
from ..auth.middleware import get_current_user
from ..config import settings
from ..db import get_conn
from ..github.service import (
    GitHubDeployError,
    deploy_to_github,
    discover_installation_id,
    fetch_github_primary_email,
    fetch_github_profile,
    github_app_is_configured,
    github_is_configured,
)

router = APIRouter(tags=["github"])
_oauth_client = None
logger = logging.getLogger(__name__)


class GitHubPrepareRequest(BaseModel):
    projectId: str = ""
    frontendUrl: str = ""


def _resolve_frontend_url(candidate: str = "") -> str:
    value = str(candidate or "").strip()
    if value.startswith("http://") or value.startswith("https://"):
        return value.rstrip("/")
    return settings.FRONTEND_URL.rstrip("/")


def _get_oauth_client():
    global _oauth_client
    if _oauth_client is not None:
        return _oauth_client

    try:
        from authlib.integrations.starlette_client import OAuth
    except ImportError as exc:
        raise HTTPException(503, "Authlib is not installed on the backend.") from exc

    oauth = OAuth()
    oauth.register(
        name="github",
        client_id=settings.GITHUB_CLIENT_ID,
        client_secret=settings.GITHUB_CLIENT_SECRET,
        access_token_url="https://github.com/login/oauth/access_token",
        authorize_url="https://github.com/login/oauth/authorize",
        api_base_url="https://api.github.com/",
        client_kwargs={'timeout': 30.0},
    )
    _oauth_client = oauth
    return _oauth_client


def _github_dashboard_redirect(*, repo_url: str = "", error: str = "", frontend_url: str = "") -> str:
    params = {}
    if repo_url:
        params["repo"] = repo_url
    if error:
        params["github_error"] = error

    base = f"{_resolve_frontend_url(frontend_url)}/dashboard"
    if not params:
        return base
    return f"{base}?{urlencode(params)}"


def _github_auth_redirect(*, token: str = "", error: str = "", frontend_url: str = "") -> str:
    params = {}
    if token:
        params["token"] = token
    if error:
        params["github_error"] = error

    base = f"{_resolve_frontend_url(frontend_url)}/login"
    if not params:
        return base
    return f"{base}?{urlencode(params)}"


def _require_github_config() -> None:
    if not github_is_configured():
        raise HTTPException(503, "GitHub OAuth is not configured on the backend.")


def _resolve_project_id_for_user(user_id: str, project_id: str) -> str:
    with get_conn() as conn:
        if project_id:
            row = conn.execute(
                "SELECT id FROM projects WHERE id=%s AND user_id=%s",
                (project_id, user_id),
            ).fetchone()
            if not row:
                raise HTTPException(404, "Project not found")
            return str(row["id"])

        row = conn.execute(
            """
            SELECT id
            FROM projects
            WHERE user_id=%s AND status <> 'GENERATING'
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "No completed project is available to deploy yet.")
        return str(row["id"])


@router.post("/api/github/prepare")
async def prepare_github_deploy(req: GitHubPrepareRequest, user: dict = Depends(get_current_user)):
    _require_github_config()

    project_id = _resolve_project_id_for_user(user["sub"], req.projectId.strip())
    context_token = create_access_token(
        {"sub": user["sub"], "scope": "github_oauth", "project_id": project_id},
        expires_delta=timedelta(minutes=15),
    )
    params = {"ctx": context_token}
    frontend_url = _resolve_frontend_url(req.frontendUrl)
    if frontend_url:
        params["frontend"] = frontend_url
    return {"redirect_url": f"{settings.BACKEND_PUBLIC_URL.rstrip('/')}/auth/github?{urlencode(params)}"}


@router.get("/auth/github")
async def github_login(request: Request, ctx: str = "", frontend: str = ""):
    _require_github_config()

    frontend_url = _resolve_frontend_url(frontend)

    if ctx:
        payload = verify_token(ctx)
        if not payload or payload.get("scope") != "github_oauth":
            raise HTTPException(400, "GitHub authorization context is missing or expired.")

        request.session["github_oauth_context"] = {
            "mode": "deploy",
            "user_id": payload["sub"],
            "project_id": payload.get("project_id", ""),
            "frontend_url": frontend_url,
        }
        scope = settings.GITHUB_DEPLOY_SCOPE or settings.GITHUB_OAUTH_SCOPE or "user:email repo"
    else:
        request.session["github_oauth_context"] = {
            "mode": "auth",
            "user_id": "",
            "project_id": "",
            "frontend_url": frontend_url,
        }
        scope = settings.GITHUB_AUTH_SCOPE or settings.GITHUB_OAUTH_SCOPE or "user:email"

    redirect_uri = f"{settings.BACKEND_PUBLIC_URL.rstrip('/')}/auth/github/callback"
    oauth = _get_oauth_client()
    return await oauth.github.authorize_redirect(request, redirect_uri, scope=scope)


@router.get("/auth/github/callback")
async def github_callback(request: Request):
    _require_github_config()

    context = request.session.pop("github_oauth_context", None) or {}
    mode = str(context.get("mode", "auth") or "auth")
    user_id = str(context.get("user_id", "") or "")
    project_id = str(context.get("project_id", "") or "")
    frontend_url = _resolve_frontend_url(str(context.get("frontend_url", "") or ""))
    if mode == "deploy" and not user_id:
        return RedirectResponse(_github_dashboard_redirect(error="GitHub authorization context expired. Try again.", frontend_url=frontend_url))

    try:
        oauth = _get_oauth_client()
        token = await oauth.github.authorize_access_token(request)
        access_token = str(token.get("access_token", "") or "")
        if not access_token:
            raise GitHubDeployError("GitHub did not return an access token.")

        github_user = await fetch_github_profile(access_token)
        await fetch_github_primary_email(access_token)
        github_id = str(github_user.get("id", "") or "")
        github_username = str(github_user.get("login", "") or "")
        primary_email = await fetch_github_primary_email(access_token)
        if not github_id or not github_username:
            raise GitHubDeployError("GitHub user profile was incomplete.")

        installation_id = await discover_installation_id(access_token, github_username, github_id)

        with get_conn() as conn:
            if mode == "deploy":
                row = conn.execute("SELECT id FROM users WHERE id=%s", (user_id,)).fetchone()
                if not row:
                    raise GitHubDeployError("Current app user was not found.")

                existing = conn.execute(
                    "SELECT id FROM users WHERE github_id=%s AND id<>%s",
                    (github_id, user_id),
                ).fetchone()
                if existing:
                    raise GitHubDeployError("This GitHub account is already linked to another user.")

                conn.execute(
                    """
                    UPDATE users
                    SET github_id=%s,
                        github_username=%s,
                        github_connected=TRUE,
                        github_installation_id=%s,
                        updated_at=NOW()
                    WHERE id=%s
                    """,
                    (github_id, github_username, installation_id, user_id),
                )
                conn.commit()
            else:
                existing_user = conn.execute(
                    "SELECT * FROM users WHERE github_id=%s",
                    (github_id,),
                ).fetchone()

                if not existing_user and primary_email:
                    existing_user = conn.execute(
                        "SELECT * FROM users WHERE email=%s",
                        (primary_email.lower().strip(),),
                    ).fetchone()

                if existing_user:
                    user_id = str(existing_user["id"])
                    conn.execute(
                        """
                        UPDATE users
                        SET github_id=%s,
                            github_username=%s,
                            github_connected=TRUE,
                            github_installation_id=%s,
                            updated_at=NOW()
                        WHERE id=%s
                        """,
                        (github_id, github_username, installation_id, user_id),
                    )
                else:
                    if not primary_email:
                        raise GitHubDeployError("Your GitHub account does not expose a usable email address.")
                    import uuid
                    from datetime import datetime

                    user_id = str(uuid.uuid4())
                    now = datetime.utcnow().isoformat()
                    conn.execute(
                        """
                        INSERT INTO users (
                            id, email, password_hash, github_id, github_username,
                            github_connected, github_installation_id, role, is_active, created_at, updated_at
                        )
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (
                            user_id,
                            primary_email.lower().strip(),
                            "",
                            github_id,
                            github_username,
                            True,
                            installation_id,
                            "USER",
                            True,
                            now,
                            now,
                        ),
                    )
                    config_id = str(uuid.uuid4())
                    conn.execute(
                        "INSERT INTO pipeline_configs (id, user_id) VALUES (%s,%s)",
                        (config_id, user_id),
                    )
                conn.commit()

        if mode != "deploy":
            with get_conn() as conn:
                user_row = conn.execute("SELECT * FROM users WHERE id=%s", (user_id,)).fetchone()
            if not user_row:
                raise GitHubDeployError("GitHub login succeeded but local user lookup failed.")

            auth_token = create_access_token({
                "sub": user_row["id"],
                "email": user_row["email"],
                "role": user_row["role"],
            })
            return RedirectResponse(_github_auth_redirect(token=auth_token, frontend_url=frontend_url))

        if not project_id:
            return RedirectResponse(_github_dashboard_redirect(error="No project was selected for deployment.", frontend_url=frontend_url))

        project_path = os.path.join(settings.SANDBOX_BASE_DIR, project_id)
        if not os.path.isdir(project_path):
            raise GitHubDeployError("Project files were not found on disk.")

        result = await deploy_to_github(project_id, project_path, access_token=access_token)
        repo_url = result.get("repo_url", "") if result else ""
        if not repo_url:
            raise GitHubDeployError(
                "GitHub account linked, but no repository is linked to this project yet. "
                + (
                    "Try again after ensuring the GitHub App is installed."
                    if github_app_is_configured()
                    else "Try again after reconnecting GitHub."
                )
            )

        return RedirectResponse(_github_dashboard_redirect(repo_url=repo_url, frontend_url=frontend_url))
    except Exception as exc:
        message = str(exc).strip() or "GitHub deployment failed."
        if mode == "deploy" and message.lower() == "not found":
            message = "GitHub deploy needs repository permission. Reconnect GitHub and approve repository access."
        logger.exception("GitHub OAuth callback failed (mode=%s): %s", mode, message)
        if mode == "deploy":
            return RedirectResponse(_github_dashboard_redirect(error=message, frontend_url=frontend_url))
        return RedirectResponse(_github_auth_redirect(error=message, frontend_url=frontend_url))
