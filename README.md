# Dogfood Portal

Self-hosted submission desk for the [Dogfood 72-Hour Hackathon](https://dogfoodhack.com) (Hackathon Raptors). Organizers run it on a laptop with one command. This repository claims **T1 only**.

## Run

```bash
docker compose up --build
```

Open **http://localhost:8000**.

Postgres 16 and the app both come from Compose. There is no cloud account, no hosted database, and no Auth0, Clerk, or other external API. The first boot creates the schema and seeds data. Later boots keep the Docker volume. `docker compose down -v` (or `SEED_FORCE=1`) reloads the seed.

`fixtures/fixtures.json` is the official kickoff file, so the first boot imports **Sample Hack 2026** at `/e/evt_01`. That event's `submissions_close` is `2026-03-01T18:00:00Z`, which is in the past, and the importer leaves it there. The gallery is public. A submission POST returns 403. Ids such as `evt_01`, `trk_04`, and `tm_01` are kept, underscores included. Fixture accounts that have no password log in with `fixture-pass-72`.

If the fixtures file is missing, empty, or `"placeholder": true`, Compose loads the built-in **Weekend Field Test** instead (`/e/field-test`, invite `/join/night-shift-invite`). Invalid JSON aborts startup.

### Logins

Staff accounts are created even when the official file is imported, so an organizer can still make a second event:

| Role | Email | Password |
| --- | --- | --- |
| Admin | admin@dogfood.local | admin-pass-72 |
| Organizer | organizer@dogfood.local | organizer-pass-72 |
| Participant (no team yet) | participant@dogfood.local | participant-pass-72 |
| Fixture judge or teammate | address in `fixtures.json` | fixture-pass-72 |

Sample Hack cannot demonstrate draft-and-edit, because it is already closed. Log in as the organizer, create an event whose deadline is in the future, publish it, then use `participant@dogfood.local` to form a team and submit. The built-in seed, when it is the one that loaded, also includes `judge@dogfood.local` / `judge-pass-72`, `teammate@dogfood.local`, `author@dogfood.local`, and `maker@dogfood.local` (same `*-pass-72` pattern). Those passwords are printed at startup and on the login page only for the built-in seed.

The acceptance checker does not log in. Seed inserts these cookies (14 days):

| Role | Cookie |
| --- | --- |
| Organizer | `dogfood_session=org_dogfood_t1` |
| Judge A | `dogfood_session=jdg_a_dogfood_t1` |
| Judge B | `dogfood_session=jdg_b_dogfood_t1` |
| Participant | `dogfood_session=prt_dogfood_t1` |

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

`.dogfood.toml` claims T1 only. The checker still runs its T2 requests; those routes 404, so T2 stays unverified. `example.dogfood.toml` is the upstream template and is not this repo's claim.

```bash
python3 acceptance/run.py .dogfood.toml --fixtures fixtures/fixtures.json
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Tests use SQLite. Compose uses Postgres 16.

## Layout

- `src/dogfood/` application
- `tests/` pytest suite
- `fixtures/fixtures.json` official kickoff data (event, tracks, judges, teams, projects, scores)
- `docker-compose.yml` app on port 8000, Postgres not published to the host

More detail: [ARCHITECTURE.md](ARCHITECTURE.md), [DATA-MODEL.md](DATA-MODEL.md), [JUDGING.md](JUDGING.md).

## License

MIT. htmx 2.0.4 is vendored under `src/dogfood/static/` and remains under its own MIT license (`HTMX-LICENSE.txt`).
