"""Organizer exit path. One JSON document, no password hashes, no session tokens."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from dogfood import clock
from dogfood.models import CustomQuestion, Event, Prize, Project, RetainedScore, Team, TeamMember, Track


def export_event(db: Session, event: Event) -> dict:
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
        .options(selectinload(Team.members).selectinload(TeamMember.user))
        .order_by(Team.name)
    ).all()
    projects = db.scalars(
        select(Project)
        .where(Project.event_id == event.id)
        .options(
            selectinload(Project.tags),
            selectinload(Project.images),
            selectinload(Project.answers),
            selectinload(Project.track),
            selectinload(Project.team),
        )
        .order_by(Project.name)
    ).all()
    scores = db.scalars(select(RetainedScore).where(RetainedScore.event_id == event.id)).all()
    question_by_id = {question.id: question for question in questions}
    return {
        "exported_at": clock.utcnow().isoformat(),
        "note": "T1 export of the event, roster, and submissions. retained_scores_unprocessed are raw import rows, not judged results.",
        "event": {
            "slug": event.slug,
            "name": event.name,
            "description": event.description,
            "starts_at": event.starts_at.isoformat() if event.starts_at else None,
            "ends_at": event.ends_at.isoformat() if event.ends_at else None,
            "submission_opens_at": event.submission_opens_at.isoformat(),
            "submission_deadline": event.submission_deadline.isoformat(),
            "published": event.published,
        },
        "tracks": [
            {"slug": track.slug, "name": track.name, "description": track.description} for track in tracks
        ],
        "prizes": [
            {
                "name": prize.name,
                "description": prize.description,
                "place": prize.place,
                "amount_label": prize.amount_label,
                "track": prize.track.slug if prize.track else None,
            }
            for prize in prizes
        ],
        "custom_questions": [
            {
                "key": question.key,
                "prompt": question.prompt,
                "help_text": question.help_text,
                "field_type": question.field_type,
                "required": question.required,
                "options": question.options_json or [],
            }
            for question in questions
        ],
        "teams": [
            {
                "name": team.name,
                "invite_code": team.invite_code,
                "members": [
                    {"email": member.user.email, "name": member.user.name, "role": member.user.role}
                    for member in team.members
                    if member.user is not None
                ],
            }
            for team in teams
        ],
        "projects": [
            {
                "name": project.name,
                "tagline": project.tagline,
                "description": project.description,
                "thumbnail_url": project.thumbnail_path,
                "gallery": [{"url": image.path, "caption": image.caption} for image in project.images],
                "demo_video_url": project.demo_video_url,
                "repository_url": project.repository_url,
                "live_url": project.live_url,
                "tech_tags": [tag.tag for tag in project.tags],
                "track": project.track.slug if project.track else None,
                "team": project.team.name if project.team else None,
                "status": project.status,
                "custom_answers": {
                    question_by_id[answer.question_id].key: answer.value
                    for answer in project.answers
                    if answer.question_id in question_by_id
                },
            }
            for project in projects
        ],
        "retained_scores_unprocessed": [
            {
                "project": score.project_name,
                "judge": score.judge_email,
                "criterion": score.criterion,
                "score": score.score_value,
            }
            for score in scores
        ],
    }
