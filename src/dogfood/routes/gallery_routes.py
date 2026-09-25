"""Public gallery. Drafts stay off it. Search and filters are query parameters."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from dogfood.authz import can_browse_gallery, can_view_project
from dogfood.models import CustomQuestion, Project, Team, Track
from dogfood.queries import gallery_projects, gallery_tags
from dogfood.routes.common import event_or_404, get_db, viewer
from dogfood.web import render

router = APIRouter()


def _gallery_context(db: Session, event, q: str, track: str, tag: str):
    projects = gallery_projects(db, event, q=q, track_slug=track, tag=tag)
    tracks = db.scalars(select(Track).where(Track.event_id == event.id).order_by(Track.name)).all()
    return {
        "event": event,
        "projects": projects,
        "tracks": tracks,
        "tags": gallery_tags(db, event),
        "q": q,
        "track": track,
        "tag": tag,
    }


@router.get("/e/{slug}/gallery")
def gallery(request: Request, slug: str, db: Session = Depends(get_db)):
    event = event_or_404(db, slug)
    user = viewer(request, db)
    if not can_browse_gallery(user, event):
        raise HTTPException(status_code=404, detail="Event not found")
    q = request.query_params.get("q", "")
    track = request.query_params.get("track", "")
    tag = request.query_params.get("tag", "")
    ctx = _gallery_context(db, event, q, track, tag)
    template = "gallery_results.html" if request.headers.get("HX-Request") == "true" else "gallery.html"
    return render(request, template, user=user, **ctx)


@router.get("/e/{slug}/p/{project_id}")
def project_detail(request: Request, slug: str, project_id: int, db: Session = Depends(get_db)):
    event = event_or_404(db, slug)
    user = viewer(request, db)
    project = db.scalar(
        select(Project)
        .where(Project.id == project_id, Project.event_id == event.id)
        .options(
            selectinload(Project.tags),
            selectinload(Project.images),
            selectinload(Project.track),
            selectinload(Project.team).selectinload(Team.members),
            selectinload(Project.answers),
        )
    )
    if project is None or not can_view_project(user, project, event):
        raise HTTPException(status_code=404, detail="Project not found")
    questions = db.scalars(
        select(CustomQuestion).where(CustomQuestion.event_id == event.id).order_by(CustomQuestion.position)
    ).all()
    by_id = {question.id: question for question in questions}
    return render(
        request,
        "project.html",
        user=user,
        event=event,
        project=project,
        qa=[(by_id[answer.question_id], answer.value) for answer in project.answers if answer.question_id in by_id and answer.value],
    )
