"""Small string helpers shared by forms and the fixture importer."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_SLUG = re.compile(r"[^a-z0-9]+")
_TAG = re.compile(r"[^a-z0-9.+# _-]")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def clip(value: str | None, limit: int) -> str:
    text = (value or "").replace("\x00", "").strip()
    return text[:limit]


def slugify(value: str | None, limit: int = 60) -> str:
    text = _SLUG.sub("-", (value or "").lower().strip())
    return text.strip("-")[:limit]


def normalize_email(value: str | None) -> str:
    return (value or "").strip().lower()


def valid_email(value: str) -> bool:
    return bool(_EMAIL.match(value)) and len(value) <= 255


def normalize_tag(value: str) -> str:
    text = (value or "").strip().lower().replace("\x00", "")
    text = re.sub(r"\s+", " ", text)
    text = _TAG.sub("", text)
    return text[:32]


def parse_tags(value: str | None) -> list[str]:
    seen: list[str] = []
    for part in (value or "").split(","):
        tag = normalize_tag(part)
        if tag and tag not in seen:
            seen.append(tag)
        if len(seen) >= 16:
            break
    return seen


def clean_http_url(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if any(ch.isspace() for ch in raw):
        raise ValueError("URL cannot contain spaces")
    if len(raw) > 500:
        raise ValueError("URL is too long")
    if raw.startswith("/") and not raw.startswith("//") and not raw.startswith("/\\"):
        return raw
    parts = urlsplit(raw)
    if parts.scheme in {"http", "https"} and parts.netloc:
        return raw
    raise ValueError("Use an http(s) URL")


def like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
