"""Shared route helpers."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from dogfood.auth import current_user
from dogfood.models import Event, User


def get_db(request: Request):
    db: Session = request.app.state.SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def redirect(url: str, notice: str = "") -> RedirectResponse:
    if notice:
        join = "&" if "?" in url else "?"
        url = f"{url}{join}notice={quote(notice)}"
    return RedirectResponse(url, status_code=303)


def login_redirect(request: Request) -> RedirectResponse:
    return RedirectResponse(f"/login?next={quote(request.url.path)}", status_code=303)


def event_or_404(db: Session, slug: str) -> Event:
    event = db.scalar(select(Event).where(Event.slug == slug))
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


def viewer(request: Request, db: Session) -> User | None:
    return current_user(request, db)
