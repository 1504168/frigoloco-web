"""Authentication primitives: bcrypt password hashing and JWT issue/verify.

The FastAPI dependency :func:`get_current_user` is attached to every API router
(see ``app.main``) except the auth router, so all ``/api/v1/*`` endpoints require
a valid Bearer token. ``/health`` stays open.
"""

from __future__ import annotations

import datetime

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models.enums import UserRole
from app.models.master import User

JWT_ALGORITHM = "HS256"

_bearer_scheme = HTTPBearer(auto_error=True)
_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="invalid or expired token",
    headers={"WWW-Authenticate": "Bearer"},
)


def hash_password(plain_password: str) -> str:
    """Return a bcrypt hash of ``plain_password`` (safe to store)."""
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Return True if ``plain_password`` matches the stored bcrypt ``password_hash``."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: int) -> str:
    """Issue a signed JWT carrying the user id and an expiry."""
    settings = get_settings()
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + datetime.timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the authenticated, active user from the Bearer token, or raise 401."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            credentials.credentials, settings.secret_key, algorithms=[JWT_ALGORITHM]
        )
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise _CREDENTIALS_EXCEPTION
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _CREDENTIALS_EXCEPTION
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency that allows only admin users through (403 otherwise)."""
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="admin privileges required"
        )
    return current_user
