"""Admin-only role changes. Participant, judge, organizer, and admin are stored roles."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dogfood.authz import MSG_LOGIN, require_admin
from dogfood.models import Role, User
from dogfood.routes.common import get_db, redirect, viewer
from dogfood.web import render

router = APIRouter()


@router.get("/admin/users")
def users(request: Request, db: Session = Depends(get_db)):
    user = viewer(request, db)
    if user is None:
        return redirect("/login?next=/admin/users")
    require_admin(user)
    rows = db.scalars(select(User).order_by(User.role, User.email)).all()
    return render(request, "admin_users.html", user=user, rows=rows, roles=Role.ALL)


@router.post("/admin/users/{user_id}/role")
def change_role(
    request: Request,
    user_id: int,
    role: str = Form(""),
    db: Session = Depends(get_db),
):
    actor = viewer(request, db)
    if actor is None:
        raise HTTPException(status_code=401, detail=MSG_LOGIN)
    require_admin(actor)
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if role not in Role.ALL:
        raise HTTPException(status_code=400, detail="Unknown role")
    if target.role == Role.ADMIN and role != Role.ADMIN:
        admins = db.scalar(select(func.count()).select_from(User).where(User.role == Role.ADMIN))
        if admins is not None and admins <= 1:
            raise HTTPException(status_code=403, detail="The last admin cannot be demoted")
    target.role = role
    db.commit()
    return redirect("/admin/users", "role")
