"""Fixture import accepts the documented shape and a looser event dump."""

import json
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select

from dogfood import clock
from dogfood.deadlines import as_utc
from dogfood.importer import DEFAULT_FIXTURE_PASSWORD, classify_fixture, import_payload
from dogfood.models import Event, Project, RetainedScore, Team, Track, User, UserSession


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


SCHEMA_EXAMPLE = {
    "event": {
        "slug": "example-event",
        "name": "Example Event",
        "description": "Canonical shape for fixtures.json.",
        "starts_at": "2026-09-25T18:00:00Z",
        "ends_at": "2026-09-28T18:00:00Z",
        "submission_opens_at": "2026-09-25T18:00:00Z",
        "submission_deadline": "2026-09-28T18:00:00Z",
        "published": True,
        "tracks": [{"slug": "general", "name": "General", "description": "Default track"}],
        "prizes": [{"name": "Grand prize", "description": "Overall", "place": 1, "amount_label": "$800", "track": None}],
        "custom_questions": [{"key": "cut", "prompt": "What did you cut?", "type": "long_text", "required": True}],
    },
    "users": [{"email": "person@example.com", "name": "Person Example", "password": "change-me-please", "role": "participant"}],
    "judges": [{"email": "judge@example.com", "name": "Judge Example"}],
    "teams": [{"name": "Example Team", "invite_code": "example-invite", "members": ["person@example.com"]}],
    "projects": [
        {
            "name": "Example Project",
            "tagline": "A short line",
            "description": "Long description of the example project.",
            "repository_url": "https://example.com/repo",
            "tech_tags": ["python"],
            "track": "general",
            "team": "Example Team",
            "status": "submitted",
            "custom_answers": {"cut": "scope"},
        }
    ],
    "scores": [{"project": "Example Project", "judge": "judge@example.com", "criterion": "impact", "score": 4}],
}


def test_documented_schema_and_aliases(db):
    example = SCHEMA_EXAMPLE
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


def test_official_kickoff_shape_stays_closed_and_public(db, client):
    path = Path(__file__).resolve().parents[1] / "fixtures" / "fixtures.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["event"]["id"] == "evt_01"
    report = import_payload(db, data)
    db.commit()
    assert report["projects"] == 41
    assert report["scores"] == 126 * 3
    event = db.scalar(select(Event).where(Event.slug == "evt_01"))
    assert event is not None
    assert event.name == "Sample Hack 2026"
    assert event.submission_deadline.year == 2026
    assert event.submission_deadline.month == 3
    assert as_utc(event.submission_opens_at) < as_utc(event.submission_deadline)
    assert as_utc(event.submission_deadline) < clock.utcnow()
    assert db.scalar(select(Track).where(Track.event_id == event.id, Track.slug == "trk_04")).name == "Security"
    assert db.scalar(select(Team).where(Team.invite_code == "tm_01")).name == "NorthKiln"
    project = db.scalar(select(Project).where(Project.name == "Glass Signal"))
    assert project.repository_url == "https://example.org/repo/01"
    assert project.track.slug == "trk_04"
    assert db.scalar(select(func.count()).select_from(Project).where(Project.name == "Dry Harbour")) == 2
    score = db.scalar(select(RetainedScore).where(RetainedScore.project_name == "Glass Signal"))
    assert score is not None
    assert score.criterion in {"functionality", "quality", "innovation"}

    page = client.get("/e/evt_01/gallery")
    assert page.status_code == 200
    for title in ("Glass Signal", "Small Meadow", "Deep Compass"):
        assert title in page.text
    filtered = client.get("/e/evt_01/gallery?track=trk_04")
    assert "Glass Signal" in filtered.text

    user = db.scalar(select(User).where(User.email == "priya1@example.org"))
    db.add(UserSession(id="prt_closed", user_id=user.id, expires_at=clock.utcnow() + timedelta(days=2)))
    db.commit()
    refused = client.post(
        "/e/evt_01/submission",
        headers={"Cookie": "dogfood_session=prt_closed"},
        json={"title": "dogfood-late-submission-probe", "summary": "probe"},
    )
    assert 400 <= refused.status_code < 500


def test_scores_route_is_not_published(client, db):
    import_payload(db, {"event_name": "Quiet", "slug": "quiet-scores", "projects": [{"name": "Only"}]})
    db.commit()
    assert client.get("/e/quiet-scores/scores").status_code == 404
