"""Backend role checks. Hiding a button is not authorization."""

from __future__ import annotations

from fastapi import HTTPException

from dogfood.models import Role, User

MSG_ORGANIZER = "Only an organizer or admin can do that"
MSG_ADMIN = "Only an admin can do that"
MSG_JUDGE_TEAM = "Judges cannot join or create teams"
MSG_JUDGE_SUBMIT = "Judges cannot edit submissions"
MSG_ROLE = "Your role cannot edit submissions"
MSG_TEAM = "Create or join a team before submitting"
MSG_ONE_TEAM = "You are already on a team for this event"
MSG_LOGIN = "Login required"


def is_manager(user: User | None) -> bool:
    return bool(user and user.role in (Role.ORGANIZER, Role.ADMIN))


def require_manager(user: User) -> None:
    if not is_manager(user):
        raise HTTPException(status_code=403, detail=MSG_ORGANIZER)


def require_admin(user: User) -> None:
    if user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail=MSG_ADMIN)


def can_participate(user: User | None) -> bool:
    return bool(user and user.role in (Role.PARTICIPANT, Role.ORGANIZER, Role.ADMIN))


def require_participant_action(user: User) -> None:
    if user.role == Role.JUDGE:
        raise HTTPException(status_code=403, detail=MSG_JUDGE_TEAM)
    if not can_participate(user):
        raise HTTPException(status_code=403, detail=MSG_JUDGE_TEAM)


def require_submitter(user: User) -> None:
    if user.role == Role.JUDGE:
        raise HTTPException(status_code=403, detail=MSG_JUDGE_SUBMIT)
    if user.role not in (Role.PARTICIPANT, Role.ORGANIZER, Role.ADMIN):
        raise HTTPException(status_code=403, detail=MSG_ROLE)


def can_browse_gallery(user: User | None, event) -> bool:
    if event.published:
        return True
    return is_manager(user)


def can_view_project(user: User | None, project, event) -> bool:
    if project.status == "submitted" and event.published:
        return True
    if is_manager(user):
        return True
    if user is None or user.role == Role.JUDGE:
        return False
    members = project.team.members if project.team is not None else []
    return any(member.user_id == user.id for member in members)
