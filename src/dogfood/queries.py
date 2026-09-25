"""Read queries shared by pages."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from dogfood.models import Event, Project, ProjectTag, Role, Team, TeamMember, Track, User
from dogfood.textutil import like_pattern


def visible_events(db: Session, user: User | None) -> list[Event]:
    stmt = select(Event).order_by(Event.starts_at.desc(), Event.name)
    if user is None or user.role not in (Role.ORGANIZER, Role.ADMIN):
        stmt = stmt.where(Event.published.is_(True))
    return list(db.scalars(stmt).all())


def user_team(db: Session, event_id: int, user_id: int) -> Team | None:
    return db.scalar(
        select(Team)
        .join(TeamMember)
        .where(Team.event_id == event_id, TeamMember.user_id == user_id)
        .options(selectinload(Team.members), selectinload(Team.project))
    )


def gallery_projects(
    db: Session,
    event: Event,
    q: str = "",
    track_slug: str = "",
    tag: str = "",
) -> list[Project]:
    stmt = (
        select(Project)
        .where(Project.event_id == event.id, Project.status == "submitted")
        .options(
            selectinload(Project.tags),
            selectinload(Project.images),
            selectinload(Project.track),
            selectinload(Project.team),
        )
    )
    if track_slug:
        stmt = stmt.join(Track, Project.track_id == Track.id).where(Track.slug == track_slug)
    if tag:
        stmt = stmt.where(
            Project.id.in_(select(ProjectTag.project_id).where(ProjectTag.tag == tag.strip().lower()))
        )
    query = (q or "").strip()
    if query:
        pattern = like_pattern(query)
        tag_ids = select(ProjectTag.project_id).where(ProjectTag.tag.ilike(pattern, escape="\\"))
        stmt = stmt.where(
            or_(
                Project.name.ilike(pattern, escape="\\"),
                Project.tagline.ilike(pattern, escape="\\"),
                Project.description.ilike(pattern, escape="\\"),
                Project.id.in_(tag_ids),
            )
        )
    stmt = stmt.order_by(Project.submitted_at.desc(), Project.name.asc())
    return list(db.scalars(stmt).unique().all())


def gallery_tags(db: Session, event: Event) -> list[str]:
    rows = db.scalars(
        select(ProjectTag.tag)
        .join(Project, ProjectTag.project_id == Project.id)
        .where(Project.event_id == event.id, Project.status == "submitted")
        .distinct()
        .order_by(ProjectTag.tag)
    ).all()
    return list(rows)
