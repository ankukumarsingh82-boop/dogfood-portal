# Data model

Postgres in `docker compose`. Tests use SQLite. The schema is created with SQLAlchemy `create_all` on startup (no migration history in this T1 build). Times are stored in UTC.

Visitor is not a row. A visitor is a request with no live session.

## Tables

### users

| Column | Notes |
| --- | --- |
| id | Integer primary key |
| email | Unique, stored lowercase |
| name | |
| password_hash | bcrypt. Never exported. |
| role | `participant`, `judge`, `organizer`, or `admin` |
| created_at | UTC |

One role per account. Event-scoped roles are not modeled; an organizer can manage every event.

### user_sessions

| Column | Notes |
| --- | --- |
| id | Random url-safe token, also the cookie value |
| user_id | |
| created_at, expires_at | 14 days from login |

### events

| Column | Notes |
| --- | --- |
| slug | Unique, permanent |
| name, description | |
| starts_at, ends_at | Event dates |
| submission_opens_at, submission_deadline | The window the server enforces |
| published | Public gallery and public event page require this |
| created_by_id | Nullable |

### tracks

Unique `(event_id, slug)`. Name, description.

### prizes

Name, description, `place` (integer), `amount_label` (free text such as `$800`), optional `track_id`. Null track means an overall prize.

### custom_questions

Unique `(event_id, key)`. Prompt, help text, `field_type` (`short_text`, `long_text`, `url`, `single_select`), `required`, `options_json`, `position`.

### teams, team_members

A team belongs to one event and has a unique `invite_code`. Membership is unique `(team_id, user_id)`. The application also refuses a second team for the same user on the same event. Judges are not added.

### projects

One project per team (`team_id` unique). Fields:

- name, tagline, description
- thumbnail_path (uploaded `/media/...` path or an http(s) URL)
- demo_video_url, repository_url, live_url
- track_id
- status `draft` or `submitted`
- submitted_at, created_at, updated_at

### project_images

Gallery rows: path, caption, position. At most 8 from the editor.

### project_tags

Lowercased tag, unique per project. Search and the tag filter read this table.

### custom_answers

Unique `(project_id, question_id)`. Text value.

### retained_scores

Raw imported judge rows: project name, judge email, criterion, score value, and the original JSON payload. **Not a judging result.** No page lists them except the organizer export, where they are named `retained_scores_unprocessed`.

### app_meta

`seed_source` is `builtin` or `fixture`. The login page shows demo passwords only when the source is `builtin`.

## How a project gets in

1. An organizer creates an event and adds tracks, prizes, and questions, then publishes.
2. A participant creates a team (or POSTs an invite link) while the window is open.
3. Team members save drafts. Submit requires name, tagline, description, track, and every required custom answer.
4. After submit, the same people can keep editing until `submission_deadline`. The check uses the database clock value and the server clock, not the browser.
5. The gallery lists `status = submitted` on published events. Filters are `q` (name, tagline, description, tag), `track` (slug), and `tag`.

## Import

File: `fixtures/fixtures.json`, overridable with `FIXTURES_PATH`.

| File state | Boot behaviour |
| --- | --- |
| Missing, `{}`, or `"placeholder": true` | Built-in demo |
| Invalid JSON | Process exits. Demo is not substituted. |
| Otherwise, if it has users, judges, teams, projects, events, or an event object | Import |

The file shipped in this repo is the official kickoff dump, not a placeholder. Its event id `evt_01` is stored as the slug. `submissions_close` becomes `submission_deadline` and is not moved forward when it is already past. Missing open and start times are placed before that close. Track ids (`trk_01` …) and team ids (`tm_01` …) are kept, including underscores. A project’s `team` and `track` fields are those ids. `title` / `summary` / `repo_url` / `submitted_at` map onto name, tagline, description, repository URL, and `submitted_at`. A second project on the same team, or a second team that reuses a display name, is stored on a sibling team so both projects stay in the gallery. A score `criteria` object becomes one retained row per criterion. Users with no password share one bcrypt hash of `fixture-pass-72`.

The same importer still accepts the canonical shape below. External ids that match `[A-Za-z0-9][A-Za-z0-9_-]*` are not slugified.

Canonical shape:

```json
{
  "event": {
    "slug": "example-event",
    "name": "Example Event",
    "description": "",
    "starts_at": "2026-09-25T18:00:00Z",
    "ends_at": "2026-09-28T18:00:00Z",
    "submission_opens_at": "2026-09-25T18:00:00Z",
    "submission_deadline": "2026-09-28T18:00:00Z",
    "published": true,
    "tracks": [{"slug": "general", "name": "General", "description": ""}],
    "prizes": [{"name": "Grand prize", "place": 1, "amount_label": "$800", "track": null}],
    "custom_questions": [{"key": "cut", "prompt": "What did you cut?", "type": "long_text", "required": true}]
  },
  "users": [{"email": "person@example.com", "name": "Person Example", "password": "change-me-please", "role": "participant"}],
  "judges": [{"email": "judge@example.com", "name": "Judge Example"}],
  "teams": [{"name": "Example Team", "invite_code": "example-invite", "members": ["person@example.com"]}],
  "projects": [{
    "name": "Example Project",
    "tagline": "A short line",
    "description": "Long description",
    "thumbnail_url": "",
    "gallery": [],
    "demo_video_url": "https://example.com/demo",
    "repository_url": "https://example.com/repo",
    "live_url": "https://example.com",
    "tech_tags": ["python"],
    "track": "general",
    "team": "Example Team",
    "status": "submitted",
    "custom_answers": {"cut": "scope"}
  }],
  "scores": [{"project": "Example Project", "judge": "judge@example.com", "criterion": "impact", "score": 4}]
}
```

A flatter dump also loads. Top-level `event_name`, `tracks`, `projects`, and `judges` are enough; a missing event becomes "Imported hackathon". Aliases include `title`/`long_description`/`github`/`technologies`/`team_name`/`track_name`, and score keys `submission`, `reviewer`, `category`, `rating`, plus official `submissions_close`, `repo_url`, and `summary`. `organiser` is stored as `organizer`. Users with no password can log in with `fixture-pass-72` (printed once at startup, not per user).

Seed also inserts stable `user_sessions` rows (`org_dogfood_t1`, `jdg_a_dogfood_t1`, `jdg_b_dogfood_t1`, `prt_dogfood_t1`) and, when the fixture file has no staff, the `admin@dogfood.local`, `organizer@dogfood.local`, and `participant@dogfood.local` accounts. Those session tokens are how `acceptance/run.py` authenticates. They are not a T2 judging API.

The importer keeps going on messy rows: duplicate project names are both stored, a second project on the same team is placed on a sibling team, unknown tracks are created, bad URLs are dropped, and a judge is not added to a team. Warnings are printed at startup. Designed for a dump on the order of 40 projects, 30 judges, and 8 tracks, including a reviewer whose scores do not vary and projects that have no score row.

Replace the file, then reset the database or the old demo remains:

```bash
docker compose down -v
docker compose up --build
```

## Export

`GET /e/{slug}/export.json` as an organizer or admin downloads the event, tracks, prizes, questions, teams (with member email, name, and role), and projects (including drafts). Password hashes and session tokens are omitted. `retained_scores_unprocessed` is included so imported score rows are not trapped in the database. That file is an exit path for the data, not a judging report and not the T2 per-stage CSV.

There is no public write API. Bulk import is the fixture file at boot.
