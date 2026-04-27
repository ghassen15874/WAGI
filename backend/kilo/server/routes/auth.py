"""Auth router — register, login, logout, me."""
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, EmailStr
import bcrypt

from ..db import get_conn, row_to_dict
from ..auth.jwt import create_access_token
from ..auth.middleware import get_current_user
from ..billing import ensure_user_subscription

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


def _user_out(row: dict) -> dict:
    return {
        "id": row["id"],
        "email": row["email"],
        "role": row["role"],
        "isActive": bool(row["is_active"]),
        "githubConnected": bool(row.get("github_connected", False)),
        "githubUsername": row.get("github_username", "") or "",
        "planId": row.get("plan_id", "free") or "free",
        "planName": row.get("plan_name", "Free") or "Free",
        "createdAt": row["created_at"],
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest):
    email = req.email.lower().strip()
    if len(req.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")

    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone()
        if existing:
            raise HTTPException(400, "Email already registered")

        user_id = str(uuid.uuid4())
        pw_hash = bcrypt.hashpw(req.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        now = datetime.utcnow().isoformat()
        conn.execute(
            "INSERT INTO users (id, email, password_hash, role, is_active, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (user_id, email, pw_hash, "USER", True, now, now),
        )
        conn.commit()

        # Auto-create empty pipeline config
        config_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO pipeline_configs (id, user_id) VALUES (%s,%s)",
            (config_id, user_id),
        )
        conn.commit()

        ensure_user_subscription(user_id)

        # Log event
        conn.execute(
            "INSERT INTO logs (id, user_id, event, detail, level) VALUES (%s,%s,%s,%s,%s)",
            (str(uuid.uuid4()), user_id, "user.register", f"email={email}", "info"),
        )
        conn.commit()

        token = create_access_token({"sub": user_id, "email": email, "role": "USER"})
        return {
            "token": token,
            "user": {
                "id": user_id,
                "email": email,
                "role": "USER",
                "isActive": True,
                "planId": "free",
                "planName": "Free",
            },
        }


@router.post("/login")
async def login(req: LoginRequest):
    email = req.email.lower().strip()
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT
                users.*,
                user_subscriptions.plan_id,
                subscription_plans.name AS plan_name
            FROM users
            LEFT JOIN user_subscriptions ON user_subscriptions.user_id = users.id
            LEFT JOIN subscription_plans ON subscription_plans.id = user_subscriptions.plan_id
            WHERE users.email = %s
            """,
            (email,),
        ).fetchone()
        if not row or not bcrypt.checkpw(req.password.encode('utf-8'), row["password_hash"].encode('utf-8')):
            raise HTTPException(401, "Invalid email or password")
        if not row["is_active"]:
            raise HTTPException(403, "Account suspended")
        user = dict(row)
        ensure_user_subscription(user["id"])
        if not user.get("plan_id"):
            user["plan_id"] = "free"
            user["plan_name"] = "Free"
        conn.execute(
            "INSERT INTO logs (id, user_id, event, level) VALUES (%s,%s,%s,%s)",
            (str(uuid.uuid4()), user["id"], "user.login", "info"),
        )
        conn.commit()
        token = create_access_token({"sub": user["id"], "email": user["email"], "role": user["role"]})
        return {"token": token, "user": _user_out(user)}


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user)):
    ensure_user_subscription(current_user["sub"])
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT
                users.*,
                user_subscriptions.plan_id,
                subscription_plans.name AS plan_name
            FROM users
            LEFT JOIN user_subscriptions ON user_subscriptions.user_id = users.id
            LEFT JOIN subscription_plans ON subscription_plans.id = user_subscriptions.plan_id
            WHERE users.id = %s
            """,
            (current_user["sub"],),
        ).fetchone()
        if not row:
            raise HTTPException(404, "User not found")
        return _user_out(dict(row))


@router.post("/logout")
async def logout():
    # JWT is stateless — client simply discards token
    return {"message": "Logged out"}
