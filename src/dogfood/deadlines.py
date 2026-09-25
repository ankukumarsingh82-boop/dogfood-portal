"""Submission window. The server clock is the only clock that counts."""

from __future__ import annotations

from datetime import datetime, timezone

from dogfood import clock

MSG_DEADLINE = "Submission deadline has passed"
MSG_NOT_OPEN = "Submissions are not open yet"
MSG_JOIN_CLOSED = "Team joining is closed because the submission deadline has passed"


def as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt: datetime | None) -> str:
    if not dt:
        return ""
    return as_utc(dt).strftime("%Y-%m-%d %H:%M")


def dt_local(dt: datetime | None) -> str:
    if not dt:
        return ""
    return as_utc(dt).strftime("%Y-%m-%dT%H:%M")


def parse_form_dt(value: str | None) -> datetime:
    raw = (value or "").strip()
    if not raw:
        raise ValueError("Date is required")
    raw = raw.replace("Z", "+00:00")
    if len(raw) == 16:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(raw)
    return as_utc(parsed)


def submission_phase(event) -> str:
    """Return early, open, or closed. The deadline instant itself is still open."""
    now = clock.utcnow()
    opens = as_utc(event.submission_opens_at)
    deadline = as_utc(event.submission_deadline)
    if now < opens:
        return "early"
    if now > deadline:
        return "closed"
    return "open"


def validate_event_window(starts: datetime, ends: datetime, opens: datetime, deadline: datetime) -> list[str]:
    errors: list[str] = []
    if starts > ends:
        errors.append("Event end must be at or after the start")
    if opens > deadline:
        errors.append("Submission deadline must be at or after submissions open")
    return errors
