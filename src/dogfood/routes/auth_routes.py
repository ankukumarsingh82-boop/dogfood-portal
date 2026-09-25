"""Register, log in, log out."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from dogfood.auth import (
    attach_session_cookie,
    clear_session_cookie,
    end_session,
    find_user_by_email,
    hash_password,
    safe_next,
    start_session,
    verify_password,
    MIN_PASSWORD,
)
from dogfood.models import AppMeta, Role, User
from dogfood.routes.common import get_db, redirect, viewer
from dogfood.seed import DEMO_ACCOUNTS
from dogfood.textutil import clip, normalize_email, valid_email
from dogfood.web import render

router = APIRouter()


def _demo_accounts(db: Session) -> list[dict]:
    row = db.get(AppMeta, "seed_source")
    if row is None or row.value != "builtin":
        return []
    return DEMO_ACCOUNTS


@router.get("/login")
def login_form(request: Request, db: Session = Depends(get_db)):
    user = viewer(request, db)
    if user:
        return redirect("/")
    return render(
        request,
        "login.html",
        user=user,
        next_url=safe_next(request.query_params.get("next")),
        demo_accounts=_demo_accounts(db),
    )


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    next: str = Form("/"),
    db: Session = Depends(get_db),
):
    cleaned = normalize_email(email)
    user = find_user_by_email(db, cleaned)
    if user is None or not verify_password(password, user.password_hash):
        return render(
            request,
            "login.html",
            status_code=401,
            errors=["Email or password is incorrect"],
            next_url=safe_next(next),
            demo_accounts=_demo_accounts(db),
            posted_email=cleaned,
        )
    session = start_session(db, user, request.app.state.settings)
    response = redirect(safe_next(next))
    attach_session_cookie(response, session.id, request.app.state.settings)
    return response


@router.get("/register")
def register_form(request: Request, db: Session = Depends(get_db)):
    if viewer(request, db):
        return redirect("/")
    return render(request, "register.html")


@router.post("/register")
def register_submit(
    request: Request,
    name: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    password_confirm: str = Form(""),
    db: Session = Depends(get_db),
):
    # A posted role is ignored. Self-registration is always participant.
    errors = []
    cleaned_name = clip(name, 200)
    cleaned_email = normalize_email(email)
    if not cleaned_name:
        errors.append("Name is required")
    if not valid_email(cleaned_email):
        errors.append("Enter a valid email")
    if len(password) < MIN_PASSWORD:
        errors.append(f"Password must be at least {MIN_PASSWORD} characters")
    if len(password.encode("utf-8")) > 72:
        errors.append("Password must be 72 bytes or fewer")
    if password != password_confirm:
        errors.append("Passwords do not match")
    if cleaned_email and find_user_by_email(db, cleaned_email):
        errors.append("An account with that email already exists")
    if errors:
        return render(
            request,
            "register.html",
            status_code=400,
            errors=errors,
            posted={"name": cleaned_name, "email": cleaned_email},
        )
    user = User(
        email=cleaned_email,
        name=cleaned_name,
        password_hash=hash_password(password),
        role=Role.PARTICIPANT,
    )
    db.add(user)
    db.commit()
    session = start_session(db, user, request.app.state.settings)
    response = redirect("/")
    attach_session_cookie(response, session.id, request.app.state.settings)
    return response


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    end_session(db, request)
    response = redirect("/")
    clear_session_cookie(response)
    return response

