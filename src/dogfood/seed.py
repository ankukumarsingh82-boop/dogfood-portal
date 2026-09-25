"""First-boot seed. Real fixtures win; otherwise a small built-in event is loaded."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from dogfood import clock
from dogfood.auth import hash_password
from dogfood.config import Settings
from dogfood.importer import classify_fixture, import_payload
from dogfood.models import AppMeta, Role, User, UserSession

DEMO_ACCOUNTS = [
    {"name": "Avery Admin", "email": "admin@dogfood.local", "password": "admin-pass-72", "role": "admin"},
    {"name": "Owen Organizer", "email": "organizer@dogfood.local", "password": "organizer-pass-72", "role": "organizer"},
    {"name": "Jules Judge", "email": "judge@dogfood.local", "password": "judge-pass-72", "role": "judge"},
    {"name": "Parker Participant", "email": "participant@dogfood.local", "password": "participant-pass-72", "role": "participant"},
    {"name": "Taylor Teammate", "email": "teammate@dogfood.local", "password": "teammate-pass-72", "role": "participant"},
    {"name": "Casey Author", "email": "author@dogfood.local", "password": "author-pass-72", "role": "participant"},
    {"name": "Morgan Maker", "email": "maker@dogfood.local", "password": "maker-pass-72", "role": "participant"},
]

INVITE_CODE = "night-shift-invite"

# The acceptance checker never logs in. It sends these Cookie values.
CHECKER_SESSIONS = {
    "organizer": "org_dogfood_t1",
    "judge_a": "jdg_a_dogfood_t1",
    "judge_b": "jdg_b_dogfood_t1",
    "participant": "prt_dogfood_t1",
}


def builtin_payload() -> dict:
    now = clock.utcnow()
    opens = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    deadline = (now + timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ends = (now + timedelta(days=16)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "event": {
            "slug": "field-test",
            "name": "Weekend Field Test",
            "description": (
                "A seeded event so the portal is usable before official fixtures arrive. "
                "Submissions stay editable until the deadline, which is enforced on the server."
            ),
            "starts_at": opens,
            "ends_at": ends,
            "submission_opens_at": opens,
            "submission_deadline": deadline,
            "published": True,
            "tracks": [
                {"slug": "field-tools", "name": "Field Tools", "description": "Offline and on-site tools."},
                {"slug": "data", "name": "Data", "description": "Models, pipelines, and ledgers."},
                {"slug": "interfaces", "name": "Interfaces", "description": "The part a judge actually touches."},
            ],
            "prizes": [
                {"name": "Grand prize", "description": "Best overall project.", "place": 1, "amount_label": "$800"},
                {
                    "name": "Field prize",
                    "description": "Best project on Field Tools.",
                    "place": 1,
                    "amount_label": "$200",
                    "track": "field-tools",
                },
            ],
            "custom_questions": [
                {
                    "key": "cut",
                    "prompt": "What did you cut?",
                    "help_text": "Required before a project can be submitted.",
                    "type": "long_text",
                    "required": True,
                }
            ],
        },
        "users": DEMO_ACCOUNTS,
        "teams": [
            {"name": "Night Shift", "invite_code": INVITE_CODE, "members": ["teammate@dogfood.local"]},
            {"name": "Paper Club", "invite_code": "paper-club-invite", "members": ["author@dogfood.local"]},
            {"name": "Signal Club", "invite_code": "signal-club-invite", "members": ["maker@dogfood.local"]},
        ],
        "projects": [
            {
                "name": "Unsent Draft",
                "tagline": "A project that is not in the gallery yet",
                "description": "Taylor started this and stopped before answering the required question.",
                "track": "interfaces",
                "team": "Night Shift",
                "tech_tags": ["draft"],
                "status": "draft",
                "repository_url": "https://example.com/unsent",
            },
            {
                "name": "Paper Ledger",
                "tagline": "Offline-first score sheet for a judging table",
                "description": (
                    "A carbon-copy ledger that records scores when the network is down "
                    "and reconciles them later. Search for ledger or filter the Field Tools track."
                ),
                "thumbnail_url": "/static/placeholders/ledger.svg",
                "gallery": ["/static/placeholders/ledger.svg"],
                "demo_video_url": "https://example.com/paper-ledger",
                "repository_url": "https://example.com/paper-ledger",
                "live_url": "https://example.com/paper-ledger/live",
                "tech_tags": ["paper", "postgres"],
                "track": "field-tools",
                "team": "Paper Club",
                "status": "submitted",
                "custom_answers": {"cut": "We cut live sync and kept the paper trail."},
            },
            {
                "name": "Signal Flags",
                "tagline": "Track status you can read across a noisy room",
                "description": "Color flags for which projects still need a judge. Lives on the Data track.",
                "thumbnail_url": "/static/placeholders/signal.svg",
                "demo_video_url": "https://example.com/signal-flags",
                "repository_url": "https://example.com/signal-flags",
                "live_url": "https://example.com/signal-flags/live",
                "tech_tags": ["radio"],
                "track": "data",
                "team": "Signal Club",
                "status": "submitted",
                "custom_answers": {"cut": "We cut push notifications."},
            },
        ],
    }


def run_seed(db: Session, settings: Settings) -> str:
    kind = classify_fixture(settings.fixtures_path)
    if kind == "invalid":
        raise SystemExit(
            f"seed: {settings.fixtures_path} is not valid JSON. "
            "Refusing to hide that behind the built-in demo."
        )
    if kind == "real":
        data = json.loads(Path(settings.fixtures_path).read_text(encoding="utf-8"))
        report = import_payload(db, data)
        _meta(db, "seed_source", "fixture")
        _meta(db, "seed_report", json.dumps(report)[:8000])
        print("seed: imported fixtures/fixtures.json")
        print(
            "  events={events} users={users} teams={teams} projects={projects} scores={scores}".format(
                **report
            )
        )
        if report["users_default_password"]:
            print(
                f"  {report['users_default_password']} users had no password; "
                "they can log in with fixture-pass-72"
            )
        for warning in report["warnings"]:
            print(f"  warning: {warning}")
        _ensure_staff(db)
        _plant_checker_sessions(db, settings)
        print("  staff logins (not in the fixture file):")
        print("    admin@dogfood.local  admin-pass-72  (admin)")
        print("    organizer@dogfood.local  organizer-pass-72  (organizer)")
        print("    participant@dogfood.local  participant-pass-72  (participant, no team yet)")
        print("  Sample Hack is closed. Create a new event to try draft and edit.")
        _print_checker_cookies()
        return "fixture"
    import_payload(db, builtin_payload())
    _meta(db, "seed_source", "builtin")
    _plant_checker_sessions(db, settings)
    print("seed: built-in demo data (fixtures file missing, empty, or marked placeholder)")
    print("Demo logins:")
    for account in DEMO_ACCOUNTS:
        print(f"  {account['email']}  {account['password']}  ({account['role']})")
    print(f"Invite link for Night Shift: /join/{INVITE_CODE}")
    _print_checker_cookies()
    return "builtin"


def _account(email: str) -> dict:
    for account in DEMO_ACCOUNTS:
        if account["email"] == email:
            return account
    raise KeyError(email)


def _ensure_staff(db: Session) -> None:
    """Keep organizer tools available when the fixture file has no staff accounts."""
    for email in ("admin@dogfood.local", "organizer@dogfood.local", "participant@dogfood.local"):
        account = _account(email)
        existing = db.scalar(select(User).where(User.email == account["email"]))
        if existing is not None:
            continue
        db.add(
            User(
                email=account["email"],
                name=account["name"],
                password_hash=hash_password(account["password"]),
                role=account["role"],
            )
        )
    db.flush()


def _plant_checker_sessions(db: Session, settings: Settings) -> None:
    organizer = db.scalar(select(User).where(User.email == "organizer@dogfood.local"))
    judges = list(db.scalars(select(User).where(User.role == Role.JUDGE).order_by(User.id)).all())
    participants = list(
        db.scalars(select(User).where(User.role == Role.PARTICIPANT).order_by(User.id)).all()
    )
    fallback = organizer or (participants[0] if participants else None)
    if fallback is None:
        return
    chosen = {
        CHECKER_SESSIONS["organizer"]: organizer or fallback,
        CHECKER_SESSIONS["judge_a"]: judges[0] if judges else fallback,
        CHECKER_SESSIONS["judge_b"]: judges[1] if len(judges) > 1 else (judges[0] if judges else fallback),
        CHECKER_SESSIONS["participant"]: participants[0] if participants else fallback,
    }
    expires = clock.utcnow() + timedelta(days=settings.session_days)
    for token, user in chosen.items():
        row = db.get(UserSession, token)
        if row is None:
            db.add(UserSession(id=token, user_id=user.id, expires_at=expires))
        else:
            row.user_id = user.id
            row.expires_at = expires
    db.flush()


def _print_checker_cookies() -> None:
    print("Acceptance cookies (the checker does not log in):")
    for role, token in CHECKER_SESSIONS.items():
        print(f"  {role}  Cookie: dogfood_session={token}")


def _meta(db: Session, key: str, value: str) -> None:
    row = db.get(AppMeta, key)
    if row is None:
        db.add(AppMeta(key=key, value=value))
    else:
        row.value = value
