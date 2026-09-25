"""Event directory, creation, and the organizer desk."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from dogfood import clock
from dogfood.authz import MSG_LOGIN, is_manager, require_manager
from dogfood.deadlines import parse_form_dt, validate_event_window
from dogfood.exporting import export_event
from dogfood.models import CustomQuestion, Event, Prize, Project, Team, TeamMember, Track
from dogfood.queries import user_team, visible_events
from dogfood.routes.common import event_or_404, get_db, redirect, viewer
from dogfood.textutil import clip, slugify
from dogfood.web import render

router = APIRouter()


def _unique_slug(db: Session, base: str) -> str:
    slug = slugify(base, 70) or "event"
    candidate = slug
    n = 2
    while db.scalar(select(Event.id).where(Event.slug == candidate)):
        candidate = f"{slug}-{n}"[:80]
        n += 1
        if n > 40:
            candidate = f"{slug}-{secrets.token_hex(3)}"[:80]
            break
    return candidate


@router.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    user = viewer(request, db)
    events = visible_events(db, user)
    return render(request, "home.html", user=user, events=events)


@router.get("/events")
def event_index(request: Request, db: Session = Depends(get_db)):
    user = viewer(request, db)
    return render(request, "events.html", user=user, events=visible_events(db, user))


@router.get("/events/new")
def new_event_form(request: Request, db: Session = Depends(get_db)):
    user = viewer(request, db)
    if user is None:
        return redirect("/login?next=/events/new")
    require_manager(user)
    return render(request, "event_new.html", user=user)


@router.post("/events")
def create_event(
    request: Request,
    name: str = Form(""),
    slug: str = Form(""),
    description: str = Form(""),
    starts_at: str = Form(""),
    ends_at: str = Form(""),
    submission_opens_at: str = Form(""),
    submission_deadline: str = Form(""),
    db: Session = Depends(get_db),
):
    user = viewer(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail=MSG_LOGIN)
    require_manager(user)
    errors: list[str] = []
    clean_name = clip(name, 200)
    if not clean_name:
        errors.append("Event name is required")
    try:
        starts = parse_form_dt(starts_at)
        ends = parse_form_dt(ends_at)
        opens = parse_form_dt(submission_opens_at)
        deadline = parse_form_dt(submission_deadline)
    except ValueError as exc:
        errors.append(str(exc))
        starts = ends = opens = deadline = None
    if starts and ends and opens and deadline:
        errors.extend(validate_event_window(starts, ends, opens, deadline))
    requested = slugify(slug, 70) if slug.strip() else ""
    if slug.strip() and not requested:
        errors.append("Slug can only use letters, numbers, and hyphens")
    if requested and db.scalar(select(Event.id).where(Event.slug == requested)):
        errors.append("That slug is already in use")
    posted = {
        "name": clean_name,
        "slug": slug.strip(),
        "description": clip(description, 20000),
        "starts_at": starts_at,
        "ends_at": ends_at,
        "submission_opens_at": submission_opens_at,
        "submission_deadline": submission_deadline,
    }
    if errors or starts is None:
        return render(request, "event_new.html", user=user, errors=errors, posted=posted, status_code=400)
    event = Event(
        slug=requested or _unique_slug(db, clean_name),
        name=clean_name,
        description=posted["description"],
        starts_at=starts,
        ends_at=ends,
        submission_opens_at=opens,
        submission_deadline=deadline,
        published=False,
        created_by_id=user.id,
        updated_at=clock.utcnow(),
    )
    db.add(event)
    db.commit()
    return redirect(f"/e/{event.slug}/manage", "created")


def _load_desk(db: Session, event: Event):
    tracks = db.scalars(select(Track).where(Track.event_id == event.id).order_by(Track.name)).all()
    prizes = db.scalars(
        select(Prize)
        .where(Prize.event_id == event.id)
        .options(selectinload(Prize.track))
        .order_by(Prize.place, Prize.name)
    ).all()
    questions = db.scalars(
        select(CustomQuestion).where(CustomQuestion.event_id == event.id).order_by(CustomQuestion.position)
    ).all()
    teams = db.scalars(
        select(Team)
        .where(Team.event_id == event.id)
        .options(selectinload(Team.members).selectinload(TeamMember.user), selectinload(Team.project))
        .order_by(Team.name)
    ).all()
    return tracks, prizes, questions, teams


@router.get("/e/{slug}")
def event_detail(request: Request, slug: str, db: Session = Depends(get_db)):
    event = event_or_404(db, slug)
    user = viewer(request, db)
    team = user_team(db, event.id, user.id) if user else None
    if not event.published and not is_manager(user) and team is None:
        raise HTTPException(status_code=404, detail="Event not found")
    tracks, prizes, questions, _teams = _load_desk(db, event)
    return render(
        request,
        "event_detail.html",
        user=user,
        event=event,
        tracks=tracks,
        prizes=prizes,
        questions=questions,
        team=team,
    )


@router.get("/e/{slug}/manage")
def manage_event(request: Request, slug: str, db: Session = Depends(get_db)):
    event = event_or_404(db, slug)
    user = viewer(request, db)
    if user is None:
        return redirect(f"/login?next=/e/{slug}/manage")
    require_manager(user)
    tracks, prizes, questions, teams = _load_desk(db, event)
    return render(
        request,
        "event_manage.html",
        user=user,
        event=event,
        tracks=tracks,
        prizes=prizes,
        questions=questions,
        teams=teams,
    )


@router.post("/e/{slug}/settings")
def update_event(
    request: Request,
    slug: str,
    name: str = Form(""),
    description: str = Form(""),
    starts_at: str = Form(""),
    ends_at: str = Form(""),
    submission_opens_at: str = Form(""),
    submission_deadline: str = Form(""),
    db: Session = Depends(get_db),
):
    event = event_or_404(db, slug)
    user = viewer(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail=MSG_LOGIN)
    require_manager(user)
    errors = []
    clean_name = clip(name, 200)
    if not clean_name:
        errors.append("Event name is required")
    try:
        starts = parse_form_dt(starts_at)
        ends = parse_form_dt(ends_at)
        opens = parse_form_dt(submission_opens_at)
        deadline = parse_form_dt(submission_deadline)
    except ValueError as exc:
        return _manage_error(request, db, event, user, [str(exc)])
    errors.extend(validate_event_window(starts, ends, opens, deadline))
    if errors:
        return _manage_error(request, db, event, user, errors)
    event.name = clean_name
    event.description = clip(description, 20000)
    event.starts_at = starts
    event.ends_at = ends
    event.submission_opens_at = opens
    event.submission_deadline = deadline
    event.updated_at = clock.utcnow()
    db.commit()
    return redirect(f"/e/{event.slug}/manage", "updated")


def _manage_error(request, db, event, user, errors):
    tracks, prizes, questions, teams = _load_desk(db, event)
    return render(
        request,
        "event_manage.html",
        user=user,
        event=event,
        tracks=tracks,
        prizes=prizes,
        questions=questions,
        teams=teams,
        errors=errors,
        status_code=400,
    )


@router.post("/e/{slug}/publish")
def publish_event(request: Request, slug: str, published: str = Form("0"), db: Session = Depends(get_db)):
    event = event_or_404(db, slug)
    user = viewer(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail=MSG_LOGIN)
    require_manager(user)
    event.published = published == "1"
    event.updated_at = clock.utcnow()
    db.commit()
    return redirect(f"/e/{event.slug}/manage", "published" if event.published else "unpublished")


@router.post("/e/{slug}/tracks")
def add_track(
    request: Request,
    slug: str,
    name: str = Form(""),
    description: str = Form(""),
    db: Session = Depends(get_db),
):
    event = event_or_404(db, slug)
    user = viewer(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail=MSG_LOGIN)
    require_manager(user)
    clean = clip(name, 120)
    if not clean:
        return _manage_error(request, db, event, user, ["Track name is required"])
    base = slugify(clean, 70) or "track"
    track_slug = base
    n = 2
    while db.scalar(select(Track.id).where(Track.event_id == event.id, Track.slug == track_slug)):
        track_slug = f"{base}-{n}"
        n += 1
    db.add(Track(event_id=event.id, slug=track_slug, name=clean, description=clip(description, 4000)))
    db.commit()
    return redirect(f"/e/{event.slug}/manage", "track")


@router.post("/e/{slug}/tracks/{track_id}/delete")
def delete_track(request: Request, slug: str, track_id: int, db: Session = Depends(get_db)):
    event = event_or_404(db, slug)
    user = viewer(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail=MSG_LOGIN)
    require_manager(user)
    track = db.get(Track, track_id)
    if track is None or track.event_id != event.id:
        raise HTTPException(status_code=404, detail="Track not found")
    used = db.scalar(select(func.count()).select_from(Project).where(Project.track_id == track.id))
    if used:
        return _manage_error(request, db, event, user, ["That track still has projects, so it was not removed"])
    db.delete(track)
    db.commit()
    return redirect(f"/e/{event.slug}/manage", "removed")


@router.post("/e/{slug}/prizes")
def add_prize(
    request: Request,
    slug: str,
    name: str = Form(""),
    description: str = Form(""),
    place: str = Form("1"),
    amount_label: str = Form(""),
    track_id: str = Form(""),
    db: Session = Depends(get_db),
):
    event = event_or_404(db, slug)
    user = viewer(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail=MSG_LOGIN)
    require_manager(user)
    clean = clip(name, 200)
    if not clean:
        return _manage_error(request, db, event, user, ["Prize name is required"])
    try:
        place_n = max(int(place), 1)
    except ValueError:
        return _manage_error(request, db, event, user, ["Place must be a number"])
    linked = None
    if track_id.strip():
        if not track_id.isdigit():
            return _manage_error(request, db, event, user, ["Unknown track"])
        linked = db.get(Track, int(track_id))
        if linked is None or linked.event_id != event.id:
            return _manage_error(request, db, event, user, ["Unknown track"])
    db.add(
        Prize(
            event_id=event.id,
            track_id=linked.id if linked else None,
            name=clean,
            description=clip(description, 4000),
            place=place_n,
            amount_label=clip(amount_label, 80),
        )
    )
    db.commit()
    return redirect(f"/e/{event.slug}/manage", "prize")


@router.post("/e/{slug}/prizes/{prize_id}/delete")
def delete_prize(request: Request, slug: str, prize_id: int, db: Session = Depends(get_db)):
    event = event_or_404(db, slug)
    user = viewer(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail=MSG_LOGIN)
    require_manager(user)
    prize = db.get(Prize, prize_id)
    if prize is None or prize.event_id != event.id:
        raise HTTPException(status_code=404, detail="Prize not found")
    db.delete(prize)
    db.commit()
    return redirect(f"/e/{event.slug}/manage", "removed")


@router.post("/e/{slug}/questions")
def add_question(
    request: Request,
    slug: str,
    prompt: str = Form(""),
    help_text: str = Form(""),
    field_type: str = Form("short_text"),
    required: str = Form(""),
    options: str = Form(""),
    db: Session = Depends(get_db),
):
    event = event_or_404(db, slug)
    user = viewer(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail=MSG_LOGIN)
    require_manager(user)
    clean = clip(prompt, 300)
    if not clean:
        return _manage_error(request, db, event, user, ["Question prompt is required"])
    allowed = {"short_text", "long_text", "url", "single_select"}
    kind = field_type if field_type in allowed else "short_text"
    choices = [clip(line, 120) for line in options.splitlines() if clip(line, 120)]
    if kind == "single_select" and not choices:
        return _manage_error(request, db, event, user, ["A single-choice question needs at least one option"])
    base = slugify(clean, 70) or "question"
    key = base
    n = 2
    while db.scalar(select(CustomQuestion.id).where(CustomQuestion.event_id == event.id, CustomQuestion.key == key)):
        key = f"{base}-{n}"
        n += 1
    position = db.scalar(
        select(func.coalesce(func.max(CustomQuestion.position), -1)).where(CustomQuestion.event_id == event.id)
    )
    db.add(
        CustomQuestion(
            event_id=event.id,
            key=key,
            prompt=clean,
            help_text=clip(help_text, 1000),
            field_type=kind,
            required=required == "on",
            options_json=choices,
            position=int(position) + 1,
        )
    )
    db.commit()
    return redirect(f"/e/{event.slug}/manage", "question")


@router.post("/e/{slug}/questions/{question_id}/delete")
def delete_question(request: Request, slug: str, question_id: int, db: Session = Depends(get_db)):
    event = event_or_404(db, slug)
    user = viewer(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail=MSG_LOGIN)
    require_manager(user)
    question = db.get(CustomQuestion, question_id)
    if question is None or question.event_id != event.id:
        raise HTTPException(status_code=404, detail="Question not found")
    db.delete(question)
    db.commit()
    return redirect(f"/e/{event.slug}/manage", "removed")


@router.get("/e/{slug}/export.json")
def export_json(request: Request, slug: str, db: Session = Depends(get_db)):
    event = event_or_404(db, slug)
    user = viewer(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail=MSG_LOGIN)
    require_manager(user)
    import json

    payload = export_event(db, event)
    body = json.dumps(payload, indent=2)
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{event.slug}-export.json"'},
    )
