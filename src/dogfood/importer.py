"""Load fixtures.json into the relational schema.

Accepts the canonical shape in DATA-MODEL.md, the official kickoff file
(event id, submissions_close, team and track ids, criteria dicts), and a
handful of aliases. External ids that contain underscores are kept as slugs.
A deadline that is already in the past stays in the past. Score rows are
retained and are not shown in the T1 interface.
"""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from dogfood import clock
from dogfood.auth import hash_password
from dogfood.deadlines import as_utc
from dogfood.models import (
    CustomAnswer,
    CustomQuestion,
    Event,
    Prize,
    Project,
    ProjectImage,
    ProjectTag,
    RetainedScore,
    Role,
    Team,
    TeamMember,
    Track,
    User,
)
from dogfood.textutil import clean_http_url, clip, normalize_email, normalize_tag, slugify, valid_email

DEFAULT_FIXTURE_PASSWORD = "fixture-pass-72"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
_QUESTION_TYPES = {
    "text": "short_text",
    "short_text": "short_text",
    "string": "short_text",
    "textarea": "long_text",
    "long_text": "long_text",
    "long": "long_text",
    "url": "url",
    "select": "single_select",
    "single_select": "single_select",
    "choice": "single_select",
}


def classify_fixture(path: str | Path | None) -> str:
    """Return missing, invalid, placeholder, empty, or real."""
    if not path:
        return "missing"
    file = Path(path)
    if not file.exists():
        return "missing"
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "invalid"
    if not isinstance(data, dict):
        return "invalid"
    if data.get("placeholder") is True or data.get("_placeholder") is True:
        return "placeholder"
    if _has_records(data):
        return "real"
    return "empty"


def _has_records(data: dict) -> bool:
    for key in (
        "users",
        "judges",
        "organisers",
        "organizers",
        "teams",
        "projects",
        "submissions",
        "events",
    ):
        if isinstance(data.get(key), list) and data[key]:
            return True
    event = data.get("event")
    if isinstance(event, dict) and (event.get("name") or event.get("slug") or event.get("title")):
        return True
    if data.get("event_name") or (data.get("tracks") and data.get("name")):
        return True
    return False


def import_payload(db: Session, data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Fixture root must be an object")
    report = {
        "events": 0,
        "users": 0,
        "users_default_password": 0,
        "teams": 0,
        "projects": 0,
        "scores": 0,
        "skipped_memberships": 0,
        "warnings": [],
    }
    events = _event_shells(data)
    if not events:
        report["warnings"].append("No event could be derived from the fixture")
        return report
    report["_default_hash"] = hash_password(DEFAULT_FIXTURE_PASSWORD)
    _import_people(db, data, report)
    for index, shell in enumerate(events):
        top = index == 0
        event = _import_event(db, data, shell, report, take_top_level=top)
        report["events"] += 1
        team_index = _import_teams(db, data, event, report, take_top_level=top)
        titles = _import_projects(db, data, event, shell, report, team_index, take_top_level=top)
        if top:
            _import_scores(db, data, event, report, titles)
    report.pop("_default_hash", None)
    return report


def _warn(report: dict, message: str) -> None:
    if len(report["warnings"]) < 30:
        report["warnings"].append(message)


def _first(row: dict, *keys: str, default: str = "") -> str:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _emails(value) -> list[str]:
    found: list[str] = []
    for item in _as_list(value):
        if isinstance(item, str) and "@" in item:
            email = normalize_email(item)
            if valid_email(email):
                found.append(email)
        elif isinstance(item, dict):
            email = normalize_email(_first(item, "email", "mail"))
            if valid_email(email):
                found.append(email)
    return found


def _parse_dt(value, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return as_utc(value)
    if not value:
        return fallback
    raw = str(value).strip().replace("Z", "+00:00")
    try:
        if len(raw) == 16:
            return datetime.strptime(raw, "%Y-%m-%dT%H:%M").replace(tzinfo=fallback.tzinfo)
        return as_utc(datetime.fromisoformat(raw))
    except ValueError:
        return fallback


def _event_shells(data: dict) -> list[dict]:
    if isinstance(data.get("events"), list) and data["events"]:
        return [row for row in data["events"] if isinstance(row, dict)]
    event = data.get("event")
    if isinstance(event, dict) and (event.get("name") or event.get("slug") or event.get("title")):
        return [event]
    name = _first(data, "event_name", "name", "title")
    if name or _has_records(data):
        return [
            {
                "name": name or "Imported hackathon",
                "slug": _first(data, "slug", "event_slug"),
                "description": _first(data, "description"),
                "starts_at": data.get("starts_at") or data.get("start") or data.get("start_at"),
                "ends_at": data.get("ends_at") or data.get("end") or data.get("end_at"),
                "submission_opens_at": data.get("submission_opens_at") or data.get("submission_open"),
                "submission_deadline": data.get("submission_deadline") or data.get("deadline"),
                "published": data.get("published", True),
            }
        ]
    return []


def _preserve_slug(value: str | None, limit: int = 80) -> str:
    """Keep ids such as evt_01 and trk_04. Slugify free text."""
    raw = (value or "").strip()
    if raw and _ID.fullmatch(raw):
        return raw[:limit]
    return slugify(raw, min(limit, 70))


def _unique_event_slug(db: Session, base: str) -> str:
    slug = _preserve_slug(base, 80) or "event"
    candidate = slug
    n = 2
    while db.scalar(select(Event.id).where(Event.slug == candidate)):
        suffix = f"-{n}"
        candidate = f"{slug[: 80 - len(suffix)]}{suffix}"
        n += 1
    return candidate


def _import_event(db: Session, data: dict, shell: dict, report: dict, take_top_level: bool = True) -> Event:
    now = clock.utcnow()
    name = clip(_first(shell, "name", "title", default="Imported hackathon"), 200)
    slug_source = _first(shell, "id", "slug") or name
    deadline_raw = (
        shell.get("submission_deadline")
        or shell.get("deadline")
        or shell.get("submissions_close")
        or shell.get("submissions_deadline")
    )
    opens_raw = shell.get("submission_opens_at") or shell.get("submission_open")
    starts_raw = shell.get("starts_at") or shell.get("start")
    ends_raw = shell.get("ends_at") or shell.get("end")
    if deadline_raw:
        deadline = _parse_dt(deadline_raw, now + timedelta(days=3))
    else:
        deadline = now + timedelta(days=3)
    if opens_raw:
        opens = _parse_dt(opens_raw, deadline - timedelta(days=3))
    elif deadline_raw:
        opens = deadline - timedelta(days=3)
    else:
        opens = now
    starts = _parse_dt(starts_raw, opens) if starts_raw else opens
    ends = _parse_dt(ends_raw, deadline) if ends_raw else deadline
    # A supplied close time is never moved later. Pull the open bound back instead.
    if opens > deadline:
        opens = deadline - timedelta(hours=1)
        _warn(report, f"Moved submission open earlier so it stays before the deadline ({slug_source})")
    if starts > ends:
        starts = ends - timedelta(hours=1)
        _warn(report, f"Moved event start earlier so it stays before the end ({slug_source})")
    event = Event(
        slug=_unique_event_slug(db, slug_source),
        name=name,
        description=clip(_first(shell, "description", "about"), 20000),
        starts_at=starts,
        ends_at=ends,
        submission_opens_at=opens,
        submission_deadline=deadline,
        published=bool(shell.get("published", True)),
    )
    db.add(event)
    db.flush()
    tracks = _as_list(shell.get("tracks"))
    if take_top_level:
        tracks = tracks + _as_list(data.get("tracks"))
    for row in tracks:
        _add_track(db, event, row, report)
    prizes = _as_list(shell.get("prizes"))
    if take_top_level:
        prizes = prizes + _as_list(data.get("prizes"))
    for row in prizes:
        _add_prize(db, event, row)
    questions = _as_list(shell.get("custom_questions")) + _as_list(shell.get("questions"))
    if take_top_level:
        questions = (
            questions
            + _as_list(data.get("custom_questions"))
            + _as_list(data.get("questions"))
            + _as_list(data.get("submission_questions"))
        )
    for index, row in enumerate(questions):
        if isinstance(row, dict):
            _add_question(db, event, row, index, report)
    return event


def _add_track(db: Session, event: Event, row, report: dict) -> Track | None:
    if isinstance(row, str):
        row = {"name": row}
    if not isinstance(row, dict):
        return None
    name = clip(_first(row, "name", "title", default="Track"), 120)
    base = _preserve_slug(_first(row, "id", "slug") or name, 80) or "track"
    slug = base
    n = 2
    while db.scalar(select(Track.id).where(Track.event_id == event.id, Track.slug == slug)):
        slug = f"{base}-{n}"
        n += 1
    track = Track(
        event_id=event.id,
        slug=slug,
        name=name,
        description=clip(_first(row, "description"), 4000),
    )
    db.add(track)
    db.flush()
    return track


def _find_track(db: Session, event: Event, label: str) -> Track | None:
    if not label:
        return None
    wanted = label.strip()
    wanted_l = wanted.lower()
    tracks = db.scalars(select(Track).where(Track.event_id == event.id)).all()
    for track in tracks:
        if (
            track.slug == wanted
            or track.slug.lower() == wanted_l
            or track.name.lower() == wanted_l
            or track.slug == slugify(wanted, 70)
        ):
            return track
    return None


def _add_prize(db: Session, event: Event, row: dict) -> None:
    if not isinstance(row, dict):
        return
    track_label = _first(row, "track", "track_slug", "track_name")
    track = _find_track(db, event, track_label) if track_label else None
    place_raw = row.get("place") or row.get("rank") or 1
    try:
        place = int(place_raw)
    except (TypeError, ValueError):
        place = 1
    db.add(
        Prize(
            event_id=event.id,
            track_id=track.id if track else None,
            name=clip(_first(row, "name", "title", default="Prize"), 200),
            description=clip(_first(row, "description"), 4000),
            place=max(place, 1),
            amount_label=clip(_first(row, "amount_label", "amount", "value"), 80),
        )
    )
    db.flush()


def _add_question(db: Session, event: Event, row: dict, index: int, report: dict) -> CustomQuestion:
    prompt = clip(_first(row, "prompt", "label", "question", default="Question"), 300)
    base = slugify(_first(row, "key", "id") or prompt, 70) or "question"
    key = base
    n = 2
    while db.scalar(select(CustomQuestion.id).where(CustomQuestion.event_id == event.id, CustomQuestion.key == key)):
        key = f"{base}-{n}"
        n += 1
    raw_type = _first(row, "field_type", "type", "kind", default="short_text").lower()
    field_type = _QUESTION_TYPES.get(raw_type, "short_text")
    options = []
    for option in _as_list(row.get("options") or row.get("choices")):
        text = clip(str(option), 120)
        if text:
            options.append(text)
    if field_type == "single_select" and not options:
        field_type = "short_text"
        _warn(report, f"Question {key} had no choices; stored as short text")
    question = CustomQuestion(
        event_id=event.id,
        key=key,
        prompt=prompt,
        help_text=clip(_first(row, "help_text", "help"), 1000),
        field_type=field_type,
        required=bool(row.get("required", row.get("is_required", False))),
        options_json=options,
        position=int(row.get("position", index) or index),
    )
    db.add(question)
    db.flush()
    return question


def _import_people(db: Session, data: dict, report: dict) -> None:
    rows = []
    for key in ("users", "organisers", "organizers"):
        rows.extend(row for row in _as_list(data.get(key)) if isinstance(row, dict))
    for row in rows:
        _ensure_user(db, row, report, default_role=Role.normalize(_first(row, "role", "type")))
    for row in _as_list(data.get("judges")):
        if isinstance(row, str):
            row = {"email": row, "role": Role.JUDGE}
        if isinstance(row, dict):
            row = dict(row)
            row["role"] = Role.JUDGE
            _ensure_user(db, row, report, default_role=Role.JUDGE)


def _ensure_user(db: Session, row: dict, report: dict, default_role: str = Role.PARTICIPANT) -> User | None:
    email = normalize_email(_first(row, "email", "mail"))
    if not valid_email(email):
        _warn(report, "Skipped a user row with no usable email")
        return None
    existing = db.scalar(select(User).where(User.email == email))
    role = Role.normalize(_first(row, "role", "type")) if row.get("role") or row.get("type") else default_role
    if existing:
        if existing.role == Role.PARTICIPANT and role != Role.PARTICIPANT:
            existing.role = role
        return existing
    password = _first(row, "password")
    password_hash = _first(row, "password_hash")
    if password_hash.startswith("$2"):
        stored = password_hash
    elif password:
        try:
            stored = hash_password(password)
        except ValueError:
            stored = hash_password(DEFAULT_FIXTURE_PASSWORD)
            report["users_default_password"] += 1
            _warn(report, f"{email} had an unusable password; set the fixture default")
    else:
        stored = report.get("_default_hash") or hash_password(DEFAULT_FIXTURE_PASSWORD)
        report["users_default_password"] += 1
    user = User(
        email=email,
        name=clip(_first(row, "name", "display_name", default=email.split("@")[0]), 200),
        password_hash=stored,
        role=role if role in Role.ALL else Role.PARTICIPANT,
    )
    db.add(user)
    db.flush()
    report["users"] += 1
    return user


def _ensure_user_email(db: Session, email: str, report: dict, role: str = Role.PARTICIPANT) -> User | None:
    return _ensure_user(db, {"email": email, "role": role, "name": email.split("@")[0]}, report, role)


def _unique_invite(db: Session, preferred: str | None) -> str:
    raw = (preferred or "").strip()
    if raw and _ID.fullmatch(raw):
        code = raw[:64]
    else:
        code = slugify(preferred, 40) if preferred else ""
    if not code:
        code = secrets.token_urlsafe(9)
    original = code
    n = 2
    while db.scalar(select(Team.id).where(Team.invite_code == code)):
        suffix = f"-{n}"
        code = f"{original[: 64 - len(suffix)]}{suffix}"
        n += 1
        if n > 40:
            code = secrets.token_urlsafe(9)
    return code


def _remember_team(index: dict, team: Team, row: dict) -> None:
    index[team.name.lower()] = team
    ref = _first(row, "id", "slug")
    if ref:
        index[ref] = team
        index[ref.lower()] = team


def _ensure_team(
    db: Session,
    event: Event,
    name: str,
    report: dict,
    invite_code: str | None = None,
    member_emails: list[str] | None = None,
    created_by: User | None = None,
) -> Team:
    clean_name = clip(name or "Untitled team", 120) or "Untitled team"
    team = db.scalar(select(Team).where(Team.event_id == event.id, Team.name == clean_name))
    if team is None:
        team = Team(
            event_id=event.id,
            name=clean_name,
            invite_code=_unique_invite(db, invite_code),
            created_by_id=created_by.id if created_by else None,
        )
        db.add(team)
        db.flush()
        report["teams"] += 1
    for email in member_emails or []:
        user = _ensure_user_email(db, email, report)
        if user is None:
            continue
        if user.role == Role.JUDGE:
            report["skipped_memberships"] += 1
            _warn(report, f"Did not add judge {email} to team {team.name}")
            continue
        already = db.scalar(
            select(TeamMember)
            .join(Team, TeamMember.team_id == Team.id)
            .where(Team.event_id == event.id, TeamMember.user_id == user.id)
        )
        if already is not None:
            if already.team_id != team.id:
                report["skipped_memberships"] += 1
                _warn(report, f"{email} is already on a team for this event")
            continue
        db.add(TeamMember(team_id=team.id, user_id=user.id))
        db.flush()
    return team


def _import_teams(db: Session, data: dict, event: Event, report: dict, take_top_level: bool = True) -> dict:
    index: dict = {}
    nested = []
    if isinstance(data.get("event"), dict):
        nested = _as_list(data["event"].get("teams"))
    rows = (_as_list(data.get("teams")) + nested) if take_top_level else []
    for row in rows:
        if isinstance(row, str):
            row = {"name": row}
        if not isinstance(row, dict):
            continue
        event_label = _first(row, "event", "event_slug")
        if event_label and event_label not in {event.slug, event.name}:
            continue
        invite = _first(row, "invite_code", "invite", "code") or _first(row, "id") or None
        team = _ensure_team(
            db,
            event,
            _first(row, "name", "team", default="Team"),
            report,
            invite_code=invite,
            member_emails=_emails(row.get("members") or row.get("users") or row.get("emails")),
        )
        _remember_team(index, team, row)
    return index


def _status_of(row: dict) -> str:
    raw = _first(row, "status", "state", default="submitted").lower()
    if raw in {"draft", "wip", "incomplete", "unsubmitted"}:
        return "draft"
    return "submitted"


def _team_for_project(db: Session, event: Event, row: dict, name: str, members: list[str], report: dict, team_index: dict) -> Team:
    raw = row.get("team")
    if isinstance(raw, dict):
        ref = _first(raw, "id", "slug", "name")
        nested = _emails(raw.get("members"))
        if nested:
            members = nested
    else:
        ref = _first(row, "team_id", "team", "team_slug", "team_name")
    team = team_index.get(ref) or team_index.get(ref.lower()) if ref else None
    if team is None:
        label = ref or f"{name} team"
        team = _ensure_team(db, event, label, report, invite_code=ref or None, member_emails=members)
        _remember_team(team_index, team, {"id": ref, "name": team.name})
    existing = db.scalar(select(Project).where(Project.team_id == team.id))
    if existing is not None:
        team = _ensure_team(db, event, f"{team.name} / {name}", report, member_emails=members)
        _warn(report, f"Team already had a project; stored '{name}' on a sibling team")
    return team


def _import_projects(
    db: Session,
    data: dict,
    event: Event,
    shell: dict,
    report: dict,
    team_index: dict | None = None,
    take_top_level: bool = True,
) -> dict[str, str]:
    team_index = team_index if team_index is not None else {}
    titles: dict[str, str] = {}
    rows = _as_list(shell.get("projects")) + _as_list(shell.get("submissions"))
    if take_top_level:
        rows = rows + _as_list(data.get("projects")) + _as_list(data.get("submissions"))
    for row in rows:
        if not isinstance(row, dict):
            continue
        event_label = _first(row, "event", "event_slug")
        if event_label and event_label not in {event.slug, event.name}:
            continue
        name = clip(_first(row, "name", "title", "project_name", default="Untitled"), 120)
        members = _emails(row.get("members") or row.get("authors") or row.get("author_email") or row.get("author"))
        team = _team_for_project(db, event, row, name, members, report, team_index)
        track_raw = row.get("track")
        if isinstance(track_raw, dict):
            track_label = _first(track_raw, "id", "slug", "name")
        else:
            track_label = _first(row, "track_id", "track", "track_slug", "track_name")
        track = _find_track(db, event, track_label)
        if track_label and track is None:
            track = _add_track(db, event, {"id": track_label, "name": track_label}, report)
        summary = clip(_first(row, "summary"), 20000)
        description = clip(_first(row, "description", "long_description", "about", "body"), 20000) or summary
        tagline = clip(_first(row, "tagline", "subtitle"), 180) or clip(summary or description or name, 180)
        status = _status_of(row)
        submitted_raw = row.get("submitted_at")
        submitted_at = None
        if status == "submitted":
            submitted_at = _parse_dt(submitted_raw, clock.utcnow()) if submitted_raw else clock.utcnow()
        project = Project(
            event_id=event.id,
            team_id=team.id,
            track_id=track.id if track else None,
            name=name,
            tagline=tagline,
            description=description,
            thumbnail_path=_optional_url(_first(row, "thumbnail_url", "thumbnail", "image"), report),
            demo_video_url=_optional_url(_first(row, "demo_video_url", "video_url", "video"), report),
            repository_url=_optional_url(
                _first(row, "repository_url", "repo_url", "repository", "github"), report
            ),
            live_url=_optional_url(_first(row, "live_url", "live_link", "demo_url", "website", "url"), report),
            status=status,
            submitted_at=submitted_at,
        )
        db.add(project)
        db.flush()
        ext_id = _first(row, "id")
        if ext_id:
            titles[ext_id] = name
            titles[ext_id.lower()] = name
        titles[name] = name
        titles[name.lower()] = name
        tags = row.get("tech_tags") or row.get("tags") or row.get("technologies") or []
        if isinstance(tags, str):
            tags = [part for part in tags.split(",")]
        seen: set[str] = set()
        for tag in tags:
            clean = normalize_tag(str(tag))
            if clean and clean not in seen:
                seen.add(clean)
                db.add(ProjectTag(project_id=project.id, tag=clean))
        images = row.get("gallery") or row.get("images") or row.get("image_gallery") or []
        for position, image in enumerate(_as_list(images)):
            if isinstance(image, dict):
                url = _optional_url(_first(image, "url", "src", "path"), report)
                caption = clip(_first(image, "caption", "alt"), 200)
            else:
                url = _optional_url(str(image), report)
                caption = ""
            if url:
                db.add(ProjectImage(project_id=project.id, path=url, caption=caption, position=position))
        answers = row.get("custom_answers") or row.get("answers") or {}
        if isinstance(answers, dict):
            for key, value in answers.items():
                question = db.scalar(
                    select(CustomQuestion).where(
                        CustomQuestion.event_id == event.id, CustomQuestion.key == slugify(str(key), 70)
                    )
                )
                if question is None:
                    question = _add_question(
                        db,
                        event,
                        {"key": str(key), "prompt": str(key).replace("-", " "), "type": "long_text"},
                        100,
                        report,
                    )
                db.add(CustomAnswer(project_id=project.id, question_id=question.id, value=clip(str(value), 5000)))
        for score in _as_list(row.get("scores")):
            if isinstance(score, dict):
                payload = dict(score)
                payload.setdefault("project", name)
                _store_score(db, event, payload, report)
        report["projects"] += 1
    db.flush()
    return titles


def _optional_url(value: str, report: dict) -> str:
    if not value:
        return ""
    try:
        return clean_http_url(value)
    except ValueError:
        _warn(report, f"Dropped URL that is not http(s): {value[:80]}")
        return ""


def _import_scores(db: Session, data: dict, event: Event, report: dict, titles: dict | None = None) -> None:
    raw = data.get("scores")
    if raw is None:
        raw = data.get("judgements", data.get("judgments", []))
    rows: list = []
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw, dict):
        for key, val in raw.items():
            if isinstance(val, dict):
                item = dict(val)
                item.setdefault("project", key)
                rows.append(item)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        copied = dict(item)
                        copied.setdefault("project", key)
                        rows.append(copied)
            else:
                rows.append({"project": key, "score": val})
    for row in rows:
        _store_score(db, event, row if isinstance(row, dict) else {"score": row}, report, titles)


def _label_project(project, titles: dict | None) -> str:
    if isinstance(project, dict):
        project = _first(project, "id", "name", "title")
    text = str(project or "")
    if titles:
        return titles.get(text) or titles.get(text.lower()) or text
    return text


def _insert_score(db: Session, event: Event, project: str, judge: str, criterion: str, score, payload: dict, report: dict) -> None:
    db.add(
        RetainedScore(
            event_id=event.id,
            project_name=clip(project, 200),
            judge_email=clip(str(judge), 255),
            criterion=clip(str(criterion), 200),
            score_value=clip("" if score is None else str(score), 64),
            payload=payload,
        )
    )
    report["scores"] += 1


def _store_score(db: Session, event: Event, row: dict, report: dict, titles: dict | None = None) -> None:
    project = _label_project(row.get("project") or row.get("project_name") or row.get("submission") or "", titles)
    judge = row.get("judge") or row.get("judge_email") or row.get("reviewer") or ""
    if isinstance(judge, dict):
        judge = _first(judge, "email", "id", "name")
    criteria = row.get("criteria")
    if isinstance(criteria, dict) and criteria and all(not isinstance(value, (dict, list)) for value in criteria.values()):
        for key, value in criteria.items():
            _insert_score(db, event, project, judge, str(key), value, row, report)
        return
    criterion = row.get("criterion") or row.get("category") or ""
    if not criterion and isinstance(criteria, str):
        criterion = criteria
    if isinstance(criterion, dict):
        criterion = _first(criterion, "name", "key")
    score = row.get("score", row.get("value", row.get("rating", "")))
    _insert_score(db, event, project, judge, str(criterion), score, row, report)
