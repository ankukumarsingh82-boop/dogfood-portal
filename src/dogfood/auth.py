"""Email and password sessions. The cookie stores a random id, not the user."""

from __future__ import annotations

import secrets
from datetime import timedelta

import bcrypt
from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from dogfood import clock
from dogfood.config import Settings
from dogfood.deadlines import as_utc
from dogfood.models import User, UserSession

COOKIE = "dogfood_session"
MIN_PASSWORD = 8


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > 72:
        raise ValueError("Password must be 72 bytes or fewer")
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        raw = password.encode("utf-8")
        if len(raw) > 72 or not password_hash:
            return False
        return bcrypt.checkpw(raw, password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def current_user(request: Request, db: Session) -> User | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    row = db.get(UserSession, token)
    if row is None:
        return None
    if as_utc(row.expires_at) <= clock.utcnow():
        return None
    return db.get(User, row.user_id)


def start_session(db: Session, user: User, settings: Settings) -> UserSession:
    row = UserSession(
        id=secrets.token_urlsafe(32),
        user_id=user.id,
        expires_at=clock.utcnow() + timedelta(days=settings.session_days),
    )
    db.add(row)
    db.commit()
    return row


def end_session(db: Session, request: Request) -> None:
    token = request.cookies.get(COOKIE)
    if not token:
        return
    row = db.get(UserSession, token)
    if row is not None:
        db.delete(row)
        db.commit()


def attach_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_days * 86400,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def safe_next(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    return value


def find_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email))
