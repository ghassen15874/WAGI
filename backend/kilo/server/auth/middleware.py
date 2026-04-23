"""FastAPI dependencies for authentication."""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .jwt import verify_token
from ..db import get_conn

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict:
    if not creds:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = verify_token(creds.credentials)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, email, role, is_active FROM users WHERE id = %s",
            (payload["sub"],),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if not row["is_active"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account suspended")

    return {
        "sub": row["id"],
        "email": row["email"],
        "role": row["role"],
        "isActive": bool(row["is_active"]),
    }


async def get_current_user_optional(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict | None:
    if not creds:
        return None
    payload = verify_token(creds.credentials)
    if not payload:
        return None

    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, email, role, is_active FROM users WHERE id = %s",
            (payload["sub"],),
        ).fetchone()

    if not row or not row["is_active"]:
        return None

    return {
        "sub": row["id"],
        "email": row["email"],
        "role": row["role"],
        "isActive": bool(row["is_active"]),
    }


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "ADMIN":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user
