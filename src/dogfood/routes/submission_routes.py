"""Draft and edit a team's project until the server-side deadline."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from dogfood import clock
from dogfood.authz import MSG_LOGIN, MSG_TEAM, require_submitter
from dogfood.deadlines import MSG_DEADLINE, MSG_NOT_OPEN, submission_phase
from dogfood.models import CustomAnswer, CustomQuestion, Project, ProjectImage, ProjectTag
from dogfood.queries import user_team
from dogfood.routes.common import event_or_404, get_db, redirect, viewer
from dogfood.textutil import clean_http_url, clip, parse_tags
from dogfood.uploads import is_upload, save_upload
from dogfood.web import render

router = APIRouter()


def _questions(db: Session, event_id: int) -> list[CustomQuestion]:
    return list(
        db.scalars(
            select(CustomQuestion).where(CustomQuestion.event_id == event_id).order_by(CustomQuestion.position)
        ).all()
    )


def _tracks(db: Session, event_id: int):
    from dogfood.models import Track

    return list(db.scalars(select(Track).where(Track.event_id == event_id).order_by(Track.name)).all())


def _project_for_team(db: Session, team) -> Project | None:
    if team is None:
        return None
    return db.scalar(
        select(Project)
        .where(Project.team_id == team.id)
        .options(
            selectinload(Project.tags),
            selectinload(Project.images),
            selectinload(Project.answers),
        )
    )


@router.get("/e/{slug}/submission")
def submission_form(request: Request, slug: str, db: Session = Depends(get_db)):
    event = event_or_404(db, slug)
    user = viewer(request, db)
    if user is None:
        return redirect(f"/login?next=/e/{slug}/submission")
    require_submitter(user)
    team = user_team(db, event.id, user.id)
    if team is None:
        return redirect(f"/e/{event.slug}", "needteam")
    project = _project_for_team(db, team)
    return _form(request, db, event, user, team, project, posted=None, errors=[])


def _form(request, db, event, user, team, project, posted, errors, status_code=200):
    answers = {}
    if project is not None:
        answers = {answer.question_id: answer.value for answer in project.answers}
    return render(
        request,
        "submission.html",
        status_code=status_code,
        user=user,
        event=event,
        team=team,
        project=project,
        tracks=_tracks(db, event.id),
        questions=_questions(db, event.id),
        answers=answers,
        posted=posted,
        errors=errors,
        phase=submission_phase(event),
        tag_text=", ".join(tag.tag for tag in project.tags) if project is not None else "",
    )


@router.post("/e/{slug}/submission")
async def save_submission(request: Request, slug: str, db: Session = Depends(get_db)):
    event = event_or_404(db, slug)
    user = viewer(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail=MSG_LOGIN)
    require_submitter(user)
    phase = submission_phase(event)
    if phase == "early":
        raise HTTPException(status_code=403, detail=MSG_NOT_OPEN)
    if phase == "closed":
        raise HTTPException(status_code=403, detail=MSG_DEADLINE)
    team = user_team(db, event.id, user.id)
    if team is None:
        raise HTTPException(status_code=403, detail=MSG_TEAM)
    form = await request.form()
    intent = str(form.get("intent") or "draft")
    if intent not in {"draft", "submit"}:
        intent = "draft"
    errors: list[str] = []
    name = clip(str(form.get("name") or ""), 120)
    tagline = clip(str(form.get("tagline") or ""), 180)
    description = clip(str(form.get("description") or ""), 20000)
    urls: dict[str, str] = {}
    for field, label in (
        ("demo_video_url", "Demo video URL"),
        ("repository_url", "Repository URL"),
        ("live_url", "Live link"),
        ("thumbnail_url", "Thumbnail URL"),
    ):
        raw = str(form.get(field) or "")
        if raw.strip():
            try:
                urls[field] = clean_http_url(raw)
            except ValueError as exc:
                errors.append(f"{label}: {exc}")
                urls[field] = ""
        else:
            urls[field] = ""
    tags = parse_tags(str(form.get("tech_tags") or ""))
    track = None
    track_raw = str(form.get("track_id") or "").strip()
    if track_raw:
        if track_raw.isdigit():
            from dogfood.models import Track

            track = db.get(Track, int(track_raw))
        if track is None or track.event_id != event.id:
            errors.append("Choose a track on this event")
            track = None
    questions = _questions(db, event.id)
    answers: dict[int, str] = {}
    for question in questions:
        value = clip(str(form.get(f"q_{question.id}") or ""), 5000)
        if question.field_type == "url" and value:
            try:
                value = clean_http_url(value)
            except ValueError:
                errors.append(f"{question.prompt} must be an http(s) URL")
        options = question.options_json or []
        if question.field_type == "single_select" and value and value not in options:
            errors.append(f"{question.prompt} is not one of the allowed options")
        if intent == "submit" and question.required and not value:
            errors.append(f"{question.prompt} is required")
        answers[question.id] = value
    if intent == "submit":
        if not name:
            errors.append("Project name is required")
        if not tagline:
            errors.append("Tagline is required")
        if not description:
            errors.append("Description is required")
        if track is None:
            errors.append("Track is required")
    saved_thumb = None
    upload = form.get("thumbnail")
    if is_upload(upload):
        try:
            saved_thumb = save_upload(upload, request.app.state.settings)
        except ValueError as exc:
            errors.append(str(exc))
    posted = {
        "name": name,
        "tagline": tagline,
        "description": description,
        "track_id": track.id if track else track_raw,
        "tech_tags": str(form.get("tech_tags") or ""),
        "demo_video_url": str(form.get("demo_video_url") or ""),
        "repository_url": str(form.get("repository_url") or ""),
        "live_url": str(form.get("live_url") or ""),
        "thumbnail_url": str(form.get("thumbnail_url") or ""),
        "answers": answers,
    }
    project = _project_for_team(db, team)
    if errors:
        return _form(request, db, event, user, team, project, posted, errors, status_code=400)
    if project is None:
        project = Project(event_id=event.id, team_id=team.id, status="draft")
        team.project = project
        db.flush()
    project.name = name
    project.tagline = tagline
    project.description = description
    project.track_id = track.id if track else None
    project.demo_video_url = urls["demo_video_url"]
    project.repository_url = urls["repository_url"]
    project.live_url = urls["live_url"]
    if saved_thumb:
        project.thumbnail_path = saved_thumb
    elif urls["thumbnail_url"]:
        project.thumbnail_path = urls["thumbnail_url"]
    elif form.get("clear_thumbnail"):
        project.thumbnail_path = ""
    project.updated_at = clock.utcnow()
    if intent == "submit":
        project.status = "submitted"
        if project.submitted_at is None:
            project.submitted_at = clock.utcnow()
    project.tags.clear()
    db.flush()
    for tag in tags:
        project.tags.append(ProjectTag(tag=tag))
    existing = {answer.question_id: answer for answer in list(project.answers)}
    for question_id, value in answers.items():
        row = existing.get(question_id)
        if row is None:
            project.answers.append(CustomAnswer(question_id=question_id, value=value))
        else:
            row.value = value
    db.commit()
    return redirect(f"/e/{event.slug}/submission", "submitted" if intent == "submit" else "saved")


def _owned_project(db: Session, event, user) -> Project:
    team = user_team(db, event.id, user.id)
    if team is None:
        raise HTTPException(status_code=403, detail=MSG_TEAM)
    project = _project_for_team(db, team)
    if project is None:
        raise HTTPException(status_code=400, detail="Save the submission before adding images")
    return project


def _guard_window(event, user) -> None:
    require_submitter(user)
    phase = submission_phase(event)
    if phase == "early":
        raise HTTPException(status_code=403, detail=MSG_NOT_OPEN)
    if phase == "closed":
        raise HTTPException(status_code=403, detail=MSG_DEADLINE)


@router.post("/e/{slug}/submission/images")
async def add_image(request: Request, slug: str, db: Session = Depends(get_db)):
    event = event_or_404(db, slug)
    user = viewer(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail=MSG_LOGIN)
    _guard_window(event, user)
    project = _owned_project(db, event, user)
    if len(project.images) >= 8:
        raise HTTPException(status_code=400, detail="A project can have at most 8 gallery images")
    form = await request.form()
    caption = clip(str(form.get("caption") or ""), 200)
    path = ""
    upload = form.get("image_file")
    if is_upload(upload):
        try:
            path = save_upload(upload, request.app.state.settings)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    elif str(form.get("image_url") or "").strip():
        try:
            path = clean_http_url(str(form.get("image_url")))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        raise HTTPException(status_code=400, detail="Add an image file or an http(s) URL")
    position = max((image.position for image in project.images), default=-1) + 1
    project.images.append(ProjectImage(path=path, caption=caption, position=position))
    project.updated_at = clock.utcnow()
    db.commit()
    return redirect(f"/e/{event.slug}/submission", "image")


@router.post("/e/{slug}/submission/images/{image_id}/delete")
def delete_image(request: Request, slug: str, image_id: int, db: Session = Depends(get_db)):
    event = event_or_404(db, slug)
    user = viewer(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail=MSG_LOGIN)
    _guard_window(event, user)
    project = _owned_project(db, event, user)
    image = db.get(ProjectImage, image_id)
    if image is None or image.project_id != project.id:
        raise HTTPException(status_code=404, detail="Image not found")
    db.delete(image)
    project.updated_at = clock.utcnow()
    db.commit()
    return redirect(f"/e/{event.slug}/submission", "removed")
