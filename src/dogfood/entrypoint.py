"""Wait for Postgres, then serve the app. Compose uses this as the container command."""

from __future__ import annotations

import time

import uvicorn
from sqlalchemy import create_engine, text

from dogfood.config import get_settings


def wait_for_db(url: str, attempts: int = 60) -> None:
    engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})
    last: Exception | None = None
    for _ in range(attempts):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            engine.dispose()
            return
        except Exception as exc:  # database is still starting
            last = exc
            time.sleep(1)
    engine.dispose()
    raise SystemExit(f"database not reachable: {last}")


def main() -> None:
    settings = get_settings()
    if not settings.database_url.startswith("sqlite"):
        wait_for_db(settings.database_url)
    uvicorn.run("dogfood.main:app", host="0.0.0.0", port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
