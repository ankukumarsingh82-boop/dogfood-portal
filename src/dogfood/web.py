"""Templates and the small notice vocabulary used in redirects."""

from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from dogfood.deadlines import dt_local, fmt_dt, submission_phase

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
TEMPLATES.env.globals["phase_of"] = submission_phase
TEMPLATES.env.filters["when"] = fmt_dt
TEMPLATES.env.filters["dt_local"] = dt_local

NOTICES = {
    "saved": "Draft saved. You can keep editing until the deadline.",
    "submitted": "Submission saved. You can keep editing until the deadline.",
    "joined": "You joined the team.",
    "team": "Team created. Share the invite link with the people you want on it.",
    "published": "Event is public. Submitted projects show in the gallery.",
    "unpublished": "Event is hidden from the public gallery.",
    "created": "Event created. Add tracks, prizes, and questions, then publish it.",
    "updated": "Event details saved.",
    "track": "Track added.",
    "prize": "Prize added.",
    "question": "Question added.",
    "removed": "Removed.",
    "role": "Role updated.",
    "needteam": "Create a team or open an invite link before you submit.",
    "image": "Image added.",
    "locked": "That change was rejected because the submission window is not open.",
}


def render(request: Request, name: str, *, status_code: int = 200, **ctx):
    ctx.setdefault("user", None)
    ctx.setdefault("errors", [])
    notice = ctx.pop("notice", None)
    if notice is None:
        notice = request.query_params.get("notice", "")
    ctx["notice"] = NOTICES.get(notice, "")
    return TEMPLATES.TemplateResponse(request, name, ctx, status_code=status_code)
