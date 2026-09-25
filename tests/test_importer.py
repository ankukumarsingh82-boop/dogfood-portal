"""Fixture import accepts the documented shape and a looser event dump."""

import json
from pathlib import Path

from sqlalchemy import func, select

from dogfood.importer import DEFAULT_FIXTURE_PASSWORD, classify_fixture, import_payload
from dogfood.models import Project, RetainedScore, User


def test_placeholder_and_empty_are_not_real(tmp_path):
    placeholder = tmp_path / "fixtures.json"
    placeholder.write_text(json.dumps({"placeholder": True, "projects": [{"name": "Nope"}]}), encoding="utf-8")
    assert classify_fixture(placeholder) == "placeholder"
    assert classify_fixture(tmp_path / "missing.json") == "missing"
    empty = tmp_path / "empty.json"
    empty.write_text("{}", encoding="utf-8")
    assert classify_fixture(empty) == "empty"
    broken = tmp_path / "bad.json"
    broken.write_text("{", encoding="utf-8")
    assert classify_fixture(broken) == "invalid"


def test_documented_schema_and_aliases(db):
    root = Path(__file__).resolve().parents[1] / "fixtures" / "fixtures.json"
    example = json.loads(root.read_text(encoding="utf-8"))["schema_example"]
    report = import_payload(db, example)
    db.commit()
    assert report["projects"] >= 1
    assert report["scores"] >= 1
    project = db.scalar(select(Project).where(Project.name == "Example Project"))
    assert project is not None
    assert project.status == "submitted"
    assert {tag.tag for tag in project.tags} == {"python"}

    user = db.scalar(select(User).where(User.email == "person@example.com"))
    assert user is not None
    from dogfood.auth import verify_password

    assert verify_password("change-me-please", user.password_hash)


def test_alternate_dump_duplicates_and_default_password(db, client):
    payload = {
        "event_name": "Alt Cup",
        "slug": "alt-cup",
        "tracks": [{"name": f"T{i}"} for i in range(8)],
        "judges": [{"email": f"j{i}@example.com", "name": f"Judge {i}"} for i in range(5)],
        "projects": [
            {
                "title": "Widget",
                "team_name": "Widgets",
                "track_name": "T0",
                "technologies": ["Rust"],
                "github": "https://example.com/w",
                "long_description": "A widget",
            },
            {
                "title": "Widget",
                "team_name": "Widgets Copy",
                "track_name": "T1",
                "summary": "duplicate entry on purpose",
            },
        ]
        + [
            {"name": f"P{i}", "team": f"Team {i}", "track": f"T{i % 8}", "tagline": "t", "description": "d"}
            for i in range(10)
        ],
        "scores": [
            {"submission": "Widget", "reviewer": "j0@example.com", "category": "impact", "rating": "ZZ-SCORE-91"}
        ],
    }
    # Same judge marks every project the same. Incomplete rows are still stored.
    payload["scores"].extend(
        {"project": f"P{i}", "judge": "j0@example.com", "criterion": "impact", "score": 3} for i in range(10)
    )
    report = import_payload(db, payload)
    db.commit()
    assert report["projects"] == 12
    assert report["users_default_password"] >= 5
    assert db.scalar(select(func.count()).select_from(Project).where(Project.name == "Widget")) == 2
    assert db.scalar(select(func.count()).select_from(RetainedScore)) == 11

    page = client.get("/e/alt-cup/gallery")
    assert page.status_code == 200
    assert "Widget" in page.text
    assert "ZZ-SCORE-91" not in page.text
    detail = client.get("/e/alt-cup/gallery?q=widget")
    assert "ZZ-SCORE-91" not in detail.text
    judge = db.scalar(select(User).where(User.email == "j0@example.com"))
    assert judge.role == "judge"
    from dogfood.auth import verify_password

    assert verify_password(DEFAULT_FIXTURE_PASSWORD, judge.password_hash)


def test_scores_route_is_not_published(client, db):
    import_payload(db, {"event_name": "Quiet", "slug": "quiet-scores", "projects": [{"name": "Only"}]})
    db.commit()
    assert client.get("/e/quiet-scores/scores").status_code == 404
