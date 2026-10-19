from datetime import datetime

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

import models
from database import SessionLocal
from routes.common import templates
from routes.entries import validate_values

router = APIRouter()


@router.get("/mood")
def mood_page(request: Request):
    # Show the user's recent mood measurements.
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    with SessionLocal() as db:
        entries = (
            db.query(models.MoodEntry)
            .filter(
                models.MoodEntry.user_id == user_id, models.MoodEntry.active.is_(True)
            )
            .order_by(models.MoodEntry.timestamp.desc())
            .limit(50)
            .all()
        )
        return templates.TemplateResponse(
            request=request, name="mood.html", context={"entries": entries}
        )


@router.post("/mood")
def add_mood(
    request: Request,
    timestamp: datetime = Form(...),
    feeling: str | None = Form(None, max_length=30),
    hunger: str | None = Form(None, max_length=30),
    head: str | None = Form(None, max_length=30),
):
    # Save the entry after checking that a mood measurement was selected.
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    if not any((feeling, hunger, head)):
        raise HTTPException(
            status_code=400, detail="Enter at least one mood measurement."
        )

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
