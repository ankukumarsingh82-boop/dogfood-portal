"""Team creation and invite links. Joining is a POST, not a GET."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from dogfood.authz import MSG_LOGIN, MSG_ONE_TEAM, require_participant_action
from dogfood.deadlines import MSG_JOIN_CLOSED, submission_phase
from dogfood.models import Team, TeamMember
from dogfood.queries import user_team
from dogfood.routes.common import event_or_404, get_db, redirect, viewer
from dogfood.textutil import clip
from dogfood.web import render

router = APIRouter()


def _fresh_code(db: Session) -> str:
    code = secrets.token_urlsafe(9)
    while db.scalar(select(Team.id).where(Team.invite_code == code)):
        code = secrets.token_urlsafe(9)
    return code


@router.post("/e/{slug}/teams")
def create_team(
    request: Request,
    slug: str,
    name: str = Form(""),
    db: Session = Depends(get_db),
):
    event = event_or_404(db, slug)
    user = viewer(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail=MSG_LOGIN)
    require_participant_action(user)
    if submission_phase(event) != "open":
        raise HTTPException(status_code=403, detail=MSG_JOIN_CLOSED)
    if user_team(db, event.id, user.id) is not None:
        raise HTTPException(status_code=403, detail=MSG_ONE_TEAM)
    clean = clip(name, 120)
    if len(clean) < 2:
        raise HTTPException(status_code=400, detail="Team name must be at least 2 characters")
    team = Team(
        event_id=event.id,
        name=clean,
        invite_code=_fresh_code(db),
        created_by_id=user.id,
    )
    db.add(team)
    db.flush()
    db.add(TeamMember(team_id=team.id, user_id=user.id))
    db.commit()
    return redirect(f"/e/{event.slug}", "team")


@router.get("/join/{code}")
def join_form(request: Request, code: str, db: Session = Depends(get_db)):
    team = db.scalar(
        select(Team)
        .where(Team.invite_code == code)
        .options(selectinload(Team.event), selectinload(Team.members))
    )
    if team is None:
        raise HTTPException(status_code=404, detail="Invite link not found")
    user = viewer(request, db)
    existing = user_team(db, team.event_id, user.id) if user else None
    return render(
        request,
        "join.html",
        user=user,
        team=team,
        event=team.event,
        existing=existing,
        phase=submission_phase(team.event),
    )


@router.post("/join/{code}")
def join_team(request: Request, code: str, db: Session = Depends(get_db)):
    team = db.scalar(select(Team).where(Team.invite_code == code).options(selectinload(Team.event)))
    if team is None:
        raise HTTPException(status_code=404, detail="Invite link not found")
    user = viewer(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail=MSG_LOGIN)
    require_participant_action(user)
    if submission_phase(team.event) != "open":
        raise HTTPException(status_code=403, detail=MSG_JOIN_CLOSED)
    existing = user_team(db, team.event_id, user.id)
    if existing is not None:
        if existing.id == team.id:
            return redirect(f"/e/{team.event.slug}", "joined")
        raise HTTPException(status_code=403, detail=MSG_ONE_TEAM)
    db.add(TeamMember(team_id=team.id, user_id=user.id))
    db.commit()
    return redirect(f"/e/{team.event.slug}", "joined")
