"""Server-enforced T1 behaviour: roles, invites, deadlines, gallery."""

from datetime import timedelta

from dogfood.auth import hash_password
from dogfood.authz import MSG_JUDGE_SUBMIT, MSG_JUDGE_TEAM, MSG_ONE_TEAM, MSG_ORGANIZER
from dogfood.deadlines import MSG_DEADLINE
from dogfood.clock import utcnow
from dogfood.models import Role, User


def add_user(db, email, role, password="test-pass-72", name=None):
    user = User(
        email=email,
        name=name or email.split("@")[0],
        password_hash=hash_password(password),
        role=role,
    )
    db.add(user)
    db.commit()
    return user


def login(client, email, password="test-pass-72"):
    response = client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return response


def stamp(delta: timedelta) -> str:
    return (utcnow() + delta).strftime("%Y-%m-%dT%H:%M")


def event_fields(name="Field Day", slug="field-day", open_days=-1, deadline_days=5):
    return {
        "name": name,
        "slug": slug,
        "description": "A test event",
        "starts_at": stamp(timedelta(days=open_days)),
        "ends_at": stamp(timedelta(days=deadline_days + 2)),
        "submission_opens_at": stamp(timedelta(days=open_days)),
        "submission_deadline": stamp(timedelta(days=deadline_days)),
    }


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_register_login_logout_and_role_is_participant(client, db):
    response = client.post(
        "/register",
        data={
            "name": "New Person",
            "email": "new@example.com",
            "password": "long-enough",
            "password_confirm": "long-enough",
            "role": "admin",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    user = db.query(User).filter(User.email == "new@example.com").one()
    assert user.role == Role.PARTICIPANT
    page = client.get("/")
    assert "New Person" in page.text
    logged_out = client.post("/logout", follow_redirects=False)
    assert logged_out.status_code == 303
    home = client.get("/")
    assert "Log in" in home.text
    bad = client.post("/login", data={"email": "new@example.com", "password": "nope"})
    assert bad.status_code == 401
    assert "Email or password is incorrect" in bad.text


def test_roles_are_enforced_on_the_server(client, db):
    add_user(db, "org@example.com", Role.ORGANIZER, name="Org")
    add_user(db, "part@example.com", Role.PARTICIPANT, name="Part")
    add_user(db, "judge@example.com", Role.JUDGE, name="Judge")

    visitor = client.get("/events/new", follow_redirects=False)
    assert visitor.status_code == 303
    assert "/login" in visitor.headers["location"]

    denied = client.post("/events", data=event_fields(), follow_redirects=False)
    assert denied.status_code == 401

    login(client, "part@example.com")
    participant = client.post("/events", data=event_fields())
    assert participant.status_code == 403
    assert MSG_ORGANIZER in participant.text
    client.post("/logout", follow_redirects=False)

    login(client, "judge@example.com")
    judge = client.post("/events", data=event_fields(slug="other"))
    assert judge.status_code == 403
    assert MSG_ORGANIZER in judge.text
    client.post("/logout", follow_redirects=False)

    login(client, "org@example.com")
    created = client.post("/events", data=event_fields(), follow_redirects=False)
    assert created.status_code == 303
    assert created.headers["location"].startswith("/e/field-day/manage")


def test_invite_submit_deadline_and_gallery(client, db):
    add_user(db, "org@example.com", Role.ORGANIZER)
    add_user(db, "ada@example.com", Role.PARTICIPANT, name="Ada")
    add_user(db, "bea@example.com", Role.PARTICIPANT, name="Bea")
    add_user(db, "judge@example.com", Role.JUDGE)

    login(client, "org@example.com")
    assert client.post("/events", data=event_fields(name="Night Market", slug="night-market"), follow_redirects=False).status_code == 303
    assert client.post("/e/night-market/tracks", data={"name": "Systems", "description": "Low level"}).status_code == 200
    assert client.post(
        "/e/night-market/prizes",
        data={"name": "Grand", "description": "Overall", "place": "1", "amount_label": "$800", "track_id": ""},
    ).status_code == 200
    assert client.post(
        "/e/night-market/questions",
        data={"prompt": "What did you cut?", "help_text": "", "field_type": "long_text", "required": "on", "options": ""},
    ).status_code == 200
    assert client.post("/e/night-market/publish", data={"published": "1"}, follow_redirects=False).status_code == 303
    client.post("/logout", follow_redirects=False)

    login(client, "judge@example.com")
    blocked = client.post("/e/night-market/teams", data={"name": "Bench"})
    assert blocked.status_code == 403
    assert MSG_JUDGE_TEAM in blocked.text
    submit_blocked = client.post("/e/night-market/submission", data={"intent": "draft", "name": "Nope"})
    assert submit_blocked.status_code == 403
    assert MSG_JUDGE_SUBMIT in submit_blocked.text
    client.post("/logout", follow_redirects=False)

    login(client, "ada@example.com")
    created = client.post("/e/night-market/teams", data={"name": "Ada Team"}, follow_redirects=False)
    assert created.status_code == 303
    page = client.get("/e/night-market")
    assert "/join/" in page.text
    code = page.text.split("/join/")[1].split('"')[0].split("<")[0].strip()
    assert code
    again = client.post("/e/night-market/teams", data={"name": "Second"})
    assert again.status_code == 403
    assert MSG_ONE_TEAM in again.text

    missing = client.post(
        "/e/night-market/submission",
        data={"intent": "submit", "name": "Widget", "tagline": "Short", "description": "Long", "track_id": ""},
    )
    assert missing.status_code == 400
    assert "Track is required" in missing.text
    gallery = client.get("/e/night-market/gallery")
    assert "Widget" not in gallery.text

    track_page = client.get("/e/night-market/submission")
    track_id = track_page.text.split('value="')[1].split('"')[0]
    # The first value may be empty option. Find the Systems option.
    assert "Systems" in track_page.text
    import re

    match = re.search(r'<option value="(\d+)"[^>]*>Systems</option>', track_page.text)
    assert match
    track_id = match.group(1)
    question = re.search(r'name="(q_\d+)"', track_page.text)
    assert question
    question_name = question.group(1)

    saved = client.post(
        "/e/night-market/submission",
        data={
            "intent": "draft",
            "name": "Widget",
            "tagline": "Counts things",
            "description": "A longer description of the widget.",
            "track_id": track_id,
            "tech_tags": "rust, postgres",
            "repository_url": "https://example.com/widget",
            "live_url": "javascript:alert(1)",
        },
        follow_redirects=False,
    )
    assert saved.status_code == 400
    assert "javascript" not in client.get("/e/night-market/gallery").text.lower() or "Widget" not in client.get("/e/night-market/gallery").text

    rejected = client.post(
        "/e/night-market/submission",
        data={
            "intent": "submit",
            "name": "Widget",
            "tagline": "Counts things",
            "description": "A longer description of the widget.",
            "track_id": track_id,
            "tech_tags": "rust, postgres",
            "repository_url": "https://example.com/widget",
            question_name: "",
        },
    )
    assert rejected.status_code == 400
    assert "required" in rejected.text.lower()
    assert "Widget" not in client.get("/e/night-market/gallery").text

    submitted = client.post(
        "/e/night-market/submission",
        data={
            "intent": "submit",
            "name": "Widget",
            "tagline": "Counts things",
            "description": "A longer description of the widget.",
            "track_id": track_id,
            "tech_tags": "rust, postgres",
            "repository_url": "https://example.com/widget",
            "live_url": "https://example.com/widget/live",
            "demo_video_url": "https://example.com/widget/video",
            question_name: "We cut the mobile app.",
        },
        follow_redirects=False,
    )
    assert submitted.status_code == 303
    edited = client.post(
        "/e/night-market/submission",
        data={
            "intent": "submit",
            "name": "Widget Revised",
            "tagline": "Counts things",
            "description": "A longer description of the widget.",
            "track_id": track_id,
            "tech_tags": "rust, postgres",
            "repository_url": "https://example.com/widget",
            question_name: "We cut the mobile app.",
        },
        follow_redirects=False,
    )
    assert edited.status_code == 303
    client.post("/logout", follow_redirects=False)

    login(client, "bea@example.com")
    joined = client.post(f"/join/{code}", follow_redirects=False)
    assert joined.status_code == 303
    second = client.post(f"/join/{code}")
    assert second.status_code == 200 or "already" in second.text.lower()
    # Bea is now on Ada's team, so a second team is refused.
    assert client.post("/e/night-market/teams", data={"name": "Bea Team"}).status_code == 403
    client.post("/logout", follow_redirects=False)

    public = client.get("/e/night-market/gallery")
    assert "Widget Revised" in public.text
    assert "Unsent" not in public.text
    by_text = client.get("/e/night-market/gallery?q=revised")
    assert "Widget Revised" in by_text.text
    by_track = client.get("/e/night-market/gallery?track=systems")
    assert "Widget Revised" in by_track.text
    by_other = client.get("/e/night-market/gallery?track=missing-track")
    assert "Widget Revised" not in by_other.text
    by_tag = client.get("/e/night-market/gallery?tag=postgres")
    assert "Widget Revised" in by_tag.text
    partial = client.get("/e/night-market/gallery?q=revised", headers={"HX-Request": "true"})
    assert "<html" not in partial.text.lower()
    assert "Widget Revised" in partial.text

    login(client, "org@example.com")
    closed = event_fields(name="Night Market", slug="ignored", open_days=-3, deadline_days=-1)
    assert client.post("/e/night-market/settings", data={
        "name": "Night Market",
        "description": "A test event",
        "starts_at": closed["starts_at"],
        "ends_at": closed["ends_at"],
        "submission_opens_at": closed["submission_opens_at"],
        "submission_deadline": closed["submission_deadline"],
    }, follow_redirects=False).status_code == 303
    client.post("/logout", follow_redirects=False)

    login(client, "ada@example.com")
    late = client.post(
        "/e/night-market/submission",
        data={
            "intent": "draft",
            "name": "Smuggled",
            "tagline": "Too late",
            "description": "Should not save",
            "track_id": track_id,
            question_name: "no",
        },
    )
    assert late.status_code == 403
    assert MSG_DEADLINE in late.text
    assert "Smuggled" not in client.get("/e/night-market/gallery").text
    assert "Widget Revised" in client.get("/e/night-market/gallery").text
    readonly = client.get("/e/night-market/submission")
    assert readonly.status_code == 200
    assert "read-only" in readonly.text


def test_submissions_before_open_are_rejected(client, db):
    add_user(db, "org@example.com", Role.ORGANIZER)
    add_user(db, "ada@example.com", Role.PARTICIPANT)
    login(client, "org@example.com")
    fields = event_fields(slug="future", open_days=2, deadline_days=4)
    assert client.post("/events", data=fields, follow_redirects=False).status_code == 303
    client.post("/e/future/publish", data={"published": "1"})
    client.post("/logout", follow_redirects=False)
    login(client, "ada@example.com")
    denied = client.post("/e/future/teams", data={"name": "Early"})
    assert denied.status_code == 403


def test_admin_roles_and_export_are_not_for_participants(client, db):
    admin = add_user(db, "admin@example.com", Role.ADMIN)
    add_user(db, "org@example.com", Role.ORGANIZER)
    participant = add_user(db, "part@example.com", Role.PARTICIPANT)
    login(client, "part@example.com")
    assert client.get("/admin/users").status_code == 403
    client.post("/logout", follow_redirects=False)
    login(client, "org@example.com")
    assert client.post("/events", data=event_fields(slug="export-me"), follow_redirects=False).status_code == 303
    client.post("/e/export-me/publish", data={"published": "1"})
    exported = client.get("/e/export-me/export.json")
    assert exported.status_code == 200
    assert "password_hash" not in exported.text
    assert exported.json()["event"]["slug"] == "export-me"
    client.post("/logout", follow_redirects=False)
    login(client, "part@example.com")
    assert client.get("/e/export-me/export.json").status_code == 403
    client.post("/logout", follow_redirects=False)
    login(client, "admin@example.com")
    changed = client.post(f"/admin/users/{participant.id}/role", data={"role": "judge"}, follow_redirects=False)
    assert changed.status_code == 303
    db.refresh(participant)
    assert participant.role == Role.JUDGE
    last = client.post(f"/admin/users/{admin.id}/role", data={"role": "participant"})
    assert last.status_code == 403
    assert "last admin" in last.text


def test_unpublished_gallery_is_hidden(client, db):
    add_user(db, "org@example.com", Role.ORGANIZER)
    login(client, "org@example.com")
    assert client.post("/events", data=event_fields(slug="quiet"), follow_redirects=False).status_code == 303
    assert client.get("/e/quiet/gallery").status_code == 200
    client.post("/logout", follow_redirects=False)
    assert client.get("/e/quiet/gallery").status_code == 404
    assert client.get("/e/quiet").status_code == 404
