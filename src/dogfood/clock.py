"""Clock indirection so tests can move time without expiring sessions."""

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
