# Architecture

Dogfood Portal is a single web process and a Postgres database. `docker compose up --build` starts both, creates the schema, and seeds data. No cloud account, hosted database, or third-party auth provider is involved.

## Why this stack

FastAPI serves HTML rendered by Jinja. HTMX is vendored (see `src/dogfood/static/HTMX-LICENSE.txt`) and only enhances the gallery filters; the same form works as a normal GET if the script does not run. Every create, join, and save is a form POST that checks the caller's role and the submission window before it writes.

That is a deliberate shipping choice for T1. The rules that matter — who may create an event, who may join a team, whether the deadline has passed — sit in the route handlers (`src/dogfood/authz.py`, `src/dogfood/deadlines.py`), not in hidden buttons. A future HTTP API can reuse the same models without a second framework. Postgres matches the shape of a real event (users, teams, projects, tracks, retained scores) and is what an organizer would run after the weekend. Tests use SQLite in memory so they do not need Docker; the compose file does not.

Django would also have reached T1. FastAPI kept the authorization checks visible as ordinary Python instead of spreading them across admin mixins, which is the part a reviewer has to trust.

## Request path

1. The browser sends the `dogfood_session` cookie. The value is a random id, not a serialized user.
2. `user_sessions` is loaded and rejected when `expires_at` has passed. The user row carries one platform role: `participant`, `judge`, `organizer`, or `admin`.
3. A request with no session is a visitor. Visitor is not stored.
4. Mutations call `require_manager`, `require_admin`, `require_submitter`, or `require_participant_action`. Failure is HTTP 403 (or 401 when nobody is logged in). The template hiding a link is not the control.
5. Submission and team writes call `submission_phase`. The server clock decides `early`, `open`, or `closed`. The deadline instant is still open; the next moment is closed. Moving the deadline is an organizer action and is itself role-checked.

Sessions last 14 days. The cookie is `HttpOnly` and `SameSite=Lax`, which is the CSRF control for this build. There is no separate CSRF token. Set `COOKIE_SECURE=1` when the portal is behind HTTPS. Logout deletes the session row.

Passwords are hashed with bcrypt. Registration always creates a participant, even if the form posts another role. Only an admin can change roles, and the last admin cannot be demoted.

## Pages

| Path | Who |
| --- | --- |
| `/`, `/events`, `/e/{slug}` | Visitors see published events. Organizers and admins also see unpublished ones. A team member can open an unpublished event they already joined. |
| `/e/{slug}/gallery`, `/e/{slug}/p/{id}` | Submitted projects on a published event are public. Drafts 404 for everyone except the team and organizers. |
| `/events/new`, `/e/{slug}/manage` | Organizer or admin. |
| `/e/{slug}/teams`, `/join/{code}` | Participant, organizer, or admin, and only while the window is open. Judges are refused. One team per person per event. GET on an invite does not join; POST does. |
| `/e/{slug}/submission` | Team members only, and only while the window is open. The editor URL does not take a project id, so you cannot address someone else's project. |
| `/e/{slug}/export.json` | Organizer or admin. |
| `/admin/users` | Admin. |
| `/health` | Process and database are up. |

Uploads (png, jpeg, gif, webp, 5 MB) are renamed to a random file under `/data/uploads` and served from `/media`. SVG uploads are refused. Thumbnails may also be an `http(s)` URL or a same-origin path such as `/static/...`.

## Seed

On an empty database the process reads `fixtures/fixtures.json`.

- Missing, empty, or `"placeholder": true` loads the built-in demo event `field-test`.
- Invalid JSON aborts startup. The demo is not used to hide a broken official file.
- Any other file with users, judges, teams, projects, or an event is imported. Official ids stay intact (`evt_01`, `trk_04`, `tm_01`). `submissions_close` is honored even when it is in the past. See `DATA-MODEL.md`.
- Seed inserts four stable session cookies so `acceptance/run.py` can call the portal without a login form. It also ensures an admin, an organizer, and an unattached participant exist.

Restarting compose does not reseed a volume that already has users. `docker compose down -v` drops it. `SEED_FORCE=1` drops and reloads on the next boot; leave it at `0` in normal use.

## What is intentionally absent

T2 judging, T3 voting and comments, and T4 API, webhooks, certificates, and an embeddable widget are not implemented. FastAPI's generated OpenAPI docs are disabled so a schema page is not mistaken for that API.

Known limits of this T1 build: no rate limiting, no email verification, no team-leave flow, no pagination (the gallery loads the submitted set in one query), the web container runs as root so the upload volume is writable on first boot, and score rows are stored but not interpreted.
