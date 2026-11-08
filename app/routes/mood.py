from datetime import datetime

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.db import models
from app.db.session import SessionLocal
from app.forms.entry_rules import validate_values
from app.routes.common import templates
from app.utils.pagination import paginate
from app.utils.time_utils import to_utc

router = APIRouter()


@router.get("/mood")
def mood_page(request: Request):
    # Show the user's recent mood measurements.
    user_id = request.state.user.id
    with SessionLocal() as db:
        query = (
            db.query(models.MoodEntry)
            .filter(
                models.MoodEntry.user_id == user_id, models.MoodEntry.active.is_(True)
            )
            .order_by(models.MoodEntry.timestamp.desc(), models.MoodEntry.id.desc())
        )
        entries, pagination = paginate(query, request)
        return templates.TemplateResponse(
            request=request,
            name="mood.html",
            context={"entries": entries, "pagination": pagination},
        )


@router.post("/mood")
def add_mood(
    request: Request,
    timestamp: datetime | None = Form(None),
    client_timezone: str = Form("America/Chicago"),
    feeling: str | None = Form(None, max_length=30),
    hunger: str | None = Form(None, max_length=30),
    head: str | None = Form(None, max_length=30),
):
    # Save the entry after checking that a mood measurement was selected.
    user_id = request.state.user.id
    if not any((feeling, hunger, head)):
        raise HTTPException(
            status_code=400, detail="Enter at least one mood measurement."
        )

    timestamp = to_utc(timestamp, client_timezone)
    validate_values(
        "mood",
        {"timestamp": timestamp, "feeling": feeling, "hunger": hunger, "head": head},
    )
    with SessionLocal() as db:
        db.add(
            models.MoodEntry(
                user_id=user_id,
                timestamp=timestamp,
                feeling=feeling or None,
                hunger=hunger or None,
                head=head or None,
                active=True,
            )
        )
        db.commit()
    return RedirectResponse("/mood", status_code=303)
