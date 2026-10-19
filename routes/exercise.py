from datetime import datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

import models
from database import SessionLocal
from routes.common import templates
from units import check_units, preferred_units, to_storage

router = APIRouter()


@router.get("/exercise")
def exercise_page(request: Request):
    # Show the user's exercise history in their preferred units.
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    with SessionLocal() as db:
        entries = (
            db.query(models.ExerciseEntry)
            .filter(
                models.ExerciseEntry.user_id == user_id,
                models.ExerciseEntry.active.is_(True),
            )
            .order_by(models.ExerciseEntry.timestamp.desc())
            .limit(50)
            .all()
        )
        return templates.TemplateResponse(
            request=request, name="exercise.html", context={"entries": entries}
        )


@router.post("/exercise")
def add_exercise(
    request: Request,
    timestamp: datetime = Form(...),
    length_minutes: float = Form(..., gt=0, allow_inf_nan=False),
    exercise_type: str = Form(...),
    intensity: str = Form(...),
    average_heart_rate: int | None = Form(None, gt=0, allow_inf_nan=False),
    peak_heart_rate: int | None = Form(None, gt=0, allow_inf_nan=False),
    distance: float | None = Form(None, ge=0, allow_inf_nan=False),
    measurement_units: str | None = Form(None),
):
    # Convert distance to storage units before saving the entry.
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    if exercise_type not in ("Cardio", "Weights", "Task") or intensity not in (
        "Low",
        "Medium",
        "High",
    ):
        from fastapi import HTTPException

        raise HTTPException(400, "Invalid exercise selection")
    with SessionLocal() as db:
        units = check_units(measurement_units or preferred_units(db, user_id))
        db.add(
            models.ExerciseEntry(
                user_id=user_id,
                timestamp=timestamp,
                length_minutes=length_minutes,
                exercise_type=exercise_type,
                intensity=intensity,
                average_heart_rate=average_heart_rate,
                peak_heart_rate=peak_heart_rate,
                distance=to_storage(distance, "distance", units),
                active=True,
            )
        )
        db.commit()
    return RedirectResponse("/exercise", status_code=303)
