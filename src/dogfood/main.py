"""ASGI app. Schema and seed run on startup so `docker compose up` is enough."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text

from dogfood.config import Settings, get_settings
from dogfood.database import make_engine, make_session_factory
from dogfood.models import Base, User
from dogfood.routes.admin_routes import router as admin_router
from dogfood.routes.auth_routes import router as auth_router
from dogfood.routes.event_routes import router as event_router
from dogfood.routes.gallery_routes import router as gallery_router
from dogfood.routes.submission_routes import router as submission_router
from dogfood.routes.team_routes import router as team_router
from dogfood.seed import run_seed
from dogfood.web import TEMPLATES

STATIC_DIR = Path(__file__).resolve().parent / "static"


def build_app(settings: Settings | None = None, engine=None) -> FastAPI:
    settings = settings or get_settings()
    engine = engine or make_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        Path(app.state.settings.upload_dir).mkdir(parents=True, exist_ok=True)
        if app.state.settings.seed_force and app.state.settings.seed_on_start:
            Base.metadata.drop_all(app.state.engine)
        Base.metadata.create_all(app.state.engine)
        if app.state.settings.seed_on_start:
            db = app.state.SessionLocal()
            try:
                populated = db.scalar(select(func.count()).select_from(User)) or 0
                if populated and not app.state.settings.seed_force:
                    print("seed: database already populated; leaving it in place")
                    print("seed: wipe the volume or set SEED_FORCE=1 to load fixtures again")
                else:
                    run_seed(db, app.state.settings)
                    db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()
        yield

    app = FastAPI(
        title="Dogfood Portal",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.SessionLocal = make_session_factory(engine)
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.mount("/media", StaticFiles(directory=settings.upload_dir), name="media")
    app.include_router(auth_router)
    app.include_router(event_router)
    app.include_router(team_router)
    app.include_router(submission_router)
    app.include_router(gallery_router)
    app.include_router(admin_router)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        accept = request.headers.get("accept", "")
        if "application/json" in accept:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        user = None
        try:
            db = request.app.state.SessionLocal()
            try:
                from dogfood.auth import current_user

                user = current_user(request, db)
            finally:
                db.close()
        except Exception:
            user = None
        return TEMPLATES.TemplateResponse(
            request,
            "error.html",
            {"user": user, "status_code": exc.status_code, "detail": str(exc.detail), "notice": "", "errors": []},
            status_code=exc.status_code,
        )

    @app.get("/health")
    def health(request: Request):
        db = request.app.state.SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
        return {"ok": True}

    return app


app = build_app()
