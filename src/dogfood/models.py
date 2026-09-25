"""Relational schema for events, teams, submissions, and retained score rows.

Visitor is not a stored role. A visitor is a request with no session.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from dogfood import clock


def _now() -> datetime:
    return clock.utcnow()


class Role:
    PARTICIPANT = "participant"
    JUDGE = "judge"
    ORGANIZER = "organizer"
    ADMIN = "admin"
    ALL = (PARTICIPANT, JUDGE, ORGANIZER, ADMIN)

    @classmethod
    def normalize(cls, value: str | None) -> str:
        raw = (value or "").strip().lower().replace(" ", "")
        aliases = {
            "organiser": cls.ORGANIZER,
            "organizer": cls.ORGANIZER,
            "owner": cls.ADMIN,
            "admin": cls.ADMIN,
            "administrator": cls.ADMIN,
            "judge": cls.JUDGE,
            "reviewer": cls.JUDGE,
            "participant": cls.PARTICIPANT,
            "hacker": cls.PARTICIPANT,
            "member": cls.PARTICIPANT,
            "user": cls.PARTICIPANT,
        }
        return aliases.get(raw, cls.PARTICIPANT)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default=Role.PARTICIPANT, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    memberships: Mapped[list[TeamMember]] = relationship(back_populates="user")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    user: Mapped[User] = relationship()


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    submission_opens_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    submission_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published: Mapped[bool] = mapped_column(default=False)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    tracks: Mapped[list[Track]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )
    prizes: Mapped[list[Prize]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )
    questions: Mapped[list[CustomQuestion]] = relationship(
        back_populates="event",
        cascade="all, delete-orphan",
        order_by="CustomQuestion.position",
    )
    teams: Mapped[list[Team]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )


class Track(Base):
    __tablename__ = "tracks"
    __table_args__ = (UniqueConstraint("event_id", "slug", name="uq_track_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")

    event: Mapped[Event] = relationship(back_populates="tracks")
    projects: Mapped[list[Project]] = relationship(back_populates="track")


class Prize(Base):
    __tablename__ = "prizes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    track_id: Mapped[int | None] = mapped_column(ForeignKey("tracks.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    place: Mapped[int] = mapped_column(Integer, default=1)
    amount_label: Mapped[str] = mapped_column(String(80), default="")

    event: Mapped[Event] = relationship(back_populates="prizes")
    track: Mapped[Track | None] = relationship()


class CustomQuestion(Base):
    __tablename__ = "custom_questions"
    __table_args__ = (UniqueConstraint("event_id", "key", name="uq_question_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(80))
    prompt: Mapped[str] = mapped_column(String(300))
    help_text: Mapped[str] = mapped_column(Text, default="")
    field_type: Mapped[str] = mapped_column(String(32), default="short_text")
    required: Mapped[bool] = mapped_column(default=False)
    options_json: Mapped[list] = mapped_column(JSON, default=list)
    position: Mapped[int] = mapped_column(Integer, default=0)

    event: Mapped[Event] = relationship(back_populates="questions")


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    invite_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    event: Mapped[Event] = relationship(back_populates="teams")
    members: Mapped[list[TeamMember]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )
    project: Mapped[Project | None] = relationship(
        back_populates="team", cascade="all, delete-orphan", uselist=False
    )


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_team_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    team: Mapped[Team] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (Index("ix_projects_event_status", "event_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), unique=True)
    track_id: Mapped[int | None] = mapped_column(ForeignKey("tracks.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    tagline: Mapped[str] = mapped_column(String(180), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    thumbnail_path: Mapped[str] = mapped_column(String(500), default="")
    demo_video_url: Mapped[str] = mapped_column(String(500), default="")
    repository_url: Mapped[str] = mapped_column(String(500), default="")
    live_url: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    team: Mapped[Team] = relationship(back_populates="project")
    track: Mapped[Track | None] = relationship(back_populates="projects")
    images: Mapped[list[ProjectImage]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectImage.position",
    )
    tags: Mapped[list[ProjectTag]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    answers: Mapped[list[CustomAnswer]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectImage(Base):
    __tablename__ = "project_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(500))
    caption: Mapped[str] = mapped_column(String(200), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)

    project: Mapped[Project] = relationship(back_populates="images")


class ProjectTag(Base):
    __tablename__ = "project_tags"
    __table_args__ = (UniqueConstraint("project_id", "tag", name="uq_project_tag"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    tag: Mapped[str] = mapped_column(String(32), index=True)

    project: Mapped[Project] = relationship(back_populates="tags")


class CustomAnswer(Base):
    __tablename__ = "custom_answers"
    __table_args__ = (UniqueConstraint("project_id", "question_id", name="uq_answer"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("custom_questions.id", ondelete="CASCADE"), index=True
    )
    value: Mapped[str] = mapped_column(Text, default="")

    project: Mapped[Project] = relationship(back_populates="answers")
    question: Mapped[CustomQuestion] = relationship()


class RetainedScore(Base):
    """Imported judge scores. Stored so a fixture dump is not lossy. Not served in T1."""

    __tablename__ = "retained_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=True, index=True
    )
    project_name: Mapped[str] = mapped_column(String(200), default="")
    judge_email: Mapped[str] = mapped_column(String(255), default="")
    criterion: Mapped[str] = mapped_column(String(200), default="")
    score_value: Mapped[str] = mapped_column(String(64), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class AppMeta(Base):
    __tablename__ = "app_meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
