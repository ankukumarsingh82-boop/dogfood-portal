"""Local image uploads. Files are renamed; the original filename is never stored."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from dogfood.config import Settings

ALLOWED = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_BYTES = 5 * 1024 * 1024


def is_upload(value) -> bool:
    return bool(value is not None and getattr(value, "filename", None))


def save_upload(upload, settings: Settings) -> str:
    ext = Path(upload.filename or "").suffix.lower()
    if ext not in ALLOWED:
        raise ValueError("Images must be png, jpg, gif, or webp")
    data = upload.file.read()
    if not data:
        raise ValueError("Image file is empty")
    if len(data) > MAX_BYTES:
        raise ValueError("Image must be 5 MB or smaller")
    name = f"{uuid4().hex}{ext}"
    dest = Path(settings.upload_dir)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / name).write_bytes(data)
    return f"/media/{name}"
