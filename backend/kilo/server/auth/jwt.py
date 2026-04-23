"""Auth utilities — JWT token creation & verification."""
import os
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt

SECRET_KEY = os.getenv("JWT_SECRET", "dev-secret-change-in-production-please-use-long-random-string")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 72


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
