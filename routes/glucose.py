from datetime import datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

import models
from database import SessionLocal
from pagination import paginate
from routes.common import templates
from time_utils import to_utc

router = APIRouter()


@router.get("/glucose")
def glucose_page(request: Request):
    # Show the user's most recent glucose readings.
    user_id = request.state.user.id

    with SessionLocal() as db:
        query = (
            db.query(models.GlucoseReading)
            .filter(
                models.GlucoseReading.user_id == user_id,
                models.GlucoseReading.active.is_(True),
            )
            .order_by(
                models.GlucoseReading.timestamp.desc(), models.GlucoseReading.id.desc()
            )
        )
        readings, pagination = paginate(query, request)

    return templates.TemplateResponse(
        request=request,
        name="glucose.html",
        context={"readings": readings, "pagination": pagination},
    )


@router.post("/glucose")
def add_glucose(
    request: Request,
    glucose: int = Form(..., ge=20, le=600),
    timestamp: datetime | None = Form(None),
    client_timezone: str = Form("America/Chicago"),
):
    # Save a validated reading for the signed-in user.
    user_id = request.state.user.id

    reading_time = to_utc(timestamp, client_timezone)

    with SessionLocal() as db:
        reading = models.GlucoseReading(
            user_id=user_id,
            glucose=glucose,
            timestamp=reading_time,
            source="manual",
            active=True,
        )

        db.add(reading)
        db.commit()

    return RedirectResponse(url="/glucose", status_code=303)
