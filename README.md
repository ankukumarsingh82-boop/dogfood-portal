# Dogfood Portal

Self-hosted submission desk for the [Dogfood 72-Hour Hackathon](https://dogfoodhack.com) (Hackathon Raptors). Organizers run it on a laptop with one command. This repository claims **T1 only**.

## Run

```bash
docker compose up --build
```

Open **http://localhost:8000**.

Postgres and the app both come from Compose. There is no cloud account, no hosted database, and no Auth0, Clerk, or other external API. The first boot creates the schema and seeds data. Later boots keep the Docker volume.

`fixtures/fixtures.json` is still a placeholder (`"placeholder": true`), so the built-in demo event is loaded. When the official kickoff file arrives, replace `fixtures/fixtures.json` and reset the volume:

```bash
docker compose down -v
docker compose up --build
```

Startup logs print which seed ran. Demo passwords appear in the logs only for the built-in seed, and on the login page while that seed is active.

### Demo logins

| Role | Email | Password |
| --- | --- | --- |
| Admin | admin@dogfood.local | admin-pass-72 |
| Organizer | organizer@dogfood.local | organizer-pass-72 |
| Judge | judge@dogfood.local | judge-pass-72 |
| Participant | participant@dogfood.local | participant-pass-72 |
| Participant (team lead, draft) | teammate@dogfood.local | teammate-pass-72 |
| Participant (gallery project) | author@dogfood.local | author-pass-72 |
| Participant (second gallery project) | maker@dogfood.local | maker-pass-72 |

The seeded event is **Weekend Field Test** at `/e/field-test`. Its gallery already has two submitted projects. Invite link for the draft team Night Shift:

http://localhost:8000/join/night-shift-invite

`participant@dogfood.local` is not on a team yet, so that account can create one or accept the invite.

All times in the product are UTC.

## What a T1 walkthrough looks like

1. Log in as `organizer@dogfood.local`. Create an event (name, UTC dates, optional slug). On the manage page add a track, a prize, and a custom question, then publish.
2. Log in as `participant@dogfood.local`. Open the event, create a team, and copy the invite link.
3. Register a second participant (or use another demo account that is not already on a team) and open `/join/{code}`. Joining is a POST. Judges are rejected.
4. Edit the project: name, tagline, description, thumbnail, gallery images, demo video URL, repository URL, live link, tech tags, track, and the organizer's questions. Save a draft, then submit. Edit again. Both succeed only before the deadline.
5. Log out. The public gallery at `/e/{slug}/gallery` lists submitted projects and filters by text, track, and tag. Drafts are absent.
6. As the organizer, move the deadline into the past. A further save returns **403** even if the form is posted by hand. The gallery still shows the last submitted version.

An admin (`admin@dogfood.local`) can change stored roles at `/admin/users`. Registration cannot self-assign organizer or admin.

## What T1 does

- Email and password sessions, stored server-side, cookie is HttpOnly and SameSite=Lax
- Roles enforced on the server: visitor (no session), participant, judge, organizer, admin
- Events with dates, tracks, and prizes
- Teams by invite link, one team per person per event
- Project draft and edit until the deadline, including organizer-defined questions
- Deadline and "not open yet" checks on the server for saves, image edits, and joins
- Public gallery with search and track/tag filters
- Organizer JSON export of the event and submissions

Submission fields: name, tagline, long description, thumbnail, image gallery, demo video URL, repository URL, live link, tech tags, track, custom questions.

## What this build does not do

| Tier | Status |
| --- | --- |
| T2 Judging | Not built. No assignment, rubric, score entry, normalization, progress dashboard, or per-stage CSV. Imported score rows are kept and not interpreted. See [JUDGING.md](JUDGING.md). |
| T3 Public voting | Not built. No comments, ballots, or abuse controls. |
| T4 API and stretch | Not built. No documented public API, webhooks, certificates, or embeddable widget. `/docs` is disabled on purpose. |

The official acceptance suite is not in this repo. See [acceptance/README.md](acceptance/README.md). There is no `acceptance-report.txt` because that file would be invented.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Tests use SQLite. Compose uses Postgres 16.

## Layout

- `src/dogfood/` application
- `tests/` pytest suite
- `fixtures/fixtures.json` placeholder plus the canonical example under `schema_example`
- `docker-compose.yml` app on port 8000, Postgres not published to the host

More detail: [ARCHITECTURE.md](ARCHITECTURE.md), [DATA-MODEL.md](DATA-MODEL.md), [JUDGING.md](JUDGING.md).

## License

MIT. htmx 2.0.4 is vendored under `src/dogfood/static/` and remains under its own MIT license (`HTMX-LICENSE.txt`).
