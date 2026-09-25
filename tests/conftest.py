import pytest
from fastapi.testclient import TestClient

from dogfood.config import Settings
from dogfood.database import make_engine
from dogfood.main import build_app


@pytest.fixture()
def app(tmp_path):
    engine = make_engine("sqlite://")
    settings = Settings(
        database_url="sqlite://",
        fixtures_path=str(tmp_path / "no-fixtures.json"),
        upload_dir=str(tmp_path / "uploads"),
        cookie_secure=False,
        seed_on_start=False,
        seed_force=False,
        port=8000,
    )
    return build_app(settings, engine)


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db(app, client):
    session = app.state.SessionLocal()
    try:
        yield session
    finally:
        session.close()
