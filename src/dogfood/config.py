"""Runtime settings from the environment. No secrets service, no hosted config."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _default_fixtures() -> str:
    env = os.environ.get("FIXTURES_PATH")
    if env:
        return env
    bundled = Path(__file__).resolve().parents[2] / "fixtures" / "fixtures.json"
    return str(bundled)


def _default_upload() -> str:
    env = os.environ.get("UPLOAD_DIR")
    if env:
        return env
    if os.environ.get("RUNNING_IN_DOCKER") == "1":
        return "/data/uploads"
    return str(Path(__file__).resolve().parents[2] / "data" / "uploads")


def _default_database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://dogfood:dogfood@localhost:5432/dogfood",
    )


@dataclass(frozen=True)
class Settings:
    database_url: str
    fixtures_path: str
    upload_dir: str
    cookie_secure: bool
    seed_on_start: bool
    seed_force: bool
    port: int
    session_days: int = 14


def get_settings() -> Settings:
    return Settings(
        database_url=_default_database_url(),
        fixtures_path=_default_fixtures(),
        upload_dir=_default_upload(),
        cookie_secure=os.environ.get("COOKIE_SECURE", "0") == "1",
        seed_on_start=os.environ.get("SEED_ON_START", "1") == "1",
        seed_force=os.environ.get("SEED_FORCE", "0") == "1",
        port=int(os.environ.get("PORT", "8000")),
    )
