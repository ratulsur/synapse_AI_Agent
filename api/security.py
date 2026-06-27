"""Authentication utilities: password hashing, JWT tokens, FastAPI dependencies.

Design notes
------------
- Passwords are hashed with bcrypt via passlib; the 72-byte input limit is
  enforced before hashing (bcrypt silently truncates beyond 72 bytes).
- JWTs are signed with HS256 using the ``JWT_SECRET`` environment variable.
  The secret is read lazily (never at module import time) so tests that do not
  set the env var can still import this module without crashing.
- Two auth dependencies are provided:
    ``get_current_user``           -- reads Bearer token from Authorization header
    ``get_current_user_from_query``-- reads token from ``?token=`` query parameter
  The query-param variant exists exclusively for the SSE stream endpoint because
  the EventSource API cannot send custom headers.

Owner: Ratul Sur
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, Query
from fastapi.security import HTTPBearer
from jose import JWTError, jwt as jose_jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from db.session import get_session
from log import GLOBAL_LOGGER as log

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALGORITHM = "HS256"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# auto_error=False so we return 401 ourselves (better error messages).
bearer_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Secret / config helpers
# ---------------------------------------------------------------------------


def _secret() -> str:
    """Return the JWT signing secret from the environment.

    Raises ``RuntimeError`` if ``JWT_SECRET`` is not set so the startup check
    in ``api/app.py`` can surface a clear error before traffic is served.
    """
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        raise RuntimeError(
            "JWT_SECRET environment variable is not set. "
            "Set it to a long, random string before starting the server."
        )
    return secret


def _expiry_days() -> int:
    """Return the token expiry in days from config; default 7."""
    try:
        from utils.config_loader import load_config  # noqa: PLC0415

        cfg = load_config()
        return int(cfg.get("auth", {}).get("jwt_expiry_days", 7))
    except Exception:
        return 7


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------


def _trunc72(password: str) -> str:
    """Truncate to the first 72 UTF-8 bytes (bcrypt's hard limit) and decode back."""
    return password.encode("utf-8")[:72].decode("utf-8", errors="ignore")


def hash_password(password: str) -> str:
    """Return a bcrypt hash of ``password`` (first 72 UTF-8 bytes only)."""
    return pwd_context.hash(_trunc72(password))


def verify_password(password: str, hashed: str) -> bool:
    """Verify ``password`` against a stored bcrypt hash."""
    return pwd_context.verify(_trunc72(password), hashed)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


def create_access_token(user_id: uuid.UUID, email: str) -> str:
    """Encode a signed HS256 JWT with ``sub``, ``email``, ``iat``, and ``exp``."""
    now = datetime.now(timezone.utc)
    expiry = now + timedelta(days=_expiry_days())
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "iat": now,
        "exp": expiry,
    }
    return jose_jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def _decode(token: str) -> dict[str, Any]:
    """Decode and verify a JWT; raise HTTP 401 on any error."""
    try:
        return jose_jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except JWTError as exc:
        log.warning("security: JWT decode failed", error=str(exc))
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def _load_user(sub: str, db: AsyncSession) -> User:
    """Load the user identified by ``sub`` (UUID string); raise HTTP 401 if absent."""
    try:
        user_id = uuid.UUID(sub)
    except ValueError as exc:
        raise HTTPException(
            status_code=401,
            detail="Invalid token subject",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


async def get_current_user(
    creds=Depends(bearer_scheme),
    db: AsyncSession = Depends(get_session),
) -> User:
    """Resolve the authenticated user from the ``Authorization: Bearer <token>`` header."""
    if creds is None:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = _decode(creds.credentials)
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=401,
            detail="Invalid token: missing subject",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await _load_user(sub, db)


async def get_current_user_from_query(
    token: str = Query(..., description="JWT access token (used for SSE endpoints only)."),
    db: AsyncSession = Depends(get_session),
) -> User:
    """Resolve the authenticated user from the ``?token=`` query parameter.

    This variant exists exclusively for the SSE stream endpoint because the
    browser's EventSource API cannot send custom headers.
    """
    payload = _decode(token)
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=401,
            detail="Invalid token: missing subject",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await _load_user(sub, db)
