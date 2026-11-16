"""Admin-only user management: list, create, update login accounts.

The whole router is gated by :func:`require_admin`, so only users with the
``admin`` role can reach any of these endpoints (non-admins get 403).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.enums import UserRole
from app.models.master import User
from app.security import hash_password, require_admin

router = APIRouter(
    prefix="/api/v1/users",
    tags=["users"],
    dependencies=[Depends(require_admin)],
)

_VALID_ROLES = {role.value for role in UserRole}


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    is_active: bool


class CreateUserRequest(BaseModel):
    email: str
    full_name: str
    password: str
    role: str = UserRole.admin.value


class UpdateUserRequest(BaseModel):
    full_name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)) -> list[UserOut]:
    """List all user accounts, oldest first."""
    users = db.execute(select(User).order_by(User.id)).scalars().all()
    return [_to_out(user) for user in users]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: CreateUserRequest, db: Session = Depends(get_db)) -> UserOut:
    """Create a new user account (admin only)."""
    role = _validate_role(payload.role)
    email = payload.email.strip().lower()
    if not payload.password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="password required"
        )
    exists = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email already exists")
    user = User(
        email=email,
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _to_out(user)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UpdateUserRequest,
    db: Session = Depends(get_db),
) -> UserOut:
    """Update a user's name, role, active state, or password (admin only)."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    if payload.full_name is not None:
        user.full_name = payload.full_name.strip()
    if payload.role is not None:
        user.role = _validate_role(payload.role)
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password:
        user.password_hash = hash_password(payload.password)
    db.commit()
    db.refresh(user)
    return _to_out(user)


def _validate_role(role: str) -> UserRole:
    if role not in _VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid role; choose one of {sorted(_VALID_ROLES)}",
        )
    return UserRole(role)


def _to_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        is_active=user.is_active,
    )
