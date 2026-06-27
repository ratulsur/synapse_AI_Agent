"""Authentication routes: register, login, and current-user.

DTOs
----
RegisterRequest  -- email + password + optional display_name
LoginRequest     -- email + password
TokenResponse    -- access_token + token_type
UserResponse     -- id + email + display_name + created_at

Routes
------
POST /auth/register  → 201 TokenResponse
POST /auth/login     → 200 TokenResponse
GET  /auth/me        → 200 UserResponse

Security notes
--------------
- Login returns the same 401 "Invalid credentials" message regardless of
  whether the email is unknown or the password is wrong (no user enumeration).
- All emails are lowercased before storage and lookup.
- Passwords are never logged or returned to the client.

Owner: Ratul Sur
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from db.models import User
from db.session import get_session
from log import GLOBAL_LOGGER as log

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_session),
) -> TokenResponse:
    """Register a new user and return a JWT access token.

    Returns HTTP 409 if the email is already registered.
    """
    email = body.email.lower()

    # Check for existing account (case-insensitive)
    existing_result = await db.execute(
        select(User).where(func.lower(User.email) == email)
    )
    if existing_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists.",
        )

    user = User(
        email=email,
        hashed_password=hash_password(body.password),
        display_name=body.display_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    log.info("auth: user registered", user_id=str(user.id))
    token = create_access_token(user.id, user.email)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_session),
) -> TokenResponse:
    """Authenticate a user and return a JWT access token.

    Returns HTTP 401 with a generic message on both unknown-email and
    wrong-password cases to prevent user enumeration.
    """
    email = body.email.lower()

    result = await db.execute(select(User).where(func.lower(User.email) == email))
    user = result.scalar_one_or_none()

    # Always call verify_password regardless of whether the user exists so the
    # response time is constant and cannot be used to enumerate valid emails.
    # _DUMMY_HASH is a real bcrypt hash (60 chars); passlib raises on malformed hashes.
    _DUMMY_HASH = "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW"  # noqa: S105
    check_hash = user.hashed_password if user is not None else _DUMMY_HASH
    password_ok = verify_password(body.password, check_hash)
    if user is None or not password_ok:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user.last_login = datetime.now(timezone.utc)
    await db.commit()

    log.info("auth: user logged in", user_id=str(user.id))
    token = create_access_token(user.id, user.email)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def me(
    user: User = Depends(get_current_user),
) -> UserResponse:
    """Return the profile of the currently authenticated user."""
    return UserResponse(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        created_at=user.created_at,
    )
