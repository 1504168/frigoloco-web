"""Authentication routes: login and current-user.

This router is included WITHOUT the ``get_current_user`` dependency (see
``app.main``) so ``/login`` is reachable without a token.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.master import User
from app.security import create_access_token, get_current_user, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Exchange email + password for a signed access token."""
    email = payload.email.strip().lower()
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    password_matches = user is not None and verify_password(payload.password, user.password_hash)
    if not password_matches or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid email or password"
        )
    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserOut)
def read_current_user(current_user: User = Depends(get_current_user)) -> UserOut:
    """Return the authenticated user (used by the frontend to validate a token)."""
    return UserOut(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role.value,
    )
